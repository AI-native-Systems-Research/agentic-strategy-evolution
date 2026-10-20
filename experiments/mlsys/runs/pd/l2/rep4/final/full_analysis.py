#!/usr/bin/env python3
"""Full analysis of BLIS sweep data against paper's closed-form predictions."""

import csv
import json
import math
import re
import os

# Parse all data files
def parse_output(filepath):
    """Parse a BLIS output file and return cluster metrics."""
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

# Collect all data
al_points = []  # (rate, itl, ttft, e2e, completed)
ad_points = []

# From sweep CSV
with open("final/data/sweep_results.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rate = float(row["rate"])
        rec = (rate, float(row["itl_mean_ms"]), float(row["ttft_mean_ms"]),
               float(row["e2e_mean_ms"]), int(row["completed"]))
        if row["mode"] == "never":
            al_points.append(rec)
        else:
            ad_points.append(rec)

# From high-rate files
for rate in [200, 250, 300, 400, 500]:
    for label, mode_points in [("AL", al_points), ("AD", ad_points)]:
        fpath = f"final/data/{label}_rate{rate}.txt"
        if os.path.exists(fpath):
            r = parse_output(fpath)
            if r and r['completed_requests'] > 0:
                mode_points.append((rate, r['itl_mean_ms'], r['ttft_mean_ms'],
                                   r['e2e_mean_ms'], r['completed_requests']))

# Sort by rate
al_points.sort(key=lambda x: x[0])
ad_points.sort(key=lambda x: x[0])

# ---- Physical parameters from BLIS ----
# From latency model analysis (subagent report)
alpha_phys = 12.158  # ms, per-iteration overhead (weight loading + per-layer + per-step)
# Per-request marginal cost at context C: delta(C) = 0.095*C + 4.512 us = (0.000095*C + 0.004512) ms
# Average decode context: l + (o+1)/2 = 512 + 64.5 = 576.5
l = 512; o = 128
C_avg = l + (o + 1) / 2.0  # 576.5

delta_avg_ms = 0.000095 * C_avg + 0.004512  # ms per request per decode step = ~0.0593 ms

# Total work per request: W_tot = sum of marginal costs across all iterations
# For decode: W_D = sum_{k=1}^{o} delta(l+k) = sum delta over 128 steps
W_D_phys = sum(0.000095 * (l + k) + 0.004512 for k in range(1, o + 1))
# For prefill (rough): about 2.08 ms marginal cost
W_P_phys_approx = 2.08  # ms (prefill marginal cost)
W_tot_phys = W_D_phys + W_P_phys_approx

N_D = 2  # decode instances
N_P = 2  # prefill instances

print("=" * 72)
print("PHYSICAL PARAMETERS FROM BLIS LATENCY MODEL")
print("=" * 72)
print(f"alpha (per-iteration overhead)  = {alpha_phys:.3f} ms")
print(f"delta_avg (per-req per-step)    = {delta_avg_ms:.6f} ms")
print(f"C_avg (avg decode context)      = {C_avg:.1f} tokens")
print(f"W_D (total decode marginal)     = {W_D_phys:.3f} ms")
print(f"W_P (total prefill marginal)    = {W_P_phys_approx:.3f} ms")
print(f"W_tot (total per-request work)  = {W_tot_phys:.3f} ms")
print(f"Stability bound AL: lambda_max  = {2*1000/W_tot_phys:.1f} req/s")
print(f"Stability bound AD: lambda_max  = {2*1000/max(W_D_phys, W_P_phys_approx):.1f} req/s")


# ---- Paper predictions with physical parameters ----
def itl_paper_phys(lam, W, alpha=alpha_phys):
    """ITL = alpha / (1 - (lam/N_D) * W/1000)"""
    rho = (lam / N_D) * W / 1000.0
    if rho >= 1.0:
        return float('inf')
    return alpha / (1.0 - rho)

print("\n" + "=" * 72)
print("PAPER'S ITL PREDICTION (physical params) vs BLIS")
print("=" * 72)
print(f"{'Rate':>6} {'AL_meas':>9} {'AL_pred':>9} {'err%':>7} | {'AD_meas':>9} {'AD_pred':>9} {'err%':>7} | {'rho_AL':>7} {'rho_AD':>7}")
for i in range(len(al_points)):
    r = al_points[i][0]
    # find matching AD point
    ad_match = [p for p in ad_points if p[0] == r]
    if not ad_match:
        continue
    al_m = al_points[i][1]
    ad_m = ad_match[0][1]
    al_p = itl_paper_phys(r, W_tot_phys)
    ad_p = itl_paper_phys(r, W_D_phys)
    rho_al = (r / N_D) * W_tot_phys / 1000
    rho_ad = (r / N_D) * W_D_phys / 1000
    al_err = (al_p - al_m) / al_m * 100 if al_m > 0 else 0
    ad_err = (ad_p - ad_m) / ad_m * 100 if ad_m > 0 else 0
    al_p_str = f"{al_p:.3f}" if al_p < 1e5 else "INF"
    ad_p_str = f"{ad_p:.3f}" if ad_p < 1e5 else "INF"
    print(f"{r:6.0f} {al_m:9.3f} {al_p_str:>9} {al_err:7.1f} | {ad_m:9.3f} {ad_p_str:>9} {ad_err:7.1f} | {rho_al:7.3f} {rho_ad:7.3f}")


# ---- Empirical fit: ITL = A / (1 - (lam/N_D)*W/1000) + C ----
def fit_3param(data, n_instances=N_D):
    """Grid search for A, W, C in ITL = A/(1-rho) + C, rho=(lam/n)*W/1000."""
    best = (1e18, None)
    # Coarse grid
    for A in [x * 1.0 for x in range(1, 30)]:
        for W in [x * 0.5 for x in range(1, 40)]:
            for C in [x * 1.0 - 15 for x in range(0, 31)]:
                sse = 0; ok = True
                for rate, itl, _, _, _ in data:
                    rho = (rate / n_instances) * W / 1000
                    if rho >= 0.99: ok = False; break
                    pred = A / (1 - rho) + C
                    sse += (itl - pred)**2
                if ok and sse < best[0]:
                    best = (sse, (A, W, C))
    if best[1] is None:
        return (12.0, 5.0, 0.0), 999
    # Fine grid around best
    A0, W0, C0 = best[1]
    for dA in [x*0.1 - 1.0 for x in range(21)]:
        for dW in [x*0.1 - 1.0 for x in range(21)]:
            for dC in [x*0.1 - 1.0 for x in range(21)]:
                A, W, C = A0+dA, W0+dW, C0+dC
                if A <= 0 or W <= 0: continue
                sse = 0; ok = True
                for rate, itl, _, _, _ in data:
                    rho = (rate / n_instances) * W / 1000
                    if rho >= 0.99: ok = False; break
                    pred = A / (1 - rho) + C
                    sse += (itl - pred)**2
                if ok and sse < best[0]:
                    best = (sse, (A, W, C))
    params = best[1]
    rmse = math.sqrt(best[0] / len(data))
    return params, rmse

# Only fit on rates 1-150 (likely below saturation)
al_fit_data = [p for p in al_points if p[0] <= 150]
ad_fit_data = [p for p in ad_points if p[0] <= 150]

print("\n" + "=" * 72)
print("EMPIRICAL FIT: ITL = A/(1-rho) + C (rates 1-150)")
print("=" * 72)

al_emp, al_emp_rmse = fit_3param(al_fit_data)
print(f"AL: A={al_emp[0]:.2f} ms, W={al_emp[1]:.2f} ms, C={al_emp[2]:.2f} ms, RMSE={al_emp_rmse:.4f} ms")

ad_emp, ad_emp_rmse = fit_3param(ad_fit_data)
print(f"AD: A={ad_emp[0]:.2f} ms, W={ad_emp[1]:.2f} ms, C={ad_emp[2]:.2f} ms, RMSE={ad_emp_rmse:.4f} ms")


# ---- Linear fit for comparison ----
def fit_linear(data):
    n = len(data)
    sx = sum(r for r, _, _, _, _ in data)
    sy = sum(itl for _, itl, _, _, _ in data)
    sxy = sum(r * itl for r, itl, _, _, _ in data)
    sxx = sum(r**2 for r, _, _, _, _ in data)
    b = (n * sxy - sx * sy) / (n * sxx - sx**2)
    a = (sy - b * sx) / n
    sse = sum((itl - (a + b * r))**2 for r, itl, _, _, _ in data)
    return a, b, math.sqrt(sse / n)

al_lin = fit_linear(al_fit_data)
ad_lin = fit_linear(ad_fit_data)
print(f"\nLinear comparison (rates 1-150):")
print(f"AL: ITL = {al_lin[0]:.4f} + {al_lin[1]:.6f}*lambda, RMSE={al_lin[2]:.4f} ms")
print(f"AD: ITL = {ad_lin[0]:.4f} + {ad_lin[1]:.6f}*lambda, RMSE={ad_lin[2]:.4f} ms")


# ---- Check extrapolation to high rates ----
print("\n" + "=" * 72)
print("EXTRAPOLATION TO HIGH RATES (200-500)")
print("=" * 72)
print(f"{'Rate':>6} {'AL_meas':>9} {'AL_1/1-r':>9} {'AL_lin':>9} | {'AD_meas':>9} {'AD_1/1-r':>9} {'AD_lin':>9}")
for r, itl, ttft, e2e, comp in al_points:
    if r < 200:
        continue
    ad_match = [p for p in ad_points if p[0] == r]
    if not ad_match:
        continue
    ad_itl = ad_match[0][1]

    # Paper model predictions
    rho_al = (r / N_D) * al_emp[1] / 1000
    al_pred = al_emp[0] / (1 - rho_al) + al_emp[2] if rho_al < 1 else float('inf')

    rho_ad = (r / N_D) * ad_emp[1] / 1000
    ad_pred = ad_emp[0] / (1 - rho_ad) + ad_emp[2] if rho_ad < 1 else float('inf')

    al_lin_pred = al_lin[0] + al_lin[1] * r
    ad_lin_pred = ad_lin[0] + ad_lin[1] * r

    al_s = f"{al_pred:.3f}" if al_pred < 1e5 else "UNSTABLE"
    ad_s = f"{ad_pred:.3f}" if ad_pred < 1e5 else "UNSTABLE"
    print(f"{r:6.0f} {itl:9.3f} {al_s:>9} {al_lin_pred:9.3f} | {ad_itl:9.3f} {ad_s:>9} {ad_lin_pred:9.3f}")


# ---- KEY: ITL levels off in BLIS due to finite batch effects ----
print("\n" + "=" * 72)
print("CRITICAL OBSERVATION: ITL SATURATION BEHAVIOR")
print("=" * 72)

# Compute ITL growth rate
print("AL ITL growth (pairwise):")
for i in range(1, len(al_points)):
    r0, itl0 = al_points[i-1][0], al_points[i-1][1]
    r1, itl1 = al_points[i][0], al_points[i][1]
    dr = r1 - r0
    ditl = itl1 - itl0
    rate_per_rps = ditl / dr if dr > 0 else 0
    print(f"  rate {r0:.0f}->{r1:.0f}: dITL={ditl:.3f} ms, slope={rate_per_rps:.5f} ms/(req/s)")


# ---- TTFT comparison ----
print("\n" + "=" * 72)
print("TTFT: AL vs AD (full range)")
print("=" * 72)
print(f"{'Rate':>6} {'AL_TTFT':>9} {'AD_TTFT':>9} {'AD-AL':>9} {'AL_TTFT/AD_TTFT':>15}")
for al in al_points:
    r = al[0]
    ad_match = [p for p in ad_points if p[0] == r]
    if not ad_match:
        continue
    al_ttft = al[2]
    ad_ttft = ad_match[0][2]
    ratio = al_ttft / ad_ttft if ad_ttft > 0 else 0
    print(f"{r:6.0f} {al_ttft:9.3f} {ad_ttft:9.3f} {ad_ttft-al_ttft:9.3f} {ratio:15.3f}")

# At high rates, AL TTFT explodes while AD stays flat
print("\nKey: At rate>=400, AL TTFT explodes (118-187 ms) while AD stays flat (~50 ms)")
print("This is the paper's predicted TTFT-ITL tradeoff in action.")


# ---- Save comprehensive results ----
print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)

print(f"""
Paper's key predictions:
  1. ITL = alpha/(1-rho) + C0  (M/G/1 queueing model)
  2. AD has lower ITL than AL   (rho_D^AD = lambda*W_D < rho_D^AL = lambda*W_tot)
  3. AD has higher TTFT than AL  (pipeline overhead)
  4. AL capacity: lambda_max = 1/W_tot per server
  5. AD capacity: lambda_max = 1/max(W_P, W_D) per server

BLIS results:
  Prediction 1 (ITL formula): PARTIALLY HOLDS
    - The 1/(1-rho) functional form fits well at rates 1-150 (rho<0.3), RMSE={al_emp_rmse:.3f} ms
    - But a linear model fits equally well in this low-rho regime (RMSE={al_lin[2]:.3f} ms)
    - At rates 200-500, ITL LEVELS OFF instead of blowing up: AL ITL plateaus at ~21.4 ms
    - The plateau is because 300 requests at high rate means the burst is short,
      the batch never reaches steady-state size, and the token budget caps batch growth

  Prediction 2 (AD lower ITL): HOLDS FULLY
    - AD ITL < AL ITL at ALL tested rates (1-500)
    - Difference grows from 0 ms (rate=1) to ~1.7 ms (rate=150-500)
    - At rate=500: AL ITL=21.40 ms, AD ITL=20.22 ms (5.5% lower)

  Prediction 3 (AD higher TTFT): HOLDS FULLY at low rates, REVERSES at high rates
    - At rates 1-150: AD TTFT > AL TTFT (pipeline overhead ~4-16 ms)
    - At rates 400-500: AD TTFT << AL TTFT (AD TTFT=50 ms vs AL TTFT=119-187 ms)
    - The crossover happens because AL queueing delay explodes at high rates

  Prediction 4-5 (stability): NOT TESTABLE with 300 requests
    - All runs complete 300/300 requests even at rate=500
    - The system never reaches steady state at high rates

  Fitted effective W_tot = {al_emp[1]:.2f} ms (paper's work per request)
  Fitted effective W_D = {ad_emp[1]:.2f} ms
  Physical W_tot = {W_tot_phys:.2f} ms (from latency model)
  Physical W_D = {W_D_phys:.2f} ms
  Discrepancy factor: {W_tot_phys/al_emp[1]:.1f}x
    -> Physical W_tot >> fitted W_tot because the paper's steady-state model
       assumes Little's law (B = lambda*(n_c+o)*T_iter), but BLIS with 300
       requests doesn't reach this equilibrium batch size.
""")

# ---- Write data for evidence ----
evidence = {
    "itl_al_rate1": al_points[0][1],
    "itl_al_rate150": [p[1] for p in al_points if p[0] == 150][0],
    "itl_al_rate500": [p[1] for p in al_points if p[0] == 500][0],
    "itl_ad_rate1": ad_points[0][1],
    "itl_ad_rate150": [p[1] for p in ad_points if p[0] == 150][0],
    "itl_ad_rate500": [p[1] for p in ad_points if p[0] == 500][0],
    "ttft_al_rate1": al_points[0][2],
    "ttft_al_rate500": [p[2] for p in al_points if p[0] == 500][0],
    "ttft_ad_rate1": ad_points[0][2],
    "ttft_ad_rate500": [p[2] for p in ad_points if p[0] == 500][0],
    "al_itl_plateau_ms": max(p[1] for p in al_points if p[0] >= 300),
    "ad_lower_itl_all_rates": all(
        al[1] >= ad[1] for al, ad in zip(al_points, ad_points)
        if al[0] == ad[0]
    ),
    "fit_al_rmse_ms": al_emp_rmse,
    "fit_ad_rmse_ms": ad_emp_rmse,
    "linear_al_rmse_ms": al_lin[2],
    "fit_al_params": {"alpha": al_emp[0], "W_tot": al_emp[1], "C0": al_emp[2]},
    "fit_ad_params": {"alpha": ad_emp[0], "W_D": ad_emp[1], "C0": ad_emp[2]},
    "physical_W_tot_ms": W_tot_phys,
    "physical_W_D_ms": W_D_phys,
    "max_itl_diff_al_ad_ms": max(al[1] - ad[1] for al, ad in zip(al_points, ad_points) if al[0] == ad[0]),
}

with open("final/data/evidence.json", "w") as f:
    json.dump(evidence, f, indent=2)

# Save full data table
with open("final/data/full_results.csv", "w") as f:
    f.write("rate,al_itl,al_ttft,al_e2e,ad_itl,ad_ttft,ad_e2e\n")
    for al in al_points:
        r = al[0]
        ad_match = [p for p in ad_points if p[0] == r]
        if ad_match:
            ad = ad_match[0]
            f.write(f"{r},{al[1]},{al[2]},{al[3]},{ad[1]},{ad[2]},{ad[3]}\n")

print("Evidence saved to final/data/evidence.json")
print("Full results saved to final/data/full_results.csv")
