#!/usr/bin/env python3
"""
Pareto-front search for BLIS serving configurations.

The space has ~1800 configs across 6 knobs with 4 objectives:
  maximize responses_per_sec, minimize ttft_p99_ms,
  minimize GPU count (tp*instances), minimize total_kv_blocks.

Key structural insights driving the search strategy:
1. TP is the dominant throughput knob (~2x per doubling).
2. Multi-instance eliminates saturation; minimum viable kvb dominates.
3. Single-instance has rich knob interactions: kvb threshold, mrr regimes.
4. block_size=32 weakly dominates 16 in the saturated regime.
5. Scheduler (sjf vs fcfs) only differs in saturated single-instance regime,
   and occasionally in tight-resource multi-instance.
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
    p.add_argument("--rate", required=True, type=float)
    p.add_argument("--budget", required=True, type=int)
    p.add_argument("--seed", required=True, type=int)
    p.add_argument("--out", required=True)
    return p.parse_args()


FIXED_TEMPLATE = (
    "--hardware H100 --latency-model trained-physics "
    "--num-requests 200 --prefix-tokens 512 "
    "--max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 "
    "--admission-policy always-admit --preemption-policy fcfs "
    "--routing-policy round-robin --gpu-memory-utilization 0.9"
)

TP_VALUES = [1, 2, 4, 8]


def valid_ni_range(tp):
    return range(1, 8 // tp + 1)


def run_blis(model, rate, seed, tp, ni, scheduler, mrr, kvb, bs, tmpdir):
    tag = f"m_{tp}_{ni}_{scheduler}_{mrr}_{kvb}_{bs}"
    metrics_path = os.path.join(tmpdir, f"{tag}.json")
    cmd = (
        f"./blis run --model {model} --rate {rate} --seed {seed} "
        f"{FIXED_TEMPLATE} "
        f"--tp {tp} --num-instances {ni} --scheduler {scheduler} "
        f"--max-num-running-reqs {mrr} --total-kv-blocks {kvb} "
        f"--block-size-in-tokens {bs} --metrics-path {metrics_path}"
    )
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        with open(metrics_path) as f:
            m = json.load(f)
        return {
            "tp": tp, "num_instances": ni, "scheduler": scheduler,
            "max_num_running_reqs": mrr, "total_kv_blocks": kvb,
            "block_size_in_tokens": bs,
            "gpus": tp * ni,
            "rps": m.get("responses_per_sec", 0),
            "ttft_p99": m.get("ttft_p99_ms", 999999),
        }
    except Exception:
        return None


def dominates(a, b):
    a_rps = a["rps"]; a_ttft = a["ttft_p99"]; a_gpus = a["gpus"]; a_kvb = a["total_kv_blocks"]
    b_rps = b["rps"]; b_ttft = b["ttft_p99"]; b_gpus = b["gpus"]; b_kvb = b["total_kv_blocks"]
    geq = (a_rps >= b_rps and a_ttft <= b_ttft and a_gpus <= b_gpus and a_kvb <= b_kvb)
    gt = (a_rps > b_rps or a_ttft < b_ttft or a_gpus < b_gpus or a_kvb < b_kvb)
    return geq and gt


def pareto_front(results):
    front = []
    for i, a in enumerate(results):
        dominated = any(dominates(results[j], a) for j in range(len(results)) if j != i)
        if not dominated:
            front.append(a)
    return front


def main():
    args = parse_args()
    tmpdir = tempfile.mkdtemp(prefix="blis_search_")
    all_results = []
    evaluated = set()
    budget_left = args.budget

    def evaluate(tp, ni, sched, mrr, kvb, bs):
        nonlocal budget_left
        key = (tp, ni, sched, mrr, kvb, bs)
        if key in evaluated or budget_left <= 0:
            return None
        evaluated.add(key)
        budget_left -= 1
        r = run_blis(args.model, args.rate, args.seed, tp, ni, sched, mrr, kvb, bs, tmpdir)
        if r:
            all_results.append(r)
        return r

    # ===== Phase 1: Single-instance FCFS core sweep =====
    # 4 tp × 2 bs × 2 mrr × 5 kvb = 80 evals
    for tp in TP_VALUES:
        for bs in [16, 32]:
            for mrr in [128, 256]:
                for kvb in [2000, 3000, 4000, 5000, 10000]:
                    evaluate(tp, 1, "fcfs", mrr, kvb, bs)

    # ===== Phase 2: Multi-instance with minimum-resource configs =====
    # Only bs=32 (dominates or ties 16), fcfs, mrr={64,128}, kvb={2000,3000}
    # 11 combos × 4 configs = 44 evals
    for tp in TP_VALUES:
        for ni in valid_ni_range(tp):
            if ni >= 2:
                for kvb in [2000, 3000]:
                    evaluate(tp, ni, "fcfs", 128, kvb, 32)
                    evaluate(tp, ni, "fcfs", 64, kvb, 32)

    # ===== Phase 3: SJF single-instance bs=32 =====
    # SJF creates distinct Pareto vectors in saturated single-instance + bs=32
    # 4 tp × 2 mrr × 3 kvb = 24 evals
    for tp in TP_VALUES:
        for mrr in [128, 256]:
            for kvb in [3000, 4000, 5000]:
                evaluate(tp, 1, "sjf", mrr, kvb, 32)

    # ===== Phase 4: SJF multi-instance with tight kvb =====
    # SJF differs from FCFS only when kvb is barely sufficient
    # 11 combos × 2 mrr = 22 evals
    for tp in TP_VALUES:
        for ni in valid_ni_range(tp):
            if ni >= 2:
                evaluate(tp, ni, "sjf", 128, 2000, 32)
                evaluate(tp, ni, "sjf", 64, 2000, 32)

    # ===== Phase 5: SJF single-instance bs=16 =====
    # 4 tp × 2 mrr × 2 kvb = 16 evals
    for tp in TP_VALUES:
        for mrr in [128, 256]:
            for kvb in [5000, 10000]:
                evaluate(tp, 1, "sjf", mrr, kvb, 16)

    # ===== Remaining budget: fill gaps =====
    # Phase 6: Multi-instance bs=16 with min kvb
    for tp in TP_VALUES:
        for ni in valid_ni_range(tp):
            if ni >= 2:
                evaluate(tp, ni, "fcfs", 128, 2000, 16)

    # Phase 7: mrr=512 single-instance
    for tp in TP_VALUES:
        for kvb in [5000, 10000]:
            evaluate(tp, 1, "fcfs", 512, kvb, 16)

    # Phase 8: kvb=7500 sweep
    for tp in TP_VALUES:
        evaluate(tp, 1, "fcfs", 128, 7500, 16)
        evaluate(tp, 1, "fcfs", 256, 7500, 16)

    # Phase 9: mrr=64, 32 single-instance
    for tp in TP_VALUES:
        evaluate(tp, 1, "fcfs", 64, 5000, 16)
        evaluate(tp, 1, "fcfs", 32, 5000, 16)

    front = pareto_front(all_results)

    seen = set()
    output = []
    for r in front:
        entry = {
            "tp": r["tp"], "num_instances": r["num_instances"],
            "scheduler": r["scheduler"], "max_num_running_reqs": r["max_num_running_reqs"],
            "total_kv_blocks": r["total_kv_blocks"], "block_size_in_tokens": r["block_size_in_tokens"],
        }
        key = tuple(sorted(entry.items()))
        if key not in seen:
            seen.add(key)
            output.append(entry)

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluated {len(evaluated)} configurations (budget: {args.budget})", file=sys.stderr)
    print(f"Found {len(output)} Pareto-optimal configurations", file=sys.stderr)


if __name__ == "__main__":
    main()
