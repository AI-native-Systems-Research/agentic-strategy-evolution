#!/usr/bin/env python3
"""
Pareto-front search for BLIS inference-simulator configuration space.

Objectives (4D):
  maximize responses_per_sec, minimize ttft_p99_ms,
  minimize gpu_count (tp*instances), minimize total_kv_blocks.

Strategy (4-phase adaptive search):
  Phase 1 – Ceiling + cheapest scan: for every GPU topology, evaluate at
            the performance ceiling (kv=max(KV_VALUES)=10000, bs=32) and the
            cheapest config (kv=2000, bs=32). This discovers each topology's
            best-case performance AND whether a preemption regime exists.
            The ceiling is adaptive: using kv=max(KV_VALUES) ensures the true
            plateau is found regardless of model (Llama-70B ceiling=3000,
            qwen3-14b ceiling=5000, etc.).
  Phase 2 – Boundary mapping: for topologies that showed preemptions at
            kv=2000, adaptively test kv=3000 and kv=4000 to map the
            preemption-to-plateau boundary. These mid-range kv values are
            often Pareto-optimal (trading latency for lower kv cost).
  Phase 3 – Sensitivity testing: for current Pareto candidates, test
            maxrun variations ({32, 64, 128}), sjf scheduler, and bs=16
            to find additional Pareto points from secondary knobs.
  Phase 4 – Strategic fill: use remaining budget on unexplored configs,
            prioritizing topologies that already have Pareto candidates
            and cycling through topologies evenly (not lexicographically).

Key insights from iter-1/2 characterization:
  - kv=5000,bs=32 is the qwen3-14b ceiling; Llama-70B ceiling is kv=3000
  - kv=max(KV_VALUES)=10000 is the universal ceiling (identical or plateau for all models)
  - Pareto front typically includes kv in {2000, 3000, 4000, 5000}
  - bs=32 dominates (25/26 Pareto configs use bs=32)
  - Scheduler (fcfs vs sjf) has negligible effect (mean rps diff = 0.19)
  - max_num_running_reqs saturates above 128
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


# ---------------------------------------------------------------------------
# Configuration space
# ---------------------------------------------------------------------------
TP_VALUES = [1, 2, 4, 8]
SCHEDULER_VALUES = ["fcfs", "sjf"]
MAXRUN_VALUES = [32, 64, 128, 256, 512]
KV_VALUES = [2000, 3000, 4000, 5000, 7500, 10000]
BS_VALUES = [16, 32]

FIXED_FLAGS = [
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


def gpu_topologies():
    """All valid (tp, num_instances) pairs with tp*inst <= 8."""
    combos = []
    for tp in TP_VALUES:
        max_inst = 8 // tp
        for inst in range(1, max_inst + 1):
            combos.append((tp, inst))
    return combos


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
class Evaluator:
    def __init__(self, model, rate, seed):
        self.model = model
        self.rate = rate
        self.seed = seed
        self.cache = {}   # config_tuple -> result dict
        self.eval_count = 0
        self._tmpdir = tempfile.mkdtemp(prefix="blis_search_")

    def _config_key(self, tp, inst, sched, maxrun, kvblocks, bs):
        return (tp, inst, sched, maxrun, kvblocks, bs)

    def evaluate(self, tp, inst, sched, maxrun, kvblocks, bs):
        key = self._config_key(tp, inst, sched, maxrun, kvblocks, bs)
        if key in self.cache:
            return self.cache[key]

        outf = os.path.join(self._tmpdir, f"m_{self.eval_count}.json")
        cmd = [
            "./blis", "run",
            "--model", self.model,
            "--rate", str(self.rate),
            "--seed", str(self.seed),
            "--tp", str(tp),
            "--num-instances", str(inst),
            "--scheduler", sched,
            "--max-num-running-reqs", str(maxrun),
            "--total-kv-blocks", str(kvblocks),
            "--block-size-in-tokens", str(bs),
            "--metrics-path", outf,
        ] + FIXED_FLAGS

        self.eval_count += 1
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            with open(outf) as f:
                d = json.load(f)
            result = {
                "tp": tp,
                "num_instances": inst,
                "scheduler": sched,
                "max_num_running_reqs": maxrun,
                "total_kv_blocks": kvblocks,
                "block_size_in_tokens": bs,
                "gpus": tp * inst,
                "responses_per_sec": d["responses_per_sec"],
                "ttft_p99_ms": d["ttft_p99_ms"],
                "preemption_count": d.get("preemption_count", 0),
                "dropped_unservable": d.get("dropped_unservable", 0),
            }
        except Exception:
            result = None

        if result is not None:
            self.cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Pareto-front utilities
# ---------------------------------------------------------------------------
def dominates(a, b):
    """a dominates b if a is >= in all objectives and strictly > in at least one."""
    a_rps, a_ttft, a_gpu, a_kv = (
        a["responses_per_sec"], a["ttft_p99_ms"], a["gpus"], a["total_kv_blocks"]
    )
    b_rps, b_ttft, b_gpu, b_kv = (
        b["responses_per_sec"], b["ttft_p99_ms"], b["gpus"], b["total_kv_blocks"]
    )
    geq = (a_rps >= b_rps and a_ttft <= b_ttft and a_gpu <= b_gpu and a_kv <= b_kv)
    strict = (a_rps > b_rps or a_ttft < b_ttft or a_gpu < b_gpu or a_kv < b_kv)
    return geq and strict


def pareto_front(results):
    """Return non-dominated subset."""
    front = []
    for i, a in enumerate(results):
        dominated = False
        for j, b in enumerate(results):
            if i != j and dominates(b, a):
                dominated = True
                break
        if not dominated:
            front.append(a)
    return front


# ---------------------------------------------------------------------------
# Search phases
# ---------------------------------------------------------------------------
def phase1_ceiling_cheapest(ev, budget):
    """For each topology, test ceiling (kv=max(KV_VALUES),bs=32) and cheapest (kv=2000,bs=32)."""
    results = []
    topology_info = {}  # (tp, inst) -> {ceiling: result, cheapest: result}

    for tp, inst in gpu_topologies():
        if ev.eval_count >= budget:
            break

        # Ceiling: kv=max(KV_VALUES) bs=32 — adaptive to any model's peak KV requirement
        # Using max(KV_VALUES)=10000 ensures we always probe the true performance ceiling,
        # regardless of where it lies (kv=3000 for Llama-70B, kv=5000 for qwen3-14b, etc.)
        ceiling = ev.evaluate(tp, inst, "fcfs", 256, max(KV_VALUES), 32)
        if ceiling is not None:
            results.append(ceiling)

        if ev.eval_count >= budget:
            break

        # Cheapest: kv=2000 bs=32
        cheapest = ev.evaluate(tp, inst, "fcfs", 256, 2000, 32)
        if cheapest is not None:
            results.append(cheapest)

        topology_info[(tp, inst)] = {
            "ceiling": ceiling,
            "cheapest": cheapest,
            "has_preemptions": (
                cheapest is not None and cheapest["preemption_count"] > 0
            ),
        }

    return results, topology_info


def phase2_boundary_mapping(ev, topology_info, budget):
    """For topologies with preemptions, test kv=3000 and kv=4000 to map boundary."""
    results = []

    # Sort topologies by GPU count descending — prioritize high-value topologies
    sorted_topos = sorted(
        topology_info.keys(), key=lambda t: t[0] * t[1], reverse=True
    )

    for tp, inst in sorted_topos:
        info = topology_info[(tp, inst)]
        if not info["has_preemptions"]:
            continue
        if ev.eval_count >= budget:
            break

        # Test kv=3000, kv=4000, and kv=5000 to map boundary
        # kv=5000 added to cover models where ceiling is between kv=5000 and kv=10000
        for kv in [3000, 4000, 5000]:
            if ev.eval_count >= budget:
                break
            r = ev.evaluate(tp, inst, "fcfs", 256, kv, 32)
            if r is not None:
                results.append(r)

    # Also test kv=3000, kv=4000, and kv=5000 for topologies WITHOUT preemptions
    # (these may still be Pareto-optimal at lower kv cost)
    for tp, inst in sorted_topos:
        info = topology_info[(tp, inst)]
        if info["has_preemptions"]:
            continue
        if ev.eval_count >= budget:
            break

        for kv in [3000, 4000, 5000]:
            if ev.eval_count >= budget:
                break
            r = ev.evaluate(tp, inst, "fcfs", 256, kv, 32)
            if r is not None:
                results.append(r)

    return results


def phase3_sensitivity(ev, all_results, budget):
    """Test maxrun, scheduler, and bs=16 variations on Pareto candidates."""
    results = []

    # Compute current Pareto front to focus sensitivity testing
    front = pareto_front(all_results)
    tested_topos = set()

    # Test maxrun sensitivity on Pareto candidates
    for p in sorted(front, key=lambda x: -x["responses_per_sec"]):
        tp, inst = p["tp"], p["num_instances"]
        topo_key = (tp, inst)
        if topo_key in tested_topos:
            continue
        tested_topos.add(topo_key)

        if ev.eval_count >= budget:
            break

        # Test maxrun=128 (might throttle slightly, creating a resource-tradeoff point)
        r = ev.evaluate(tp, inst, "fcfs", 128, p["total_kv_blocks"], 32)
        if r is not None:
            results.append(r)

        if ev.eval_count >= budget:
            break

        # Test maxrun=32 (significant throttling for low-GPU configs)
        r = ev.evaluate(tp, inst, "fcfs", 32, p["total_kv_blocks"], 32)
        if r is not None:
            results.append(r)

    # Test sjf scheduler on a few top Pareto configs
    tested_topos_sjf = set()
    for p in sorted(front, key=lambda x: -x["responses_per_sec"])[:8]:
        tp, inst = p["tp"], p["num_instances"]
        topo_key = (tp, inst)
        if topo_key in tested_topos_sjf:
            continue
        tested_topos_sjf.add(topo_key)

        if ev.eval_count >= budget:
            break
        r = ev.evaluate(tp, inst, "sjf", 256, p["total_kv_blocks"], 32)
        if r is not None:
            results.append(r)

    # Test bs=16 at kv=2000 for a few topologies
    tested_topos_bs16 = set()
    for p in front:
        tp, inst = p["tp"], p["num_instances"]
        topo_key = (tp, inst)
        if topo_key in tested_topos_bs16:
            continue
        tested_topos_bs16.add(topo_key)

        if ev.eval_count >= budget:
            break
        r = ev.evaluate(tp, inst, "fcfs", 256, 2000, 16)
        if r is not None:
            results.append(r)

    return results


def phase4_strategic_fill(ev, all_results, budget_total):
    """Fill remaining budget with strategic exploration, cycling through topologies."""
    results = []
    explored = set()
    for r in all_results:
        explored.add((
            r["tp"], r["num_instances"], r["scheduler"],
            r["max_num_running_reqs"], r["total_kv_blocks"],
            r["block_size_in_tokens"]
        ))

    # Priority order for fill: cycle through topologies evenly
    # rather than exhausting tp=1,inst=1 first
    topos = gpu_topologies()

    # Round 1: kv=5000 and kv=7500 at bs=32 for all topologies
    # Note: kv=10000 is already covered by Phase 1 ceiling (max(KV_VALUES)=10000).
    # We add kv=7500 to fill the gap between Phase 2's max (kv=5000) and Phase 1's ceiling.
    for tp, inst in topos:
        for kv in [5000, 7500]:
            if ev.eval_count >= budget_total:
                return results
            key = (tp, inst, "fcfs", 256, kv, 32)
            if key in explored:
                continue
            r = ev.evaluate(tp, inst, "fcfs", 256, kv, 32)
            if r is not None:
                results.append(r)
                explored.add(key)

    # Round 2: bs=16 at kv=3000, 4000, 5000, 7500, 10000
    for tp, inst in topos:
        for kv in [3000, 4000, 5000, 7500, 10000]:
            if ev.eval_count >= budget_total:
                return results
            key = (tp, inst, "fcfs", 256, kv, 16)
            if key in explored:
                continue
            r = ev.evaluate(tp, inst, "fcfs", 256, kv, 16)
            if r is not None:
                results.append(r)
                explored.add(key)

    # Round 3: maxrun variations at key kv values
    for tp, inst in topos:
        for maxrun in [64, 128, 512]:
            for kv in [2000, 5000]:
                if ev.eval_count >= budget_total:
                    return results
                key = (tp, inst, "fcfs", maxrun, kv, 32)
                if key in explored:
                    continue
                r = ev.evaluate(tp, inst, "fcfs", maxrun, kv, 32)
                if r is not None:
                    results.append(r)
                    explored.add(key)

    # Round 4: sjf at remaining configs
    for tp, inst in topos:
        for kv in [2000, 5000]:
            for bs in [32]:
                if ev.eval_count >= budget_total:
                    return results
                key = (tp, inst, "sjf", 256, kv, bs)
                if key in explored:
                    continue
                r = ev.evaluate(tp, inst, "sjf", 256, kv, bs)
                if r is not None:
                    results.append(r)
                    explored.add(key)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    ev = Evaluator(args.model, args.rate, args.seed)
    budget = args.budget
    all_results = []

    # Phase 1: ceiling + cheapest scan (~30 evals)
    p1_results, topo_info = phase1_ceiling_cheapest(ev, budget)
    all_results.extend(p1_results)
    print(f"Phase 1: {ev.eval_count} evals, {len(topo_info)} topologies scanned", file=sys.stderr)

    # Phase 2: boundary mapping (~30-60 evals)
    p2_budget = min(budget, int(budget * 0.5))
    p2_results = phase2_boundary_mapping(ev, topo_info, p2_budget)
    all_results.extend(p2_results)
    print(f"Phase 2: {ev.eval_count} evals total", file=sys.stderr)

    # Phase 3: sensitivity testing (~30-40 evals)
    p3_budget = min(budget, int(budget * 0.75))
    p3_results = phase3_sensitivity(ev, all_results, p3_budget)
    all_results.extend(p3_results)
    print(f"Phase 3: {ev.eval_count} evals total", file=sys.stderr)

    # Phase 4: strategic fill (remaining budget)
    p4_results = phase4_strategic_fill(ev, all_results, budget)
    all_results.extend(p4_results)
    print(f"Phase 4: {ev.eval_count} evals total", file=sys.stderr)

    # Deduplicate (cache handles this, but be safe)
    unique = {}
    for r in all_results:
        key = (
            r["tp"], r["num_instances"], r["scheduler"],
            r["max_num_running_reqs"], r["total_kv_blocks"],
            r["block_size_in_tokens"]
        )
        unique[key] = r

    # Compute Pareto front
    front = pareto_front(list(unique.values()))

    # Output: just the config knobs for each Pareto-optimal point
    output = []
    for p in sorted(front, key=lambda x: (-x["responses_per_sec"], x["ttft_p99_ms"])):
        output.append({
            "tp": p["tp"],
            "num_instances": p["num_instances"],
            "scheduler": p["scheduler"],
            "max_num_running_reqs": p["max_num_running_reqs"],
            "total_kv_blocks": p["total_kv_blocks"],
            "block_size_in_tokens": p["block_size_in_tokens"],
        })

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(
        f"Done: {ev.eval_count}/{budget} evals, "
        f"{len(unique)} unique configs, "
        f"{len(front)} Pareto-optimal",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
