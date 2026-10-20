# Handoff Snapshot — Iteration 4

## Goal

Deliver a v4 search.py that achieves >=98% mean Pareto tuple recall across 9 (rate, seed) conditions and demonstrates model generalization. Write final/answer.json with comprehensive claims and evidence.

## Key Discoveries

1. **v3 achieves 100% tuple recall at rate=100 across 3 seeds**, 100% at rate=50, and 97.6% at rate=200 (iter-3 confirmed). The only gap is 1 sjf+kv=5000 tuple at rate=200.

2. **The rate=200 missed tuple** is (rps=7.0656902, ttft=299.5, gpu=1, kv=5000) at tp=1,ni=1,sjf,maxrun=256,kv=5000,bs=32. It's non-dominated because sjf has 0.0006% higher rps than fcfs (7.0656902 vs 7.0656500) at the same config, trading higher TTFT (299.5 vs 178.3ms).

3. **The v4 fix is one line:** add `(5000, 256, 32, "sjf")` to `rich_tier_combos` in search.py (around line 341, after the existing `(5000, 256, 32, "fcfs")` entry). Budget impact: +1 eval per rich tier (~7 more evals total).

4. **Meta-llama/llama-2-7b-hf works with BLIS.** Probed: tp=1,ni=1,rate=100 gives rps=3.85 (kv=5000), rps=3.59 (kv=2000, 117 preemptions). The preemption zone exists and the structural properties (rich/simple tiers) should generalize.

5. **Pareto front complexity across rates:** rate=50: 23 tuples/9 tiers, rate=100: 35 tuples/12 tiers, rate=200: 41 tuples/12 tiers. Higher rates produce more tuples (wider preemption zone) but the structure remains qualitatively similar.

6. **14 sjf-only Pareto tuples exist at rate=200**, but v3 already covers 13 of them through sjf combos at kv=2000-4000. Only the kv=5000 sjf combo is missed.

7. **Existing ground truth data:**
   - rate=100, seeds 42/123/999: `runs/iter-2/results/exhaustive/exhaustive_seed{42,123,999}.json`
   - rate=50, seed=42: `runs/iter-3/results/h-robustness/rate50/exhaustive_seed42.json`
   - rate=200, seed=42: `runs/iter-3/results/h-robustness/rate200/exhaustive_seed42.json`

## System Interface

- **Build:** `go build -o blis main.go` (validated, exit 0)
- **Run baseline:** `./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 --admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin --gpu-memory-utilization 0.9 --tp 2 --num-instances 2 --scheduler fcfs --max-num-running-reqs 128 --total-kv-blocks 3000 --block-size-in-tokens 32 --metrics-path results/baseline.json`
- **Output format:** `--metrics-path` writes JSON dict with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `completed_requests`, etc.
- **Baseline result:** rps=16.28, ttft_p99=39.18ms, 200/200 completed, 0 preemptions
- **search.py interface:** `python3 search.py --model <m> --rate <r> --budget 200 --seed <s> --out <file>`

## Code Map

- `cmd/root.go:2078` — `--metrics-path` flag definition. Check here if output file isn't being written.
- `cmd/root.go:1768` — `SaveResults("cluster", ...)` call that writes aggregated metrics JSON.
- `sim/metrics.go:127` — `ResponsesPerSec` computation: `completed_requests / vllm_estimated_duration_s`.
- `search.py:318-341` — Phase 2 `rich_tier_combos` list. **This is where the v4 fix goes.**
- `search.py:248-280` — Phase 1 deterministic template (5 configs per tier, no shuffling).
- `search.py:288-308` — Rich/simple tier classification logic.
- `search.py:368-402` — Phase 3 neighbor expansion.
- `search.py:98-109` — Pareto dominance function (4 objectives: -rps, ttft, gpu, kv).

## Code Targets

### h-main: v4 fix to search.py
- **File:** `search.py` (repo root)
- **Location:** Line ~341, the `rich_tier_combos` list
- **What to change:** Add `(5000, 256, 32, "sjf")` after the existing `(5000, 256, 32, "fcfs")` entry.
- **Why this location:** This is the ONLY change needed. Phase 2 already covers sjf at kv=2000-4000. The gap is specifically at kv=5000 where sjf produces a barely-non-dominated tuple at high rates.

### h-robustness: exhaustive enumeration for llama-2-7b-hf
- **File:** Create `inputs/exhaustive_enumerate.py` (adapt from iter-2/iter-3 pattern)
- **What:** Run all 1800 configs at meta-llama/llama-2-7b-hf, rate=100, seed=42 for ground truth.
- **Note:** llama-2-7b is ~35% slower per eval (~0.3s vs 0.22s for qwen3-14b). Total: ~9 min.

## What I Tried That Didn't Work

1. **(From iter-1) Shell variable expansion:** Always use explicit inline flags, not `$FIXED` variables.
2. **(From iter-1) Grep on stdout:** Always use `--metrics-path` and parse JSON.
3. **(From iter-1) Assumption that block_size is negligible:** bs=32 is strictly Pareto-dominant.
4. **(From iter-2) Shuffled Phase 1:** Introduces seed-dependent variance. Deterministic Phase 1 eliminates this.
5. **(From iter-2) Uniform neighbor expansion:** Wastes budget at simple tiers. Diversity-directed Phase 2 is superior.
6. **(From iter-3) sjf coverage only at kv=2000-4000:** Misses the kv=5000 sjf edge case at rate=200.

## What I Excluded and Why

1. **Budget vs recall dose-response:** How recall scales with budget (100, 150, 200) is interesting but secondary to confirming the deliverable works at the specified 200-eval budget.
2. **Ablation of v4 fix:** Reverting to v3 was already tested in iter-3 (97.6% at rate=200). The fix is a single-line addition — ablation adds no new insight.
3. **Higher rates (rate=300+):** The task specifies the search should work with "a different model or rate." Testing rate=50 and rate=200 brackets the default rate=100. Extremely high rates may produce qualitatively different behavior but are beyond the stated scope.
4. **Multiple models for robustness:** Testing all available models (8 total) would require ~72 min of exhaustive enumeration. One different model (llama-2-7b-hf) is sufficient to validate generalization.

## Evolution of Thinking

**Iter-1:** Assumed space was simple, search was "near-complete." No ground truth. Recall was actually ~34%.

**Iter-2:** Established exhaustive ground truth. Discovered bs=32 dominance, real recall was far lower than claimed. Improved to v2 (57.9% mean recall).

**Iter-3:** Structural analysis of Pareto front revealed it's concentrated in partial-preemption zone at rich tiers. v3 with deterministic Phase 1 + diversity-directed Phase 2 achieved 100% at rate=100, but 97.6% at rate=200 due to one sjf+kv=5000 edge case.

**Iter-4 (current):** The fix is surgical — one combo addition. The scientific question shifts from "can we find all tuples?" to "how robust is this across conditions?" Multi-seed at non-100 rates and model generalization are the remaining validation frontiers. The algorithm is essentially complete; iter-4 is about comprehensive validation and final deliverable quality.

## Current Status

- **Validated:** BLIS builds (exit 0, ~2s)
- **Validated:** BLIS works with meta-llama/llama-2-7b-hf (exit 0, rps=3.85 at tp=1,ni=1,kv=5000)
- **Validated:** v3 achieves 100% at rate=100 (3 seeds), 100% at rate=50 (seed=42), 97.6% at rate=200 (seed=42)
- **Validated:** The missed tuple at rate=200 is exactly sjf+kv=5000+maxrun=256 at tp=1,ni=1
- **Validated:** Adding (5000, 256, 32, "sjf") costs only +7 Phase 2 evals (within budget)
- **Uncertain:** Whether the fix closes the gap at rate=200 for seeds 123 and 999
- **Uncertain:** Whether multi-seed at rate=50 and rate=200 maintains 100%/97.6%+ recall
- **Uncertain:** Recall on llama-2-7b-hf (probed preemption exists, but Pareto structure unknown)
- **Suggested next:** If all conditions pass, finalize deliverable. If model generalization fails, investigate model-specific Phase 2 templates.

## Warnings & Constraints

1. **BLIS `--metrics-path` JSON is a single dict, not a list.** Parse with `json.load()`.
2. **tp x num_instances must be <= 8.** 15 valid GPU tiers total.
3. **Eval times vary by model:** qwen3-14b ~0.22s, llama-2-7b ~0.3s per eval.
4. **Exhaustive enumeration times:** ~6.6 min for qwen3-14b, ~9 min for llama-2-7b (1800 configs).
5. **`total_kv_blocks` is per-instance.** Multi-instance configs spread load.
6. **Pareto recall should use distinct metric tuples, not raw config counts.**
7. **Existing exhaustive data locations:**
   - rate=100: `runs/iter-2/results/exhaustive/exhaustive_seed{42,123,999}.json`
   - rate=50, seed=42: `runs/iter-3/results/h-robustness/rate50/exhaustive_seed42.json`
   - rate=200, seed=42: `runs/iter-3/results/h-robustness/rate200/exhaustive_seed42.json`
8. **search.py in repo root is currently v3.** The executor must modify it to v4 (add 1 line).
9. **The Phase 2 budget can be exhausted at high rates** (many rich tiers). The algorithm handles this gracefully (budget cap at line 358) but Phase 3 gets fewer evals. This is acceptable since Phase 2 covers the key combos.
10. **At rate=200, there are 14 sjf-only Pareto tuples.** v3 covers 13 of them. v4 should cover all 14.
