#!/usr/bin/env python3
"""
Pareto-front search v4 for BLIS LLM inference simulator.

Strategy: Three-phase structure-aware deterministic search.
  Phase 1 (~75 evals): Deterministic foundation — exactly 5 configs per GPU tier,
           no shuffling. Covers each tier with configs spanning min-to-high kv,
           all using bs=32 (Pareto-dominant as established in iter-2).
  Phase 2 (~80 evals): Diversity-directed expansion — classify tiers as "rich"
           (partial preemption present: high ttft_p99 diversity) vs "simple"
           (cache always ample). Allocate budget to rich tiers systematically
           covering the partial-preemption zone (kv=2000-4000, bs=32, various maxrun).
           Simple tiers get minimal additional evals.
  Phase 3 (~45 evals): Standard neighbor expansion from current Pareto front.

Four objectives (all to be minimized for Pareto dominance):
  1. -responses_per_sec  (maximize throughput → minimize negative)
  2. ttft_p99_ms         (minimize tail latency)
  3. gpu_count           (tp * num_instances, minimize cost)
  4. total_kv_blocks     (minimize memory)

Key improvements over v2 (v3) and v3 (v4):
  - Phase 1 is fully deterministic (no shuffling), guaranteeing complete tier coverage
  - Phase 2 directs budget to "rich" tiers where Pareto diversity exists
  - bs=32 used preferentially (iter-2 established it as strictly Pareto-dominant)
  - v4: sjf@kv=5000 added to Phase 2 rich-tier combos (closes iter-3 rate=200 gap)
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict


# --- Configuration space ---
TP_VALUES = [1, 2, 4, 8]
SCHEDULER_VALUES = ["fcfs", "sjf"]
MAX_RUN_REQS_VALUES = [32, 64, 128, 256, 512]
KV_BLOCKS_VALUES = [2000, 3000, 4000, 5000, 7500, 10000]
BLOCK_SIZE_VALUES = [16, 32]


def valid_instances(tp):
    """Return valid num_instances for a given tp (tp * instances <= 8)."""
    return list(range(1, 8 // tp + 1))


def all_gpu_tiers():
    """Return all valid (tp, num_instances) pairs, sorted by GPU count."""
    tiers = []
    for tp in TP_VALUES:
        for ni in valid_instances(tp):
            tiers.append((tp, ni))
    tiers.sort(key=lambda x: x[0] * x[1])
    return tiers


def run_blis(config, model, fixed_flags, metrics_dir, eval_id):
    """Run BLIS with given config, return metrics dict or None on failure."""
    metrics_path = os.path.join(metrics_dir, f"eval_{eval_id}.json")
    cmd = [
        "./blis", "run",
        "--model", model,
        "--tp", str(config["tp"]),
        "--num-instances", str(config["num_instances"]),
        "--scheduler", config["scheduler"],
        "--max-num-running-reqs", str(config["max_num_running_reqs"]),
        "--total-kv-blocks", str(config["total_kv_blocks"]),
        "--block-size-in-tokens", str(config["block_size_in_tokens"]),
        "--metrics-path", metrics_path,
    ] + fixed_flags

    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        with open(metrics_path) as f:
            data = json.load(f)
        return {
            "responses_per_sec": data.get("responses_per_sec", 0),
            "ttft_p99_ms": data.get("ttft_p99_ms", float("inf")),
            "e2e_p99_ms": data.get("e2e_p99_ms", float("inf")),
            "preemption_count": data.get("preemption_count", 0),
            "completed_requests": data.get("completed_requests", 0),
            "dropped_unservable": data.get("dropped_unservable", 0),
        }
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, Exception) as e:
        print(f"  [WARN] eval {eval_id} failed: {e}", file=sys.stderr)
        return None


def config_key(cfg):
    """Hashable key for a configuration."""
    return (cfg["tp"], cfg["num_instances"], cfg["scheduler"],
            cfg["max_num_running_reqs"], cfg["total_kv_blocks"],
            cfg["block_size_in_tokens"])


def dominates(a, b):
    """Return True if a dominates b in all 4 objectives (lower is better)."""
    objs_a = [-a["responses_per_sec"], a["ttft_p99_ms"], a["gpu_count"], a["total_kv_blocks"]]
    objs_b = [-b["responses_per_sec"], b["ttft_p99_ms"], b["gpu_count"], b["total_kv_blocks"]]
    at_least_one_better = False
    for oa, ob in zip(objs_a, objs_b):
        if oa > ob:
            return False
        if oa < ob:
            at_least_one_better = True
    return at_least_one_better


def compute_pareto_front(results):
    """Return non-dominated subset of results."""
    pareto = []
    for i, ri in enumerate(results):
        dominated = False
        for j, rj in enumerate(results):
            if i != j and dominates(rj, ri):
                dominated = True
                break
        if not dominated:
            pareto.append(ri)
    return pareto


def make_config(tp, ni, scheduler, max_run, kv_blocks, block_size):
    return {
        "tp": tp,
        "num_instances": ni,
        "scheduler": scheduler,
        "max_num_running_reqs": max_run,
        "total_kv_blocks": kv_blocks,
        "block_size_in_tokens": block_size,
    }


def neighbors(cfg):
    """Generate neighbor configurations by changing one knob at a time."""
    nbrs = []
    tp = cfg["tp"]
    ni = cfg["num_instances"]

    # Vary max_num_running_reqs
    idx = MAX_RUN_REQS_VALUES.index(cfg["max_num_running_reqs"]) if cfg["max_num_running_reqs"] in MAX_RUN_REQS_VALUES else -1
    if idx >= 0:
        for di in [-1, 1]:
            ni_idx = idx + di
            if 0 <= ni_idx < len(MAX_RUN_REQS_VALUES):
                nbrs.append(make_config(tp, ni, cfg["scheduler"],
                                       MAX_RUN_REQS_VALUES[ni_idx],
                                       cfg["total_kv_blocks"],
                                       cfg["block_size_in_tokens"]))

    # Vary total_kv_blocks
    idx = KV_BLOCKS_VALUES.index(cfg["total_kv_blocks"]) if cfg["total_kv_blocks"] in KV_BLOCKS_VALUES else -1
    if idx >= 0:
        for di in [-1, 1]:
            ni_idx = idx + di
            if 0 <= ni_idx < len(KV_BLOCKS_VALUES):
                nbrs.append(make_config(tp, ni, cfg["scheduler"],
                                       cfg["max_num_running_reqs"],
                                       KV_BLOCKS_VALUES[ni_idx],
                                       cfg["block_size_in_tokens"]))

    # Vary tp/instances (same GPU count if possible, or ±1 GPU)
    gpu = tp * ni
    for tp2 in TP_VALUES:
        for ni2 in valid_instances(tp2):
            if (tp2, ni2) != (tp, ni) and abs(tp2 * ni2 - gpu) <= 1:
                nbrs.append(make_config(tp2, ni2, cfg["scheduler"],
                                       cfg["max_num_running_reqs"],
                                       cfg["total_kv_blocks"],
                                       cfg["block_size_in_tokens"]))

    # Flip scheduler
    other_sched = "sjf" if cfg["scheduler"] == "fcfs" else "fcfs"
    nbrs.append(make_config(tp, ni, other_sched,
                           cfg["max_num_running_reqs"],
                           cfg["total_kv_blocks"],
                           cfg["block_size_in_tokens"]))

    # Flip block size
    other_bs = 32 if cfg["block_size_in_tokens"] == 16 else 16
    nbrs.append(make_config(tp, ni, cfg["scheduler"],
                           cfg["max_num_running_reqs"],
                           cfg["total_kv_blocks"],
                           other_bs))

    return nbrs


def main():
    parser = argparse.ArgumentParser(description="BLIS Pareto-front search v4")
    parser.add_argument("--model", required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    # Fixed flags from the campaign
    fixed_flags = [
        "--hardware", "H100",
        "--latency-model", "trained-physics",
        "--num-requests", "200",
        "--rate", str(int(args.rate)),
        "--prefix-tokens", "512",
        "--seed", str(args.seed),
        "--max-num-scheduled-tokens", "4096",
        "--long-prefill-token-threshold", "0",
        "--admission-policy", "always-admit",
        "--preemption-policy", "fcfs",
        "--routing-policy", "round-robin",
        "--gpu-memory-utilization", "0.9",
    ]

    metrics_dir = os.path.join(os.path.dirname(args.out) or ".", ".search_v3_metrics")
    os.makedirs(metrics_dir, exist_ok=True)

    all_results = []
    evaluated = set()
    eval_count = 0

    def evaluate(cfg):
        nonlocal eval_count
        key = config_key(cfg)
        if key in evaluated:
            return None
        if eval_count >= args.budget:
            return None
        evaluated.add(key)
        eval_count += 1
        print(f"[{eval_count}/{args.budget}] tp={cfg['tp']} ni={cfg['num_instances']} "
              f"sched={cfg['scheduler']} maxrun={cfg['max_num_running_reqs']} "
              f"kv={cfg['total_kv_blocks']} bs={cfg['block_size_in_tokens']}",
              file=sys.stderr)
        metrics = run_blis(cfg, args.model, fixed_flags, metrics_dir, eval_count)
        if metrics is None:
            return None
        result = {
            **cfg,
            **metrics,
            "gpu_count": cfg["tp"] * cfg["num_instances"],
        }
        all_results.append(result)
        return result

    # =========================================================================
    # PHASE 1: Deterministic foundation (5 configs per GPU tier, no shuffling)
    # ~75 evals for 15 GPU tiers
    # These 5 configs per tier span the kv range and always use bs=32
    # (Pareto-dominant: halves effective cache token count for same kv_blocks).
    # =========================================================================
    gpu_tiers = all_gpu_tiers()

    # Deterministic 5-config template per tier:
    # 1. Min kv, moderate concurrency: anchor at cache-pressure boundary
    # 2. Min kv, lower concurrency: different maxrun at minimum cache
    # 3. Intermediate kv, moderate concurrency: mid-range cache
    # 4. High kv bs=16: above-threshold reference (identifies "simple" tiers)
    # 5. Moderate-high kv, high concurrency: wide coverage
    phase1_template = [
        ("kv2000-maxrun128", 2000, 128, 32, "fcfs"),
        ("kv2000-maxrun64",  2000,  64, 32, "fcfs"),
        ("kv3000-maxrun128", 3000, 128, 32, "fcfs"),
        ("kv5000-maxrun128-bs16", 5000, 128, 16, "fcfs"),  # bs=16 reference point
        ("kv4000-maxrun256", 4000, 256, 32, "fcfs"),
    ]

    phase1_configs = []
    for tp, ni in gpu_tiers:
        for _name, kv, maxrun, bs, sched in phase1_template:
            phase1_configs.append(make_config(tp, ni, sched, maxrun, kv, bs))

    print(f"\n=== PHASE 1 v3: Deterministic foundation ({len(phase1_configs)} configs, no shuffling) ===",
          file=sys.stderr)
    for cfg in phase1_configs:
        if eval_count >= args.budget:
            break
        evaluate(cfg)

    print(f"Phase 1 complete: {eval_count} evals", file=sys.stderr)

    # =========================================================================
    # PHASE 2: Diversity-directed expansion
    # Classify tiers as "rich" (high metric diversity → partial preemption) or
    # "simple" (low diversity → cache always ample). Direct budget to rich tiers.
    # =========================================================================
    # Build per-tier ttft_p99 range from Phase 1 results
    tier_results = defaultdict(list)
    for r in all_results:
        tier = (r["tp"], r["num_instances"])
        tier_results[tier].append(r["ttft_p99_ms"])

    rich_tiers = []
    simple_tiers = []
    for tier in gpu_tiers:
        ttfts = tier_results.get(tier, [])
        if not ttfts:
            simple_tiers.append(tier)
            continue
        max_ttft = max(ttfts)
        min_ttft = min(ttfts)
        # Rich: meaningful preemption diversity (max > 100ms AND max > 2x min)
        if max_ttft > 100.0 and max_ttft > 2.0 * min_ttft:
            rich_tiers.append(tier)
        else:
            simple_tiers.append(tier)

    print(f"\n=== PHASE 2 v3: Diversity-directed expansion ===", file=sys.stderr)
    print(f"  Rich tiers ({len(rich_tiers)}): {rich_tiers}", file=sys.stderr)
    print(f"  Simple tiers ({len(simple_tiers)}): {simple_tiers}", file=sys.stderr)

    # Phase 2 configs to evaluate
    phase2_configs = []

    # For rich tiers: systematic exploration of the partial-preemption zone
    # These combos are known to produce diverse Pareto tuples at rich tiers
    rich_tier_combos = [
        # Very low concurrency at min kv — creates severe preemption
        (2000, 32, 32, "fcfs"),
        # High concurrency at min kv — different preemption regime
        (2000, 256, 32, "fcfs"),
        # Max concurrency at min kv
        (2000, 512, 32, "fcfs"),
        # SJF at min kv — scheduler effect at preemption boundary
        (2000, 128, 32, "sjf"),
        (2000, 64, 32, "sjf"),
        # Mid kv with SJF
        (3000, 128, 32, "sjf"),
        # Mid kv with high maxrun
        (3000, 256, 32, "fcfs"),
        (3000, 256, 32, "sjf"),
        # Moderate-high kv at various concurrencies
        (4000, 128, 32, "fcfs"),
        (4000, 512, 32, "fcfs"),
        (4000, 256, 32, "sjf"),
        # High kv bs=32 — bs=32 equivalent of the bs=16 reference
        (5000, 256, 32, "fcfs"),
        # SJF at high kv — covers sjf-only Pareto tuples at high rates (iter-3 gap)
        (5000, 256, 32, "sjf"),
        # Unique cache point: bs=16 at min kv (captures bs effect at threshold)
        (2000, 128, 16, "fcfs"),
    ]

    for tp, ni in rich_tiers:
        for kv, maxrun, bs, sched in rich_tier_combos:
            phase2_configs.append(make_config(tp, ni, sched, maxrun, kv, bs))

    # For simple tiers: just 2 additional evals at extremes of concurrency
    simple_tier_combos = [
        (2000, 32, 32, "fcfs"),
        (2000, 512, 32, "fcfs"),
    ]
    for tp, ni in simple_tiers:
        for kv, maxrun, bs, sched in simple_tier_combos:
            phase2_configs.append(make_config(tp, ni, sched, maxrun, kv, bs))

    # Evaluate Phase 2 (deterministic order, no shuffling)
    for cfg in phase2_configs:
        if eval_count >= args.budget:
            break
        evaluate(cfg)

    print(f"Phase 2 complete: {eval_count} evals", file=sys.stderr)

    # =========================================================================
    # PHASE 3: Neighbor expansion from current Pareto front
    # Standard iterative expansion to fill gaps
    # =========================================================================
    print(f"\n=== PHASE 3 v3: Neighbor expansion (remaining budget: {args.budget - eval_count}) ===",
          file=sys.stderr)

    max_rounds = 5
    for round_num in range(max_rounds):
        if eval_count >= args.budget:
            break

        pareto = compute_pareto_front(all_results)
        candidates = []
        for p in pareto:
            for nbr in neighbors(p):
                if config_key(nbr) not in evaluated:
                    candidates.append(nbr)

        # Deduplicate
        seen = set()
        unique_candidates = []
        for c in candidates:
            k = config_key(c)
            if k not in seen:
                seen.add(k)
                unique_candidates.append(c)

        # Budget for this round (split evenly across remaining rounds)
        round_budget = min(len(unique_candidates), (args.budget - eval_count) // max(1, max_rounds - round_num))
        print(f"\n  Round {round_num+1}: {len(unique_candidates)} candidates, evaluating {round_budget}",
              file=sys.stderr)

        for cfg in unique_candidates[:round_budget]:
            if eval_count >= args.budget:
                break
            evaluate(cfg)

    print(f"Phase 3 complete: {eval_count} evals", file=sys.stderr)

    # =========================================================================
    # Compute final Pareto front
    # =========================================================================
    pareto = compute_pareto_front(all_results)

    # Output: non-dominated configs
    output = []
    for r in pareto:
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

    print(f"\n=== RESULTS ===", file=sys.stderr)
    print(f"Evaluated: {eval_count} configs", file=sys.stderr)
    print(f"Pareto front size: {len(pareto)}", file=sys.stderr)
    print(f"Rich tiers: {len(rich_tiers)}, Simple tiers: {len(simple_tiers)}", file=sys.stderr)
    for r in sorted(pareto, key=lambda x: -x["responses_per_sec"]):
        print(f"  rps={r['responses_per_sec']:.1f} ttft_p99={r['ttft_p99_ms']:.1f} "
              f"gpu={r['gpu_count']} kv={r['total_kv_blocks']} "
              f"tp={r['tp']} ni={r['num_instances']} sched={r['scheduler']} "
              f"maxrun={r['max_num_running_reqs']} bs={r['block_size_in_tokens']}",
              file=sys.stderr)

    print(f"Wrote {len(output)} Pareto-optimal configs to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
