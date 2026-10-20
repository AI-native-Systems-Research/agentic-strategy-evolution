#!/usr/bin/env python3
"""
Pareto-front search for BLIS serving configurations.

Searches over 6 knobs (tp, num_instances, scheduler, max_num_running_reqs,
total_kv_blocks, block_size_in_tokens) with 4 objectives (maximize responses_per_sec,
minimize ttft_p99_ms, minimize GPU count, minimize total_kv_blocks).

Design rationale (from empirical analysis of the space):
  - block_size=32 dominates or ties block_size=16 in all tested configs
  - scheduler=fcfs dominates sjf (sjf trades worse TTFT for marginally higher RPS)
  - max_num_running_reqs has a sufficiency threshold; below it, queueing hurts
  - The dominant knob is tp × num_instances (GPU allocation)
  - total_kv_blocks has a "sufficiency threshold" per (GPU config, mrr)
  - Some configs show "soft saturation": zero preemptions but degraded TTFT/RPS
    due to insufficient concurrency (mrr too low for the throughput capacity)

Algorithm:
  Phase 1 (30 evals): All GPU configs at high + moderate capacity
  Phase 2 (~75 evals): KVB × MRR sweep for configs showing any saturation
  Phase 3 (~45 evals): MRR sweep at key KVB for all GPU configs
  Phase 4 (~30 evals): Fill (gpu, kvb, mrr) combos
  Phase 5 (~20 evals): Verify block_size=16 and sjf on Pareto front
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

TP_VALUES = [1, 2, 4, 8]
NUM_INSTANCES_MAX = 8
MRR_VALUES = [32, 64, 128, 256, 512]
KVB_VALUES = [2000, 3000, 4000, 5000, 7500, 10000]

FIXED_FLAGS = (
    "--hardware H100 --latency-model trained-physics "
    "--num-requests 200 --prefix-tokens 512 "
    "--max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 "
    "--admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin "
    "--gpu-memory-utilization 0.9"
)


def gpu_configs():
    configs = []
    for tp in TP_VALUES:
        for ni in range(1, NUM_INSTANCES_MAX // tp + 1):
            configs.append((tp, ni))
    return configs


def run_blis(model, rate, seed, cfg, tmpdir):
    metrics_path = os.path.join(
        tmpdir,
        f"m_{cfg['tp']}_{cfg['num_instances']}_{cfg['scheduler']}_"
        f"{cfg['max_num_running_reqs']}_{cfg['total_kv_blocks']}_"
        f"{cfg['block_size_in_tokens']}.json",
    )
    cmd = (
        f"./blis run {FIXED_FLAGS} --model {model} --rate {rate} --seed {seed} "
        f"--tp {cfg['tp']} --num-instances {cfg['num_instances']} "
        f"--scheduler {cfg['scheduler']} "
        f"--max-num-running-reqs {cfg['max_num_running_reqs']} "
        f"--total-kv-blocks {cfg['total_kv_blocks']} "
        f"--block-size-in-tokens {cfg['block_size_in_tokens']} "
        f"--metrics-path {metrics_path}"
    )
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return None
    with open(metrics_path) as f:
        m = json.load(f)
    return {
        "responses_per_sec": m["responses_per_sec"],
        "ttft_p99_ms": m["ttft_p99_ms"],
        "gpu_count": cfg["tp"] * cfg["num_instances"],
        "total_kv_blocks": cfg["total_kv_blocks"],
        "preemption_count": m.get("preemption_count", 0),
    }


def dominates(a_cfg, a_met, b_cfg, b_met):
    a_objs = (
        a_met["responses_per_sec"],
        -a_met["ttft_p99_ms"],
        -(a_cfg["tp"] * a_cfg["num_instances"]),
        -a_cfg["total_kv_blocks"],
    )
    b_objs = (
        b_met["responses_per_sec"],
        -b_met["ttft_p99_ms"],
        -(b_cfg["tp"] * b_cfg["num_instances"]),
        -b_cfg["total_kv_blocks"],
    )
    at_least = all(a >= b for a, b in zip(a_objs, b_objs))
    strictly = any(a > b for a, b in zip(a_objs, b_objs))
    return at_least and strictly


def compute_pareto(evaluated):
    pareto = []
    for i, (ci, mi) in enumerate(evaluated):
        dominated = False
        for j, (cj, mj) in enumerate(evaluated):
            if i != j and dominates(cj, mj, ci, mi):
                dominated = True
                break
        if not dominated:
            pareto.append((ci, mi))
    return pareto


def cfg_key(cfg):
    return (
        cfg["tp"],
        cfg["num_instances"],
        cfg["scheduler"],
        cfg["max_num_running_reqs"],
        cfg["total_kv_blocks"],
        cfg["block_size_in_tokens"],
    )


def is_degraded(moderate_met, generous_met):
    """Detect soft saturation: moderate settings show worse RPS or TTFT than generous."""
    if moderate_met is None or generous_met is None:
        return True
    if moderate_met["preemption_count"] > 0:
        return True
    rps_ratio = moderate_met["responses_per_sec"] / max(generous_met["responses_per_sec"], 0.01)
    ttft_ratio = moderate_met["ttft_p99_ms"] / max(generous_met["ttft_p99_ms"], 0.01)
    return rps_ratio < 0.95 or ttft_ratio > 2.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    tmpdir = tempfile.mkdtemp(prefix="blis_search_")
    evaluated = []
    eval_count = 0
    seen = set()

    def budget_left():
        return args.budget - eval_count

    def evaluate(cfg):
        nonlocal eval_count
        if eval_count >= args.budget:
            return None
        key = cfg_key(cfg)
        if key in seen:
            for c, m in evaluated:
                if cfg_key(c) == key:
                    return m
            return None
        seen.add(key)
        met = run_blis(args.model, args.rate, args.seed, cfg, tmpdir)
        if met is not None:
            eval_count += 1
            evaluated.append((cfg, met))
        return met

    def make_cfg(tp, ni, sched="fcfs", mrr=128, kvb=5000, bs=32):
        return {
            "tp": tp,
            "num_instances": ni,
            "scheduler": sched,
            "max_num_running_reqs": mrr,
            "total_kv_blocks": kvb,
            "block_size_in_tokens": bs,
        }

    gc = gpu_configs()

    # === Phase 1: Baseline scan (30 evals) ===
    phase1 = {}
    for tp, ni in gc:
        gen = evaluate(make_cfg(tp, ni, mrr=256, kvb=10000))
        mod = evaluate(make_cfg(tp, ni, mrr=128, kvb=5000))
        phase1[(tp, ni)] = {"generous": gen, "moderate": mod}

    if budget_left() <= 0:
        write_output(compute_pareto(evaluated), args.out)
        return

    # === Phase 2: KVB sweep for all GPU configs ===
    # Degraded configs: sweep all kvb for both mrr=128 and mrr=256
    # Non-degraded: find minimum sufficient kvb
    for tp, ni in gc:
        if budget_left() <= 0:
            break
        p1 = phase1.get((tp, ni), {})
        gen = p1.get("generous")
        mod = p1.get("moderate")

        if is_degraded(mod, gen):
            for kvb in KVB_VALUES:
                if budget_left() <= 0:
                    break
                evaluate(make_cfg(tp, ni, mrr=128, kvb=kvb))
                evaluate(make_cfg(tp, ni, mrr=256, kvb=kvb))
        else:
            for kvb in [2000, 3000, 4000]:
                if budget_left() <= 0:
                    break
                evaluate(make_cfg(tp, ni, kvb=kvb))
            # Also check mrr=256 at the min sufficient kvb
            results_for_gc = [
                (c, m) for c, m in evaluated
                if c["tp"] == tp and c["num_instances"] == ni
            ]
            non_preempted = [
                (c, m) for c, m in results_for_gc if m["preemption_count"] == 0
            ]
            if non_preempted:
                min_kvb = min(c["total_kv_blocks"] for c, m in non_preempted)
                evaluate(make_cfg(tp, ni, mrr=256, kvb=min_kvb))

    if budget_left() <= 0:
        write_output(compute_pareto(evaluated), args.out)
        return

    # === Phase 3: MRR sweep at key KVB levels ===
    for tp, ni in gc:
        if budget_left() <= 0:
            break
        results_for_gc = [
            (c, m) for c, m in evaluated
            if c["tp"] == tp and c["num_instances"] == ni
        ]
        if not results_for_gc:
            continue

        non_preempted = [
            (c, m) for c, m in results_for_gc if m["preemption_count"] == 0
        ]
        kvb_to_test = set()
        if non_preempted:
            kvb_to_test.add(min(c["total_kv_blocks"] for c, m in non_preempted))
        preempted = [
            (c, m) for c, m in results_for_gc if m["preemption_count"] > 0
        ]
        if preempted:
            kvb_to_test.add(max(c["total_kv_blocks"] for c, m in preempted))

        for kvb in kvb_to_test:
            for mrr in [32, 64, 256, 512]:
                if budget_left() <= 0:
                    break
                evaluate(make_cfg(tp, ni, mrr=mrr, kvb=kvb))

    if budget_left() <= 0:
        write_output(compute_pareto(evaluated), args.out)
        return

    # === Phase 4: Verify block_size=16 and sjf on Pareto front ===
    current_pareto = compute_pareto(evaluated)
    checked_gcs = set()
    for cfg, met in current_pareto:
        if budget_left() <= 0:
            break
        gc_key = (cfg["tp"], cfg["num_instances"])
        if gc_key in checked_gcs:
            continue
        checked_gcs.add(gc_key)
        evaluate(make_cfg(
            cfg["tp"], cfg["num_instances"],
            mrr=cfg["max_num_running_reqs"], kvb=cfg["total_kv_blocks"], bs=16,
        ))
        if budget_left() > 0:
            evaluate(make_cfg(
                cfg["tp"], cfg["num_instances"], sched="sjf",
                mrr=cfg["max_num_running_reqs"], kvb=cfg["total_kv_blocks"],
            ))

    if budget_left() <= 0:
        write_output(compute_pareto(evaluated), args.out)
        return

    # === Phase 5: Fill remaining budget ===
    for tp, ni in gc:
        if budget_left() <= 0:
            break
        for kvb in KVB_VALUES:
            if budget_left() <= 0:
                break
            for mrr in [128, 256]:
                if budget_left() <= 0:
                    break
                evaluate(make_cfg(tp, ni, mrr=mrr, kvb=kvb))

    pareto = compute_pareto(evaluated)
    write_output(pareto, args.out)
    print(
        f"Search complete: {eval_count} evaluations, "
        f"{len(pareto)} Pareto-optimal configs",
        file=sys.stderr,
    )


def write_output(pareto, out_path):
    output = []
    for cfg, met in pareto:
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


if __name__ == "__main__":
    main()
