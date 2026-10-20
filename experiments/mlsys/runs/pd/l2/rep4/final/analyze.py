#!/usr/bin/env python3
"""Analyze BLIS sweep data against paper's closed-form predictions. No external deps."""

import csv
import json
import math

# Load data
al_data = []  # (rate, itl, ttft, e2e, completed)
ad_data = []

with open("final/data/sweep_results.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rate = float(row["rate"])
        rec = (rate, float(row["itl_mean_ms"]), float(row["ttft_mean_ms"]),
               float(row["e2e_mean_ms"]), int(row["completed"]))
        if row["mode"] == "never":
            al_data.append(rec)
        else:
            ad_data.append(rec)

# Constants
l = 512   # prompt tokens
o = 128   # output tokens
N_D = 2   # decode instances
N_P = 2   # prefill instances


def itl_model(lam, A, W, C):
    """Paper's ITL model: ITL = A / (1 - (lam/N_D)*W/1000) + C"""
    rho = (lam / N_D) * W / 1000.0
    if rho >= 1.0:
        return 1e6
    return A / (1.0 - rho) + C


def fit_itl_model(data, label):
    """Brute-force grid search + refinement to fit A/(1-rho)+C."""
    best_rmse = 1e18
    best_params = None

    # Grid search
    for A_try in [x * 0.5 for x in range(1, 50)]:
        for W_try in [x * 0.5 for x in range(1, 60)]:
            for C_try in [x * 0.5 - 10 for x in range(0, 41)]:
                sse = 0
                valid = True
                for rate, itl, _, _, _ in data:
                    pred = itl_model(rate, A_try, W_try, C_try)
                    if pred > 1e5:
                        valid = False
                        break
                    sse += (itl - pred) ** 2
                if valid and sse < best_rmse:
                    best_rmse = sse
                    best_params = (A_try, W_try, C_try)

    # Refine around best
    if best_params:
        A0, W0, C0 = best_params
        for dA in [x * 0.05 - 0.5 for x in range(21)]:
            for dW in [x * 0.05 - 0.5 for x in range(21)]:
                for dC in [x * 0.05 - 0.5 for x in range(21)]:
                    A_try = A0 + dA
                    W_try = W0 + dW
                    C_try = C0 + dC
                    if A_try <= 0 or W_try <= 0:
                        continue
                    sse = 0
                    valid = True
                    for rate, itl, _, _, _ in data:
                        pred = itl_model(rate, A_try, W_try, C_try)
                        if pred > 1e5:
                            valid = False
                            break
                        sse += (itl - pred) ** 2
                    if valid and sse < best_rmse:
                        best_rmse = sse
                        best_params = (A_try, W_try, C_try)

    # Second refinement
    if best_params:
        A0, W0, C0 = best_params
        for dA in [x * 0.01 - 0.1 for x in range(21)]:
            for dW in [x * 0.01 - 0.1 for x in range(21)]:
                for dC in [x * 0.01 - 0.1 for x in range(21)]:
                    A_try = A0 + dA
                    W_try = W0 + dW
                    C_try = C0 + dC
                    if A_try <= 0 or W_try <= 0:
                        continue
                    sse = 0
                    valid = True
                    for rate, itl, _, _, _ in data:
                        pred = itl_model(rate, A_try, W_try, C_try)
                        if pred > 1e5:
                            valid = False
                            break
                        sse += (itl - pred) ** 2
                    if valid and sse < best_rmse:
                        best_rmse = sse
                        best_params = (A_try, W_try, C_try)

    rmse = math.sqrt(best_rmse / len(data))
    return best_params, rmse


def fit_linear(data):
    """Fit ITL = a + b*lambda."""
    n = len(data)
    sx = sum(r for r, _, _, _, _ in data)
    sy = sum(itl for _, itl, _, _, _ in data)
    sxy = sum(r * itl for r, itl, _, _, _ in data)
    sxx = sum(r * r for r, _, _, _, _ in data)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    sse = sum((itl - (a + b * r)) ** 2 for r, itl, _, _, _ in data)
    rmse = math.sqrt(sse / n)
    return a, b, rmse


print("=" * 70)
print("FITTING PAPER'S MODEL: ITL = alpha / (1 - lambda_eff * W) + C0")
print("  where lambda_eff = lambda / N_D, N_D = 2")
print("=" * 70)

# Fit AL
print("\nFitting AL (pd-decider=never) ...")
al_params, al_rmse = fit_itl_model(al_data, "AL")
A_al, W_al, C_al = al_params
print(f"  alpha = {A_al:.3f} ms, W_tot = {W_al:.3f} ms, C0 = {C_al:.3f} ms")
print(f"  RMSE = {al_rmse:.4f} ms")
print(f"  Stability bound (lambda_max = 2*1000/W): {2*1000/W_al:.1f} req/s")

# Fit AD
print("\nFitting AD (pd-decider=always) ...")
ad_params, ad_rmse = fit_itl_model(ad_data, "AD")
A_ad, W_ad, C_ad = ad_params
print(f"  alpha = {A_ad:.3f} ms, W_D = {W_ad:.3f} ms, C0 = {C_ad:.3f} ms")
print(f"  RMSE = {ad_rmse:.4f} ms")
print(f"  Stability bound: {2*1000/W_ad:.1f} req/s")

# Linear fits
al_lin_a, al_lin_b, al_lin_rmse = fit_linear(al_data)
ad_lin_a, ad_lin_b, ad_lin_rmse = fit_linear(ad_data)
print(f"\nLinear fit comparison:")
print(f"  AL: ITL = {al_lin_a:.4f} + {al_lin_b:.6f}*lambda, RMSE = {al_lin_rmse:.4f} ms")
print(f"  AD: ITL = {ad_lin_a:.4f} + {ad_lin_b:.6f}*lambda, RMSE = {ad_lin_rmse:.4f} ms")

# ---- Detailed comparison table ----
print("\n" + "=" * 70)
print("DETAILED ITL COMPARISON: AL")
print(f"{'Rate':>6} {'Meas':>9} {'1/(1-rho)':>10} {'Err':>8} {'Rel%':>7} {'rho':>6}")
for rate, itl, ttft, e2e, comp in al_data:
    pred = itl_model(rate, *al_params)
    err = itl - pred
    relerr = err / itl * 100
    rho = (rate / N_D) * W_al / 1000
    print(f"{rate:6.0f} {itl:9.3f} {pred:10.3f} {err:8.3f} {relerr:7.2f} {rho:6.3f}")

print(f"\nDETAILED ITL COMPARISON: AD")
print(f"{'Rate':>6} {'Meas':>9} {'1/(1-rho)':>10} {'Err':>8} {'Rel%':>7} {'rho':>6}")
for rate, itl, ttft, e2e, comp in ad_data:
    pred = itl_model(rate, *ad_params)
    err = itl - pred
    relerr = err / itl * 100
    rho = (rate / N_D) * W_ad / 1000
    print(f"{rate:6.0f} {itl:9.3f} {pred:10.3f} {err:8.3f} {relerr:7.2f} {rho:6.3f}")

# ---- TTFT and ITL comparison ----
print("\n" + "=" * 70)
print("TTFT-ITL TRADEOFF: AL vs AD")
print(f"{'Rate':>6} {'AL_TTFT':>9} {'AD_TTFT':>9} {'dTTFT':>8} {'AL_ITL':>9} {'AD_ITL':>9} {'dITL':>8}")
for i in range(len(al_data)):
    r = al_data[i][0]
    al_ttft_v = al_data[i][2]
    ad_ttft_v = ad_data[i][2]
    al_itl_v = al_data[i][1]
    ad_itl_v = ad_data[i][1]
    print(f"{r:6.0f} {al_ttft_v:9.3f} {ad_ttft_v:9.3f} {ad_ttft_v-al_ttft_v:8.3f} "
          f"{al_itl_v:9.3f} {ad_itl_v:9.3f} {al_itl_v-ad_itl_v:8.3f}")

# ---- Key findings ----
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

# 1. AD always lower ITL?
all_ad_lower = all(al[1] >= ad[1] for al, ad in zip(al_data, ad_data))
itl_diffs = [al[1] - ad[1] for al, ad in zip(al_data, ad_data)]
print(f"\n1. AD always has lower ITL than AL: {all_ad_lower}")
print(f"   ITL difference (AL-AD): {min(itl_diffs):.3f} to {max(itl_diffs):.3f} ms")
print(f"   Relative: {min(d/al[1]*100 for d, al in zip(itl_diffs, al_data)):.1f}% to "
      f"{max(d/al[1]*100 for d, al in zip(itl_diffs, al_data)):.1f}%")

# 2. AD always higher TTFT?
all_ad_higher_ttft = all(ad[2] >= al[2] for al, ad in zip(al_data, ad_data))
ttft_diffs = [ad[2] - al[2] for al, ad in zip(al_data, ad_data)]
print(f"\n2. AD always has higher TTFT than AL: {all_ad_higher_ttft}")
print(f"   TTFT difference (AD-AL): {min(ttft_diffs):.3f} to {max(ttft_diffs):.3f} ms")

# 3. Is the 1/(1-rho) model a good fit?
print(f"\n3. Model fit quality (1/(1-rho) vs linear):")
print(f"   AL: 1/(1-rho) RMSE={al_rmse:.4f} ms, linear RMSE={al_lin_rmse:.4f} ms")
print(f"   AD: 1/(1-rho) RMSE={ad_rmse:.4f} ms, linear RMSE={ad_lin_rmse:.4f} ms")
if al_rmse < al_lin_rmse:
    print(f"   -> 1/(1-rho) fits AL {al_lin_rmse/al_rmse:.1f}x better than linear")
else:
    print(f"   -> Linear fits AL {al_rmse/al_lin_rmse:.1f}x better than 1/(1-rho)")

# 4. Work ratio
W_P_est = W_al - W_ad
print(f"\n4. Work ratio:")
print(f"   W_tot = {W_al:.3f} ms (from AL fit)")
print(f"   W_D = {W_ad:.3f} ms (from AD fit)")
print(f"   W_P = W_tot - W_D = {W_P_est:.3f} ms")
if W_P_est > 0:
    eta = W_al / W_P_est
    print(f"   eta = W_tot/W_P = {eta:.3f}")
    print(f"   Paper predicts decode-heavy when W_D > W_P: {W_ad > W_P_est}")

# 5. Utilization at max tested rate
rho_al_max = (150 / N_D) * W_al / 1000
rho_ad_max = (150 / N_D) * W_ad / 1000
print(f"\n5. Utilization at rate=150:")
print(f"   AL rho_D = {rho_al_max:.3f}")
print(f"   AD rho_D = {rho_ad_max:.3f}")

# ---- Save summary ----
summary = {
    "al_fit": {"alpha_ms": A_al, "W_tot_ms": W_al, "C0_ms": C_al, "rmse_ms": al_rmse},
    "ad_fit": {"alpha_ms": A_ad, "W_D_ms": W_ad, "C0_ms": C_ad, "rmse_ms": ad_rmse},
    "al_linear": {"intercept_ms": al_lin_a, "slope_ms_per_rps": al_lin_b, "rmse_ms": al_lin_rmse},
    "ad_linear": {"intercept_ms": ad_lin_a, "slope_ms_per_rps": ad_lin_b, "rmse_ms": ad_lin_rmse},
    "al_stability_bound_rps": 2*1000/W_al,
    "ad_stability_bound_rps": 2*1000/W_ad,
    "itl_al_gt_ad_all_rates": all_ad_lower,
    "ttft_ad_gt_al_all_rates": all_ad_higher_ttft,
    "rho_al_at_150": rho_al_max,
    "rho_ad_at_150": rho_ad_max,
    "itl_at_rate1": {"al": al_data[0][1], "ad": ad_data[0][1]},
    "itl_at_rate150": {"al": al_data[-1][1], "ad": ad_data[-1][1]},
    "ttft_at_rate1": {"al": al_data[0][2], "ad": ad_data[0][2]},
    "ttft_at_rate150": {"al": al_data[-1][2], "ad": ad_data[-1][2]},
    "max_itl_diff_al_minus_ad_ms": max(itl_diffs),
    "min_itl_diff_al_minus_ad_ms": min(itl_diffs),
}

with open("final/data/analysis_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print(f"\nSummary saved to final/data/analysis_summary.json")
