# Problem Framing: BLIS Configuration Space Pareto Front

## Research Question

What is the structure of the BLIS configuration space's 4-objective Pareto front (maximize `responses_per_sec`, minimize `ttft_p99_ms`, minimize GPU count, minimize `total_kv_blocks`), and can a search algorithm find a near-complete Pareto front within 200 evaluations?

The 6-knob configuration space spans 1800 total configurations across GPU topology (tp × num_instances ≤ 8), scheduler policy, concurrency limits, KV cache size, and block granularity. The key mechanism is the interaction between GPU parallelism (throughput), KV cache capacity (preemption avoidance), and concurrency limits (queuing behavior), implemented in:
- `sim/scheduler.go` — FCFS and SJF scheduling policies
- `sim/kvcache/` — KV cache block allocation and preemption
- `sim/cluster/` — multi-instance routing and load distribution
- `cmd/run.go` — CLI flag parsing and simulation orchestration

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags relevant to experiment:**
  - `--tp` (tensor parallelism degree) — parsed in `cmd/run.go`
  - `--num-instances` (cluster instances) — parsed in `cmd/run.go`
  - `--scheduler` (fcfs, sjf) — parsed in `cmd/run.go`
  - `--max-num-running-reqs` (concurrency limit) — parsed in `cmd/run.go`
  - `--total-kv-blocks` (KV cache blocks per instance) — parsed in `cmd/run.go`
  - `--block-size-in-tokens` (tokens per block) — parsed in `cmd/run.go`
  - `--metrics-path` (JSON output file) — writes cluster-level MetricsOutput JSON
- **Code evidence:** All flags defined in `cmd/run.go` via cobra flag bindings.
- **Native output:** `--metrics-path <path>` writes JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `dropped_unservable`, and per-request arrays.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 4 --num-instances 2 --scheduler fcfs --max-num-running-reqs 128 \
  --total-kv-blocks 5000 --block-size-in-tokens 16 \
  --metrics-path results/baseline.json
```

## Baseline Validation

- **Exit code:** 0
- **Output file:** `results/probes/baseline.json` (cluster-level JSON)
- **Key metric:** `responses_per_sec = 26.78`, `ttft_p99_ms = 29.57`
- **Observation:** tp=4, inst=2 with 5000 blocks × 16 tokens is a comfortable config with zero preemptions.

## Experimental Conditions

### Condition 1: Full grid exploration (540 evals)
Systematically evaluate all 15 GPU topologies × 2 schedulers × 3 maxrun values × 3 kv_blocks values × 2 block sizes to characterize the space.

### Condition 2: Search algorithm (200 evals)
Run `search.py` with 200-eval budget to find near-complete Pareto front using 5-phase adaptive strategy:
1. Ceiling scan: evaluate each GPU topology with generous cache
2. Cache minimization: binary search for minimum viable kv_blocks per topology
3. maxrun sensitivity: test concurrency limit effects
4. Scheduler check: test sjf where fcfs showed stress
5. Fill: explore remaining promising configs

## Success Criteria

1. **Pareto front coverage:** Search algorithm finds ≥80% of the distinct performance tiers found by exhaustive grid (17 tiers)
2. **Budget efficiency:** Search uses ≤200 evaluations
3. **Wall time:** Search completes in <3 minutes
4. **Structural understanding:** Identify and rank all 6 knobs by importance with quantitative evidence

## Constraints

- Each BLIS evaluation takes 0.1–0.3 seconds
- Search budget: ≤200 evaluations
- GPU constraint: tp × num_instances ≤ 8
- Python 3 standard library only for search.py
- Script must accept --model, --rate, --budget, --seed, --out flags

## Prior Knowledge

This is the first iteration. No active principles exist.

Key findings from exploration:
- **Scheduler (fcfs vs sjf):** Nearly irrelevant — 0.19 rps mean range across all configs
- **GPU topology:** Dominates all other knobs — max RPS ranges from 7.0 (1 GPU) to 32.0 (8 GPUs)
- **KV cache:** Threshold effect — below critical capacity, preemptions cause severe TTFT degradation; above, no effect
- **block_size=32 dominates 16:** Doubles effective cache capacity at same block count
- **max_num_running_reqs:** Saturates above 128-256 for most topologies
