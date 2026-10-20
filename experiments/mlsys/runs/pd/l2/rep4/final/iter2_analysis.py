#!/usr/bin/env python3
"""
Iteration 2 analysis: test the paper's ITL/TTFT predictions against BLIS
using exact extracted BLIS latency model parameters.

Paper: "When to Disaggregate" — closed-form P/D model under continuous batching.
Key formula: ITL = alpha/(1-rho) + C_0 where rho = (lambda/N_D) * W_tot
"""

import csv
import json
import math
import os
import sys

# =====================================================================
# BLIS LATENCY MODEL PARAMETERS (qwen3-14b on H100, TP=1)
# Extracted from defaults.yaml and model_configs/qwen3-14b/config.json
# =====================================================================

# Alpha coefficients (us)
ALPHA_0 = 15563.199579  # QueueingTime (not in step time)
ALPHA_1 = 777.3455      # PostDecodeFixedOverhead (once per request)
ALPHA_2 = 45.907545     # OutputTokenProcessingTime (per output token)

# Beta coefficients
BETA = [0.152128, 0.0, 1.36252915, 0.752037, 32.09546717,
        4.41684444, 126.024825, 481.8613888, 0.0, 1.94710771]
# Indices: 0=beta1a(pf_compute), 1=beta2a(dc_compute, unused),
#          2=beta3(weight), 3=beta4(tp), 4=beta5(per_layer),
#          5=beta6(per_request), 6=beta7(per_step),
#          7=beta8(moe, unused for dense), 8=beta9(pf_kv, unused),
#          9=beta10(dc_kv)

# Model architecture (qwen3-14b)
NUM_LAYERS = 40
HIDDEN_DIM = 5120
NUM_HEADS = 40
NUM_KV_HEADS = 8
HEAD_DIM = HIDDEN_DIM // NUM_HEADS  # 128
D_KV = NUM_KV_HEADS * HEAD_DIM     # 1024
INTERMEDIATE_DIM = 17408
BYTES_PER_KV = 2.0   # FP16
WEIGHT_BPP = 2.0     # BF16

# Hardware (H100)
FLOPS_PEAK_US = 989.5e6   # FLOP/us
BW_HBM_US = 3.35e6        # bytes/us

# Workload
L_TOKENS = 512   # input tokens
O_TOKENS = 128   # output tokens
N_C = 1          # prefill chunks (always 1 with M=2048, l=512, B<=256)
N_D = 2          # decode instances
N_P = 2          # prefill instances
NUM_REQUESTS = 300
MAX_RUNNING = 256
MAX_SCHED_TOKENS = 2048

TP = 1  # tensor parallelism


# =====================================================================
# COMPUTE BLIS STEP TIME COMPONENTS
# =====================================================================

def compute_weight_loading_time():
    """T_weight: constant weight loading time per step (us)."""
    bytesAttn = NUM_LAYERS * HIDDEN_DIM * (2*HIDDEN_DIM + 2*D_KV) * WEIGHT_BPP / TP
    bytesFfn = NUM_LAYERS * 1 * 3 * HIDDEN_DIM * INTERMEDIATE_DIM * WEIGHT_BPP / TP
    return (bytesAttn + bytesFfn) / BW_HBM_US

def compute_alpha_blis():
    """Per-iteration overhead (constant part of step time, independent of batch)."""
    t_weight = compute_weight_loading_time()
    return BETA[2] * t_weight + BETA[4] * NUM_LAYERS + BETA[6]

def compute_decode_kv_per_request(context):
    """Decode KV bandwidth cost for 1 request at given context (us)."""
    bytes_kv = NUM_LAYERS * 2 * (D_KV / TP) * BYTES_PER_KV * (context + 1)
    return bytes_kv / BW_HBM_US

def compute_prefill_flops(tokens):
    """Prefill compute FLOPs for `tokens` input tokens of a single request."""
    d = HIDDEN_DIM
    dKV = D_KV
    dH = HEAD_DIM
    hPerGPU = NUM_HEADS / TP
    L = NUM_LAYERS

    flopsProj = L * 2 * tokens * d * (2*d + 2*dKV) / TP
    flopsAttn = L * 4 * hPerGPU * tokens * (tokens + tokens/2) * dH
    flopsFfn = L * tokens * 1 * 6 * d * INTERMEDIATE_DIM / TP
    return flopsProj + flopsAttn + flopsFfn


# =====================================================================
# PAPER'S WORK QUANTITIES
# =====================================================================

def compute_W_P():
    """Prefill marginal work W_P (us): cost of adding one request's prefill to the batch."""
    pf_flops = compute_prefill_flops(L_TOKENS)
    t_pf_compute = pf_flops / FLOPS_PEAK_US
    return BETA[0] * t_pf_compute + BETA[5]  # beta1a * compute + beta6

def compute_W_D():
    """Decode marginal work W_D (us): sum of per-step costs across all decode steps."""
    total = 0
    for k in range(1, O_TOKENS + 1):
        ctx = L_TOKENS + k  # context at decode step k
        t_dc_kv = compute_decode_kv_per_request(ctx)
        delta_k = BETA[5] + BETA[9] * t_dc_kv  # beta6 + beta10 * kv
        total += delta_k
    return total

def compute_W_tot():
    """Total per-request work = W_P + W_D (us)."""
    return compute_W_P() + compute_W_D()

def compute_delta_avg():
    """Average per-request per-iteration marginal cost (us)."""
    return compute_W_tot() / (N_C + O_TOKENS)

def compute_C0_itl():
    """Average per-step single-request overhead that appears as C_0 in ITL = T_iter + C_0.
    This includes beta6 + beta10*kv at average context + alpha2."""
    avg_ctx = L_TOKENS + (O_TOKENS + 1) / 2.0
    t_dc_kv = compute_decode_kv_per_request(avg_ctx)
    return BETA[5] + BETA[9] * t_dc_kv + ALPHA_2


# =====================================================================
# PAPER'S PREDICTIONS
# =====================================================================

def predict_itl_paper(lam, W_per_server, alpha):
    """Paper eq 42/45: ITL = alpha/(1-rho) + C_0, rho = lam_per_server * W / 1e6."""
    rho = lam * W_per_server / 1e6
    if rho >= 1.0:
        return float('inf'), rho
    t_iter = alpha / (1 - rho)
    # C_0 accounts for per-request overhead in ITL measurement
    c0 = compute_C0_itl()
    return (t_iter + c0) / 1000.0, rho  # convert to ms

def predict_ttft_al(lam, alpha, W_tot):
    """Paper eq 43: TTFT_AL = T_iter + W_P (prefill work).
    Simplified: at low load, TTFT ≈ QueueingTime + prefill_step_time."""
    rho = (lam / N_D) * W_tot / 1e6
    if rho >= 1.0:
        return float('inf')
    t_iter = alpha / (1 - rho)
    # TTFT in BLIS: QueueingTime + prefill step time + some overhead
    # prefill step time ≈ alpha_blis + prefill compute for 1 request
    pf_flops = compute_prefill_flops(L_TOKENS)
    t_pf_compute = pf_flops / FLOPS_PEAK_US
    pf_step = alpha + BETA[0] * t_pf_compute + BETA[5]
    return (ALPHA_0 + pf_step) / 1000.0  # ms

def predict_ttft_ad(lam, alpha, W_P, W_D):
    """Paper eq 45: TTFT_AD = T_P + W_P + c + Q_D + T_iter_D.
    At low load: TTFT_AD ≈ QueueingTime + prefill_step + KV_transfer + decode_iter."""
    rho_P = (lam / N_P) * W_P / 1e6
    rho_D = (lam / N_D) * W_D / 1e6
    if rho_P >= 1.0 or rho_D >= 1.0:
        return float('inf')
    # Very rough: pipeline overhead + base decode iter
    return float('nan')  # too complex, use measurement


# =====================================================================
# TRANSIENT MODEL
# =====================================================================

def simulate_transient_batch(lam, alpha_us, W_tot_us, n_iters_per_req):
    """Simulate transient batch dynamics with finite 300-request burst.

    Returns: average batch size actually experienced, average ITL.
    """
    per_instance_rate = lam / N_D  # req/s per decode instance
    requests_per_instance = NUM_REQUESTS / N_D  # 150

    # Time for all requests to arrive at this instance
    burst_duration_s = requests_per_instance / per_instance_rate if per_instance_rate > 0 else float('inf')

    # Rough batch dynamics: at time t, B(t) ≈ arrived(t) - completed(t)
    # A request takes n_iters_per_req * T_step(B) to complete
    # This is complex, so estimate average batch size as:
    # avg_B ≈ per_instance_rate * avg_sojourn_time

    # Start with small B, compute step time, compute sojourn, update B
    B = 1.0
    for _ in range(20):  # iterate to convergence
        delta_us = W_tot_us / n_iters_per_req
        step_time_us = alpha_us + delta_us * B
        sojourn_s = n_iters_per_req * step_time_us / 1e6

        # Effective B is limited by how many requests are present
        # Can't exceed requests_per_instance
        new_B = min(per_instance_rate * sojourn_s, requests_per_instance, MAX_RUNNING)
        if abs(new_B - B) < 0.01:
            break
        B = new_B

    # But also limited by burst length: if burst < sojourn, not all requests overlap
    if burst_duration_s < sojourn_s:
        # Not all requests arrive before first ones complete
        # Effective overlap is less
        overlap_fraction = min(1.0, burst_duration_s / sojourn_s)
        B = B * overlap_fraction * 1.2  # rough correction

    step_time_us = alpha_us + compute_W_tot() / n_iters_per_req * B
    itl_us = step_time_us + ALPHA_2
    return B, itl_us / 1000.0  # ms


# =====================================================================
# LOAD AND ANALYZE DATA
# =====================================================================

def parse_output(filepath):
    """Parse BLIS output file and return cluster metrics dict."""
    with open(filepath) as f:
        text = f.read()
    depth = 0; start = -1; results = []
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try: results.append(json.loads(text[start:i+1]))
                except: pass
                start = -1
    for r in reversed(results):
        if r.get('instance_id') == 'cluster':
            return r
    return None


def load_sweep_data():
    """Load rate sweep data from prior iteration."""
    al = []
    ad = []
    with open("final/data/sweep_results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rate = float(row["rate"])
            if rate > 150:
                continue  # only rates 1-150
            rec = (rate, float(row["itl_mean_ms"]), float(row["ttft_mean_ms"]),
                   float(row["e2e_mean_ms"]), int(row["completed"]))
            if row["mode"] == "never":
                al.append(rec)
            else:
                ad.append(rec)
    al.sort(key=lambda x: x[0])
    ad.sort(key=lambda x: x[0])
    return al, ad


def load_multiseed_data():
    """Load multi-seed experiment data."""
    results = {}  # (rate, mode, seed) -> (itl, ttft, e2e)
    msdir = "final/data/multiseed"
    if not os.path.isdir(msdir):
        return results
    for fname in os.listdir(msdir):
        if not fname.endswith(".txt"):
            continue
        # Parse: r{rate}_s{seed}_{mode}.txt
        parts = fname.replace(".txt", "").split("_")
        if len(parts) != 3:
            continue
        rate = int(parts[0][1:])
        seed = int(parts[1][1:])
        mode = parts[2]
        r = parse_output(os.path.join(msdir, fname))
        if r and r.get('completed_requests', 0) > 0:
            results[(rate, mode, seed)] = (r['itl_mean_ms'], r['ttft_mean_ms'], r['e2e_mean_ms'])
    return results


def main():
    # Compute BLIS physical parameters
    alpha_blis = compute_alpha_blis()
    W_P = compute_W_P()
    W_D = compute_W_D()
    W_tot = compute_W_tot()
    delta_avg = compute_delta_avg()
    C0 = compute_C0_itl()

    print("=" * 78)
    print("BLIS PHYSICAL PARAMETERS (qwen3-14b, H100, TP=1)")
    print("=" * 78)
    print(f"alpha_BLIS (per-iteration overhead)  = {alpha_blis:.1f} µs = {alpha_blis/1000:.3f} ms")
    print(f"W_P (prefill marginal work)          = {W_P:.1f} µs = {W_P/1000:.3f} ms")
    print(f"W_D (decode marginal work)           = {W_D:.1f} µs = {W_D/1000:.3f} ms")
    print(f"W_tot (total per-request work)       = {W_tot:.1f} µs = {W_tot/1000:.3f} ms")
    print(f"delta_avg (per-iteration marginal)   = {delta_avg:.2f} µs = {delta_avg/1000:.4f} ms")
    print(f"C_0 (single-request ITL overhead)    = {C0:.1f} µs = {C0/1000:.4f} ms")
    print(f"n_c + o (iterations per request)     = {N_C + O_TOKENS}")
    print(f"")
    print(f"Stability limits (per server):")
    print(f"  AL: lambda_max = N_D * 1e6/W_tot = 2 * {1e6/W_tot:.1f} = {2e6/W_tot:.1f} req/s")
    print(f"  AD: lambda_max(decode) = N_D * 1e6/W_D = 2 * {1e6/W_D:.1f} = {2e6/W_D:.1f} req/s")
    print(f"  AD: lambda_max(prefill) = N_P * 1e6/W_P = 2 * {1e6/W_P:.1f} = {2e6/W_P:.1f} req/s")

    # Zero-load ITL prediction
    itl_zero = (alpha_blis + C0) / 1000.0
    print(f"\nZero-load ITL prediction: alpha + C_0 = {itl_zero:.3f} ms")

    # Load measurement data
    al_data, ad_data = load_sweep_data()
    ms_data = load_multiseed_data()

    print(f"\nLoaded {len(al_data)} AL rate points, {len(ad_data)} AD rate points")
    print(f"Loaded {len(ms_data)} multi-seed measurements")

    # =====================================================================
    # PAPER PREDICTIONS VS BLIS MEASUREMENTS
    # =====================================================================
    print("\n" + "=" * 78)
    print("PAPER ITL PREDICTIONS (exact BLIS params) vs MEASUREMENTS")
    print("=" * 78)
    print(f"{'Rate':>5} {'ρ_AL':>7} {'ρ_AD':>7} | {'AL_pred':>8} {'AL_meas':>8} {'err%':>7} | "
          f"{'AD_pred':>8} {'AD_meas':>8} {'err%':>7} | {'AL-AD':>6}")

    results_table = []
    for i, al in enumerate(al_data):
        rate = al[0]
        ad_match = [p for p in ad_data if p[0] == rate]
        if not ad_match:
            continue
        ad = ad_match[0]

        # Per-instance rate
        lam_d = rate / N_D  # per decode instance

        # Paper predictions
        al_pred, rho_al = predict_itl_paper(lam_d, W_tot, alpha_blis)
        ad_pred, rho_ad = predict_itl_paper(lam_d, W_D, alpha_blis)

        al_meas = al[1]
        ad_meas = ad[1]

        al_err = (al_pred - al_meas) / al_meas * 100 if al_meas > 0 and al_pred < 1e5 else float('inf')
        ad_err = (ad_pred - ad_meas) / ad_meas * 100 if ad_meas > 0 and ad_pred < 1e5 else float('inf')

        al_p_s = f"{al_pred:.3f}" if al_pred < 1e5 else "UNSTABLE"
        ad_p_s = f"{ad_pred:.3f}" if ad_pred < 1e5 else "UNSTABLE"

        diff = al_meas - ad_meas

        print(f"{rate:5.0f} {rho_al:7.4f} {rho_ad:7.4f} | {al_p_s:>8} {al_meas:8.3f} {al_err:7.1f} | "
              f"{ad_p_s:>8} {ad_meas:8.3f} {ad_err:7.1f} | {diff:6.3f}")

        results_table.append({
            "rate": rate, "rho_al": rho_al, "rho_ad": rho_ad,
            "al_pred": al_pred if al_pred < 1e5 else None,
            "al_meas": al_meas, "ad_pred": ad_pred if ad_pred < 1e5 else None,
            "ad_meas": ad_meas, "al_err_pct": al_err if al_err < 1e5 else None,
            "ad_err_pct": ad_err if ad_err < 1e5 else None,
            "al_minus_ad_meas": diff
        })

    # =====================================================================
    # EMPIRICAL FIT: find effective W that matches data
    # =====================================================================
    print("\n" + "=" * 78)
    print("EFFECTIVE W_eff FIT: ITL = alpha/(1 - (lam/N_D)*W_eff/1e6) + C_0")
    print("=" * 78)

    def fit_W_eff(data, alpha_us, c0_us):
        """Find W_eff that minimizes RMSE for ITL = alpha/(1-rho) + C0/1000."""
        best_sse = float('inf')
        best_W = None
        for W_test in [x * 10 for x in range(1, 2000)]:  # 10 to 20000 us
            sse = 0
            for rate, itl, _, _, _ in data:
                lam_d = rate / N_D
                rho = lam_d * W_test / 1e6
                if rho >= 0.99:
                    sse = float('inf')
                    break
                pred = (alpha_us / (1 - rho) + c0_us) / 1000.0
                sse += (itl - pred) ** 2
            if sse < best_sse:
                best_sse = sse
                best_W = W_test
        # Fine search
        if best_W is not None:
            for W_test in [best_W + x * 0.5 for x in range(-20, 21)]:
                if W_test <= 0:
                    continue
                sse = 0
                for rate, itl, _, _, _ in data:
                    lam_d = rate / N_D
                    rho = lam_d * W_test / 1e6
                    if rho >= 0.99:
                        sse = float('inf')
                        break
                    pred = (alpha_us / (1 - rho) + c0_us) / 1000.0
                    sse += (itl - pred) ** 2
                if sse < best_sse:
                    best_sse = sse
                    best_W = W_test
        rmse = math.sqrt(best_sse / len(data)) if best_sse < float('inf') else float('inf')
        return best_W, rmse

    W_eff_al, rmse_al = fit_W_eff(al_data, alpha_blis, C0)
    W_eff_ad, rmse_ad = fit_W_eff(ad_data, alpha_blis, C0)

    print(f"AL: W_eff = {W_eff_al:.1f} µs ({W_eff_al/1000:.3f} ms), RMSE = {rmse_al:.4f} ms")
    print(f"    vs physical W_tot = {W_tot:.1f} µs ({W_tot/1000:.3f} ms)")
    print(f"    ratio: physical/effective = {W_tot/W_eff_al:.2f}x")
    print(f"AD: W_eff = {W_eff_ad:.1f} µs ({W_eff_ad/1000:.3f} ms), RMSE = {rmse_ad:.4f} ms")
    print(f"    vs physical W_D = {W_D:.1f} µs ({W_D/1000:.3f} ms)")
    print(f"    ratio: physical/effective = {W_D/W_eff_ad:.2f}x")

    # =====================================================================
    # ALSO FIT LINEAR MODEL FOR COMPARISON
    # =====================================================================
    def fit_linear(data):
        n = len(data)
        sx = sum(r for r, _, _, _, _ in data)
        sy = sum(itl for _, itl, _, _, _ in data)
        sxy = sum(r * itl for r, itl, _, _, _ in data)
        sxx = sum(r ** 2 for r, _, _, _, _ in data)
        b = (n * sxy - sx * sy) / (n * sxx - sx ** 2)
        a = (sy - b * sx) / n
        sse = sum((itl - (a + b * r)) ** 2 for r, itl, _, _, _ in data)
        return a, b, math.sqrt(sse / n)

    al_lin = fit_linear(al_data)
    ad_lin = fit_linear(ad_data)
    print(f"\nLinear fit comparison (rates 1-150):")
    print(f"  AL: ITL = {al_lin[0]:.4f} + {al_lin[1]:.6f}*λ, RMSE = {al_lin[2]:.4f} ms")
    print(f"  AD: ITL = {ad_lin[0]:.4f} + {ad_lin[1]:.6f}*λ, RMSE = {ad_lin[2]:.4f} ms")

    # =====================================================================
    # TRANSIENT ANALYSIS: WHY LITTLE'S LAW BREAKS DOWN
    # =====================================================================
    print("\n" + "=" * 78)
    print("TRANSIENT ANALYSIS: STEADY-STATE BATCH SIZE vs REALITY")
    print("=" * 78)
    print(f"{'Rate':>5} {'B_ss':>8} {'B_max':>8} {'B_ratio':>8} | "
          f"{'ITL_ss':>8} {'ITL_meas':>8} {'ρ_eff':>7}")

    n_iters = N_C + O_TOKENS  # 129

    transient_analysis = []
    for al in al_data:
        rate = al[0]
        lam_d = rate / N_D
        rho = lam_d * W_tot / 1e6

        # Steady-state batch size from Little's law
        if rho < 1:
            t_iter_ss = alpha_blis / (1 - rho)
            B_ss = lam_d * n_iters * t_iter_ss / 1e6
        else:
            B_ss = float('inf')
            t_iter_ss = float('inf')

        # Maximum possible batch size (limited by requests per instance)
        B_max = min(NUM_REQUESTS / N_D, MAX_RUNNING)

        # Effective rho from measurement: ITL = alpha/(1-rho_eff) + C0
        itl_meas = al[1]
        itl_us = itl_meas * 1000
        # alpha/(1-rho_eff) = itl_us - C0
        t_iter_eff = itl_us - C0
        if t_iter_eff > alpha_blis:
            rho_eff = 1 - alpha_blis / t_iter_eff
        else:
            rho_eff = 0

        B_ss_s = f"{B_ss:.1f}" if B_ss < 1e5 else "INF"
        ratio = B_ss / B_max if B_ss < 1e5 else float('inf')
        ratio_s = f"{ratio:.2f}" if ratio < 100 else "INF"

        itl_ss_ms = (t_iter_ss + C0) / 1000 if t_iter_ss < 1e10 else float('inf')
        itl_ss_s = f"{itl_ss_ms:.3f}" if itl_ss_ms < 1e5 else "UNSTABLE"

        print(f"{rate:5.0f} {B_ss_s:>8} {B_max:8.0f} {ratio_s:>8} | "
              f"{itl_ss_s:>8} {itl_meas:8.3f} {rho_eff:7.4f}")

        transient_analysis.append({
            "rate": rate,
            "B_steady_state": B_ss if B_ss < 1e5 else None,
            "B_max_possible": B_max,
            "rho_theoretical": rho,
            "rho_effective": rho_eff,
            "itl_steady_state_ms": itl_ss_ms if itl_ss_ms < 1e5 else None,
            "itl_measured_ms": itl_meas,
        })

    # =====================================================================
    # EFFECTIVE BATCH SIZE BACK-CALCULATION
    # =====================================================================
    print("\n" + "=" * 78)
    print("EFFECTIVE BATCH SIZE FROM MEASUREMENTS")
    print("=" * 78)
    print(f"{'Rate':>5} {'B_eff':>8} {'B_ss':>8} {'B_ratio':>8} {'Comment':>30}")

    for al in al_data:
        rate = al[0]
        lam_d = rate / N_D
        itl_us = al[1] * 1000
        # T_iter = ITL - C0 (approximately)
        t_iter = itl_us - C0
        # T_iter = alpha + delta * B_eff
        # B_eff = (T_iter - alpha) / delta_avg
        if t_iter > alpha_blis:
            B_eff = (t_iter - alpha_blis) / delta_avg
        else:
            B_eff = 0

        rho = lam_d * W_tot / 1e6
        if rho < 1:
            B_ss = lam_d * n_iters * (alpha_blis / (1 - rho)) / 1e6
        else:
            B_ss = float('inf')

        B_ss_s = f"{B_ss:.1f}" if B_ss < 1e5 else "INF"
        ratio = B_eff / B_ss if B_ss > 0 and B_ss < 1e5 else 0

        comment = ""
        if B_eff < 5:
            comment = "near-empty batch"
        elif ratio < 0.3:
            comment = "far below steady state"
        elif ratio < 0.7:
            comment = "partially toward steady state"
        else:
            comment = "near steady state"

        print(f"{rate:5.0f} {B_eff:8.1f} {B_ss_s:>8} {ratio:8.3f} {comment:>30}")

    # =====================================================================
    # MULTI-SEED VARIANCE
    # =====================================================================
    if ms_data:
        print("\n" + "=" * 78)
        print("MULTI-SEED VARIANCE ANALYSIS")
        print("=" * 78)
        print(f"{'Rate':>5} {'Mode':>8} | {'Mean ITL':>9} {'Std ITL':>9} {'CV%':>6} | "
              f"{'Mean TTFT':>10} {'Std TTFT':>10}")

        for rate in [50, 100, 150]:
            for mode in ["never", "always"]:
                itls = []
                ttfts = []
                for seed in [42, 43, 44, 45, 46]:
                    key = (rate, mode, seed)
                    if key in ms_data:
                        itls.append(ms_data[key][0])
                        ttfts.append(ms_data[key][1])
                if len(itls) >= 2:
                    mean_itl = sum(itls) / len(itls)
                    std_itl = math.sqrt(sum((x - mean_itl)**2 for x in itls) / (len(itls) - 1))
                    cv = std_itl / mean_itl * 100
                    mean_ttft = sum(ttfts) / len(ttfts)
                    std_ttft = math.sqrt(sum((x - mean_ttft)**2 for x in ttfts) / (len(ttfts) - 1))
                    label = "AL" if mode == "never" else "AD"
                    print(f"{rate:5} {label:>8} | {mean_itl:9.3f} {std_itl:9.4f} {cv:6.2f} | "
                          f"{mean_ttft:10.3f} {std_ttft:10.4f}")

    # =====================================================================
    # TTFT COMPARISON
    # =====================================================================
    print("\n" + "=" * 78)
    print("TTFT: AL vs AD (rates 1-150)")
    print("=" * 78)
    print(f"{'Rate':>5} {'AL_TTFT':>9} {'AD_TTFT':>9} {'ΔT(AD-AL)':>10} {'Winner':>8}")

    ttft_crossover = None
    for al in al_data:
        rate = al[0]
        ad_match = [p for p in ad_data if p[0] == rate]
        if not ad_match:
            continue
        al_ttft = al[2]
        ad_ttft = ad_match[0][2]
        delta = ad_ttft - al_ttft
        winner = "AL" if delta > 0 else "AD"
        if ttft_crossover is None and delta <= 0:
            ttft_crossover = rate
        print(f"{rate:5.0f} {al_ttft:9.3f} {ad_ttft:9.3f} {delta:10.3f} {winner:>8}")

    # =====================================================================
    # KEY FINDINGS
    # =====================================================================
    print("\n" + "=" * 78)
    print("KEY FINDINGS")
    print("=" * 78)

    # 1. ITL formula accuracy by utilization range
    low_rho = [r for r in results_table if r["rho_al"] < 0.10 and r["al_err_pct"] is not None]
    mid_rho = [r for r in results_table if 0.10 <= r["rho_al"] < 0.30 and r["al_err_pct"] is not None]
    high_rho = [r for r in results_table if r["rho_al"] >= 0.30 and r["al_err_pct"] is not None]

    if low_rho:
        max_err_low = max(abs(r["al_err_pct"]) for r in low_rho)
        print(f"\n1. ITL formula accuracy by utilization:")
        print(f"   Low ρ (<0.10, rates≤{max(r['rate'] for r in low_rho):.0f}): max |error| = {max_err_low:.1f}%")
    if mid_rho:
        max_err_mid = max(abs(r["al_err_pct"]) for r in mid_rho)
        print(f"   Mid ρ (0.10-0.30, rates {min(r['rate'] for r in mid_rho):.0f}-{max(r['rate'] for r in mid_rho):.0f}): max |error| = {max_err_mid:.1f}%")
    if high_rho:
        max_err_high = max(abs(r["al_err_pct"]) for r in high_rho)
        print(f"   High ρ (≥0.30, rates {min(r['rate'] for r in high_rho):.0f}-{max(r['rate'] for r in high_rho):.0f}): max |error| = {max_err_high:.1f}%")

    # 2. AD always lower ITL
    ad_lower = all(r["al_minus_ad_meas"] >= -0.001 for r in results_table)
    max_diff = max(r["al_minus_ad_meas"] for r in results_table)
    print(f"\n2. AD ITL < AL ITL at all rates: {ad_lower}")
    print(f"   Max difference (AL - AD): {max_diff:.3f} ms at rate={[r['rate'] for r in results_table if abs(r['al_minus_ad_meas'] - max_diff) < 0.001][0]:.0f}")

    # 3. TTFT crossover
    if ttft_crossover:
        print(f"\n3. TTFT crossover: AD TTFT < AL TTFT starting at rate≈{ttft_crossover}")
    else:
        print(f"\n3. AD TTFT > AL TTFT at all rates 1-150 (no crossover in range)")

    # 4. Effective vs theoretical W
    print(f"\n4. Work parameter mismatch:")
    print(f"   Physical W_tot = {W_tot/1000:.3f} ms  →  predicts instability at λ={2e6/W_tot:.0f} req/s")
    print(f"   Effective W_eff = {W_eff_al/1000:.3f} ms  →  predicts instability at λ={2e6/W_eff_al:.0f} req/s")
    print(f"   Ratio = {W_tot/W_eff_al:.1f}x — the system acts as if each request contributes")
    print(f"   {W_tot/W_eff_al:.1f}x less work than the physical model predicts.")
    print(f"   ROOT CAUSE: 300-request finite horizon prevents batch sizes from")
    print(f"   reaching Little's law steady state. Effective batch sizes are")
    print(f"   {W_tot/W_eff_al:.1f}x smaller than predicted.")

    # =====================================================================
    # SAVE EVIDENCE
    # =====================================================================
    evidence = {
        "physical_params": {
            "alpha_blis_us": alpha_blis,
            "alpha_blis_ms": alpha_blis / 1000,
            "W_P_us": W_P,
            "W_P_ms": W_P / 1000,
            "W_D_us": W_D,
            "W_D_ms": W_D / 1000,
            "W_tot_us": W_tot,
            "W_tot_ms": W_tot / 1000,
            "C0_us": C0,
            "C0_ms": C0 / 1000,
            "delta_avg_us": delta_avg,
            "n_iters_per_request": N_C + O_TOKENS,
        },
        "effective_params": {
            "W_eff_al_us": W_eff_al,
            "W_eff_al_ms": W_eff_al / 1000,
            "W_eff_ad_us": W_eff_ad,
            "W_eff_ad_ms": W_eff_ad / 1000,
            "physical_to_effective_ratio_al": W_tot / W_eff_al,
            "physical_to_effective_ratio_ad": W_D / W_eff_ad,
        },
        "fit_quality": {
            "paper_with_W_eff_rmse_al_ms": rmse_al,
            "paper_with_W_eff_rmse_ad_ms": rmse_ad,
            "linear_rmse_al_ms": al_lin[2],
            "linear_rmse_ad_ms": ad_lin[2],
        },
        "predictions_vs_measurements": results_table,
        "transient_analysis": transient_analysis,
        "ad_always_lower_itl": ad_lower,
        "max_itl_diff_al_ad_ms": max_diff,
        "ttft_crossover_rate": ttft_crossover,
    }

    # Add multi-seed stats if available
    if ms_data:
        ms_stats = {}
        for rate in [50, 100, 150]:
            for mode in ["never", "always"]:
                itls = [ms_data[(rate, mode, s)][0] for s in [42,43,44,45,46] if (rate, mode, s) in ms_data]
                if len(itls) >= 2:
                    mean = sum(itls) / len(itls)
                    std = math.sqrt(sum((x - mean)**2 for x in itls) / (len(itls) - 1))
                    label = f"{'al' if mode == 'never' else 'ad'}_rate{rate}"
                    ms_stats[label] = {"mean": mean, "std": std, "cv_pct": std/mean*100, "n": len(itls)}
        evidence["multiseed_stats"] = ms_stats

    with open("final/data/iter2_evidence.json", "w") as f:
        json.dump(evidence, f, indent=2)
    print(f"\nEvidence saved to final/data/iter2_evidence.json")


if __name__ == "__main__":
    main()
