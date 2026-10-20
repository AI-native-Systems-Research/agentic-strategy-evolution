#!/usr/bin/env python3
"""
Multi-objective Pareto search for BLIS LLM inference simulator configuration space.

Searches over 6 knobs: tp, num_instances, scheduler, max_num_running_reqs,
total_kv_blocks, block_size_in_tokens. Four objectives: maximize responses_per_sec,
minimize ttft_p99_ms, minimize GPU count (tp*instances), minimize total_kv_blocks.

Strategy: hierarchical search exploiting discovered space structure:
1. Higher TP is strictly better for throughput at same GPU count (when cache sufficient)
2. Effective cache = kv_blocks * block_size_in_tokens; block_size=32 is more cache-efficient
3. max_num_running_reqs has a saturation plateau (~128-256 depending on tp/instances)
4. Many configs are plateau-equivalent above sufficient cache/concurrency
5. In cache-degraded regimes, SJF x low-maxr creates non-obvious Pareto tradeoffs
   (higher rps at cost of higher ttft) invisible to independent knob exploration

The search allocates budget across phases:
  Phase 1 (15 evals): Ceiling performance per tp/instances combo
  Phase 2 (60 evals): Cache sweep with bs=32 (most cache-efficient)
  Phase 3 (30 evals): Cache sweep with bs=16 at low kv (different effective capacity)
  Phase 2.5 (~16 evals): Targeted degraded-regime interaction (SJF x low-maxr)
  Phase 4+: Scheduler, concurrency, and Pareto-guided refinement
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

# --- Configuration space ---
ALL_TP_VALUES = [1, 2, 4, 8]
SCHEDULER_VALUES = ["fcfs", "sjf"]
MAXR_VALUES = [32, 64, 128, 256, 512]
KV_VALUES = [2000, 3000, 4000, 5000, 7500, 10000]
BS_VALUES = [16, 32]


def get_tp_instance_combos(valid_tps=None):
    """All valid (tp, instances) combinations where tp*instances <= 8."""
    tps = valid_tps if valid_tps is not None else ALL_TP_VALUES
    combos = []
    for tp in tps:
        max_inst = 8 // tp
        for ni in range(1, max_inst + 1):
            combos.append((tp, ni))
    return combos


def dominates(a, b):
    """True if a dominates b on all 4 objectives (rps, ttft, gpus, kv)."""
    a_rps, a_ttft, a_gpus, a_kv = a
    b_rps, b_ttft, b_gpus, b_kv = b
    ge = (a_rps >= b_rps and a_ttft <= b_ttft and a_gpus <= b_gpus and a_kv <= b_kv)
    strictly = (a_rps > b_rps or a_ttft < b_ttft or a_gpus < b_gpus or a_kv < b_kv)
    return ge and strictly


def extract_pareto(results):
    """Extract non-dominated configs from results list."""
    pareto = []
    for i, (cfg_i, obj_i) in enumerate(results):
        is_dominated = False
        for j, (cfg_j, obj_j) in enumerate(results):
            if i != j and dominates(obj_j, obj_i):
                is_dominated = True
                break
        if not is_dominated:
            pareto.append(cfg_i)
    return pareto


def extract_pareto_with_objs(results):
    """Extract non-dominated (cfg, obj) pairs from results list."""
    pareto = []
    for i, (cfg_i, obj_i) in enumerate(results):
        is_dominated = False
        for j, (cfg_j, obj_j) in enumerate(results):
            if i != j and dominates(obj_j, obj_i):
                is_dominated = True
                break
        if not is_dominated:
            pareto.append((cfg_i, obj_i))
    return pareto


class BLISSearcher:
    def __init__(self, model, rate, seed, budget, blis_path="./blis"):
        self.model = model
        self.rate = rate
        self.seed = seed
        self.budget = budget
        self.blis_path = blis_path
        self.eval_count = 0
        self.results = []
        self.tmpdir = tempfile.mkdtemp(prefix="blis_search_")
        self._cache = {}
        self.valid_tps = None  # Set by _discover_valid_tp()

    def _discover_valid_tp(self):
        """Probe each TP value to discover which are valid for this model.

        Some models have attention head counts not divisible by all TP values,
        causing the simulator to panic. This method probes each TP value with
        a minimal eval and filters out invalid ones.

        These probes do NOT count toward the search budget.
        """
        valid = []
        for tp in ALL_TP_VALUES:
            probe_path = os.path.join(self.tmpdir, "probe_tp{}.json".format(tp))
            cmd = [
                self.blis_path, "run",
                "--model", self.model,
                "--hardware", "H100",
                "--latency-model", "trained-physics",
                "--num-requests", "5",
                "--rate", "10",
                "--prefix-tokens", "512",
                "--seed", str(self.seed),
                "--max-num-scheduled-tokens", "4096",
                "--long-prefill-token-threshold", "0",
                "--admission-policy", "always-admit",
                "--preemption-policy", "fcfs",
                "--routing-policy", "round-robin",
                "--gpu-memory-utilization", "0.9",
                "--tp", str(tp),
                "--num-instances", "1",
                "--scheduler", "fcfs",
                "--max-num-running-reqs", "256",
                "--total-kv-blocks", "10000",
                "--block-size-in-tokens", "16",
                "--metrics-path", probe_path,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0 and os.path.exists(probe_path):
                    valid.append(tp)
                else:
                    print("TP={} invalid for model {} (exit={})".format(
                        tp, self.model, result.returncode), file=sys.stderr)
            except Exception as e:
                print("TP={} probe failed: {}".format(tp, e), file=sys.stderr)
        self.valid_tps = valid
        print("Valid TP values for {}: {}".format(
            self.model, self.valid_tps), file=sys.stderr)
        return valid

    def evaluate(self, tp, ni, sched, maxr, kv, bs):
        """Run one BLIS evaluation. Returns (rps, ttft_p99, gpus, kv) or None."""
        key = (tp, ni, sched, maxr, kv, bs)
        if key in self._cache:
            return self._cache[key]
        if self.eval_count >= self.budget:
            return None

        self.eval_count += 1
        metrics_path = os.path.join(
            self.tmpdir, "eval_{}.json".format(self.eval_count))
        cmd = [
            self.blis_path, "run",
            "--model", self.model,
            "--hardware", "H100",
            "--latency-model", "trained-physics",
            "--num-requests", "200",
            "--rate", str(self.rate),
            "--prefix-tokens", "512",
            "--seed", str(self.seed),
            "--max-num-scheduled-tokens", "4096",
            "--long-prefill-token-threshold", "0",
            "--admission-policy", "always-admit",
            "--preemption-policy", "fcfs",
            "--routing-policy", "round-robin",
            "--gpu-memory-utilization", "0.9",
            "--tp", str(tp),
            "--num-instances", str(ni),
            "--scheduler", sched,
            "--max-num-running-reqs", str(maxr),
            "--total-kv-blocks", str(kv),
            "--block-size-in-tokens", str(bs),
            "--metrics-path", metrics_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            with open(metrics_path) as f:
                m = json.load(f)
            rps = m.get("responses_per_sec", 0)
            ttft = m.get("ttft_p99_ms", 1e9)
            gpus = tp * ni
            cfg = {
                "tp": tp, "num_instances": ni, "scheduler": sched,
                "max_num_running_reqs": maxr, "total_kv_blocks": kv,
                "block_size_in_tokens": bs,
            }
            obj = (rps, ttft, gpus, kv)
            self.results.append((cfg, obj))
            self._cache[key] = obj
            return obj
        except Exception:
            return None

    def _get_ceiling_rps(self):
        """Compute ceiling rps per (tp, ni) from results so far."""
        ceiling = {}
        for cfg, obj in self.results:
            key = (cfg["tp"], cfg["num_instances"])
            rps = obj[0]
            if key not in ceiling or rps > ceiling[key]:
                ceiling[key] = rps
        return ceiling

    def search(self):
        """Run hierarchical search and return Pareto-optimal configs."""
        # Phase 0: Discover valid TP values for this model
        self._discover_valid_tp()
        combos = get_tp_instance_combos(self.valid_tps)

        # Phase 1: Ceiling performance (15 evals for 14B; fewer for 7B)
        for tp, ni in combos:
            self.evaluate(tp, ni, "fcfs", 256, 10000, 16)

        # Phase 2 (selective): Cache sweep with bs=32.
        # All combos tested at kv=2000,3000. Extension to kv=4000,5000 only
        # for combos still degraded at kv=3000 (ratio < 0.99 vs ceiling).
        # Saves ~22 evals vs full sweep by skipping non-degrading combos at high kv.
        ceiling_p1 = self._get_ceiling_rps()
        for tp, ni in combos:
            self.evaluate(tp, ni, "fcfs", 256, 2000, 32)
            self.evaluate(tp, ni, "fcfs", 256, 3000, 32)

        # Check which combos are still degraded at kv=3000
        for tp, ni in combos:
            key = (tp, ni)
            rps_at_3000 = self._cache.get((tp, ni, "fcfs", 256, 3000, 32))
            ceil_rps = ceiling_p1.get(key)
            if (rps_at_3000 is not None and ceil_rps is not None
                    and ceil_rps > 0
                    and rps_at_3000[0] < 0.99 * ceil_rps):
                # Still degraded at kv=3000: extend to kv=4000,5000
                self.evaluate(tp, ni, "fcfs", 256, 4000, 32)
                self.evaluate(tp, ni, "fcfs", 256, 5000, 32)

        # Phase 2.5 (expanded): All degraded combos at 0.99 threshold.
        # Backbone combos (best-per-GPU): sjf+128, sjf+256, fcfs+128 at each
        # degraded kv, plus near-ceiling sjf+256 at first non-degraded kv.
        # Non-best combos: sjf+128, sjf+64, fcfs+64 at each degraded kv.
        ceiling = self._get_ceiling_rps()

        # Identify best combo per GPU count (backbone)
        best_per_gpu = {}
        for (tp, ni), rps in ceiling.items():
            gpus = tp * ni
            if gpus not in best_per_gpu or rps > best_per_gpu[gpus][1]:
                best_per_gpu[gpus] = ((tp, ni), rps)
        backbone_combos = set(v[0] for v in best_per_gpu.values())

        # Collect all degraded combos (all tested kv values, bs=32, ratio < 0.99)
        # and for each combo remember which kv values were degraded
        degraded_by_tpni = {}   # (tp,ni) -> sorted list of degraded (kv, rps)
        tested_kv_by_tpni = {}  # (tp,ni) -> sorted list of all tested kv values
        for cfg, obj in self.results:
            if cfg["block_size_in_tokens"] != 32 or cfg["scheduler"] != "fcfs":
                continue
            key = (cfg["tp"], cfg["num_instances"])
            ceil_rps = ceiling.get(key, 0)
            kv = cfg["total_kv_blocks"]
            if key not in tested_kv_by_tpni:
                tested_kv_by_tpni[key] = []
            tested_kv_by_tpni[key].append(kv)
            if ceil_rps > 0 and obj[0] < 0.99 * ceil_rps:
                if key not in degraded_by_tpni:
                    degraded_by_tpni[key] = []
                degraded_by_tpni[key].append((kv, obj[0]))

        # Sort tested kv lists
        for key in tested_kv_by_tpni:
            tested_kv_by_tpni[key].sort()

        # Process backbone combos first (highest TP = highest rps = highest impact),
        # then non-best combos, both sorted by descending TP
        all_degraded_combos = list(degraded_by_tpni.keys())
        backbone_degraded = sorted(
            [c for c in all_degraded_combos if c in backbone_combos],
            key=lambda c: -c[0])
        nonbest_degraded = sorted(
            [c for c in all_degraded_combos if c not in backbone_combos],
            key=lambda c: -c[0])
        ordered_degraded = backbone_degraded + nonbest_degraded

        for (tp, ni) in ordered_degraded:
            if self.eval_count >= self.budget:
                break
            degs = sorted(degraded_by_tpni[(tp, ni)], key=lambda x: x[1])
            # All degraded kv values for this combo
            degraded_kvs = [kv for kv, _ in degs]
            max_degraded_kv = max(degraded_kvs)

            if (tp, ni) in backbone_combos:
                # Backbone: sjf+128, sjf+256, fcfs+128 at each degraded kv
                for kv, _ in degs:
                    if self.eval_count >= self.budget:
                        break
                    self.evaluate(tp, ni, "sjf", 128, kv, 32)
                    self.evaluate(tp, ni, "sjf", 256, kv, 32)
                    self.evaluate(tp, ni, "fcfs", 128, kv, 32)
                # Near-ceiling probe: sjf+256 at first non-degraded kv above
                # the highest degraded kv (captures scheduler differentiation
                # at the degradation knee)
                if self.eval_count < self.budget:
                    tested_kvs = sorted(tested_kv_by_tpni.get((tp, ni), []))
                    for kv in tested_kvs:
                        if kv > max_degraded_kv:
                            self.evaluate(tp, ni, "sjf", 256, kv, 32)
                            break
            else:
                # Non-best combo: sjf+128, sjf+64, fcfs+64 at each degraded kv
                for kv, _ in degs:
                    if self.eval_count >= self.budget:
                        break
                    self.evaluate(tp, ni, "sjf", 128, kv, 32)
                    self.evaluate(tp, ni, "sjf", 64, kv, 32)
                    self.evaluate(tp, ni, "fcfs", 64, kv, 32)

        # Phase 3 (eliminated): bs=16 sweep at low kv produced zero unique
        # Pareto tuples — bs=32 at same kv always dominates (RP-11). Saves 30 evals.

        # Phase 4: SJF scheduler for Pareto-near configs (~15 evals)
        pareto_cfgs = extract_pareto(self.results)
        for cfg in pareto_cfgs:
            if self.eval_count >= self.budget:
                break
            self.evaluate(cfg["tp"], cfg["num_instances"], "sjf",
                          cfg["max_num_running_reqs"],
                          cfg["total_kv_blocks"],
                          cfg["block_size_in_tokens"])

        # Phase 5: Concurrency exploration (~20 evals)
        pareto_cfgs = extract_pareto(self.results)
        for cfg in pareto_cfgs:
            if self.eval_count >= self.budget:
                break
            tp, ni = cfg["tp"], cfg["num_instances"]
            sched = cfg["scheduler"]
            kv, bs = cfg["total_kv_blocks"], cfg["block_size_in_tokens"]
            for maxr in [128, 64, 512]:
                self.evaluate(tp, ni, sched, maxr, kv, bs)

        # Phase 6: Fill remaining budget with neighbor exploration
        pareto_cfgs = extract_pareto(self.results)
        for cfg in pareto_cfgs:
            if self.eval_count >= self.budget:
                break
            tp, ni = cfg["tp"], cfg["num_instances"]
            sched = cfg["scheduler"]
            maxr = cfg["max_num_running_reqs"]
            kv = cfg["total_kv_blocks"]
            bs = cfg["block_size_in_tokens"]

            # Other block size
            self.evaluate(tp, ni, sched, maxr, kv, 32 if bs == 16 else 16)
            # Adjacent kv
            if kv in KV_VALUES:
                idx = KV_VALUES.index(kv)
                for d in [-1, 1]:
                    ni2 = idx + d
                    if 0 <= ni2 < len(KV_VALUES):
                        self.evaluate(tp, ni, sched, maxr, KV_VALUES[ni2], bs)
            # Other scheduler
            self.evaluate(tp, ni,
                          "sjf" if sched == "fcfs" else "fcfs",
                          maxr, kv, bs)

        return extract_pareto(self.results)


def main():
    parser = argparse.ArgumentParser(
        description="Multi-objective Pareto search for BLIS configs")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--rate", type=float, required=True,
                        help="Request arrival rate")
    parser.add_argument("--budget", type=int, required=True,
                        help="Max number of evaluations")
    parser.add_argument("--seed", type=int, required=True,
                        help="Random seed")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    searcher = BLISSearcher(
        model=args.model, rate=args.rate,
        seed=args.seed, budget=args.budget,
    )
    pareto_configs = searcher.search()

    with open(args.out, "w") as f:
        json.dump(pareto_configs, f, indent=2)

    print("Search complete: {}/{} evaluations used".format(
        searcher.eval_count, args.budget), file=sys.stderr)
    print("Found {} Pareto-optimal configurations".format(
        len(pareto_configs)), file=sys.stderr)


if __name__ == "__main__":
    main()
