#!/usr/bin/env python3
"""
Pareto-front search for BLIS serving configurations.

Searches 6 knobs (tp, num_instances, scheduler, max_num_running_reqs,
total_kv_blocks, block_size_in_tokens) to find non-dominated configs
across 4 objectives: maximize responses_per_sec, minimize ttft_p99_ms,
minimize gpu_count, minimize total_kv_blocks.

Space structure (1800 total configs):
  - tp in {1,2,4,8}, instances in {1..8/tp} → 15 combos
  - scheduler in {fcfs, sjf}
  - max_num_running_reqs in {32, 64, 128, 256, 512}
  - total_kv_blocks in {2000, 3000, 4000, 5000, 7500, 10000}
  - block_size_in_tokens in {16, 32}

Key findings driving the search design:
  1. block_size=32 dominates 16 (more capacity per block)
  2. sjf trades ~5% better rps for ~10% worse ttft vs fcfs
  3. maxr >= 128 all behave identically; 32 and 64 cause queuing
  4. KV blocks have a threshold effect per config
  5. Higher TP gives better throughput per GPU

Strategy (5 phases):
  Phase 1 (15 evals): All tp/inst at mid-ceiling (kv=5000, maxr=128, bs=32, fcfs)
  Phase 2 (5 evals): Sensitivity checks for block_size and scheduler
  Phase 3 (~105 evals): Core sweep: kv={2000,3000,4000} × maxr={32,128} for all tp/inst
  Phase 4 (~32 evals): sjf sweep for single-instance configs
  Phase 5 (remaining): Fill maxr=64 gaps, kv=7500, and verify alternatives
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

TP_VALUES = [1, 2, 4, 8]
MAX_GPUS = 8

FIXED_FLAGS_TEMPLATE = [
    "--hardware", "H100",
    "--latency-model", "trained-physics",
    "--num-requests", "200",
    "--prefix-tokens", "512",
    "--max-num-scheduled-tokens", "4096",
    "--long-prefill-token-threshold", "0",
    "--admission-policy", "always-admit",
    "--preemption-policy", "fcfs",
    "--routing-policy", "round-robin",
    "--gpu-memory-utilization", "0.9",
]


def get_tp_inst_combos():
    combos = []
    for tp in TP_VALUES:
        for inst in range(1, MAX_GPUS // tp + 1):
            combos.append((tp, inst))
    return combos


def run_blis(cfg, model, rate, seed, metrics_dir, eval_id):
    metrics_path = os.path.join(metrics_dir, f"eval_{eval_id}.json")
    cmd = ["./blis", "run",
           "--model", model, "--rate", str(rate), "--seed", str(seed),
           ] + FIXED_FLAGS_TEMPLATE + [
           "--tp", str(cfg["tp"]),
           "--num-instances", str(cfg["num_instances"]),
           "--scheduler", cfg["scheduler"],
           "--max-num-running-reqs", str(cfg["max_num_running_reqs"]),
           "--total-kv-blocks", str(cfg["total_kv_blocks"]),
           "--block-size-in-tokens", str(cfg["block_size_in_tokens"]),
           "--metrics-path", metrics_path,
           ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        with open(metrics_path) as f:
            data = json.load(f)
        return {
            "responses_per_sec": data["responses_per_sec"],
            "ttft_p99_ms": data["ttft_p99_ms"],
            "gpu_count": cfg["tp"] * cfg["num_instances"],
            "total_kv_blocks": cfg["total_kv_blocks"],
        }
    except Exception:
        return None


def dominates(a, b):
    ge = (a["responses_per_sec"] >= b["responses_per_sec"] and
          a["ttft_p99_ms"] <= b["ttft_p99_ms"] and
          a["gpu_count"] <= b["gpu_count"] and
          a["total_kv_blocks"] <= b["total_kv_blocks"])
    gt = (a["responses_per_sec"] > b["responses_per_sec"] or
          a["ttft_p99_ms"] < b["ttft_p99_ms"] or
          a["gpu_count"] < b["gpu_count"] or
          a["total_kv_blocks"] < b["total_kv_blocks"])
    return ge and gt


def compute_pareto(results):
    pareto = []
    for i, (ci, mi) in enumerate(results):
        if not any(dominates(mj, mi) for j, (cj, mj) in enumerate(results) if i != j):
            pareto.append((ci, mi))
    return pareto


def make_cfg(tp, inst, scheduler="fcfs", maxr=128, kv=5000, bs=32):
    return {"tp": tp, "num_instances": inst, "scheduler": scheduler,
            "max_num_running_reqs": maxr, "total_kv_blocks": kv,
            "block_size_in_tokens": bs}


def cfg_key(cfg):
    return (cfg["tp"], cfg["num_instances"], cfg["scheduler"],
            cfg["max_num_running_reqs"], cfg["total_kv_blocks"],
            cfg["block_size_in_tokens"])


def search(model, rate, budget, seed, out_path):
    metrics_dir = tempfile.mkdtemp(prefix="blis_search_")
    all_results = []
    seen = set()
    eval_count = [0]

    def evaluate(cfg):
        key = cfg_key(cfg)
        if key in seen or eval_count[0] >= budget:
            return None
        seen.add(key)
        eval_count[0] += 1
        met = run_blis(cfg, model, rate, seed, metrics_dir, eval_count[0])
        if met is not None:
            all_results.append((dict(cfg), met))
        return met

    tp_inst_combos = get_tp_inst_combos()  # 15 combos
    single_inst = [(tp, 1) for tp in TP_VALUES]  # 4 combos

    # -----------------------------------------------------------
    # Phase 1 (15 evals): All tp/inst at ceiling
    # Use kv=5000, maxr=128 so these overlap with Phase 3 grid
    # -----------------------------------------------------------
    ceiling = {}
    for tp, inst in tp_inst_combos:
        cfg = make_cfg(tp, inst, "fcfs", 128, 5000, 32)
        met = evaluate(cfg)
        if met:
            ceiling[(tp, inst)] = met

    # -----------------------------------------------------------
    # Phase 2 (5 evals): Sensitivity checks
    # -----------------------------------------------------------
    # 2a. Block-size: test bs=16 on 2 diverse stressed configs
    best_bs = 32
    bs16_better = 0
    for tp, inst in [(2, 1), (8, 1)]:
        met16 = evaluate(make_cfg(tp, inst, "fcfs", 128, 3000, 16))
        met32 = evaluate(make_cfg(tp, inst, "fcfs", 128, 3000, 32))
        if met16 and met32:
            if (met16["responses_per_sec"] > met32["responses_per_sec"] and
                    met16["ttft_p99_ms"] < met32["ttft_p99_ms"]):
                bs16_better += 1
    if bs16_better >= 1:
        best_bs = 16

    # 2b. Scheduler: check if sjf creates trade-off on 1 config
    sjf_tradeoff = False
    met_sjf = evaluate(make_cfg(4, 1, "sjf", 128, 5000, best_bs))
    if met_sjf and (4, 1) in ceiling:
        if met_sjf["responses_per_sec"] > ceiling[(4, 1)]["responses_per_sec"] * 1.01:
            sjf_tradeoff = True

    # -----------------------------------------------------------
    # Phase 3 (~105 evals): Core KV × maxr sweep with fcfs
    # kv in {2000, 3000, 4000} × maxr in {32, 128} for all 15 tp/inst
    # Plus kv=5000 × maxr=32 (kv=5000 × maxr=128 already from Phase 1)
    # -----------------------------------------------------------
    for tp, inst in tp_inst_combos:
        if eval_count[0] >= budget:
            break
        for kv in [2000, 3000, 4000]:
            for maxr in [32, 128]:
                if eval_count[0] >= budget:
                    break
                evaluate(make_cfg(tp, inst, "fcfs", maxr, kv, best_bs))
        # Also test kv=5000 with maxr=32
        evaluate(make_cfg(tp, inst, "fcfs", 32, 5000, best_bs))

    # -----------------------------------------------------------
    # Phase 4 (~32 evals): sjf for single-instance configs
    # These create genuine rps/ttft trade-offs
    # -----------------------------------------------------------
    if sjf_tradeoff:
        for tp, inst in single_inst:
            if eval_count[0] >= budget:
                break
            for kv in [2000, 3000, 4000, 5000]:
                for maxr in [32, 128]:
                    if eval_count[0] >= budget:
                        break
                    evaluate(make_cfg(tp, inst, "sjf", maxr, kv, best_bs))

    # -----------------------------------------------------------
    # Phase 5 (remaining): Fill gaps adaptively
    # -----------------------------------------------------------
    remaining = budget - eval_count[0]

    if remaining > 0:
        # 5a. Test maxr=64 for all tp/inst at promising KV values
        for tp, inst in tp_inst_combos:
            if eval_count[0] >= budget:
                break
            for kv in [2000, 3000, 4000]:
                if eval_count[0] >= budget:
                    break
                evaluate(make_cfg(tp, inst, "fcfs", 64, kv, best_bs))

    remaining = budget - eval_count[0]

    if remaining > 0:
        # 5b. Test kv=7500 for configs where kv=5000 was better than kv=4000
        for tp, inst in tp_inst_combos:
            if eval_count[0] >= budget:
                break
            evaluate(make_cfg(tp, inst, "fcfs", 128, 7500, best_bs))

    remaining = budget - eval_count[0]

    if remaining > 0:
        # 5c. sjf at maxr=64 for single-instance
        if sjf_tradeoff:
            for tp, inst in single_inst:
                if eval_count[0] >= budget:
                    break
                for kv in [2000, 3000, 4000, 5000]:
                    if eval_count[0] >= budget:
                        break
                    evaluate(make_cfg(tp, inst, "sjf", 64, kv, best_bs))

    remaining = budget - eval_count[0]

    if remaining > 0:
        # 5d. Test kv=10000 and kv=7500 for single-instance sjf
        if sjf_tradeoff:
            for tp, inst in single_inst:
                if eval_count[0] >= budget:
                    break
                for kv in [7500, 10000]:
                    if eval_count[0] >= budget:
                        break
                    evaluate(make_cfg(tp, inst, "sjf", 128, kv, best_bs))

    remaining = budget - eval_count[0]

    if remaining > 0:
        # 5e. Alternative bs for current Pareto configs
        alt_bs = 16 if best_bs == 32 else 32
        current_pareto = compute_pareto(all_results)
        for cfg, met in current_pareto:
            if eval_count[0] >= budget:
                break
            alt_cfg = dict(cfg)
            alt_cfg["block_size_in_tokens"] = alt_bs
            evaluate(alt_cfg)

    # Compute final Pareto front
    final_pareto = compute_pareto(all_results)

    output = []
    for cfg, met in final_pareto:
        output.append({
            "tp": cfg["tp"],
            "num_instances": cfg["num_instances"],
            "scheduler": cfg["scheduler"],
            "max_num_running_reqs": cfg["max_num_running_reqs"],
            "total_kv_blocks": cfg["total_kv_blocks"],
            "block_size_in_tokens": cfg["block_size_in_tokens"],
        })

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluations used: {eval_count[0]}/{budget}", file=sys.stderr)
    print(f"Pareto front size: {len(final_pareto)}", file=sys.stderr)
    print(f"Results written to: {out_path}", file=sys.stderr)

    return final_pareto, eval_count[0]


def main():
    parser = argparse.ArgumentParser(description="BLIS Pareto-front search")
    parser.add_argument("--model", required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    search(args.model, args.rate, args.budget, args.seed, args.out)


if __name__ == "__main__":
    main()
