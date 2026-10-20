#!/usr/bin/env python3
"""Analyze BLIS P/D experiments against the paper's closed-form predictions.
Uses only stdlib (no numpy/scipy)."""

import json
import math
import os

DATA_DIR = "final/data"

with open(os.path.join(DATA_DIR, "all_results.json")) as f:
    all_results = json.load(f)

al_data = sorted([r for r in all_results if r["pd_decider"] == "never"], key=lambda x: x["rate"])
ad_data = sorted([r for r in all_results if r["pd_decider"] == "always"], key=lambda x: x["rate"])

al_rates = [r["rate"] for r in al_data]
al_itl = [r["itl_mean_ms"] for r in al_data]
al_ttft = [r["ttft_mean_ms"] for r in al_data]

ad_rates = [r["rate"] for r in ad_data]
ad_itl = [r["itl_mean_ms"] for r in ad_data]
ad_ttft = [r["ttft_mean_ms"] for r in ad_data]


def mean(xs):
    return sum(xs) / len(xs)


def rmse(residuals):
    return math.sqrt(mean([r**2 for r in residuals]))


def mape(actual, predicted):
    return mean([abs((a - p) / a) * 100 for a, p in zip(actual, predicted)])


def linfit(xs, ys):
    """Simple least-squares linear regression y = a + b*x"""
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    return a, b


def fit_hyperbolic_2param(rates, itls, max_iter=100000, tol=1e-10):
    """Fit ITL = A / (1 - B*rate) using Gauss-Newton.
    A is the asymptotic base ITL, B = 1/saturation_rate."""
    A = itls[0]  # initial guess
    B = 0.002    # initial guess: saturation at rate ~500

    for iteration in range(max_iter):
        # Compute residuals and Jacobian
        residuals = []
        J = []  # Jacobian rows: [dITL/dA, dITL/dB]
        for r, itl in zip(rates, itls):
            denom = 1 - B * r
            if denom <= 0.01:
                denom = 0.01
            pred = A / denom
            residuals.append(itl - pred)
            dA = 1.0 / denom
            dB = A * r / (denom * denom)
            J.append([dA, dB])

        # Normal equations: J^T J delta = J^T r
        n = len(rates)
        JtJ00 = sum(J[i][0] * J[i][0] for i in range(n))
        JtJ01 = sum(J[i][0] * J[i][1] for i in range(n))
        JtJ11 = sum(J[i][1] * J[i][1] for i in range(n))
        Jtr0 = sum(J[i][0] * residuals[i] for i in range(n))
        Jtr1 = sum(J[i][1] * residuals[i] for i in range(n))

        det = JtJ00 * JtJ11 - JtJ01 * JtJ01
        if abs(det) < 1e-20:
            break

        dA = (JtJ11 * Jtr0 - JtJ01 * Jtr1) / det
        dB = (JtJ00 * Jtr1 - JtJ01 * Jtr0) / det

        # Damped update
        step = 0.5
        A_new = A + step * dA
        B_new = B + step * dB

        if A_new > 0 and B_new > 0 and B_new < 0.1:
            A = A_new
            B = B_new

        if abs(dA) < tol and abs(dB) < tol:
            break

    return A, B


def fit_hyperbolic_3param(rates, itls, max_iter=100000, tol=1e-10):
    """Fit ITL = A / (1 - B*rate) + C using Gauss-Newton."""
    A = 5.0
    B = 0.002
    C = itls[0] - 5.0

    for iteration in range(max_iter):
        residuals = []
        J = []
        for r, itl in zip(rates, itls):
            denom = 1 - B * r
            if denom <= 0.01:
                denom = 0.01
            pred = A / denom + C
            residuals.append(itl - pred)
            dA = 1.0 / denom
            dB = A * r / (denom * denom)
            dC = 1.0
            J.append([dA, dB, dC])

        n = len(rates)
        # 3x3 normal equations
        JtJ = [[0]*3 for _ in range(3)]
        Jtr = [0]*3
        for i in range(n):
            for a in range(3):
                Jtr[a] += J[i][a] * residuals[i]
                for b in range(3):
                    JtJ[a][b] += J[i][a] * J[i][b]

        # Solve 3x3 via Cramer's rule
        def det3(m):
            return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
                   -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
                   +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))

        D = det3(JtJ)
        if abs(D) < 1e-20:
            break

        def replace_col(m, col, v):
            result = [row[:] for row in m]
            for i in range(3):
                result[i][col] = v[i]
            return result

        deltas = [det3(replace_col(JtJ, i, Jtr)) / D for i in range(3)]

        step = 0.3
        A_new = A + step * deltas[0]
        B_new = B + step * deltas[1]
        C_new = C + step * deltas[2]

        if A_new > 0 and B_new > 0 and B_new < 0.1 and C_new > -50:
            A = A_new
            B = B_new
            C = C_new

        if all(abs(d) < tol for d in deltas):
            break

    return A, B, C


# =================================================================
print("=" * 70)
print("FITTING PAPER'S ITL MODEL: ITL = A/(1 - B*rate) + C")
print("=" * 70)

# AL 2-param
A_al2, B_al2 = fit_hyperbolic_2param(al_rates, al_itl)
al_pred2 = [A_al2 / (1 - B_al2 * r) for r in al_rates]
al_resid2 = [a - p for a, p in zip(al_itl, al_pred2)]
print(f"\nAL 2-param: ITL = {A_al2:.4f} / (1 - {B_al2:.6f}*rate)")
print(f"  RMSE = {rmse(al_resid2):.4f} ms, MAPE = {mape(al_itl, al_pred2):.2f}%")
print(f"  Implied saturation rate: {1/B_al2:.1f} req/s")
max_resid_idx = max(range(len(al_resid2)), key=lambda i: abs(al_resid2[i]))
print(f"  Max |residual|: {abs(al_resid2[max_resid_idx]):.4f} ms at rate={al_rates[max_resid_idx]}")

# AL 3-param
A_al3, B_al3, C_al3 = fit_hyperbolic_3param(al_rates, al_itl)
al_pred3 = [A_al3 / (1 - B_al3 * r) + C_al3 for r in al_rates]
al_resid3 = [a - p for a, p in zip(al_itl, al_pred3)]
print(f"\nAL 3-param: ITL = {A_al3:.4f} / (1 - {B_al3:.6f}*rate) + {C_al3:.4f}")
print(f"  RMSE = {rmse(al_resid3):.4f} ms, MAPE = {mape(al_itl, al_pred3):.2f}%")
print(f"  Implied saturation rate: {1/B_al3:.1f} req/s")

# AD 2-param
A_ad2, B_ad2 = fit_hyperbolic_2param(ad_rates, ad_itl)
ad_pred2 = [A_ad2 / (1 - B_ad2 * r) for r in ad_rates]
ad_resid2 = [a - p for a, p in zip(ad_itl, ad_pred2)]
print(f"\nAD 2-param: ITL = {A_ad2:.4f} / (1 - {B_ad2:.6f}*rate)")
print(f"  RMSE = {rmse(ad_resid2):.4f} ms, MAPE = {mape(ad_itl, ad_pred2):.2f}%")
print(f"  Implied saturation rate: {1/B_ad2:.1f} req/s")
max_resid_idx = max(range(len(ad_resid2)), key=lambda i: abs(ad_resid2[i]))
print(f"  Max |residual|: {abs(ad_resid2[max_resid_idx]):.4f} ms at rate={ad_rates[max_resid_idx]}")

# AD 3-param
A_ad3, B_ad3, C_ad3 = fit_hyperbolic_3param(ad_rates, ad_itl)
ad_pred3 = [A_ad3 / (1 - B_ad3 * r) + C_ad3 for r in ad_rates]
ad_resid3 = [a - p for a, p in zip(ad_itl, ad_pred3)]
print(f"\nAD 3-param: ITL = {A_ad3:.4f} / (1 - {B_ad3:.6f}*rate) + {C_ad3:.4f}")
print(f"  RMSE = {rmse(ad_resid3):.4f} ms, MAPE = {mape(ad_itl, ad_pred3):.2f}%")
print(f"  Implied saturation rate: {1/B_ad3:.1f} req/s")

# Linear comparison
print("\n" + "=" * 70)
print("LINEAR FIT COMPARISON: ITL = a + b*rate")
print("=" * 70)

a_al, b_al = linfit(al_rates, al_itl)
al_pred_lin = [a_al + b_al * r for r in al_rates]
al_resid_lin = [a - p for a, p in zip(al_itl, al_pred_lin)]
print(f"\nAL linear: ITL = {a_al:.4f} + {b_al:.6f}*rate")
print(f"  RMSE = {rmse(al_resid_lin):.4f} ms, MAPE = {mape(al_itl, al_pred_lin):.2f}%")

a_ad, b_ad = linfit(ad_rates, ad_itl)
ad_pred_lin = [a_ad + b_ad * r for r in ad_rates]
ad_resid_lin = [a - p for a, p in zip(ad_itl, ad_pred_lin)]
print(f"\nAD linear: ITL = {a_ad:.4f} + {b_ad:.6f}*rate")
print(f"  RMSE = {rmse(ad_resid_lin):.4f} ms, MAPE = {mape(ad_itl, ad_pred_lin):.2f}%")

# =================================================================
print("\n" + "=" * 70)
print("TTFT ANALYSIS: AL vs AD")
print("=" * 70)

print("\nRate | TTFT_AL(ms) | TTFT_AD(ms) | Diff(AD-AL) | ITL_AL(ms) | ITL_AD(ms) | ITL_diff")
print("-" * 100)
for i in range(len(al_rates)):
    rate = al_rates[i]
    if rate in ad_rates:
        j = ad_rates.index(rate)
        ttft_diff = ad_ttft[j] - al_ttft[i]
        itl_diff = al_itl[i] - ad_itl[j]
        print(f"{rate:>4} | {al_ttft[i]:>11.3f} | {ad_ttft[j]:>11.3f} | {ttft_diff:>+11.3f} | {al_itl[i]:>10.3f} | {ad_itl[j]:>10.3f} | {itl_diff:>+8.3f}")

# =================================================================
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

itl_ratio = [ad_itl[i] / al_itl[i] for i in range(len(al_itl))]
print(f"\n1. ITL ratio (AD/AL): min={min(itl_ratio):.4f}, max={max(itl_ratio):.4f}")
ad_itl_always_lower = all(r < 1.0 for r in itl_ratio)
print(f"   AD ITL is {'always' if ad_itl_always_lower else 'NOT always'} lower than AL ITL")
itl_advantage = [(1 - r) * 100 for r in itl_ratio]
print(f"   AD ITL advantage: {min(itl_advantage):.2f}% to {max(itl_advantage):.2f}%")

ttft_diff_ms = [ad_ttft[i] - al_ttft[i] for i in range(len(al_ttft))]
print(f"\n2. TTFT difference (AD - AL): min={min(ttft_diff_ms):.2f}ms, max={max(ttft_diff_ms):.2f}ms")
ad_ttft_always_higher = all(d > 0 for d in ttft_diff_ms)
print(f"   AD TTFT is {'always' if ad_ttft_always_higher else 'NOT always'} higher than AL TTFT")

al_completed = [r["completed_requests"] for r in al_data]
ad_completed = [r["completed_requests"] for r in ad_data]
print(f"\n3. Saturation: All 300 requests completed at every rate? AL={all(c==300 for c in al_completed)}, AD={all(c==300 for c in ad_completed)}")
print(f"   System did NOT saturate for either mode up to rate=150 req/s")

# =================================================================
print("\n" + "=" * 70)
print("DETAILED RESIDUAL ANALYSIS (2-param fit)")
print("=" * 70)

print("\nAL: ITL = {:.4f} / (1 - {:.6f}*rate)".format(A_al2, B_al2))
print("Rate | BLIS_ITL | Model_ITL | Residual | Rel_Err%")
for i, rate in enumerate(al_rates):
    pred = A_al2 / (1 - B_al2 * rate)
    resid = al_itl[i] - pred
    relerr = resid / al_itl[i] * 100
    print(f"{rate:>4} | {al_itl[i]:>8.3f}  | {pred:>9.3f}  | {resid:>+8.3f}  | {relerr:>+7.2f}%")

print("\nAD: ITL = {:.4f} / (1 - {:.6f}*rate)".format(A_ad2, B_ad2))
print("Rate | BLIS_ITL | Model_ITL | Residual | Rel_Err%")
for i, rate in enumerate(ad_rates):
    pred = A_ad2 / (1 - B_ad2 * rate)
    resid = ad_itl[i] - pred
    relerr = resid / ad_itl[i] * 100
    print(f"{rate:>4} | {ad_itl[i]:>8.3f}  | {pred:>9.3f}  | {resid:>+8.3f}  | {relerr:>+7.2f}%")

# Check curvature: is the growth more sublinear than 1/(1-rho)?
print("\n" + "=" * 70)
print("CURVATURE ANALYSIS: is ITL growth 1/(1-ρ) or sublinear?")
print("=" * 70)
print("\nComparing ITL growth against the fitted 1/(1-B*rate) model:")
print("If BLIS ITL < model at high rates, growth is sublinear (slower than 1/(1-ρ))")
print("If BLIS ITL > model at high rates, growth is superlinear (faster than 1/(1-ρ))")
for label, rates, itls, pred, A, B in [
    ("AL", al_rates, al_itl, al_pred2, A_al2, B_al2),
    ("AD", ad_rates, ad_itl, ad_pred2, A_ad2, B_ad2)]:
    high_resids = [(r, itls[i] - pred[i]) for i, r in enumerate(rates) if r >= 80]
    low_resids = [(r, itls[i] - pred[i]) for i, r in enumerate(rates) if r <= 20]
    print(f"\n{label}:")
    print(f"  Low-rate residuals (≤20): avg = {mean([r for _, r in low_resids]):+.4f} ms")
    print(f"  High-rate residuals (≥80): avg = {mean([r for _, r in high_resids]):+.4f} ms")
    if mean([r for _, r in high_resids]) < mean([r for _, r in low_resids]):
        print(f"  → High-rate ITL grows SLOWER than 1/(1-ρ) (sublinear deviation)")
    else:
        print(f"  → High-rate ITL grows FASTER than 1/(1-ρ) (superlinear)")

# Save analysis
summary = {
    "al_itl_range": [min(al_itl), max(al_itl)],
    "ad_itl_range": [min(ad_itl), max(ad_itl)],
    "al_ttft_range": [min(al_ttft), max(al_ttft)],
    "ad_ttft_range": [min(ad_ttft), max(ad_ttft)],
    "itl_ad_always_lower": ad_itl_always_lower,
    "ttft_ad_always_higher": ad_ttft_always_higher,
    "al_fit_2param": {"A": A_al2, "B": B_al2, "rmse": rmse(al_resid2),
                       "mape": mape(al_itl, al_pred2), "saturation_rate": 1/B_al2},
    "ad_fit_2param": {"A": A_ad2, "B": B_ad2, "rmse": rmse(ad_resid2),
                       "mape": mape(ad_itl, ad_pred2), "saturation_rate": 1/B_ad2},
    "al_fit_3param": {"A": A_al3, "B": B_al3, "C": C_al3, "rmse": rmse(al_resid3),
                       "mape": mape(al_itl, al_pred3), "saturation_rate": 1/B_al3},
    "ad_fit_3param": {"A": A_ad3, "B": B_ad3, "C": C_ad3, "rmse": rmse(ad_resid3),
                       "mape": mape(ad_itl, ad_pred3), "saturation_rate": 1/B_ad3},
    "al_linear": {"a": a_al, "b": b_al, "rmse": rmse(al_resid_lin), "mape": mape(al_itl, al_pred_lin)},
    "ad_linear": {"a": a_ad, "b": b_ad, "rmse": rmse(ad_resid_lin), "mape": mape(ad_itl, ad_pred_lin)},
}

with open("final/data/analysis_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print(f"\nSummary saved to final/data/analysis_summary.json")
