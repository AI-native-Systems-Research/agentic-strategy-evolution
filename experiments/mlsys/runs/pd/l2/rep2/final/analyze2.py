#!/usr/bin/env python3
"""Deeper analysis: compare model forms and investigate residual patterns."""
import csv
import json
import math

def load_data(path):
    al_data, ad_data = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = {
                'rate': float(row['rate']),
                'itl': float(row['itl_mean_ms']),
                'ttft': float(row['ttft_mean_ms']),
                'e2e': float(row['e2e_mean_ms']),
            }
            if row['mode'] == 'AL':
                al_data.append(entry)
            else:
                ad_data.append(entry)
    return al_data, ad_data


def nelder_mead(func, x0, args=(), tol=1e-12, max_iter=100000):
    n = len(x0)
    simplex = [list(x0)]
    for i in range(n):
        p = list(x0)
        p[i] *= 1.05 if p[i] != 0 else 0.00025
        simplex.append(p)
    f_vals = [func(s, *args) for s in simplex]
    for iteration in range(max_iter):
        order = sorted(range(n + 1), key=lambda i: f_vals[i])
        simplex = [simplex[i] for i in order]
        f_vals = [f_vals[i] for i in order]
        if abs(f_vals[-1] - f_vals[0]) < tol:
            break
        centroid = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]
        xr = [2 * centroid[j] - simplex[-1][j] for j in range(n)]
        fr = func(xr, *args)
        if f_vals[0] <= fr < f_vals[-2]:
            simplex[-1] = xr; f_vals[-1] = fr; continue
        if fr < f_vals[0]:
            xe = [3 * centroid[j] - 2 * simplex[-1][j] for j in range(n)]
            fe = func(xe, *args)
            if fe < fr:
                simplex[-1] = xe; f_vals[-1] = fe
            else:
                simplex[-1] = xr; f_vals[-1] = fr
            continue
        xc = [0.5 * (centroid[j] + simplex[-1][j]) for j in range(n)]
        fc = func(xc, *args)
        if fc < f_vals[-1]:
            simplex[-1] = xc; f_vals[-1] = fc; continue
        for i in range(1, n + 1):
            simplex[i] = [0.5 * (simplex[0][j] + simplex[i][j]) for j in range(n)]
            f_vals[i] = func(simplex[i], *args)
    return simplex[0], f_vals[0]


def compute_metrics(measured, predicted):
    n = len(measured)
    residuals = [measured[i] - predicted[i] for i in range(n)]
    mape = sum(abs(r)/m*100 for r, m in zip(residuals, measured)) / n
    rmse = math.sqrt(sum(r**2 for r in residuals) / n)
    ss_res = sum(r**2 for r in residuals)
    mean_m = sum(measured) / n
    ss_tot = sum((m - mean_m)**2 for m in measured)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    max_abs = max(abs(r) for r in residuals)
    return {'mape': mape, 'rmse': rmse, 'r2': r2, 'max_abs': max_abs, 'residuals': residuals}


def fit_model(rates, vals, model_fn, initial_guesses, bounds=None):
    """Fit a model using grid search + Nelder-Mead."""
    best_sse = float('inf')
    best_p0 = None
    for guess in initial_guesses:
        s = sum((model_fn(r, *guess) - v)**2 for r, v in zip(rates, vals))
        if s < best_sse:
            best_sse = s
            best_p0 = list(guess)
    popt, fval = nelder_mead(
        lambda p, rs, vs: sum((model_fn(r, *p) - v)**2 for r, v in zip(rs, vs)),
        best_p0, args=(rates, vals)
    )
    predicted = [model_fn(r, *popt) for r in rates]
    return popt, predicted, compute_metrics(vals, predicted)


def main():
    al_data, ad_data = load_data("final/data/sweep_results.csv")

    for label, data in [("AL", al_data), ("AD", ad_data)]:
        rates = [d['rate'] for d in data]
        itls = [d['itl'] for d in data]

        print(f"\n{'='*60}")
        print(f"Model Comparison: {label} ITL")
        print(f"{'='*60}")

        # Model 1: Linear ITL = a + b*lambda
        def linear(lam, a, b):
            return a + b * lam
        guesses_lin = [(12.0, 0.05), (12.5, 0.04), (11.0, 0.06)]
        p1, pred1, m1 = fit_model(rates, itls, linear, guesses_lin)
        print(f"\n  M1: ITL = a + b*lambda")
        print(f"      a={p1[0]:.4f}, b={p1[1]:.6f}")
        print(f"      R²={m1['r2']:.6f}, RMSE={m1['rmse']:.4f}, MAPE={m1['mape']:.3f}%")

        # Model 2: M/G/1  ITL = alpha/(1 - lambda*w) [2-param, no C0]
        def mg1_2p(lam, alpha, w):
            rho = lam * w
            return alpha / (1 - rho) if rho < 1 else 1e10
        guesses_mg1 = [(12.0, 0.002), (13.0, 0.003), (11.0, 0.001), (14.0, 0.004)]
        p2, pred2, m2 = fit_model(rates, itls, mg1_2p, guesses_mg1)
        print(f"\n  M2: ITL = alpha/(1 - lambda*w)  [paper model, C0=0]")
        print(f"      alpha={p2[0]:.4f}, w={p2[1]:.6f}")
        print(f"      Capacity = {1/p2[1]:.1f} req/s, rho@150 = {150*p2[1]:.3f}")
        print(f"      R²={m2['r2']:.6f}, RMSE={m2['rmse']:.4f}, MAPE={m2['mape']:.3f}%")

        # Model 3: M/G/1 with C0  ITL = alpha/(1 - lambda*w) + C0 [3-param]
        def mg1_3p(lam, alpha, w, c0):
            rho = lam * w
            return alpha / (1 - rho) + c0 if rho < 1 else 1e10
        guesses_3p = []
        for a in [0.5, 1.0, 2.0, 5.0, 8.0]:
            for w in [0.001, 0.002, 0.003, 0.005]:
                for c in [5.0, 8.0, 10.0, 12.0]:
                    guesses_3p.append((a, w, c))
        p3, pred3, m3 = fit_model(rates, itls, mg1_3p, guesses_3p)
        print(f"\n  M3: ITL = alpha/(1-lambda*w) + C0  [paper model, 3-param]")
        print(f"      alpha={p3[0]:.4f}, w={p3[1]:.6f}, C0={p3[2]:.4f}")
        print(f"      R²={m3['r2']:.6f}, RMSE={m3['rmse']:.4f}, MAPE={m3['mape']:.3f}%")

        # Model 4: Quadratic  ITL = a + b*lambda + c*lambda^2
        def quadratic(lam, a, b, c):
            return a + b * lam + c * lam**2
        guesses_q = [(12.0, 0.05, 0.0), (12.0, 0.06, -0.0001), (12.0, 0.04, 0.0001)]
        p4, pred4, m4 = fit_model(rates, itls, quadratic, guesses_q)
        print(f"\n  M4: ITL = a + b*lambda + c*lambda²  [quadratic]")
        print(f"      a={p4[0]:.4f}, b={p4[1]:.6f}, c={p4[2]:.10f}")
        print(f"      R²={m4['r2']:.6f}, RMSE={m4['rmse']:.4f}, MAPE={m4['mape']:.3f}%")

        # Model 5: Square root  ITL = a + b*sqrt(lambda)
        def sqrt_model(lam, a, b):
            return a + b * math.sqrt(max(lam, 0))
        guesses_sqrt = [(10.0, 0.8), (11.0, 0.7), (12.0, 0.6)]
        p5, pred5, m5 = fit_model(rates, itls, sqrt_model, guesses_sqrt)
        print(f"\n  M5: ITL = a + b*sqrt(lambda)  [square-root]")
        print(f"      a={p5[0]:.4f}, b={p5[1]:.6f}")
        print(f"      R²={m5['r2']:.6f}, RMSE={m5['rmse']:.4f}, MAPE={m5['mape']:.3f}%")

        # Model 6: Log  ITL = a + b*ln(1 + lambda)
        def log_model(lam, a, b):
            return a + b * math.log(1 + lam)
        guesses_log = [(10.0, 1.5), (11.0, 1.0), (12.0, 1.5)]
        p6, pred6, m6 = fit_model(rates, itls, log_model, guesses_log)
        print(f"\n  M6: ITL = a + b*ln(1+lambda)  [logarithmic]")
        print(f"      a={p6[0]:.4f}, b={p6[1]:.6f}")
        print(f"      R²={m6['r2']:.6f}, RMSE={m6['rmse']:.4f}, MAPE={m6['mape']:.3f}%")

        # Summary table
        print(f"\n  {'Model':>5s}  {'R²':>8s}  {'RMSE':>8s}  {'MAPE':>8s}  {'MaxErr':>8s}")
        for name, m in [("M1-lin", m1), ("M2-MG1", m2), ("M3-MG1c", m3),
                        ("M4-quad", m4), ("M5-sqrt", m5), ("M6-log", m6)]:
            print(f"  {name:>7s}  {m['r2']:8.6f}  {m['rmse']:8.4f}  {m['mape']:7.3f}%  {m['max_abs']:8.4f}")

        # Best model
        models = [("Linear", m1, pred1), ("M/G/1-2p", m2, pred2), ("M/G/1-3p", m3, pred3),
                  ("Quadratic", m4, pred4), ("Sqrt", m5, pred5), ("Log", m6, pred6)]
        best = min(models, key=lambda x: x[1]['rmse'])
        print(f"\n  Best fit: {best[0]} (RMSE={best[1]['rmse']:.4f})")

        # Print residuals for M/G/1-2p to show the S-shape pattern
        print(f"\n  M/G/1 (M2) residuals — S-shaped pattern:")
        print(f"  {'Rate':>5s}  {'Residual':>8s}")
        for i, r in enumerate(rates):
            print(f"  {r:5.0f}  {m2['residuals'][i]:+8.4f}")

    # TTFT analysis for AD: fit two-queue model
    # TTFT_AD = alpha_P/(1 - lambda*w_P) + W_P_const + c + alpha_D/(1 - lambda*w_D)
    print(f"\n{'='*60}")
    print("AD TTFT Two-Queue Model Fit")
    print(f"{'='*60}")
    rates_ad = [d['rate'] for d in ad_data]
    ttfts_ad = [d['ttft'] for d in ad_data]
    itls_ad = [d['itl'] for d in ad_data]

    # From the ITL fit, we know the decode queue parameters
    # For TTFT_AD = (prefill_queue_delay + prefill_work + KV_transfer) + decode_iter
    # At low rate: TTFT_AD ≈ prefill_overhead + KV_transfer + decode_iter ≈ 45.56 ms
    # ITL at low rate ≈ 12.26 ms (decode iteration time at zero load)
    # So prefill_overhead + KV_transfer ≈ 45.56 - 12.26 = 33.3 ms
    # KV transfer measured at ~3.4 ms
    # So prefill_overhead ≈ 29.9 ms (includes prefill work + scheduling)

    ttft_ad_decomp_low = ttfts_ad[0]  # rate=1
    itl_ad_low = itls_ad[0]
    prefill_plus_transfer = ttft_ad_decomp_low - itl_ad_low
    print(f"  At rate=1:")
    print(f"    TTFT_AD = {ttft_ad_decomp_low:.1f} ms")
    print(f"    ITL_AD  = {itl_ad_low:.3f} ms (decode iteration)")
    print(f"    Prefill pipeline + KV transfer = {prefill_plus_transfer:.1f} ms")
    print(f"    KV transfer ≈ 3.4 ms (from PD metrics)")
    print(f"    Prefill work + overhead ≈ {prefill_plus_transfer - 3.4:.1f} ms")

    # For AL TTFT decomposition
    ttfts_al = [d['ttft'] for d in al_data]
    itls_al = [d['itl'] for d in al_data]
    ttft_al_low = ttfts_al[0]
    itl_al_low = itls_al[0]
    print(f"\n  AL at rate=1:")
    print(f"    TTFT_AL = {ttft_al_low:.1f} ms")
    print(f"    ITL_AL  = {itl_al_low:.3f} ms")
    print(f"    Prefill overhead (local) = TTFT - ITL = {ttft_al_low - itl_al_low:.1f} ms")

    # TTFT difference at various rates
    print(f"\n  Delta_TTFT = TTFT_AD - TTFT_AL (paper: prefill pipeline + KV transfer + chunking diff)")
    for i in range(len(al_data)):
        r = al_data[i]['rate']
        delta_ttft = ad_data[i]['ttft'] - al_data[i]['ttft']
        delta_itl = al_data[i]['itl'] - ad_data[i]['itl']  # ITL saving
        e2e_al = al_data[i]['e2e']
        e2e_ad = ad_data[i]['e2e']
        e2e_saving = e2e_al - e2e_ad
        itl_contrib = delta_itl * 128  # 128 output tokens
        print(f"  rate={r:3.0f}: ΔTTFT={delta_ttft:+6.1f}ms, ΔITL={delta_itl:+5.2f}ms, "
              f"ΔITL×128={itl_contrib:+7.1f}ms, ΔE2E={e2e_saving:+7.1f}ms")

    print(f"\n  Note: ΔE2E ≈ ΔITL×128 - ΔTTFT (since E2E ≈ TTFT + ITL×(o-1))")
    for i in range(len(al_data)):
        r = al_data[i]['rate']
        delta_ttft = ad_data[i]['ttft'] - al_data[i]['ttft']
        delta_itl = al_data[i]['itl'] - ad_data[i]['itl']
        e2e_saving = al_data[i]['e2e'] - ad_data[i]['e2e']
        predicted_saving = delta_itl * 127 - delta_ttft  # ITL applies to o-1 tokens after first
        reconstruction_err = e2e_saving - predicted_saving
        if i % 5 == 0:  # print every 5th
            print(f"  rate={r:3.0f}: actual ΔE2E={e2e_saving:+7.1f}, "
                  f"predicted={predicted_saving:+7.1f}, error={reconstruction_err:+5.1f}ms")


if __name__ == '__main__':
    main()
