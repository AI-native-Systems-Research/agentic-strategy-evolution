#!/usr/bin/env python3
"""Analyze BLIS P/D sweep results against the paper's closed-form model.

Paper model (Section 5):
  ITL(lambda) = alpha / (1 - lambda * w_eff) + C_0

We fit this using grid search + Nelder-Mead simplex (no scipy needed).
"""
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
                'itl_p99': float(row['itl_p99_ms']),
                'ttft_p99': float(row['ttft_p99_ms']),
                'completed': int(row['completed']),
                'injected': int(row['injected']),
            }
            if row['mode'] == 'AL':
                al_data.append(entry)
            else:
                ad_data.append(entry)
    return al_data, ad_data


def mg1_itl(lam, alpha, w_eff, c0):
    rho = lam * w_eff
    if rho >= 1:
        return 1e10
    return alpha / (1 - rho) + c0


def sse(params, rates, itls):
    alpha, w_eff, c0 = params
    if alpha <= 0 or w_eff <= 0 or c0 <= 0:
        return 1e20
    total = 0
    for r, itl in zip(rates, itls):
        pred = mg1_itl(r, alpha, w_eff, c0)
        total += (pred - itl) ** 2
    return total


def nelder_mead(func, x0, args=(), tol=1e-10, max_iter=50000):
    """Minimal Nelder-Mead simplex for 3 parameters."""
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

        # Reflection
        xr = [2 * centroid[j] - simplex[-1][j] for j in range(n)]
        fr = func(xr, *args)

        if f_vals[0] <= fr < f_vals[-2]:
            simplex[-1] = xr
            f_vals[-1] = fr
            continue

        if fr < f_vals[0]:
            xe = [3 * centroid[j] - 2 * simplex[-1][j] for j in range(n)]
            fe = func(xe, *args)
            if fe < fr:
                simplex[-1] = xe
                f_vals[-1] = fe
            else:
                simplex[-1] = xr
                f_vals[-1] = fr
            continue

        xc = [0.5 * (centroid[j] + simplex[-1][j]) for j in range(n)]
        fc = func(xc, *args)
        if fc < f_vals[-1]:
            simplex[-1] = xc
            f_vals[-1] = fc
            continue

        for i in range(1, n + 1):
            simplex[i] = [0.5 * (simplex[0][j] + simplex[i][j]) for j in range(n)]
            f_vals[i] = func(simplex[i], *args)

    return simplex[0], f_vals[0]


def fit_itl_model(data, label):
    rates = [d['rate'] for d in data]
    itls = [d['itl'] for d in data]

    # Grid search for initial guess
    best_sse = float('inf')
    best_p0 = None
    for alpha in [0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]:
        for w_eff in [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]:
            for c0 in [8.0, 9.0, 10.0, 11.0, 12.0, 12.5]:
                s = sse([alpha, w_eff, c0], rates, itls)
                if s < best_sse:
                    best_sse = s
                    best_p0 = [alpha, w_eff, c0]

    popt, fval = nelder_mead(sse, best_p0, args=(rates, itls))
    alpha, w_eff, c0 = popt

    predicted = [mg1_itl(r, alpha, w_eff, c0) for r in rates]
    residuals = [itls[i] - predicted[i] for i in range(len(rates))]
    mape = sum(abs(r) / itls[i] * 100 for i, r in enumerate(residuals)) / len(residuals)
    max_abs_err = max(abs(r) for r in residuals)
    max_rel_err = max(abs(r) / itls[i] * 100 for i, r in enumerate(residuals))
    rmse = math.sqrt(sum(r**2 for r in residuals) / len(residuals))
    capacity = 1.0 / w_eff if w_eff > 0 else float('inf')

    print(f"\n=== {label} ITL Model Fit ===")
    print(f"  ITL(lambda) = alpha/(1 - lambda*w_eff) + C_0")
    print(f"  alpha = {alpha:.4f} ms")
    print(f"  w_eff = {w_eff:.6f} (1/capacity per instance)")
    print(f"  C_0   = {c0:.4f} ms")
    print(f"  Implied capacity = {capacity:.1f} req/s")
    print(f"  RMSE  = {rmse:.4f} ms")
    print(f"  MAPE  = {mape:.3f}%")
    print(f"  Max absolute error = {max_abs_err:.4f} ms")
    print(f"  Max relative error = {max_rel_err:.3f}%")

    print(f"\n  {'Rate':>5s}  {'Measured':>8s}  {'Predicted':>9s}  {'Residual':>8s}  {'Rel%':>6s}  {'rho':>5s}")
    for i, r in enumerate(rates):
        rho = r * w_eff
        print(f"  {r:5.0f}  {itls[i]:8.3f}   {predicted[i]:8.3f}  {residuals[i]:+8.4f}  {residuals[i]/itls[i]*100:+5.2f}%  {rho:.3f}")

    return {
        'alpha': alpha,
        'w_eff': w_eff,
        'c0': c0,
        'capacity': capacity,
        'mape': mape,
        'max_abs_err': max_abs_err,
        'max_rel_err': max_rel_err,
        'rmse': rmse,
        'predicted': predicted,
        'residuals': residuals,
    }


def fit_ttft_mg1(data, label):
    """Fit TTFT(lambda) = alpha_t / (1 - lambda * w_t) + C_t for single-queue model."""
    rates = [d['rate'] for d in data]
    ttfts = [d['ttft'] for d in data]

    best_sse_val = float('inf')
    best_p0 = None
    for alpha in [0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 15.0]:
        for w in [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]:
            for c in [20.0, 25.0, 28.0, 30.0, 35.0, 40.0, 45.0]:
                s = sse([alpha, w, c], rates, ttfts)
                if s < best_sse_val:
                    best_sse_val = s
                    best_p0 = [alpha, w, c]

    popt, fval = nelder_mead(sse, best_p0, args=(rates, ttfts))
    alpha, w, c = popt

    predicted = [mg1_itl(r, alpha, w, c) for r in rates]
    residuals = [ttfts[i] - predicted[i] for i in range(len(rates))]
    mape = sum(abs(r) / ttfts[i] * 100 for i, r in enumerate(residuals)) / len(residuals)
    rmse = math.sqrt(sum(r**2 for r in residuals) / len(residuals))

    print(f"\n=== {label} TTFT Model Fit ===")
    print(f"  TTFT(lambda) = alpha/(1 - lambda*w) + C")
    print(f"  alpha = {alpha:.4f} ms, w = {w:.6f}, C = {c:.4f} ms")
    print(f"  RMSE = {rmse:.4f} ms, MAPE = {mape:.3f}%")

    return {'alpha': alpha, 'w': w, 'c': c, 'mape': mape, 'rmse': rmse,
            'predicted': predicted, 'residuals': residuals}


def main():
    al_data, ad_data = load_data("final/data/sweep_results.csv")

    print("=" * 70)
    print("BLIS P/D Disaggregation: Paper Model Validation")
    print("=" * 70)
    print(f"\nSetup: --num-instances 4 --prefill-instances 2 --decode-instances 2")
    print(f"  AL (pd-decider=never): 2 decode instances handle all traffic")
    print(f"  AD (pd-decider=always): 2 prefill + 2 decode instances")
    print(f"  Workload: l=512, o=128, deterministic, seed=42")

    # 1. Fit ITL models
    al_fit = fit_itl_model(al_data, "AL (Always-Local)")
    ad_fit = fit_itl_model(ad_data, "AD (Always-Disaggregate)")

    # 2. Fit TTFT models
    al_ttft_fit = fit_ttft_mg1(al_data, "AL TTFT")
    ad_ttft_fit = fit_ttft_mg1(ad_data, "AD TTFT")

    # 3. ITL comparison
    print("\n=== ITL Comparison: AL vs AD ===")
    print(f"  {'Rate':>5s}  {'ITL_AL':>8s}  {'ITL_AD':>8s}  {'Diff':>8s}  {'Paper':>7s}")
    for i in range(len(al_data)):
        r = al_data[i]['rate']
        ial, iad = al_data[i]['itl'], ad_data[i]['itl']
        diff = ial - iad
        holds = "OK" if diff >= -0.01 else "FAIL"
        print(f"  {r:5.0f}  {ial:8.3f}  {iad:8.3f}  {diff:+8.3f}  {holds:>7s}")

    # 4. TTFT comparison
    print("\n=== TTFT Comparison: AL vs AD ===")
    print(f"  {'Rate':>5s}  {'TTFT_AL':>8s}  {'TTFT_AD':>8s}  {'Diff':>8s}  {'Paper':>7s}")
    for i in range(len(al_data)):
        r = al_data[i]['rate']
        tal, tad = al_data[i]['ttft'], ad_data[i]['ttft']
        diff = tad - tal
        holds = "OK" if diff > 0 else "FAIL"
        print(f"  {r:5.0f}  {tal:8.3f}  {tad:8.3f}  {diff:+8.3f}  {holds:>7s}")

    # 5. Structural predictions
    print("\n=== Paper Structural Predictions ===")

    print(f"\n  P1: alpha same for AL and AD")
    print(f"      alpha_AL = {al_fit['alpha']:.4f} ms, alpha_AD = {ad_fit['alpha']:.4f} ms")
    ratio = al_fit['alpha'] / ad_fit['alpha'] if ad_fit['alpha'] > 0 else float('inf')
    print(f"      Ratio = {ratio:.3f}")

    print(f"\n  P2: C_0 same for AL and AD")
    print(f"      C_0_AL = {al_fit['c0']:.4f} ms, C_0_AD = {ad_fit['c0']:.4f} ms")

    print(f"\n  P3: AD has higher capacity (W_D < W_tot)")
    print(f"      AL capacity = {al_fit['capacity']:.1f} req/s")
    print(f"      AD capacity = {ad_fit['capacity']:.1f} req/s")
    print(f"      w_eff ratio (AL/AD) = {al_fit['w_eff']/ad_fit['w_eff']:.3f}")
    print(f"      This is the effective W_tot/W_D ratio")

    print(f"\n  P4: ITL model quality")
    print(f"      AL MAPE = {al_fit['mape']:.3f}%, AD MAPE = {ad_fit['mape']:.3f}%")
    print(f"      Model fits {'well' if max(al_fit['mape'], ad_fit['mape']) < 1 else 'moderately well' if max(al_fit['mape'], ad_fit['mape']) < 5 else 'poorly'}")

    # 6. E2E comparison
    print("\n=== E2E Latency: AL vs AD ===")
    print(f"  {'Rate':>5s}  {'E2E_AL':>9s}  {'E2E_AD':>9s}  {'Diff':>8s}  {'Winner':>7s}")
    crossover_rate = None
    for i in range(len(al_data)):
        r = al_data[i]['rate']
        eal, ead = al_data[i]['e2e'], ad_data[i]['e2e']
        diff = eal - ead
        winner = "AD" if diff > 0 else "AL"
        if diff > 0 and crossover_rate is None:
            crossover_rate = r
        print(f"  {r:5.0f}  {eal:9.3f}  {ead:9.3f}  {diff:+8.3f}  {winner:>7s}")
    if crossover_rate:
        print(f"\n  AD wins on E2E starting at rate >= {crossover_rate} req/s")

    # Save results
    results = {
        'al_itl_fit': {k: v for k, v in al_fit.items() if k not in ('predicted', 'residuals')},
        'ad_itl_fit': {k: v for k, v in ad_fit.items() if k not in ('predicted', 'residuals')},
        'al_ttft_fit': {k: v for k, v in al_ttft_fit.items() if k not in ('predicted', 'residuals')},
        'ad_ttft_fit': {k: v for k, v in ad_ttft_fit.items() if k not in ('predicted', 'residuals')},
        'al_data': al_data,
        'ad_data': ad_data,
    }
    with open('final/data/analysis_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    return al_fit, ad_fit


if __name__ == '__main__':
    main()
