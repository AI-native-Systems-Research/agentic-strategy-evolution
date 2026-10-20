# Problem Framing — Iteration 3

## Research Question

Does the 4-phase Pareto search algorithm (validated at 100% coverage for qwen3-14b at rate=100) generalize across different models and arrival rates, or is it overfit to the specific kv-ceiling and preemption-boundary structure of the reference regime?

The core mechanism under test: the algorithm's Phase 1 ceiling/cheapest scan and Phase 2 adaptive boundary mapping discover the preemption boundary _regardless_ of where it lies in the kv-blocks range, because the strategy is data-driven (preemption detection from Phase 1 probes), not hardcoded to specific thresholds.

Key source files:
- `search.py` (current 459 lines) — the search algorithm deliverable
- `sim/kvcache/store.go` — KV block allocation; ceiling depends on model's per-token KV cache size
- `sim/scheduler.go` — scheduling policy; preemption triggered when KV cache is full

## System Interface

- **Build:** `go build -o blis main.go` (validated, exit 0)
- **CLI flags relevant to experiment:** `--model`, `--rate`, `--seed`, `--tp`, `--num-instances`, `--scheduler`, `--max-num-running-reqs`, `--total-kv-blocks`, `--block-size-in-tokens`, `--metrics-path`
  - `--model`: defined in `cmd/run.go`; any HuggingFace model name accepted; architecture resolved from model_configs/ or HF API
  - `--rate`: Poisson arrival rate (requests/sec), defined in `cmd/run.go`
  - `--metrics-path`: writes cluster-level JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`
- **Code evidence:**
  - `cmd/run.go` — all CLI flags parsed via cobra
  - `sim/kvcache/store.go` — KV block allocation and preemption logic
  - `sim/scheduler.go:25-80` — FCFS and SJF scheduling implementations
- **Output:** `--metrics-path <file>` writes JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `dropped_unservable`

## Baseline Command

```bash
python3 search.py --model qwen/qwen3-14b --rate 100 --budget 200 --seed 42 --out /tmp/search_output.json
```

## Baseline Validation

Ran current search.py at reference settings. Exit 0. Output: 38 Pareto-optimal configs from 200 evaluations. Completed in ~30 seconds. Coverage vs 26-config reference Pareto: 100% (iter-2 validated).

## Experimental Conditions

### Condition 1: Reference regime (control)
- search.py on qwen/qwen3-14b, rate=100, seed=42, budget=200
- Expected: 100% coverage (replication of iter-2)

### Condition 2: Cross-model — Llama-3.1-70B-Instruct
- search.py on meta-llama/Llama-3.1-70B-Instruct, rate=100, seed=42, budget=200
- Key probe findings:
  - tp=4,inst=2,kv=5000: rps=8.35, ttft_p99=68.79, preempt=0
  - tp=4,inst=2,kv=2000: rps=7.69, ttft_p99=8926, preempt=36
  - tp=4,inst=2,kv=3000: rps=8.35, ttft_p99=68.79, preempt=0 (ceiling at kv=3000!)
  - tp=8,inst=1,kv=5000: rps=12.49, ttft_p99=53.47, preempt=0
  - **Ceiling is at kv=3000 for Llama-70B (not kv=5000)**; kv=3000 through kv=10000 are byte-identical

### Condition 3: Cross-rate high — qwen3-14b at rate=200
- search.py on qwen/qwen3-14b, rate=200, seed=42, budget=200
- Probe findings:
  - tp=4,inst=2,kv=5000: rps=28.16, ttft_p99=29.12, preempt=0
  - tp=4,inst=2,kv=2000: rps=26.42, ttft_p99=1759.97, preempt=29
  - Ceiling still at kv=5000; more preemptions at kv=2000 due to higher load

### Condition 4: Cross-rate low — qwen3-14b at rate=50
- search.py on qwen/qwen3-14b, rate=50, seed=42, budget=200
- Probe findings:
  - tp=4,inst=2,kv=5000: rps=22.36, ttft_p99=28.49, preempt=0
  - System under-loaded at rate=50; fewer preemption regimes expected

### Code change: Adaptive ceiling detection in search.py
- **Phase 1**: Change hardcoded ceiling from kv=5000 to kv=max(KV_VALUES)=10000, ensuring the true performance ceiling is found for ANY model
- **Phase 2**: Expand intermediate fill from [3000, 4000] to [3000, 4000, 5000], covering the gap when ceiling is at kv=10000 instead of kv=5000
- **Phase 4**: Remove redundant kv=7500/10000 exploration (already covered by Phase 1 ceiling), repurpose budget for additional intermediate kv values and topology coverage
- **Rationale**: The hardcoded kv=5000 ceiling works for qwen3-14b but is a fragile assumption. For Llama-70B, ceiling is kv=3000 (lower); for a very small model under extreme load, ceiling could be kv=7500+ (higher). Using kv=max makes the algorithm model-agnostic.

For each regime, also compute an exhaustive reference Pareto front (15 topologies × 6 kv × 2 bs = 180 configs) to measure coverage.

## Success Criteria

- **h-main**: Improved search.py achieves ≥90% Pareto coverage across ALL 4 regimes (reference, cross-model, cross-rate-high, cross-rate-low) within 200 evaluations each
- Direction: adaptive ceiling makes coverage model/rate-invariant
- Falsification: If coverage drops below 80% for any regime, the algorithm's structural assumptions don't generalize

## Constraints

- Budget: ≤200 evaluations per search run
- Wall time: ≤3 minutes per search run
- Python standard library only
- search.py must accept --model, --rate, --budget, --seed, --out flags

## Prior Knowledge

- RP-1 (high confidence): KV cache capacity has saturating effect — below critical threshold, preemptions cause TTFT degradation; above, performance plateaus
- RP-2 (high confidence): TP consistently outperforms instance parallelism for throughput
- RP-4 (high confidence): GPU count not monotone predictor; topology selection > raw GPU count
- RP-5 (high confidence): Ceiling-cheapest-boundary search achieves 100% coverage at 100 evals for qwen3-14b/rate=100
- RP-6 (high confidence): Budget-coverage saturates sharply at ~60 evals for Phase 1+2

**New observation from probes**: The kv ceiling is model-dependent (kv=3000 for Llama-70B vs kv=5000 for qwen3-14b) but rate-independent (kv=5000 at rate=200 equals rate=100 for qwen3-14b). This is consistent with RP-1: the ceiling depends on per-token KV cache size × max batch concurrency, which scales with model architecture but not arrival rate.
