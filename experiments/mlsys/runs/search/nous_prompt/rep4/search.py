#!/usr/bin/env python3
"""
Adaptive multi-phase search for Pareto-optimal BLIS serving configurations.

Objectives (4D):
  1. maximize responses_per_sec
  2. minimize ttft_p99_ms
  3. minimize GPU count (tp * num_instances)
  4. minimize total_kv_blocks

Strategy:
  Phase 1: Test peak and minimal configs for each (tp, instances) combo
  Phase 2: Dense grid on sensitive combos (where knobs affect outcomes)
  Phase 3: Refinement, verification, and edge case exploration
  Phase 4: Extract 4D Pareto front
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

TP_VALUES = [1, 2, 4, 8]
KV_VALUES = [2000, 3000, 4000, 5000, 7500, 10000]
MR_VALUES = [32, 64, 128, 256, 512]


def parse_args():
    p = argparse.ArgumentParser(description="Search BLIS config space for Pareto front")
    p.add_argument("--model", required=True)
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--budget", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    return p.parse_args()


class BLISSearcher:
    def __init__(self, model, rate, seed, budget):
        self.model = model
        self.rate = rate
        self.seed = seed
        self.budget = budget
        self.eval_count = 0
        self.cache = {}
        self.tmpdir = tempfile.mkdtemp(prefix="blis_search_")
        self._file_counter = 0

    def _run(self, tp, inst, sched, mr, kv, bs, count_budget=True):
        key = (tp, inst, sched, mr, kv, bs)
        if key in self.cache:
            return self.cache[key]
        if self.eval_count >= self.budget:
            return None

        self._file_counter += 1
        metrics_path = os.path.join(self.tmpdir, "m%d.json" % self._file_counter)

        cmd = [
            "./blis", "run",
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
            "--num-instances", str(inst),
            "--scheduler", sched,
            "--max-num-running-reqs", str(mr),
            "--total-kv-blocks", str(kv),
            "--block-size-in-tokens", str(bs),
            "--metrics-path", metrics_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.eval_count += 1
            return None

        self.eval_count += 1

        if result.returncode != 0:
            return None

        try:
            with open(metrics_path) as f:
                d = json.load(f)
            metrics = (d["responses_per_sec"], d["ttft_p99_ms"])
            self.cache[key] = metrics
            return metrics
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def _has_budget(self):
        return self.eval_count < self.budget

    @staticmethod
    def get_combos():
        combos = []
        for tp in TP_VALUES:
            for inst in range(1, 8 // tp + 1):
                combos.append((tp, inst))
        return combos

    def search(self):
        combos = self.get_combos()

        # Phase 1: Peak (generous) and minimal config for each combo
        peak = {}
        minimal = {}
        for tp, inst in combos:
            p = self._run(tp, inst, "fcfs", 256, 10000, 32)
            if p:
                peak[(tp, inst)] = p
            m = self._run(tp, inst, "fcfs", 32, 2000, 32)
            if m:
                minimal[(tp, inst)] = m

        # Classify combos as sensitive or insensitive
        sensitive = []
        insensitive = []
        for tp, inst in combos:
            p = peak.get((tp, inst))
            m = minimal.get((tp, inst))
            if p and m:
                rps_diff = abs(p[0] - m[0]) / max(p[0], 1e-6)
                ttft_diff = abs(p[1] - m[1]) / max(min(p[1], m[1]), 1e-6)
                if rps_diff > 0.02 or ttft_diff > 0.1:
                    sensitive.append((tp, inst))
                else:
                    insensitive.append((tp, inst))
            elif p or m:
                sensitive.append((tp, inst))

        # Phase 2: Targeted search on sensitive combos
        remaining = self.budget - self.eval_count
        n_sensitive = len(sensitive)
        if n_sensitive:
            per_combo = max(remaining // (n_sensitive + 2), 8)
        else:
            per_combo = 0

        for tp, inst in sensitive:
            before = self.eval_count
            # Priority 1: test mr=256 at all KV levels (finds minimum kv for peak)
            for kv in KV_VALUES:
                if (self.eval_count - before) >= per_combo or not self._has_budget():
                    break
                self._run(tp, inst, "fcfs", 256, kv, 32)

            # Priority 2: test mr=128 at all KV levels (transition points)
            for kv in KV_VALUES:
                if (self.eval_count - before) >= per_combo or not self._has_budget():
                    break
                self._run(tp, inst, "fcfs", 128, kv, 32)

            # Priority 3: test mr=64 at key KV levels
            for kv in [2000, 3000, 5000, 10000]:
                if (self.eval_count - before) >= per_combo or not self._has_budget():
                    break
                self._run(tp, inst, "fcfs", 64, kv, 32)

        # Phase 3: Refinement with remaining budget
        # 3a: Test kv=2000 with various mr for sensitive combos
        for tp, inst in sensitive:
            if not self._has_budget():
                break
            for mr in [64, 128, 256]:
                if not self._has_budget():
                    break
                self._run(tp, inst, "fcfs", mr, 2000, 32)

        # 3b: Test mr=32 with higher kv (might match peak for free)
        for tp, inst in sensitive:
            if not self._has_budget():
                break
            for kv in [5000, 7500, 10000]:
                if not self._has_budget():
                    break
                self._run(tp, inst, "fcfs", 32, kv, 32)

        # 3c: Verify insensitive combos with a middle config
        for tp, inst in insensitive:
            if not self._has_budget():
                break
            self._run(tp, inst, "fcfs", 64, 3000, 32)

        # 3d: Test bs=16 with kv=2000 for sensitive (lowest resource point)
        for tp, inst in sensitive:
            if not self._has_budget():
                break
            self._run(tp, inst, "fcfs", 128, 2000, 16)
            if self._has_budget():
                self._run(tp, inst, "fcfs", 256, 3000, 16)

        # 3e: Additional kv=4000 tests for sensitive combos
        for tp, inst in sensitive:
            if not self._has_budget():
                break
            for mr in [64, 128, 256]:
                if not self._has_budget():
                    break
                self._run(tp, inst, "fcfs", mr, 4000, 32)

        # 3f: Use any remaining budget on untested configs for sensitive combos
        for tp, inst in sensitive:
            for kv in KV_VALUES:
                for mr in MR_VALUES:
                    if not self._has_budget():
                        break
                    self._run(tp, inst, "fcfs", mr, kv, 32)

        return self._compute_pareto()

    @staticmethod
    def _dominates(a, b):
        """Check if objective vector a dominates b.

        Objectives: (rps [max], ttft [min], gpu [min], kv [min]).
        Uses tolerance for float objectives (rps, ttft) to handle
        deterministic simulator producing identical results across
        configs that differ only in over-provisioned resources.
        """
        EPS_RPS = 0.01
        EPS_TTFT = 0.5
        ge_rps = a[0] >= b[0] - EPS_RPS
        le_ttft = a[1] <= b[1] + EPS_TTFT
        le_gpu = a[2] <= b[2]
        le_kv = a[3] <= b[3]
        all_ok = ge_rps and le_ttft and le_gpu and le_kv

        gt_rps = a[0] > b[0] + EPS_RPS
        lt_ttft = a[1] < b[1] - EPS_TTFT
        lt_gpu = a[2] < b[2]
        lt_kv = a[3] < b[3]
        strictly = gt_rps or lt_ttft or lt_gpu or lt_kv

        return all_ok and strictly

    def _compute_pareto(self):
        entries = []
        for key, (rps, ttft) in self.cache.items():
            tp, inst, sched, mr, kv, bs = key
            config = {
                "tp": tp,
                "num_instances": inst,
                "scheduler": sched,
                "max_num_running_reqs": mr,
                "total_kv_blocks": kv,
                "block_size_in_tokens": bs,
            }
            obj = (rps, ttft, tp * inst, kv)
            entries.append((config, obj))

        n = len(entries)
        dominated = [False] * n
        for i in range(n):
            if dominated[i]:
                continue
            oi = entries[i][1]
            for j in range(n):
                if i == j or dominated[j]:
                    continue
                oj = entries[j][1]
                if self._dominates(oj, oi):
                    dominated[i] = True
                    break

        front = [entries[i] for i in range(n) if not dominated[i]]

        # Deduplicate: group by objective vector, keep best config per group
        seen = {}
        EPS_RPS = 0.01
        EPS_TTFT = 0.5
        for config, obj in front:
            obj_key = (round(obj[0] / EPS_RPS) * EPS_RPS,
                       round(obj[1] / EPS_TTFT) * EPS_TTFT,
                       obj[2], obj[3])
            if obj_key not in seen:
                seen[obj_key] = config
            else:
                existing = seen[obj_key]
                new_score = (config["block_size_in_tokens"],
                             -config["max_num_running_reqs"])
                old_score = (existing["block_size_in_tokens"],
                             -existing["max_num_running_reqs"])
                if new_score > old_score:
                    seen[obj_key] = config

        result = sorted(seen.values(),
                        key=lambda c: (c["tp"] * c["num_instances"],
                                       c["total_kv_blocks"],
                                       c["tp"]))
        return result


def main():
    args = parse_args()
    searcher = BLISSearcher(args.model, args.rate, args.seed, args.budget)
    pareto = searcher.search()

    with open(args.out, "w") as f:
        json.dump(pareto, f, indent=2)

    print("Evaluated %d/%d configs, found %d Pareto-optimal" % (
        searcher.eval_count, args.budget, len(pareto)), file=sys.stderr)


if __name__ == "__main__":
    main()
