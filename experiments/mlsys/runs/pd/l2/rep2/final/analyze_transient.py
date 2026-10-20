#!/usr/bin/env python3
"""Check whether finite-experiment transient effects explain the concave ITL growth.

Key hypothesis: With 300 requests, the ramp-up and drain phases have lower batch sizes
than steady state, pulling the mean ITL below the M/G/1 steady-state prediction.
This effect is more pronounced at higher rates (shorter experiment duration).
"""
import json
import math

# Data from sweep
data = {
    'AL': [
        (1, 12.261), (2, 12.320), (5, 12.491), (10, 12.801),
        (15, 13.113), (20, 13.436), (25, 13.767), (30, 14.103),
        (35, 14.447), (40, 14.793), (45, 15.146), (50, 15.498),
        (55, 15.845), (60, 16.183), (65, 16.521), (70, 16.842),
        (75, 17.148), (80, 17.436), (85, 17.712), (90, 17.969),
        (95, 18.208), (100, 18.436), (110, 18.837), (120, 19.172),
        (130, 19.450), (140, 19.686), (150, 19.889),
    ],
    'AD': [
        (1, 12.261), (2, 12.303), (5, 12.434), (10, 12.672),
        (15, 12.910), (20, 13.153), (25, 13.401), (30, 13.651),
        (35, 13.904), (40, 14.161), (45, 14.414), (50, 14.668),
        (55, 14.921), (60, 15.170), (65, 15.414), (70, 15.651),
        (75, 15.878), (80, 16.101), (85, 16.311), (90, 16.510),
        (95, 16.701), (100, 16.880), (110, 17.215), (120, 17.510),
        (130, 17.769), (140, 18.002), (150, 18.204),
    ]
}

print("Transient Effect Analysis")
print("=" * 60)

for mode in ['AL', 'AD']:
    points = data[mode]
    print(f"\n--- {mode} ---")

    # Estimate steady-state ITL from the paper's model:
    # T_iter = alpha/(1-rho), ITL = T_iter + C_0
    # The zero-load ITL gives alpha + C_0 = 12.26 ms
    # The derivative dITL/dlambda at lambda=0 gives alpha * w_eff
    # From points near zero load:
    itl_0 = points[0][1]  # rate=1
    itl_10 = points[3][1]  # rate=10

    # Approximate dITL/dlambda from low-rate data
    dITL = (itl_10 - itl_0) / (10 - 1)

    # For AL: w_eff = W_tot/N_D = W_tot/2
    # dITL/dlambda ≈ alpha * w_eff at low rho
    # alpha ≈ itl_0, w_eff ≈ dITL / itl_0

    alpha_est = itl_0
    w_eff_est = dITL / alpha_est

    print(f"  Zero-load ITL = {itl_0:.3f} ms (≈ alpha + C_0)")
    print(f"  Low-rate dITL/dlambda = {dITL:.4f} ms per req/s")
    print(f"  Estimated w_eff = {w_eff_est:.6f}")
    print(f"  Estimated capacity = {1/w_eff_est:.0f} req/s")

    # Compute transient effect: with 300 requests at rate lambda,
    # the experiment lasts ~300/lambda seconds.
    # During ramp-up (first ~alpha/delta seconds), the batch is building up.
    # During drain (last ~alpha/delta seconds), the batch is emptying.
    # These periods have lower ITL than steady state.

    # Steady-state batch size B_ss = lambda * T_iter * (1 + 128) for n_c=1
    # = lambda * alpha/(1-rho) * 129
    # But we use N=2 instances for AL, so per-instance: lambda/2 * T_iter * 129

    n_instances = 2  # effective instances for both AL and AD decode
    o = 128  # output tokens
    n_c = 1  # prefill chunks (unlimited budget)
    total_iters_per_request = n_c + o  # 129

    print(f"\n  Rate  Exp_dur(s)  B_ss   rho    MG1_pred   Measured  Residual  Frac_transient")
    for rate, itl in points:
        rho = rate * w_eff_est
        if rho >= 1:
            print(f"  {rate:5.0f}  UNSTABLE")
            continue

        t_iter_ss = alpha_est / (1 - rho)
        b_ss = (rate / n_instances) * t_iter_ss / 1000 * total_iters_per_request

        # Experiment duration
        exp_dur = 300 / rate  # seconds

        # Ramp-up time: approximately the time for the batch to reach B_ss
        # This is roughly B_ss * T_iter / n_c (time to fill the batch)
        # Actually it's more nuanced, but roughly the first B_ss requests
        # arrive over B_ss / (rate/n_instances) seconds
        ramp_up_s = b_ss / (rate / n_instances) if rate > 0 else 0

        # Drain time: the last request arrives at 300/rate seconds,
        # and it takes ~129 * T_iter to process = ~129 * T_iter_ss ms
        drain_s = 129 * t_iter_ss / 1e3  # ms to s

        frac_transient = min(1.0, (ramp_up_s + drain_s) / exp_dur) if exp_dur > 0 else 0

        mg1_pred = t_iter_ss  # ITL ≈ T_iter in our model (C_0 absorbed)
        residual = itl - mg1_pred

        print(f"  {rate:5.0f}  {exp_dur:8.1f}    {b_ss:4.1f}  {rho:5.3f}  {mg1_pred:8.3f}    {itl:8.3f}  {residual:+7.3f}    {frac_transient:.2f}")


# Now examine the rate-dependence of the ITL growth rate
print("\n" + "=" * 60)
print("Empirical ITL Growth Rate (Δ ITL / Δ rate)")
print("=" * 60)

for mode in ['AL', 'AD']:
    points = data[mode]
    print(f"\n--- {mode} ---")
    print(f"  {'Rate_mid':>8s}  {'dITL/dlam':>10s}  {'MG1_pred':>10s}  {'Ratio':>8s}")

    for i in range(1, len(points)):
        r0, itl0 = points[i-1]
        r1, itl1 = points[i]
        actual_slope = (itl1 - itl0) / (r1 - r0)

        # M/G/1 prediction: dITL/dlambda = alpha * w_eff / (1-rho)^2
        # where rho = lambda_mid * w_eff
        alpha_est = points[0][1]
        dITL_01 = (points[3][1] - points[0][1]) / (10 - 1)
        w_eff_est = dITL_01 / alpha_est
        r_mid = (r0 + r1) / 2
        rho_mid = r_mid * w_eff_est
        mg1_slope = alpha_est * w_eff_est / (1 - rho_mid)**2

        ratio = actual_slope / mg1_slope if mg1_slope > 0 else 0
        print(f"  {r_mid:8.1f}  {actual_slope:10.4f}  {mg1_slope:10.4f}  {ratio:8.3f}")

print("\nIf ratio < 1, actual ITL grows slower than M/G/1 predicts")
print("If ratio > 1, actual ITL grows faster")
print("Ratio decreasing with rate = concave deviation (transient effect)")
