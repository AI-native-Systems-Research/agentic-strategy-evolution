"""
Measurement harness for iter-5 experiments.
Captures both direct warm-call timing (timeit) and harness timing (fork-based workload.py).
Outputs JSON per seed to results/<arm>/<seed>.json.
"""
import sys
import os
import json
import timeit
import statistics
import subprocess
import time

def measure_direct(n_warmup=10, n_measure=500):
    """Direct measurement: warm up, then time n_measure calls."""
    # Must import AFTER PYTHONPATH is set (done by caller)
    from sympy.solvers.diophantine import diop_DN
    D = 15591784605
    N = -20

    # Warm up
    for _ in range(n_warmup):
        sorted(diop_DN(D, N))

    # Measure
    times_us = []
    for _ in range(n_measure):
        t0 = time.perf_counter_ns()
        result = sorted(diop_DN(D, N))
        t1 = time.perf_counter_ns()
        times_us.append((t1 - t0) / 1000.0)

    # Verify correctness
    solutions = sorted(diop_DN(D, N))
    correct = all(x*x - D*y*y == N for x, y in solutions)

    return {
        "direct_mean_us": round(statistics.mean(times_us), 2),
        "direct_median_us": round(statistics.median(times_us), 2),
        "direct_min_us": round(min(times_us), 2),
        "direct_std_us": round(statistics.stdev(times_us), 2),
        "solutions_count": len(solutions),
        "solutions_correct": correct,
        "solutions": [(int(x), int(y)) for x, y in solutions],
    }

def measure_harness(workload_path="/tmp/workload.py", pythonpath=None):
    """Run the fork-based harness and capture its output."""
    env = os.environ.copy()
    if pythonpath:
        env["PYTHONPATH"] = pythonpath

    result = subprocess.run(
        [sys.executable, workload_path],
        capture_output=True, text=True, env=env, timeout=120
    )
    if result.returncode != 0:
        return {"error": result.stderr}

    lines = result.stdout.strip().split('\n')
    harness_mean = None
    harness_std = None
    for line in lines:
        if line.startswith("Mean:"):
            harness_mean = float(line.split(":")[1].strip())
        elif line.startswith("Std Dev:"):
            harness_std = float(line.split(":")[1].strip())

    return {
        "harness_mean_s": harness_mean,
        "harness_std_s": harness_std,
    }

def run_seed(seed_id, output_path, pythonpath):
    """Run one complete measurement for a seed."""
    direct = measure_direct(n_warmup=10, n_measure=500)
    harness = measure_harness(pythonpath=pythonpath)

    campaign_baseline = 57.3288
    result = {
        "seed": seed_id,
        **direct,
        **harness,
        "campaign_speedup_direct": round(campaign_baseline / (direct["direct_mean_us"] / 1e6)),
        "campaign_speedup_harness": round(campaign_baseline / harness["harness_mean_s"]) if harness.get("harness_mean_s") else None,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    return result

if __name__ == "__main__":
    seed = int(sys.argv[1])
    output = sys.argv[2]
    pythonpath = sys.argv[3] if len(sys.argv) > 3 else os.getcwd()
    result = run_seed(seed, output, pythonpath)
    print(json.dumps(result, indent=2))
