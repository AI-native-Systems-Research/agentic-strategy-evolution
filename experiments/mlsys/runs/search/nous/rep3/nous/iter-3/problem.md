# Problem Framing — Iteration 3

## Research Question

Can a structure-aware search algorithm achieve >90% Pareto tuple recall within 200 evaluations of the BLIS 6-knob configuration space, and does it generalize across arrival rates?

Iteration 2 established that v2's balanced block_size coverage improved recall from 0.337 to 0.579 (mean across seeds), but 0.579 is still far from complete. Analysis of the exhaustive ground truth (1800 configs, 35 distinct Pareto metric tuples at rate=100) reveals the source of the remaining gap: v2 still shuffles Phase 1 configs, wasting budget on redundant evaluations while missing systematic maxrun × kv exploration at "rich" GPU tiers (those with partial preemption creating metric diversity).

Key code references:
- `sim/config.go:10-11` — `TotalKVBlocks` and `BlockSizeTokens` in `KVCacheConfig`. The critical quantity is `kv_blocks × block_size` (total cache tokens per instance).
- `sim/metrics.go:127` — `ResponsesPerSec` = `completed_requests / vllm_estimated_duration_s`.
- `cmd/root.go:2078` — `--metrics-path` flag for JSON output.
- `cmd/root.go:964` — `--max-num-running-reqs` default 256.

## System Interface

- **Build:** `go build -o blis main.go` (exit 0, ~2s)
- **CLI flags:** `./blis run --model <m> --hardware H100 --latency-model trained-physics --num-requests 200 --rate <r> --prefix-tokens 512 --seed <s> --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 --admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin --gpu-memory-utilization 0.9 --tp <tp> --num-instances <ni> --scheduler <sched> --max-num-running-reqs <maxrun> --total-kv-blocks <kv> --block-size-in-tokens <bs> --metrics-path <path>`
- **Code evidence:**
  - `cmd/root.go:2078` — `--metrics-path` flag defined
  - `cmd/root.go:1768` — `SaveResults("cluster", ...)` writes JSON
  - `cmd/root.go:964` — `--max-num-running-reqs` default
- **Output:** `--metrics-path` writes JSON dict with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `completed_requests`, etc.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 2 --num-instances 2 --scheduler fcfs --max-num-running-reqs 128 \
  --total-kv-blocks 3000 --block-size-in-tokens 32 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Exit 0. Output: `rps=16.28, ttft_p99=39.18, preemptions=0, completed=200`. Matches iter-2 ground truth exactly. This config (tp=2,ni=2,kv=3000,bs=32) is above the KV threshold (96K total cache tokens per instance).

## Experimental Conditions

### h-main: v3 search (structure-aware deterministic search)

**Code change to search.py:**
Replace the entire search algorithm with a 3-phase structure-aware approach:
1. **Deterministic Phase 1 (~38% budget):** For each of 15 GPU tiers, evaluate 5 fixed configs: (kv=2000,bs=32,maxrun=128,fcfs), (kv=2000,bs=32,maxrun=64,fcfs), (kv=3000,bs=32,maxrun=128,fcfs), (kv=5000,bs=16,maxrun=128,fcfs), (kv=4000,bs=32,maxrun=256,fcfs). No shuffling — deterministic coverage.
2. **Diversity-directed Phase 2 (~40% budget):** Classify tiers as "rich" (TTFT range > 100ms, indicating partial preemption) vs "simple". At rich tiers, systematically test maxrun × kv × scheduler combos in the preemption zone (kv=2000–4000, bs=32, multiple maxrun values, both schedulers). At simple tiers, test 2 additional minimum-kv configs.
3. **Neighbor expansion Phase 3 (remaining ~22% budget):** Standard Pareto neighbor expansion.

**Validation against exhaustive ground truth at rate=100:**
- v3 achieves 1.000 tuple recall (35/35) at all 3 seeds (42, 123, 999) — using existing iter-2 exhaustive data as lookup table simulation.
- v2 achieved 0.579 mean recall at same seeds.

**Command:** `python3 search.py --model qwen/qwen3-14b --rate 100 --budget 200 --seed <s> --out results/h-main/v3_seed<s>.json`

### h-robustness: v3 at different arrival rates

Test v3 at rate=50 (lower load, less preemption) and rate=200 (higher load, more preemption) to verify the algorithm generalizes.

**Commands:**
- `python3 search.py --model qwen/qwen3-14b --rate 50 --budget 200 --seed 42 --out results/h-robustness/v3_rate50_seed42.json`
- `python3 search.py --model qwen/qwen3-14b --rate 200 --budget 200 --seed 42 --out results/h-robustness/v3_rate200_seed42.json`

**Requires:** Exhaustive enumeration at rate=50 and rate=200 (seed=42) for ground truth.

## Success Criteria

- **h-main:** v3 mean tuple recall > 0.90 across seeds 42, 123, 999 at rate=100. Minimum recall across seeds > 0.85.
- **h-robustness:** v3 tuple recall > 0.80 at rate=50 and rate=200 (seed=42).

## Constraints

- Budget: 200 evaluations per search run (11.1% of 1800 total configs).
- Wall time: < 3 minutes per search run (~0.22s per BLIS eval × 200 = ~44s).
- search.py must use Python 3 standard library only.
- Exhaustive enumeration for ground truth at rate=50,200: ~6.6 min each (1800 × 0.22s).

## Prior Knowledge

- **RP-1:** KV cache binary threshold — above: TTFT ≈ 40ms; below: TTFT 1000–50000ms.
- **RP-2:** GPU count is dominant throughput factor; within each tier, KV/maxrun have threshold-gated effects.
- **RP-3:** Two-phase search covers all GPU tiers in 200 evals / 18s — but "near-complete" was overstated (actual recall: 33.7% v1, 57.9% v2).
- **RP-4:** Balanced bs=32 Phase 1 improves recall by 72% relative (v1→v2).
- **RP-5:** Shuffled Phase 1 can produce recall below random sampling for specific seeds.

**New structural discovery from iter-3 exploration:**
The exhaustive Pareto front at rate=100 has 35 distinct metric tuples across 12 active GPU tiers. The "rich" tiers (ni=1, ni=2 with low instance count) have 4–6 tuples each in the partial preemption zone (kv=2000–4000), while multi-instance tiers (ni≥3) have only 1 tuple (cache is ample even at minimum kv). Block_size=32 is strictly Pareto-dominant: every Pareto config uses bs=32 (when kv is above the minimum) because it halves kv_blocks for the same total cache tokens.
