# Problem Framing: BLIS Configuration Space Pareto Front

## Research Question

What is the structure of the BLIS 6-knob configuration space's Pareto front (which knobs matter, which do not, what are the trade-offs), and can a search algorithm find a near-complete Pareto front with at most 200 evaluations out of 1800 total configurations?

The configuration space is defined by 6 knobs:
- `--tp` ∈ {1, 2, 4, 8} — tensor parallelism degree
- `--num-instances` ∈ {1..8/tp} — number of serving instances (constrained: tp × instances ≤ 8)
- `--scheduler` ∈ {fcfs, sjf} — scheduling policy
- `--max-num-running-reqs` ∈ {32, 64, 128, 256, 512} — max concurrent batch size
- `--total-kv-blocks` ∈ {2000, 3000, 4000, 5000, 7500, 10000} — KV cache capacity
- `--block-size-in-tokens` ∈ {16, 32} — tokens per KV block

Four objectives: maximize `responses_per_sec`, minimize `ttft_p99_ms`, minimize GPU count (tp × instances), minimize `total_kv_blocks`.

Key source files:
- `cmd/root.go:964` — `--max-num-running-reqs` flag definition (default 256)
- `cmd/root.go:585` — KV cache auto-calculation logic
- `sim/config.go:10-11` — `TotalKVBlocks` and `BlockSizeTokens` in `KVCacheConfig`
- `sim/metrics.go:127` — `ResponsesPerSec` computation

## System Interface

- **Build command:** `go build -o blis main.go`
- **Run command:** `./blis run` with configuration flags
- **Metrics output:** `--metrics-path <file.json>` writes a JSON dict with cluster-level aggregated metrics including `responses_per_sec`, `ttft_p99_ms`, `e2e_p99_ms`, `preemption_count`, `dropped_unservable`, `completed_requests`

**Code evidence:**
- `cmd/root.go:2078` — `--metrics-path` flag definition
- `cmd/root.go:1768` — `SaveResults()` call with metricsPath
- `cmd/root.go:964` — `--max-num-running-reqs` defined with default 256
- `sim/config.go:10` — `TotalKVBlocks int64` field
- `sim/config.go:11` — `BlockSizeTokens int64` field

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 --max-num-scheduled-tokens 4096 \
  --long-prefill-token-threshold 0 --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 2 --num-instances 2 --scheduler fcfs --max-num-running-reqs 128 \
  --total-kv-blocks 5000 --block-size-in-tokens 16 \
  --metrics-path results/baseline.json
```

## Baseline Validation

- **Exit code:** 0
- **Output file:** `results/probes/baseline.json` — JSON dict with cluster-level metrics
- **Key metrics:** `responses_per_sec=16.28`, `ttft_p99_ms=39.18`, `preemption_count=0`, `completed_requests=200`
- **Wall time:** ~0.1-0.3 seconds per evaluation

## Experimental Conditions

### Condition 1: h-main — Adaptive search algorithm
The primary deliverable is a Python script `search.py` that implements a two-phase adaptive search:
- Phase 1 (40% budget): Structured sampling across (tp, num_instances) tiers with varied resource levels
- Phase 2 (60% budget): Iterative neighbor expansion from current Pareto front

The script is evaluated by running:
```bash
python3 search.py --model qwen/qwen3-14b --rate 100 --budget 200 --seed 42 --out final/pareto_results.json
```

### Condition 2: h-dose-response — KV blocks effect on TTFT
Vary `--total-kv-blocks` across {2000, 3000, 4000, 5000, 7500, 10000} with fixed tp=2, num_instances=2, scheduler=fcfs, max_run=128, block_size=16 to characterize the threshold-saturation shape.

## Success Criteria

1. The search algorithm finds a Pareto front covering all reachable GPU count tiers (1-8 GPUs) within 200 evaluations
2. The Pareto front includes configs with both high throughput (rps > 30) and low resource usage (1 GPU, low KV)
3. The algorithm completes in under 3 minutes wall time
4. The space structure analysis correctly identifies which knobs dominate (GPU count, KV blocks threshold) and which are negligible (scheduler, block_size under sufficient resources)

## Constraints

- Budget: at most 200 BLIS evaluations per search run
- Wall time: under 3 minutes total
- Python 3 standard library only (no numpy, scipy, etc.)
- Fixed flags per campaign specification (model, hardware, rate, etc.)
- Must work with different `--model`, `--rate`, `--seed` values

## Prior Knowledge

This is iteration 1. No prior principles exist.

Key empirical findings from 39 probe runs:
1. GPU count (tp × instances) is the dominant throughput factor — roughly linear scaling from 1→8 GPUs
2. Higher TP with single instance gives better per-request compute but suffers queuing; multiple lower-TP instances give better TTFT through parallelism
3. KV blocks exhibit threshold behavior: below a tier-dependent threshold (~5000 for tp=2,i=2), preemptions cause TTFT to spike 100-250×
4. max_num_running_reqs has a similar threshold: below ~128 for most tiers, queuing delays dominate
5. Scheduler (fcfs vs sjf) and block_size (16 vs 32) are negligible when resources are sufficient; block_size=32 slightly helps under cache pressure
