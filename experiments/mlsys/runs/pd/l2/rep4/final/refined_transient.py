#!/usr/bin/env python3
"""
Refined transient model with variable per-step costs:
- Prefill step: request contributes W_P to step time (heavy burst)
- Decode step k: request contributes delta_decode(k) (varies with context)
- Tracks actual request states (prefill vs decode + step number)
"""

import math
import json
import csv

# BLIS parameters
ALPHA_US = 12157.2
N_ITERS = 129  # 1 prefill + 128 decode
N_D = 2
NUM_REQUESTS = 300
C0_US = 105.3

# Prefill cost: work added to step time by one prefill request (512 tokens)
# = beta1a * prefill_FLOPs / flopsPeakUs + beta6
W_P_STEP = 2133.9  # us (from iter2 analysis)

# Beta parameters for decode
BETA_6 = 4.41684444     # per-request scheduling overhead (us)
BETA_10 = 1.94710771    # decode memory correction

# KV bandwidth constants for qwen3-14b
# tDcKv = L * 2 * (dKV/tp) * 2 * (ctx + 1) / bwHbmUs
# = 40 * 2 * 1024 * 2 * (ctx+1) / 3350000
# = 163840 * (ctx+1) / 3350000
KV_COEFF = 163840.0 / 3350000.0  # us per (ctx+1)

L_TOKENS = 512
O_TOKENS = 128


def decode_delta(k):
    """Marginal cost of one decode request at step k (1-indexed) in us."""
    ctx = L_TOKENS + k  # context at decode step k
    t_dc_kv = KV_COEFF * (ctx + 1)
    return BETA_6 + BETA_10 * t_dc_kv


def simulate_refined(lam, use_poisson=False, seed=42):
    """Simulate with separate prefill/decode costs per request.

    Each request state: (step_number, is_prefill)
    step 0 = prefill, steps 1..128 = decode 1..128
    """
    import random
    rng = random.Random(seed)

    per_inst_rate = lam / N_D
    reqs_per_inst = NUM_REQUESTS // N_D

    if per_inst_rate <= 0:
        return 0, ALPHA_US + C0_US, (ALPHA_US + C0_US) / 1000

    # Generate arrival times
    if use_poisson:
        arrivals = []
        t = 0
        for _ in range(reqs_per_inst):
            t += rng.expovariate(per_inst_rate) * 1e6  # us
            arrivals.append(t)
    else:
        inter = 1e6 / per_inst_rate
        arrivals = [i * inter for i in range(reqs_per_inst)]

    # State: list of (decode_step, arrival_time) for each active request
    # decode_step=0 means prefill, 1..128 means decode step 1..128
    active = []  # [(step, arrival_time)]
    next_arr = 0
    current_time = 0.0

    total_step_time = 0.0
    total_weighted_batch = 0.0
    num_steps = 0

    while active or next_arr < reqs_per_inst:
        # Admit new arrivals
        while next_arr < reqs_per_inst and arrivals[next_arr] <= current_time:
            active.append(0)  # step 0 = prefill
            next_arr += 1

        if not active:
            if next_arr < reqs_per_inst:
                current_time = arrivals[next_arr]
                continue
            else:
                break

        # Compute step time
        B = len(active)
        marginal_cost = 0.0
        for step in active:
            if step == 0:
                marginal_cost += W_P_STEP
            else:
                marginal_cost += decode_delta(step)

        step_time = ALPHA_US + marginal_cost
        total_step_time += step_time
        total_weighted_batch += B * step_time
        num_steps += 1

        current_time += step_time

        # Advance each request
        new_active = []
        for step in active:
            if step < O_TOKENS:  # not yet complete
                new_active.append(step + 1)
        active = new_active

    avg_batch = total_weighted_batch / total_step_time if total_step_time > 0 else 0
    avg_step = total_step_time / num_steps if num_steps > 0 else ALPHA_US
    avg_itl = avg_step + C0_US

    return avg_batch, avg_step, avg_itl / 1000.0


def paper_ss(lam):
    W_tot = W_P_STEP + sum(decode_delta(k) for k in range(1, O_TOKENS + 1))
    rho = (lam / N_D) * W_tot / 1e6
    if rho >= 1:
        return float('inf'), float('inf'), float('inf')
    t_iter = ALPHA_US / (1 - rho)
    B = (lam / N_D) * N_ITERS * t_iter / 1e6
    itl = (t_iter + C0_US) / 1000
    return B, t_iter, itl


def main():
    al_data = {}
    with open("final/data/sweep_results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["mode"] == "never" and float(row["rate"]) <= 150:
                al_data[float(row["rate"])] = float(row["itl_mean_ms"])

    rates = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]

    print("=" * 105)
    print("REFINED TRANSIENT MODEL (variable prefill/decode costs)")
    print("=" * 105)
    print(f"{'Rate':>5} | {'B_ref':>7} {'B_ss':>7} | {'ITL_det':>8} {'ITL_poi':>8} {'ITL_ss':>8} {'ITL_meas':>8} | "
          f"{'det_e%':>7} {'poi_e%':>7} {'ss_e%':>7}")

    results = []
    for rate in rates:
        B_det, _, itl_det = simulate_refined(rate, use_poisson=False)
        _, _, itl_poi_sum = 0, 0, 0
        # Average over 5 Poisson seeds
        poi_itls = []
        for seed in range(42, 47):
            _, _, itl_p = simulate_refined(rate, use_poisson=True, seed=seed)
            poi_itls.append(itl_p)
        itl_poi = sum(poi_itls) / len(poi_itls)

        B_ss, _, itl_ss = paper_ss(rate)
        itl_meas = al_data.get(rate, float('nan'))

        det_err = (itl_det - itl_meas) / itl_meas * 100 if not math.isnan(itl_meas) else 0
        poi_err = (itl_poi - itl_meas) / itl_meas * 100 if not math.isnan(itl_meas) else 0
        ss_err = (itl_ss - itl_meas) / itl_meas * 100 if not math.isnan(itl_meas) and itl_ss < 1e5 else float('inf')

        B_ss_s = f"{B_ss:.1f}" if B_ss < 1e5 else "INF"
        itl_ss_s = f"{itl_ss:.3f}" if itl_ss < 1e5 else "UNSTABLE"
        ss_err_s = f"{ss_err:.1f}" if ss_err < 1e5 else "INF"

        print(f"{rate:5} | {B_det:7.1f} {B_ss_s:>7} | {itl_det:8.3f} {itl_poi:8.3f} {itl_ss_s:>8} {itl_meas:8.3f} | "
              f"{det_err:7.1f} {poi_err:7.1f} {ss_err_s:>7}")

        results.append({
            "rate": rate,
            "itl_deterministic_ms": round(itl_det, 3),
            "itl_poisson_avg_ms": round(itl_poi, 3),
            "itl_steady_state_ms": round(itl_ss, 3) if itl_ss < 1e5 else None,
            "itl_measured_ms": round(itl_meas, 3) if not math.isnan(itl_meas) else None,
            "det_error_pct": round(det_err, 2),
            "poi_error_pct": round(poi_err, 2),
            "ss_error_pct": round(ss_err, 2) if ss_err < 1e5 else None,
            "B_simulated": round(B_det, 1),
        })

    # Summary
    print("\n" + "=" * 60)
    print("MODEL COMPARISON SUMMARY (rates 1-150)")
    print("=" * 60)
    valid = [r for r in results if r["itl_measured_ms"] is not None]
    for model, key in [("Deterministic transient", "det_error_pct"),
                       ("Poisson transient (5-seed avg)", "poi_error_pct"),
                       ("Steady-state formula", "ss_error_pct")]:
        errs = [abs(r[key]) for r in valid if r[key] is not None]
        if errs:
            rmse = math.sqrt(sum(e**2 for e in errs) / len(errs))
            maxe = max(errs)
            mae = sum(errs) / len(errs)
            print(f"  {model:35}: RMSE={rmse:6.2f}%  MAE={mae:5.2f}%  Max={maxe:6.1f}%")

    # Key: at what rate does the Poisson transient model diverge?
    for r in valid:
        if r["poi_error_pct"] is not None and abs(r["poi_error_pct"]) > 3:
            print(f"\n  Poisson transient exceeds 3% error at rate={r['rate']}")
            break

    with open("final/data/refined_transient_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved to final/data/refined_transient_results.json")


if __name__ == "__main__":
    main()
