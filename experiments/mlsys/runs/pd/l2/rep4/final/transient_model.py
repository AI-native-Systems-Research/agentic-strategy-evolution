#!/usr/bin/env python3
"""
Transient batch-dynamics model: simulate discrete batch evolution
with finite 300-request burst to explain the ITL formula breakdown.

We model the decode instance as a discrete-time system where:
- Requests arrive according to Poisson process at rate lambda/N_D per instance
- Each step takes T_step = alpha + delta * B(t) microseconds
- Each request occupies 129 steps (1 prefill + 128 decode)
- Requests depart after completing their steps

This captures the transient build-up of the batch that the
paper's steady-state Little's law analysis assumes is instantaneous.
"""

import math
import json

# Parameters from BLIS
ALPHA_US = 12157.2      # per-iteration overhead (us)
DELTA_AVG_US = 75.49    # per-request per-iteration marginal cost (us)
N_ITERS = 129           # steps per request (1 prefill + 128 decode)
N_D = 2                 # decode instances
NUM_REQUESTS = 300
ALPHA_2_US = 45.9       # OutputTokenProcessingTime
C0_US = 105.3           # single-request overhead in ITL

def simulate_batch_dynamics(lam, verbose=False):
    """Simulate batch evolution for a finite burst at rate lam.

    Returns: time-weighted average batch size, average step time, predicted ITL.
    """
    per_instance_rate = lam / N_D
    requests_per_instance = NUM_REQUESTS // N_D  # 150

    # Generate inter-arrival times (deterministic for analysis)
    if per_instance_rate <= 0:
        return 0, ALPHA_US, ALPHA_US / 1000

    inter_arrival_us = 1e6 / per_instance_rate  # us between arrivals

    # Track each request's remaining steps
    # active_requests[i] = remaining steps for request i
    active_requests = []

    # Track arrival times
    next_arrival_idx = 0
    next_arrival_time = 0.0  # us

    current_time = 0.0
    total_step_time = 0.0
    num_steps = 0
    batch_size_sum = 0.0

    # Simulate step by step
    while active_requests or next_arrival_idx < requests_per_instance:
        # Add any requests that have arrived by current_time
        while next_arrival_idx < requests_per_instance and next_arrival_time <= current_time:
            active_requests.append(N_ITERS)
            next_arrival_idx += 1
            next_arrival_time = next_arrival_idx * inter_arrival_us

        if not active_requests:
            # Jump to next arrival
            if next_arrival_idx < requests_per_instance:
                current_time = next_arrival_time
                continue
            else:
                break

        # Compute step time
        B = len(active_requests)
        step_time = ALPHA_US + DELTA_AVG_US * B

        batch_size_sum += B * step_time
        total_step_time += step_time
        num_steps += 1

        # Advance time
        current_time += step_time

        # Each request in the batch completes one step
        active_requests = [r - 1 for r in active_requests if r > 1]

    avg_batch = batch_size_sum / total_step_time if total_step_time > 0 else 0
    avg_step_time = total_step_time / num_steps if num_steps > 0 else ALPHA_US
    avg_itl = avg_step_time + C0_US  # approximate

    return avg_batch, avg_step_time, avg_itl / 1000.0


def paper_steady_state(lam):
    """Paper's steady-state predictions."""
    W_tot_us = DELTA_AVG_US * N_ITERS
    per_instance_rate = lam / N_D
    rho = per_instance_rate * W_tot_us / 1e6

    if rho >= 1.0:
        return float('inf'), float('inf'), float('inf')

    t_iter = ALPHA_US / (1 - rho)
    B_ss = per_instance_rate * N_ITERS * t_iter / 1e6
    itl = (t_iter + C0_US) / 1000.0

    return B_ss, t_iter, itl


def main():
    # Load measurement data
    import csv
    al_data = {}
    with open("final/data/sweep_results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["mode"] == "never" and float(row["rate"]) <= 150:
                al_data[float(row["rate"])] = float(row["itl_mean_ms"])

    print("=" * 90)
    print("TRANSIENT BATCH DYNAMICS SIMULATION")
    print("=" * 90)
    print(f"{'Rate':>5} | {'B_sim':>7} {'B_ss':>7} {'B_ratio':>8} | "
          f"{'ITL_sim':>8} {'ITL_ss':>8} {'ITL_meas':>8} | "
          f"{'sim_err%':>9} {'ss_err%':>9}")

    results = []
    for rate in [1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]:
        B_sim, step_sim, itl_sim = simulate_batch_dynamics(rate)
        B_ss, step_ss, itl_ss = paper_steady_state(rate)

        itl_meas = al_data.get(rate, float('nan'))

        B_ss_s = f"{B_ss:.1f}" if B_ss < 1e5 else "INF"
        itl_ss_s = f"{itl_ss:.3f}" if itl_ss < 1e5 else "UNSTABLE"

        sim_err = (itl_sim - itl_meas) / itl_meas * 100 if not math.isnan(itl_meas) else 0
        ss_err = (itl_ss - itl_meas) / itl_meas * 100 if not math.isnan(itl_meas) and itl_ss < 1e5 else float('inf')
        ss_err_s = f"{ss_err:.1f}" if ss_err < 1e5 else "INF"

        ratio = B_sim / B_ss if B_ss > 0 and B_ss < 1e5 else 0

        print(f"{rate:5} | {B_sim:7.1f} {B_ss_s:>7} {ratio:8.3f} | "
              f"{itl_sim:8.3f} {itl_ss_s:>8} {itl_meas:8.3f} | "
              f"{sim_err:9.1f} {ss_err_s:>9}")

        results.append({
            "rate": rate,
            "B_simulated": round(B_sim, 2),
            "B_steady_state": round(B_ss, 2) if B_ss < 1e5 else None,
            "B_ratio": round(ratio, 4),
            "itl_simulated_ms": round(itl_sim, 3),
            "itl_steady_state_ms": round(itl_ss, 3) if itl_ss < 1e5 else None,
            "itl_measured_ms": round(itl_meas, 3) if not math.isnan(itl_meas) else None,
            "sim_error_pct": round(sim_err, 2),
            "ss_error_pct": round(ss_err, 2) if ss_err < 1e5 else None,
        })

    # Summary
    sim_errors = [abs(r["sim_error_pct"]) for r in results if r["itl_measured_ms"]]
    ss_errors = [abs(r["ss_error_pct"]) for r in results if r["ss_error_pct"] is not None and r["itl_measured_ms"]]

    sim_rmse = math.sqrt(sum(e**2 for e in sim_errors) / len(sim_errors))
    ss_rmse = math.sqrt(sum(e**2 for e in ss_errors) / len(ss_errors))

    print(f"\nRMSE of % errors:")
    print(f"  Transient simulation: {sim_rmse:.2f}%")
    print(f"  Steady-state formula: {ss_rmse:.2f}%")
    print(f"  Max transient error: {max(sim_errors):.1f}% at rate={[r['rate'] for r, e in zip(results, sim_errors) if e == max(sim_errors)][0]}")
    print(f"  Max steady-state error: {max(ss_errors):.1f}% at rate={[r['rate'] for r, e in zip(results, ss_errors) if e == max(ss_errors)][0]}")

    # At what rate does the steady-state formula diverge from the transient?
    for r in results:
        if r["ss_error_pct"] is not None and abs(r["ss_error_pct"]) > 5:
            print(f"\n  Steady-state error exceeds 5% at rate={r['rate']} (ρ={(r['rate']/N_D)*DELTA_AVG_US*N_ITERS/1e6:.3f})")
            break

    # Save
    with open("final/data/transient_model_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to final/data/transient_model_results.json")


if __name__ == "__main__":
    main()
