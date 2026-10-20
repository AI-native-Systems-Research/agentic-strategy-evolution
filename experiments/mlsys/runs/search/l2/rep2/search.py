#!/usr/bin/env python3
"""
Pareto-front search for BLIS LLM inference serving configurations.

Finds the non-dominated set over 4 objectives: maximize responses_per_sec,
minimize ttft_p99_ms, minimize GPU count (tp*instances), minimize total_kv_blocks.

Search strategy exploits empirically-discovered structure:

1. **Preemption boundary**: Each tp/instance combo has a minimum effective KV
   capacity below which preemptions degrade throughput and latency. bs=32
   doubles effective capacity vs bs=16, so bs=32 almost always dominates.

2. **mrr=256 phase transition**: For single-instance configs with sufficient KV,
   mrr=256 enables full GPU batching saturation — dramatically better than mrr=128
   (e.g., 93ms vs 12,000ms TTFT). Multi-instance configs already distribute load
   so mrr=128 suffices there.

3. **Scheduler near-irrelevance**: fcfs ≈ sjf in most configs. sjf creates marginal
   Pareto-distinct points only in the preemption regime.

4. **Massive redundancy**: 1800 configs collapse to ~35 unique objective vectors.
   Many scheduler/mrr/kv/bs combos produce identical performance once above the
   preemption threshold.

Budget allocation (targeting ~180 evals for 200 budget):
- Phase 1 (30): All tp/instance at mrr=128 and mrr=256 with safe KV
- Phase 2 (60-90): KV boundary sweep per tp/instance/mrr
- Phase 3 (30): Low mrr={32,64} exploration
- Phase 4 (12): SJF scheduler for single-instance
- Phase 5 (15): SJF + low-kv for multi-instance gap filling
- Phase 6 (15): Low-mrr + low-kv combos
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--budget", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    return p.parse_args()


FIXED_FLAGS_TEMPLATE = [
    "--hardware", "H100", "--latency-model", "trained-physics",
    "--num-requests", "200", "--prefix-tokens", "512",
    "--max-num-scheduled-tokens", "4096", "--long-prefill-token-threshold", "0",
    "--admission-policy", "always-admit", "--preemption-policy", "fcfs",
    "--routing-policy", "round-robin", "--gpu-memory-utilization", "0.9",
]

TP_INSTANCES = [
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 1), (2, 2), (2, 3), (2, 4),
    (4, 1), (4, 2),
    (8, 1),
]


def run_blis(config, model, rate, seed, tmpdir):
    metrics_path = os.path.join(tmpdir, "m.json")
    cmd = ["./blis", "run",
           "--model", model,
           "--rate", str(rate),
           "--seed", str(seed),
           ] + FIXED_FLAGS_TEMPLATE + [
        "--tp", str(config["tp"]),
        "--num-instances", str(config["num_instances"]),
        "--scheduler", config["scheduler"],
        "--max-num-running-reqs", str(config["max_num_running_reqs"]),
        "--total-kv-blocks", str(config["total_kv_blocks"]),
        "--block-size-in-tokens", str(config["block_size_in_tokens"]),
        "--metrics-path", metrics_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        with open(metrics_path) as f:
            metrics = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "responses_per_sec": metrics.get("responses_per_sec", 0),
        "ttft_p99_ms": metrics.get("ttft_p99_ms", float("inf")),
        "gpu_count": config["tp"] * config["num_instances"],
        "total_kv_blocks": config["total_kv_blocks"],
        "preemption_count": metrics.get("preemption_count", 0),
    }


def dominates(a, b):
    a_better = [
        a["responses_per_sec"] >= b["responses_per_sec"],
        a["ttft_p99_ms"] <= b["ttft_p99_ms"],
        a["gpu_count"] <= b["gpu_count"],
        a["total_kv_blocks"] <= b["total_kv_blocks"],
    ]
    a_strict = [
        a["responses_per_sec"] > b["responses_per_sec"],
        a["ttft_p99_ms"] < b["ttft_p99_ms"],
        a["gpu_count"] < b["gpu_count"],
        a["total_kv_blocks"] < b["total_kv_blocks"],
    ]
    return all(a_better) and any(a_strict)


def compute_pareto(evaluated):
    pareto = []
    items = list(evaluated.items())
    for i, (k1, v1) in enumerate(items):
        is_dominated = False
        for j, (k2, v2) in enumerate(items):
            if i != j and dominates(v2, v1):
                is_dominated = True
                break
        if not is_dominated:
            pareto.append((k1, v1))
    return pareto


def config_key(config):
    return (config["tp"], config["num_instances"], config["scheduler"],
            config["max_num_running_reqs"], config["total_kv_blocks"],
            config["block_size_in_tokens"])


def key_to_config(key):
    return {
        "tp": key[0], "num_instances": key[1], "scheduler": key[2],
        "max_num_running_reqs": key[3], "total_kv_blocks": key[4],
        "block_size_in_tokens": key[5],
    }


def evaluate(config, model, rate, seed, tmpdir, evaluated, eval_count_ref):
    key = config_key(config)
    if key in evaluated:
        return evaluated[key]
    m = run_blis(config, model, rate, seed, tmpdir)
    eval_count_ref[0] += 1
    if m is not None:
        evaluated[key] = m
        n = eval_count_ref[0]
        sys.stderr.write(
            f"[{n:3d}] tp={config['tp']} i={config['num_instances']} "
            f"s={config['scheduler']} mrr={config['max_num_running_reqs']} "
            f"kv={config['total_kv_blocks']} bs={config['block_size_in_tokens']}: "
            f"rps={m['responses_per_sec']:.2f} ttft={m['ttft_p99_ms']:.1f} "
            f"gpu={m['gpu_count']} preempt={m['preemption_count']}\n"
        )
    return m


def main():
    args = parse_args()
    model = args.model
    rate = args.rate
    budget = args.budget
    seed = args.seed

    evaluated = {}
    eval_count = [0]

    with tempfile.TemporaryDirectory() as tmpdir:
        def ev(config):
            if eval_count[0] >= budget:
                return None
            return evaluate(config, model, rate, seed, tmpdir, evaluated, eval_count)

        def budget_left():
            return budget - eval_count[0]

        # Phase 1: All tp/instance combos at mrr={128, 256} with safe KV (bs=32)
        # This establishes throughput ceilings and reveals the mrr=256 phase transition
        sys.stderr.write("=== Phase 1: TP/Instance x mrr ceiling scan ===\n")
        for tp, inst in TP_INSTANCES:
            for mrr in [128, 256]:
                ev({"tp": tp, "num_instances": inst, "scheduler": "fcfs",
                    "max_num_running_reqs": mrr, "total_kv_blocks": 5000,
                    "block_size_in_tokens": 32})

        # Phase 2: KV boundary search — bottom-up to save budget
        # Test kv=2000 first. If no preemption, skip higher kv (identical perf).
        # If preemption, test kv=3000 and kv=4000 to find the boundary.
        sys.stderr.write("\n=== Phase 2: KV boundary search ===\n")
        for tp, inst in TP_INSTANCES:
            for mrr in [128, 256]:
                m = ev({"tp": tp, "num_instances": inst, "scheduler": "fcfs",
                        "max_num_running_reqs": mrr, "total_kv_blocks": 2000,
                        "block_size_in_tokens": 32})
                if m is None:
                    break
                if m["preemption_count"] > 0:
                    for kv in [3000, 4000]:
                        m2 = ev({"tp": tp, "num_instances": inst, "scheduler": "fcfs",
                                 "max_num_running_reqs": mrr, "total_kv_blocks": kv,
                                 "block_size_in_tokens": 32})
                        if m2 is None:
                            break

        # Phase 3: Low-mrr exploration (mrr=32, 64 create distinct trade-off points)
        sys.stderr.write("\n=== Phase 3: Low-mrr exploration ===\n")
        for tp, inst in TP_INSTANCES:
            for mrr in [32, 64]:
                m = ev({"tp": tp, "num_instances": inst, "scheduler": "fcfs",
                        "max_num_running_reqs": mrr, "total_kv_blocks": 5000,
                        "block_size_in_tokens": 32})
                if m is None:
                    break

        # Phase 4: SJF for single-instance at ceiling KV
        sys.stderr.write("\n=== Phase 4: SJF scheduler ===\n")
        for tp, inst in TP_INSTANCES:
            if inst == 1:
                for mrr in [128, 256]:
                    ev({"tp": tp, "num_instances": inst, "scheduler": "sjf",
                        "max_num_running_reqs": mrr, "total_kv_blocks": 5000,
                        "block_size_in_tokens": 32})
                ev({"tp": tp, "num_instances": inst, "scheduler": "sjf",
                    "max_num_running_reqs": 128, "total_kv_blocks": 3000,
                    "block_size_in_tokens": 32})

        # Phase 5: SJF + mrr=256 at preemption boundary for single-instance
        sys.stderr.write("\n=== Phase 5: SJF boundary exploration ===\n")
        for tp, inst in TP_INSTANCES:
            if budget_left() <= 0:
                break
            if inst == 1:
                for kv in [4000, 3000]:
                    ev({"tp": tp, "num_instances": inst, "scheduler": "sjf",
                        "max_num_running_reqs": 256, "total_kv_blocks": kv,
                        "block_size_in_tokens": 32})

        # Phase 6: SJF for multi-instance with low kv (fills gap for sjf Pareto points)
        sys.stderr.write("\n=== Phase 6: SJF multi-instance low-kv ===\n")
        for tp, inst in TP_INSTANCES:
            if budget_left() <= 0:
                break
            if inst > 1:
                for kv in [2000, 3000]:
                    ev({"tp": tp, "num_instances": inst, "scheduler": "sjf",
                        "max_num_running_reqs": 128, "total_kv_blocks": kv,
                        "block_size_in_tokens": 32})

        # Phase 7: mrr=64 at low kv for multi-instance Pareto diversity
        sys.stderr.write("\n=== Phase 7: Low mrr + low kv ===\n")
        for tp, inst in TP_INSTANCES:
            if budget_left() <= 0:
                break
            ev({"tp": tp, "num_instances": inst, "scheduler": "fcfs",
                "max_num_running_reqs": 64, "total_kv_blocks": 2000,
                "block_size_in_tokens": 32})

        # Phase 8: sjf mrr=64 at low kv for multi-instance (marginal Pareto points)
        sys.stderr.write("\n=== Phase 8: SJF low-mrr low-kv ===\n")
        for tp, inst in TP_INSTANCES:
            if budget_left() <= 0:
                break
            if inst > 1:
                ev({"tp": tp, "num_instances": inst, "scheduler": "sjf",
                    "max_num_running_reqs": 64, "total_kv_blocks": 2000,
                    "block_size_in_tokens": 32})

        # Compute final Pareto front
        pareto = compute_pareto(evaluated)

        output = []
        for key, metrics in pareto:
            output.append(key_to_config(key))

        output.sort(key=lambda c: (c["tp"] * c["num_instances"],
                                   -c["tp"], c["total_kv_blocks"]))

        with open(args.out, "w") as f:
            json.dump(output, f, indent=2)

        sys.stderr.write(f"\n=== Done: {eval_count[0]} evaluations, "
                         f"{len(pareto)} Pareto-optimal configs ===\n")
        for key, metrics in sorted(pareto, key=lambda x: (x[1]["gpu_count"],
                                                           -x[1]["responses_per_sec"])):
            c = key_to_config(key)
            sys.stderr.write(
                f"  tp={c['tp']} i={c['num_instances']} s={c['scheduler']} "
                f"mrr={c['max_num_running_reqs']} kv={c['total_kv_blocks']} "
                f"bs={c['block_size_in_tokens']}: "
                f"rps={metrics['responses_per_sec']:.2f} "
                f"ttft={metrics['ttft_p99_ms']:.1f} "
                f"gpu={metrics['gpu_count']}\n"
            )


if __name__ == "__main__":
    main()
