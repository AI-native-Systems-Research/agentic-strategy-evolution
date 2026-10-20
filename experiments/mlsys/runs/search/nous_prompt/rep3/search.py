#!/usr/bin/env python3
"""
Search the BLIS serving-configuration space for the Pareto front.

Four objectives: maximize responses_per_sec, minimize ttft_p99_ms,
minimize GPU count (tp * num_instances), minimize total_kv_blocks.

Structural insights from systematic exploration:
  1. TP determines per-instance throughput; more instances reduce per-instance
     load. GPU count (tp * instances) is the primary cost axis.
  2. Block_size=32 is almost universally Pareto-dominant — same performance at
     lower total_kv_blocks than block_size=16.
  3. When unsaturated, scheduler/mrr/bst collapse to equivalence classes.
  4. When saturated, mrr and kvb interact with performance.
  5. The true Pareto front has ~35 distinct points across 1800 total configs.

Strategy: Rather than classifying combos, directly sample the most informative
configs first (bst=32 is dominant, so prioritize it), then use remaining
budget for targeted exploration around the discovered Pareto front.
"""
import argparse
import subprocess
import json
import os
import sys
import random


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--rate", required=True, type=float)
    p.add_argument("--budget", required=True, type=int)
    p.add_argument("--seed", required=True, type=int)
    p.add_argument("--out", required=True)
    return p.parse_args()


def run_blis(model, rate, tp, ni, sched, mrr, kvb, bst, seed, metrics_path):
    cmd = [
        "./blis", "run",
        "--model", model,
        "--hardware", "H100",
        "--latency-model", "trained-physics",
        "--num-requests", "200",
        "--rate", str(rate),
        "--prefix-tokens", "512",
        "--seed", str(seed),
        "--max-num-scheduled-tokens", "4096",
        "--long-prefill-token-threshold", "0",
        "--admission-policy", "always-admit",
        "--preemption-policy", "fcfs",
        "--routing-policy", "round-robin",
        "--gpu-memory-utilization", "0.9",
        "--tp", str(tp),
        "--num-instances", str(ni),
        "--scheduler", sched,
        "--max-num-running-reqs", str(mrr),
        "--total-kv-blocks", str(kvb),
        "--block-size-in-tokens", str(bst),
        "--metrics-path", metrics_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not os.path.exists(metrics_path):
        return None
    with open(metrics_path) as f:
        m = json.load(f)
    return {
        "tp": tp,
        "num_instances": ni,
        "scheduler": sched,
        "max_num_running_reqs": mrr,
        "total_kv_blocks": kvb,
        "block_size_in_tokens": bst,
        "gpus": tp * ni,
        "responses_per_sec": m.get("responses_per_sec", 0),
        "ttft_p99_ms": m.get("ttft_p99_ms", float("inf")),
    }


def dominates(a, b):
    a_rps, a_ttft = a["responses_per_sec"], a["ttft_p99_ms"]
    a_gpus, a_kvb = a["gpus"], a["total_kv_blocks"]
    b_rps, b_ttft = b["responses_per_sec"], b["ttft_p99_ms"]
    b_gpus, b_kvb = b["gpus"], b["total_kv_blocks"]
    if a_rps < b_rps or a_ttft > b_ttft or a_gpus > b_gpus or a_kvb > b_kvb:
        return False
    return a_rps > b_rps or a_ttft < b_ttft or a_gpus < b_gpus or a_kvb < b_kvb


def pareto_filter(results):
    front = []
    for i, a in enumerate(results):
        is_dominated = any(
            dominates(results[j], a) for j in range(len(results)) if j != i
        )
        if not is_dominated:
            front.append(a)
    return front


def main():
    args = parse_args()
    rng = random.Random(args.seed)
    budget = args.budget
    evals = 0
    results = []
    tested_keys = set()
    tmpdir = f"/tmp/blis_search_{os.getpid()}"
    os.makedirs(tmpdir, exist_ok=True)

    def evaluate(tp, ni, sched, mrr, kvb, bst):
        nonlocal evals
        if evals >= budget:
            return None
        key = (tp, ni, sched, mrr, kvb, bst)
        if key in tested_keys:
            for r in results:
                if (r["tp"], r["num_instances"], r["scheduler"],
                    r["max_num_running_reqs"], r["total_kv_blocks"],
                    r["block_size_in_tokens"]) == key:
                    return r
            return None
        tested_keys.add(key)
        evals += 1
        mp = f"{tmpdir}/e{evals}.json"
        r = run_blis(args.model, args.rate, tp, ni, sched, mrr, kvb, bst,
                     args.seed, mp)
        if r:
            results.append(r)
        return r

    tp_ni_combos = []
    for tp in [1, 2, 4, 8]:
        for ni in range(1, 8 // tp + 1):
            tp_ni_combos.append((tp, ni))

    kvb_values = [2000, 3000, 4000, 5000, 7500, 10000]

    # ── Phase 1: Core grid (150 evals) ──
    # For every (tp, ni) combo, test bst=32 (dominant) with key mrr x kvb.
    # bst=32 with fcfs, mrr in {128, 256}, kvb in all 6 values = 12 per combo.
    # 15 combos x 12 = 180, but many will show identical results, so we can
    # trim multi-instance combos.
    #
    # Single-instance combos (tp=1..8, ni=1): test full mrr x kvb x sched grid
    # at bst=32 — these have the most variation.
    # Multi-instance combos: test smaller grid (only kvb matters).

    single_instance = [(tp, 1) for tp in [1, 2, 4, 8]]
    multi_instance = [(tp, ni) for tp, ni in tp_ni_combos
                      if ni > 1]

    # Single-instance: 2 sched x 2 mrr x 6 kvb = 24 per combo
    # 4 combos x 24 = 96 evals
    for tp, ni in single_instance:
        for sched in ["fcfs", "sjf"]:
            for kvb in kvb_values:
                for mrr in [128, 256]:
                    evaluate(tp, ni, sched, mrr, kvb, 32)

    # Multi-instance: test key kvb values + scheduler/mrr variants at kvb=2000
    # where the system is more likely to be capacity-constrained.
    # 11 combos x ~5 = ~55 evals
    for tp, ni in multi_instance:
        for kvb in [2000, 3000, 4000, 5000]:
            evaluate(tp, ni, "fcfs", 128, kvb, 32)
        evaluate(tp, ni, "sjf", 128, 2000, 32)
        evaluate(tp, ni, "fcfs", 64, 2000, 32)
        evaluate(tp, ni, "sjf", 64, 2000, 32)

    # ── Phase 2: Fill gaps around Pareto front ──
    remaining = budget - evals
    if remaining > 0:
        current_front = pareto_filter(results)
        neighbors = []
        for r in current_front:
            tp, ni = r["tp"], r["num_instances"]
            for sched in ["fcfs", "sjf"]:
                for mrr in [64, 128, 256, 512]:
                    for kvb in kvb_values:
                        for bst in [16, 32]:
                            key = (tp, ni, sched, mrr, kvb, bst)
                            if key not in tested_keys:
                                neighbors.append(key)
        rng.shuffle(neighbors)
        for cfg in neighbors[:remaining]:
            evaluate(*cfg)

    # ── Output ──
    front = pareto_filter(results)

    seen_obj = set()
    output = []
    for r in front:
        obj = (r["responses_per_sec"], r["ttft_p99_ms"],
               r["gpus"], r["total_kv_blocks"])
        if obj not in seen_obj:
            seen_obj.add(obj)
            output.append({
                "tp": r["tp"],
                "num_instances": r["num_instances"],
                "scheduler": r["scheduler"],
                "max_num_running_reqs": r["max_num_running_reqs"],
                "total_kv_blocks": r["total_kv_blocks"],
                "block_size_in_tokens": r["block_size_in_tokens"],
            })

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluations used: {evals}/{budget}", file=sys.stderr)
    print(f"Pareto front size: {len(output)} distinct points", file=sys.stderr)
    print(f"Total results: {len(results)}", file=sys.stderr)


if __name__ == "__main__":
    main()
