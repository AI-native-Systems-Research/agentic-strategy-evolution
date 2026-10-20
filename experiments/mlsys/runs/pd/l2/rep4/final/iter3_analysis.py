#!/usr/bin/env python3
"""
Iteration 3: Close the ~7% transient model gap by fixing two systematic biases.

Prior finding: transient model underpredicts BLIS ITL by ~7% at high rates.

Root causes identified by reading BLIS source:
1. BLIS itl_mean_ms = flat mean of ALL per-step ITL entries (AllITLs).
   Each step with B_decode requests contributes B entries of (StepTime + alpha2).
   This is a batch-size-WEIGHTED average: heavier steps get more weight.
   The iter2 transient model uses an UNWEIGHTED average, which misses the
   Cov(B, T)/E[B] bias term.

2. C0_US was computed incorrectly in iter2. The actual per-step overhead added
   to each ITL entry is just alpha2 = int64(45.907545) = 45 us (OutputTokenProcessingTime).
   The iter2 model used C0 = 105.3 us which included beta6 + beta10*kv terms
   that are already in the step time.

3. int64 truncation: BLIS StepTime() returns int64(float64), truncating the
   fractional microsecond. Over many steps this can accumulate a small bias.
"""

import math
import json
import csv
import random

# =====================================================================
# BLIS PHYSICAL PARAMETERS (exact, from source + defaults.yaml)
# =====================================================================

BETA = [0.152128, 0.0, 1.36252915, 0.752037, 32.09546717,
        4.41684444, 126.024825, 481.8613888, 0.0, 1.94710771]

NUM_LAYERS = 40
HIDDEN_DIM = 5120
NUM_HEADS = 40
NUM_KV_HEADS = 8
HEAD_DIM = HIDDEN_DIM // NUM_HEADS  # 128
D_KV = NUM_KV_HEADS * HEAD_DIM     # 1024
INTERMEDIATE_DIM = 17408
BYTES_PER_KV = 2.0
WEIGHT_BPP = 2.0
FLOPS_PEAK_US = 989.5e6
BW_HBM_US = 3.35e6

L_TOKENS = 512
O_TOKENS = 128
N_D = 2
N_P = 2
NUM_REQUESTS = 300
MAX_RUNNING = 256
MAX_SCHED_TOKENS = 2048
TP = 1

ALPHA_0 = 15563.199579  # QueueingTime (us)
ALPHA_1 = 777.3455      # PostDecodeFixedOverhead (us)
ALPHA_2 = 45.907545     # OutputTokenProcessingTime (us/token)
ALPHA_2_INT = int(ALPHA_2)  # 45 us (int64 truncation in BLIS)
# BLIS does N_DECODE = OutputTokens - 1 decode steps (first output token is in TTFT)
N_DECODE = O_TOKENS - 1  # 127

def compute_weight_loading_time():
    bytesAttn = NUM_LAYERS * HIDDEN_DIM * (2*HIDDEN_DIM + 2*D_KV) * WEIGHT_BPP / TP
    bytesFfn = NUM_LAYERS * 1 * 3 * HIDDEN_DIM * INTERMEDIATE_DIM * WEIGHT_BPP / TP
    return (bytesAttn + bytesFfn) / BW_HBM_US

def compute_alpha_blis():
    t_weight = compute_weight_loading_time()
    return BETA[2] * t_weight + BETA[4] * NUM_LAYERS + BETA[6]

KV_COEFF = NUM_LAYERS * 2 * (D_KV / TP) * BYTES_PER_KV / BW_HBM_US

def decode_delta(k):
    """Marginal decode cost for one request at decode step k (1-indexed), in us.
    BLIS context at decode step k: ProgressIndex = InputLen + (k-1) = 512+(k-1).
    KV bandwidth = KV_COEFF * (PI + 1) = KV_COEFF * (512 + k).
    Note: k=1 is the FIRST decode step (PI=512, generates first decode token)."""
    pi = L_TOKENS + (k - 1)  # ProgressIndex at start of step k
    t_dc_kv = KV_COEFF * (pi + 1)  # sumCtx + totalDecodeTokens for 1 req
    return BETA[5] + BETA[9] * t_dc_kv

def prefill_flops(tokens):
    d = HIDDEN_DIM
    dKV = D_KV
    dH = HEAD_DIM
    hPerGPU = NUM_HEADS / TP
    L = NUM_LAYERS
    flopsProj = L * 2 * tokens * d * (2*d + 2*dKV) / TP
    flopsAttn = L * 4 * hPerGPU * tokens * (tokens + tokens/2) * dH
    flopsFfn = L * tokens * 1 * 6 * d * INTERMEDIATE_DIM / TP
    return flopsProj + flopsAttn + flopsFfn

def prefill_step_cost():
    """Marginal cost of one prefill request (512 tokens) in the batch (us)."""
    pf_flops = prefill_flops(L_TOKENS)
    t_pf_compute = pf_flops / FLOPS_PEAK_US
    return BETA[0] * t_pf_compute + BETA[5]

ALPHA_BLIS = compute_alpha_blis()
W_P_STEP = prefill_step_cost()

# Verify (W_D spans decode steps 1..N_DECODE = 1..127)
W_D_total = sum(decode_delta(k) for k in range(1, N_DECODE + 1))
W_tot = W_P_STEP + W_D_total

print(f"BLIS Parameters:")
print(f"  alpha_BLIS = {ALPHA_BLIS:.1f} us ({ALPHA_BLIS/1000:.3f} ms)")
print(f"  W_P_STEP   = {W_P_STEP:.1f} us ({W_P_STEP/1000:.3f} ms)")
print(f"  W_D_total  = {W_D_total:.1f} us ({W_D_total/1000:.3f} ms)")
print(f"  W_tot      = {W_tot:.1f} us ({W_tot/1000:.3f} ms)")
print(f"  alpha2     = {ALPHA_2:.6f} us → int64 = {ALPHA_2_INT} us")
print(f"  alpha2 per step (BLIS ITL overhead) = {ALPHA_2_INT} us")
print()


# =====================================================================
# CORRECTED TRANSIENT MODEL
# =====================================================================

def step_time_float(active_steps):
    """Compute float64 step time like BLIS does, given list of decode steps
    (0=prefill, 1..128=decode step k).
    Returns float64 before int64 truncation."""
    marginal = 0.0
    B = len(active_steps)
    for step in active_steps:
        if step == 0:
            marginal += W_P_STEP
        else:
            marginal += decode_delta(step)
    # Step time = alpha + sum(marginals) + (beta6 is already in marginals!)
    # Actually beta6 is per-request overhead already in decode_delta and W_P_STEP
    # The stepTime formula is: prefillTerm + decodeTerm + beta3*tWeight + beta5*L + beta6*B + beta7
    # But decode_delta already includes beta6... wait, let me re-check.
    #
    # From BLIS source: stepTime = prefillTerm + decodeTerm + beta3*tWeight + beta5*L + beta6*batchSize + beta7
    # And decodeTerm = beta9(beta10) * tDcKv (the KV bandwidth term only)
    #
    # So step_time = beta10*tDcKv + beta3*tWeight + beta5*L + beta6*B + beta7 + prefillTerm
    # where tDcKv = L*2*(dKV/TP)*2*(sumCtx + totalDecodeTokens) / bwHbmUs
    #
    # But decode_delta(k) = BETA[5] + BETA[9]*kv_for_one_request
    # So sum(decode_delta(k)) = BETA[5]*numDecode + BETA[9]*sum(kv_j)
    # While BLIS computes: beta6*batchSize + beta10*tDcKv
    # = beta6*(numPrefill+numDecode) + beta10*(sum_j kv_j)
    #
    # These match since beta6 = BETA[5]. OK good.
    #
    # But wait: the BLIS formula includes beta6*batchSize which counts BOTH prefill
    # and decode requests. And W_P_STEP already includes BETA[5]. So for a batch
    # with numPrefill prefill requests and numDecode decode requests:
    # BLIS step_time = prefillTerm + decodeTerm + beta3*tWeight + beta5*L + beta6*(numPrefill+numDecode) + beta7
    # Our model: alpha + sum(W_P for prefills) + sum(decode_delta for decodes)
    # = (beta3*tWeight + beta5*L + beta7) + numPrefill*W_P_STEP + sum(decode_delta(k_j))
    # = alpha + numPrefill*(beta1a*t_pf_compute + beta6) + sum_j(beta6 + beta10*kv_j)
    # = alpha + beta1a*t_pf_compute*numPrefill + beta6*numPrefill + beta6*numDecode + beta10*sum(kv_j)
    # = alpha + beta1a*t_pf_compute*numPrefill + beta6*(numPrefill+numDecode) + beta10*sum(kv_j)
    #
    # BLIS: alpha + prefillTerm + beta6*(numPrefill+numDecode) + beta10*tDcKv
    # where prefillTerm = beta1a * t_pf_compute (which is beta1a * total prefill FLOPs / flopsPeak)
    # and tDcKv = total KV bandwidth for ALL decode requests
    #
    # These match! Good. Our model is correct.
    return ALPHA_BLIS + marginal


def simulate_corrected(lam, use_poisson=False, seed=42, use_int64=True):
    """Corrected transient model:
    1. Computes batch-size-weighted ITL (matching BLIS AllITLs mean)
    2. Uses exact alpha2_int per step (not C0)
    3. Optionally applies int64 truncation to step times
    """
    rng = random.Random(seed)
    per_inst_rate = lam / N_D
    reqs_per_inst = NUM_REQUESTS // N_D

    if per_inst_rate <= 0:
        st = step_time_float([1])  # single decode request
        if use_int64:
            st = float(int(st))
        return 0, (st + ALPHA_2_INT) / 1000.0, (st + ALPHA_2_INT) / 1000.0, 0

    # Generate arrival times (in us)
    if use_poisson:
        arrivals = []
        t = 0
        for _ in range(reqs_per_inst):
            t += rng.expovariate(per_inst_rate) * 1e6
            arrivals.append(t)
    else:
        inter = 1e6 / per_inst_rate
        arrivals = [i * inter for i in range(reqs_per_inst)]

    # State tracking
    active = []  # list of decode step (0=prefill, 1..128=decode)
    next_arr = 0
    current_time = 0.0

    # Metrics for WEIGHTED average (matching BLIS AllITLs)
    sum_weighted_itl = 0.0  # sum of B_decode * (step_time + alpha2)
    total_decode_entries = 0  # total AllITLs entries

    # Metrics for UNWEIGHTED average (iter2 transient model style)
    sum_step_time = 0.0
    num_steps = 0

    # Batch size tracking
    batch_sizes = []
    sum_batch_sq = 0.0

    while active or next_arr < reqs_per_inst:
        # Admit new arrivals
        while next_arr < reqs_per_inst and arrivals[next_arr] <= current_time:
            active.append(0)  # prefill step
            next_arr += 1

        if not active:
            if next_arr < reqs_per_inst:
                current_time = arrivals[next_arr]
                continue
            else:
                break

        B = len(active)
        st_float = step_time_float(active)
        if use_int64:
            st = float(max(1, int(st_float)))
        else:
            st = st_float

        # Count decode-phase requests (those that contribute to AllITLs)
        num_decode = sum(1 for s in active if s > 0)  # step > 0 means decode phase
        # Actually, in BLIS, ALL requests in the running batch with NumNewTokens > 0
        # get an ITL entry during decode phase. A request in prefill (step=0) doesn't
        # get an ITL entry. So only decode-phase requests contribute.
        # But wait: a request at step=0 is in its first step (prefill). After this step,
        # it advances to step=1 (first decode). The ITL is only appended for decode steps.
        # So in our model, requests with step > 0 are the ones that GET an ITL entry.
        # Hmm, actually let me re-check. Looking at BLIS code:
        # In executeBatchStep, for decode phase (ProgressIndex >= InputTokens):
        #   if NumNewTokens > 0: ProgressIndex++; ITL = append(ITL, step + alpha2)
        # For prefill phase (ProgressIndex < InputTokens):
        #   ProgressIndex = computedTokens (no ITL append)
        # So only decode-phase requests get ITL entries. In our model, step=0 is prefill
        # (no ITL), step=1..128 are decode (get ITL).

        if num_decode > 0:
            itl_this_step = st + ALPHA_2_INT  # int64 in BLIS
            sum_weighted_itl += num_decode * itl_this_step
            total_decode_entries += num_decode

        sum_step_time += st
        num_steps += 1
        batch_sizes.append(B)
        sum_batch_sq += B * B

        current_time += st

        # Advance requests
        # BLIS completion: ProgressIndex >= InputLen + max(OutputLen,1) - 1
        # = 512 + 128 - 1 = 639. PI after step k = 512 + k.
        # Completion at step where PI = 639, i.e., k = 127 = N_DECODE.
        # So step k=127 participates in batch, gets ITL, then completes.
        new_active = []
        for step in active:
            if step == 0:
                new_active.append(1)  # prefill → first decode
            elif step < N_DECODE:  # steps 1..126 advance to next
                new_active.append(step + 1)
            # step == N_DECODE (127): request complete after this step
        active = new_active

    # Weighted average ITL (BLIS style)
    weighted_itl_ms = (sum_weighted_itl / total_decode_entries / 1000.0) if total_decode_entries > 0 else 0

    # Unweighted average ITL (iter2 style)
    unweighted_itl_ms = ((sum_step_time / num_steps) + ALPHA_2_INT) / 1000.0 if num_steps > 0 else 0

    # Batch size stats
    avg_batch = sum(batch_sizes) / len(batch_sizes) if batch_sizes else 0
    var_batch = sum_batch_sq / len(batch_sizes) - avg_batch**2 if batch_sizes else 0
    cv_batch = math.sqrt(var_batch) / avg_batch if avg_batch > 0 else 0

    return weighted_itl_ms, unweighted_itl_ms, avg_batch, cv_batch


def paper_steady_state(lam):
    """Paper's steady-state ITL formula."""
    rho = (lam / N_D) * W_tot / 1e6
    if rho >= 1:
        return float('inf'), rho
    t_iter = ALPHA_BLIS / (1 - rho)
    itl = (t_iter + ALPHA_2_INT) / 1000.0
    return itl, rho


# =====================================================================
# LOAD BLIS MEASUREMENT DATA
# =====================================================================

def load_sweep():
    al = {}
    ad = {}
    with open("final/data/sweep_results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rate = float(row["rate"])
            if rate > 150:
                continue
            rec = {
                "rate": rate,
                "itl": float(row["itl_mean_ms"]),
                "ttft": float(row["ttft_mean_ms"]),
                "e2e": float(row["e2e_mean_ms"]),
                "completed": int(row["completed"]),
            }
            if row["mode"] == "never":
                al[rate] = rec
            else:
                ad[rate] = rec
    return al, ad


# =====================================================================
# MAIN ANALYSIS
# =====================================================================

def main():
    al_data, ad_data = load_sweep()

    rates = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]

    print("=" * 130)
    print("ITERATION 3: BATCH-SIZE-WEIGHTED ITL CORRECTION")
    print("=" * 130)
    print(f"{'Rate':>5} | {'BLIS':>8} {'Weighted':>8} {'Unwtd':>8} {'SS':>8} | "
          f"{'Wtd_e%':>7} {'Unwtd_e%':>8} {'SS_e%':>7} | "
          f"{'AvgB':>6} {'CV_B':>6} {'Bias':>6}")

    results = []
    for rate in rates:
        if rate not in al_data:
            continue
        meas = al_data[rate]["itl"]

        # Average over 5 Poisson seeds
        wtd_itls = []
        unwtd_itls = []
        avg_batches = []
        cv_batches = []
        for seed in range(42, 47):
            w, u, ab, cv = simulate_corrected(rate, use_poisson=True, seed=seed, use_int64=True)
            wtd_itls.append(w)
            unwtd_itls.append(u)
            avg_batches.append(ab)
            cv_batches.append(cv)

        wtd_mean = sum(wtd_itls) / len(wtd_itls)
        unwtd_mean = sum(unwtd_itls) / len(unwtd_itls)
        avg_b = sum(avg_batches) / len(avg_batches)
        cv_b = sum(cv_batches) / len(cv_batches)

        ss_itl, rho = paper_steady_state(rate)

        wtd_err = (wtd_mean - meas) / meas * 100
        unwtd_err = (unwtd_mean - meas) / meas * 100
        ss_err = (ss_itl - meas) / meas * 100 if ss_itl < 1e5 else float('inf')
        bias = wtd_mean - unwtd_mean  # ms

        ss_s = f"{ss_itl:.3f}" if ss_itl < 1e5 else "UNSTABLE"
        ss_e = f"{ss_err:.1f}" if ss_err < 1e5 else "INF"

        print(f"{rate:5} | {meas:8.3f} {wtd_mean:8.3f} {unwtd_mean:8.3f} {ss_s:>8} | "
              f"{wtd_err:7.2f} {unwtd_err:8.2f} {ss_e:>7} | "
              f"{avg_b:6.1f} {cv_b:6.3f} {bias:6.3f}")

        results.append({
            "rate": rate,
            "blis_measured_ms": meas,
            "weighted_itl_ms": round(wtd_mean, 4),
            "unweighted_itl_ms": round(unwtd_mean, 4),
            "steady_state_itl_ms": round(ss_itl, 3) if ss_itl < 1e5 else None,
            "weighted_error_pct": round(wtd_err, 3),
            "unweighted_error_pct": round(unwtd_err, 3),
            "ss_error_pct": round(ss_err, 2) if ss_err < 1e5 else None,
            "avg_batch_size": round(avg_b, 1),
            "batch_cv": round(cv_b, 4),
            "weighting_bias_ms": round(bias, 4),
            "rho": round(rho, 5) if rho < 1 else None,
        })

    # Summary statistics
    print("\n" + "=" * 80)
    print("MODEL COMPARISON SUMMARY")
    print("=" * 80)
    for model, key in [("Weighted transient (corrected)", "weighted_error_pct"),
                       ("Unweighted transient (iter2-style)", "unweighted_error_pct"),
                       ("Steady-state formula", "ss_error_pct")]:
        errs = [abs(r[key]) for r in results if r[key] is not None]
        if errs:
            rmse = math.sqrt(sum(e**2 for e in errs) / len(errs))
            maxe = max(errs)
            mae = sum(errs) / len(errs)
            print(f"  {model:40}: RMSE={rmse:6.2f}%  MAE={mae:5.2f}%  MaxErr={maxe:6.2f}%")

    # Bias analysis
    print("\n" + "=" * 80)
    print("WEIGHTING BIAS ANALYSIS")
    print("=" * 80)
    print("The batch-size weighting bias grows with batch-size variance.")
    print(f"{'Rate':>5} {'AvgB':>7} {'CV':>7} {'Bias_ms':>8} {'Bias_%':>8}")
    for r in results:
        bias_pct = r["weighting_bias_ms"] / r["blis_measured_ms"] * 100
        print(f"{r['rate']:5} {r['avg_batch_size']:7.1f} {r['batch_cv']:7.3f} "
              f"{r['weighting_bias_ms']:8.3f} {bias_pct:8.2f}")

    # Save evidence
    evidence = {
        "model": "iter3_corrected_transient",
        "corrections": [
            "batch-size-weighted ITL (matching BLIS AllITLs flat mean)",
            "alpha2_int = 45 us (exact BLIS int64 truncation, not C0=105.3)",
            "int64 truncation of step times",
        ],
        "results": results,
    }
    with open("final/data/iter3_evidence.json", "w") as f:
        json.dump(evidence, f, indent=2)
    print(f"\nSaved to final/data/iter3_evidence.json")

    return results


# =====================================================================
# AD vs AL COMPARISON (both weighted)
# =====================================================================

def simulate_ad_corrected(lam, seed=42):
    """Simulate AD mode: prefill on dedicated instances, only decode on decode instances.
    In AD mode, decode instances never see prefill requests - they receive requests
    that have already been prefilled. So every request enters the decode batch directly
    at step 1 (first decode step).
    """
    rng = random.Random(seed)
    per_inst_rate = lam / N_D
    reqs_per_inst = NUM_REQUESTS // N_D

    if per_inst_rate <= 0:
        st = step_time_float([1])
        return (float(int(st)) + ALPHA_2_INT) / 1000.0

    # Arrival times at decode instance (after prefill on P instance)
    # In AD mode, there's additional TTFT overhead before the request reaches decode.
    # But for ITL comparison, what matters is when requests enter the decode batch.
    # The prefill time is roughly: alpha + W_P_STEP ≈ 14.3 ms
    # This delays arrivals at the decode instance, spreading them out slightly.
    # For simplicity (and because iter2 found this is a small effect), we use
    # the same arrival times but with decode-only step times.

    arrivals = []
    t = 0
    for _ in range(reqs_per_inst):
        t += rng.expovariate(per_inst_rate) * 1e6
        arrivals.append(t)

    active = []  # all start at step 1 (decode) in AD mode
    next_arr = 0
    current_time = 0.0
    sum_weighted_itl = 0.0
    total_decode_entries = 0

    while active or next_arr < reqs_per_inst:
        while next_arr < reqs_per_inst and arrivals[next_arr] <= current_time:
            active.append(1)  # Start at decode step 1 (no prefill on decode instance)
            next_arr += 1

        if not active:
            if next_arr < reqs_per_inst:
                current_time = arrivals[next_arr]
                continue
            else:
                break

        B = len(active)
        st = float(max(1, int(step_time_float(active))))

        # All requests are in decode phase
        itl_entry = st + ALPHA_2_INT
        sum_weighted_itl += B * itl_entry
        total_decode_entries += B

        current_time += st

        new_active = []
        for step in active:
            if step < N_DECODE:  # steps 1..126 advance; step 127 completes
                new_active.append(step + 1)
        active = new_active

    return (sum_weighted_itl / total_decode_entries / 1000.0) if total_decode_entries > 0 else 0


def ad_al_comparison():
    al_data, ad_data = load_sweep()

    print("\n" + "=" * 120)
    print("AD vs AL ITL COMPARISON (weighted transient model)")
    print("=" * 120)
    print(f"{'Rate':>5} | {'AL_BLIS':>8} {'AL_model':>8} {'AL_e%':>7} | "
          f"{'AD_BLIS':>8} {'AD_model':>8} {'AD_e%':>7} | "
          f"{'diff_BLIS':>9} {'diff_model':>10} | {'pred_ok':>8}")

    ad_results = []
    for rate in [1, 5, 10, 20, 50, 100, 150]:
        if rate not in al_data or rate not in ad_data:
            continue
        al_meas = al_data[rate]["itl"]
        ad_meas = ad_data[rate]["itl"]

        # AL model (5-seed avg)
        al_preds = []
        for s in range(42, 47):
            w, _, _, _ = simulate_corrected(rate, use_poisson=True, seed=s)
            al_preds.append(w)
        al_model = sum(al_preds) / len(al_preds)

        # AD model (5-seed avg)
        ad_preds = [simulate_ad_corrected(rate, seed=s) for s in range(42, 47)]
        ad_model = sum(ad_preds) / len(ad_preds)

        al_err = (al_model - al_meas) / al_meas * 100
        ad_err = (ad_model - ad_meas) / ad_meas * 100

        diff_blis = al_meas - ad_meas
        diff_model = al_model - ad_model
        pred_ok = "YES" if (diff_blis > 0) == (diff_model > 0) else "NO"

        print(f"{rate:5} | {al_meas:8.3f} {al_model:8.3f} {al_err:7.2f} | "
              f"{ad_meas:8.3f} {ad_model:8.3f} {ad_err:7.2f} | "
              f"{diff_blis:9.3f} {diff_model:10.3f} | {pred_ok:>8}")

        ad_results.append({
            "rate": rate,
            "al_blis": al_meas, "al_model": round(al_model, 4), "al_err_pct": round(al_err, 3),
            "ad_blis": ad_meas, "ad_model": round(ad_model, 4), "ad_err_pct": round(ad_err, 3),
            "diff_blis": round(diff_blis, 4), "diff_model": round(diff_model, 4),
        })

    return ad_results


# =====================================================================
# TTFT ANALYSIS
# =====================================================================

def ttft_analysis():
    al_data, ad_data = load_sweep()

    print("\n" + "=" * 90)
    print("TTFT COMPARISON: AL vs AD (from BLIS measurements)")
    print("=" * 90)
    print(f"{'Rate':>5} | {'AL_TTFT':>9} {'AD_TTFT':>9} {'AD-AL':>8} {'Winner':>7} | "
          f"{'AL_E2E':>9} {'AD_E2E':>9}")

    ttft_results = []
    crossover = None
    for rate in sorted(al_data.keys()):
        if rate not in ad_data:
            continue
        al = al_data[rate]
        ad = ad_data[rate]
        delta = ad["ttft"] - al["ttft"]
        winner = "AL" if delta > 0 else "AD"
        if crossover is None and delta <= 0:
            crossover = rate

        print(f"{rate:5.0f} | {al['ttft']:9.3f} {ad['ttft']:9.3f} {delta:8.3f} {winner:>7} | "
              f"{al['e2e']:9.3f} {ad['e2e']:9.3f}")

        ttft_results.append({
            "rate": rate,
            "al_ttft": al["ttft"], "ad_ttft": ad["ttft"],
            "delta_ttft": round(delta, 3),
            "al_e2e": al["e2e"], "ad_e2e": ad["e2e"],
        })

    return ttft_results, crossover


if __name__ == "__main__":
    al_results = main()
    ad_results = ad_al_comparison()
    ttft_results, crossover = ttft_analysis()

    # Combine all evidence
    evidence = json.load(open("final/data/iter3_evidence.json"))
    evidence["ad_comparison"] = ad_results
    evidence["ttft_analysis"] = ttft_results
    evidence["ttft_crossover_rate"] = crossover

    with open("final/data/iter3_evidence.json", "w") as f:
        json.dump(evidence, f, indent=2)
    print(f"\nAll evidence saved to final/data/iter3_evidence.json")
