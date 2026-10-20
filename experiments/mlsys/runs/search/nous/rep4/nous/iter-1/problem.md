# Problem Framing: BLIS Configuration Space Pareto Search

## Research Question

What is the structure of the BLIS 6-knob configuration space's Pareto front (which knobs matter, which do not, what are the trade-offs), and can a search algorithm find a near-complete Pareto front with at most 200 evaluations out of 1800 total configurations?

The configuration space consists of:
- `--tp` (tensor parallelism): {1, 2, 4, 8}
- `--num-instances`: {1..8/tp} such that tp × instances ≤ 8 GPUs → 15 valid (tp, instances) combos
- `--scheduler`: {fcfs, sjf}
- `--max-num-running-reqs`: {32, 64, 128, 256, 512}
- `--total-kv-blocks`: {2000, 3000, 4000, 5000, 7500, 10000}
- `--block-size-in-tokens`: {16, 32}

Total: 15 × 2 × 5 × 6 × 2 = 1800 configurations.

Four objectives: maximize `responses_per_sec`, minimize `ttft_p99_ms`, minimize GPU count (tp × instances), minimize `total_kv_blocks`.

Key source files:
- `cmd/root.go:963-980` — CLI flag definitions for all 6 knobs
- `sim/metrics.go:127` — `ResponsesPerSec` calculation
- `sim/metrics_utils.go:66` — `MetricsOutput` struct with `responses_per_sec` and `ttft_p99_ms` fields
- `cmd/root.go:2078` — `--metrics-path` flag for JSON output

## System Interface

- **Build:** `go build -o blis main.go`
- **CLI flags (experiment knobs):**
  - `--tp N` — tensor parallelism (cmd/root.go:974)
  - `--num-instances N` — cluster instance count (cmd/root.go:980)
  - `--scheduler {fcfs,sjf}` — scheduling policy (cmd/root.go:791)
  - `--max-num-running-reqs N` — max concurrent batch size (cmd/root.go:964)
  - `--total-kv-blocks N` — KV cache block count per instance (cmd/root.go:963)
  - `--block-size-in-tokens N` — tokens per KV block (cmd/root.go:968)
- **Output:** `--metrics-path <path>` writes a JSON file with all metrics (cmd/root.go:2078)

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 1 --num-instances 1 --scheduler fcfs --max-num-running-reqs 128 \
  --total-kv-blocks 5000 --block-size-in-tokens 16 \
  --metrics-path results/baseline.json
```

## Baseline Validation

- **Exit code:** 0
- **Output file:** `results/baseline_probe.json`
- **Key metric:** `responses_per_sec = 5.72`, `ttft_p99_ms = 16316.5`
- **Execution time:** ~0.1 seconds

## Experimental Conditions

### Condition 1: Full space enumeration (ground truth)
All 1800 configurations evaluated to establish the true Pareto front. Used for validation only.

### Condition 2: Hierarchical search (200 evaluations)
The `search.py` script evaluates at most 200 configs using a 6-phase strategy:
1. Ceiling performance for all 15 tp/instances combos (kv=10000, maxr=256, bs=16, fcfs)
2. Cache sweep: all combos × kv={2000,3000,4000,5000} × bs=32
3. Low-cache with small blocks: all combos × kv={2000,3000} × bs=16
4. SJF scheduler for Pareto-near configs
5. Concurrency exploration (maxr sweep) for Pareto-near configs
6. Neighbor refinement for remaining budget

### Condition 3: Random baseline (200 evaluations)
200 randomly selected configs for comparison (not implemented in search.py but evaluable from full enumeration).

## Success Criteria

1. Search finds ≥80% of unique Pareto objective tuples with 200/1800 evaluations
2. ≥95% of search-returned configs are truly Pareto-optimal (precision)
3. Search completes within 3 minutes

## Constraints

- Budget: max 200 evaluations per search run
- Time: 3 minutes total wall time
- Standard library only (no numpy, scipy, etc.)
- Must generalize to different models and rates

## Prior Knowledge

This is iteration 1. No prior principles or findings exist.

Key structural discoveries from exploration:
1. **TP dominance**: Higher TP is strictly better for throughput at same GPU count (tp=8,i=1: 32 rps vs tp=1,i=8: 12 rps at 8 GPUs)
2. **Effective cache equivalence**: kv×bs determines effective cache. (kv=2000,bs=32) ≡ (kv=4000,bs=16) in performance
3. **maxr=256 always plateaus with 512**: 100% of configs show identical performance at maxr=256 vs 512
4. **Scheduler negligible**: avg rps difference between fcfs/sjf is +0.61%, max 13.6% (only in degraded regimes)
5. **Plateau equivalence**: 124 Pareto configs map to only 35 unique performance levels
