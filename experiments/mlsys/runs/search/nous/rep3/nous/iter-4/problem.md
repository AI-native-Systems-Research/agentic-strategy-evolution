# Problem Framing — Iteration 4

## Research Question

Can the v3 structure-aware Pareto search, with a minor fix to cover the sjf+kv=5000 edge case, achieve ≥98% tuple recall across all combinations of rates {50, 100, 200} and seeds {42, 123, 999}, and does it generalize to a different model (meta-llama/llama-2-7b-hf)?

The search algorithm is implemented in `search.py` (repo root). The mechanism under study is a three-phase deterministic search:
- Phase 1 (`search.py:248-280`): 5 deterministic configs per GPU tier (75 evals)
- Phase 2 (`search.py:288-362`): diversity-directed expansion (rich vs simple tiers)
- Phase 3 (`search.py:368-402`): neighbor expansion from current Pareto front

The v3→v4 fix adds `(5000, 256, 32, "sjf")` to the Phase 2 rich-tier combos (`search.py:318-341`), closing the one gap observed at rate=200 in iter-3 (sjf at kv=5000 produces a non-dominated tuple due to a 0.0006% rps advantage over fcfs).

## System Interface

- **Build:** `go build -o blis main.go` (validated, exit 0)
- **CLI flags relevant to experiment:**
  - `--metrics-path <path>`: writes JSON output with `responses_per_sec`, `ttft_p99_ms`, etc. Defined at `cmd/root.go:2078`.
  - `--tp`, `--num-instances`, `--scheduler`, `--max-num-running-reqs`, `--total-kv-blocks`, `--block-size-in-tokens`: the 6 search knobs.
  - `--model`: model identifier (e.g., `qwen/qwen3-14b`, `meta-llama/llama-2-7b-hf`). Defined at `cmd/root.go` model flag section.
  - `--rate`: arrival rate (requests per second).
  - `--seed`: RNG seed for deterministic output.
- **Code evidence:**
  - `cmd/root.go:2078` — `--metrics-path` flag definition
  - `cmd/root.go:1768` — `SaveResults("cluster", ...)` writes aggregated metrics JSON
  - `sim/metrics.go:127` — `ResponsesPerSec` = `completed_requests / vllm_estimated_duration_s`
- **Output:** `--metrics-path` writes a JSON dict. Key fields: `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `completed_requests`.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin \
  --gpu-memory-utilization 0.9 --tp 2 --num-instances 2 --scheduler fcfs \
  --max-num-running-reqs 128 --total-kv-blocks 3000 --block-size-in-tokens 32 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Ran the baseline command. Exit code 0. Output file written to `/tmp/blis_smoke.json`. Key metrics: `responses_per_sec=16.28`, `ttft_p99_ms=39.18`, `preemption_count=0`, `completed_requests=200`.

Also validated with `meta-llama/llama-2-7b-hf` at tp=1,ni=1: `responses_per_sec=3.85`, `ttft_p99_ms=24106.55` (kv=5000), `responses_per_sec=3.59`, `ttft_p99_ms=35529.73` (kv=2000, 117 preemptions). Model generalization probe confirms BLIS runs correctly with different models and the preemption zone exists.

## Experimental Conditions

### h-main: Multi-seed multi-rate validation of v4 search

**Code change:** Modify `search.py` to add `(5000, 256, 32, "sjf")` to the `rich_tier_combos` list (around line 341). This costs +1 eval per rich tier (~7 more evals in Phase 2), closing the sjf+kv=5000 gap observed at rate=200 in iter-3.

**Execution:** Run v4 search at 9 conditions: rates {50, 100, 200} × seeds {42, 123, 999}. Compare against exhaustive ground truth at each (rate, seed) combination.

**Ground truth needed:**
- rate=100, seeds 42/123/999: reuse iter-2 data
- rate=50, seed=42: reuse iter-3 data
- rate=200, seed=42: reuse iter-3 data
- rate=50, seeds 123/999: run exhaustive (1800 configs each)
- rate=200, seeds 123/999: run exhaustive (1800 configs each)

### h-robustness: Model generalization

**Execution:** Run v4 search with `--model meta-llama/llama-2-7b-hf` at rate=100, seed=42. Run exhaustive ground truth for this model. Compare recall.

**Ground truth needed:** exhaustive at meta-llama/llama-2-7b-hf, rate=100, seed=42.

## Success Criteria

- **h-main:** Mean tuple recall ≥ 0.98 across all 9 (rate, seed) conditions. Minimum recall across conditions ≥ 0.95.
- **h-robustness:** Tuple recall ≥ 0.85 at meta-llama/llama-2-7b-hf, rate=100, seed=42.

## Constraints

- Budget: 200 evaluations per search run (hard limit)
- Wall time: 3 minutes per search run (hard limit)
- search.py: standard library only (no numpy, scipy, etc.)
- Exhaustive enumerations: ~1800 configs × ~0.22s/eval ≈ 6.6 min per (rate, seed, model) combination
- Total experiment time: ~4 exhaustive runs (new) × 7 min + 1 exhaustive llama × 9 min + 10 search runs × 0.7 min ≈ 44 min

## Prior Knowledge

- **RP-1 (high):** KV cache binary threshold — below threshold, preemptions spike TTFT by 100-250×.
- **RP-2 (high):** GPU count is dominant throughput factor; within tiers, KV and maxrun have threshold-gated effects.
- **RP-4 (high):** bs=32 is Pareto-dominant; balanced coverage improves recall.
- **RP-5 (high):** Shuffled Phase 1 can produce recall below random for specific seeds.
- **RP-6 (high):** v3 achieves 100% at rate=100, >97% at rate=50/200.
- **RP-7 (high):** Pareto front complexity is low (23-41 tuples), concentrated in partial-preemption zone.

Iter-3 identified the rate=200 gap: sjf at kv=5000 produces a non-dominated tuple (rps=7.0657 vs fcfs rps=7.0657, difference at 5th decimal place) that v3's Phase 2 template doesn't cover. The v4 fix addresses this directly.
