# Problem Framing — Iteration 2

## Research Question

Can an improved search algorithm that adaptively explores scheduler×concurrency interactions in cache-degraded regimes close the coverage gap from iter-1 (82.9% → ≥90% unique Pareto tuple recall) while staying within 200 evaluations? Does this improved search generalize to different arrival rates (50, 200)?

**Key source files:**
- `cmd/root.go:963-980` — all 6 knob flag definitions (`--tp`, `--num-instances`, `--scheduler`, `--max-num-running-reqs`, `--total-kv-blocks`, `--block-size-in-tokens`)
- `cmd/root.go:2078` — `--metrics-path` flag for JSON output
- `sim/metrics.go:127` — `ResponsesPerSec` calculation
- `sim/metrics_utils.go:66` — `MetricsOutput` struct defining JSON output fields

## Prior Iteration Analysis

### Iter-1 Results
- Exhaustive enumeration of 1800 configs produced 124 Pareto configs → 35 unique objective tuples
- Hierarchical search achieved 82.9% recall (29/35 unique tuples) and 96.4% precision (80/83 truly Pareto) using ~200 evaluations
- Established four principles: TP dominance (RP-1), structural redundancy (RP-2), gradual cache degradation (RP-3), maxr=256 plateau (RP-4)

### Gap Analysis — 6 Missed Pareto Tuples
The 6 missed GT Pareto tuples share a clear structural pattern:

| Config | rps | ttft_p99 | gpus | kv | Key Pattern |
|--------|-----|----------|------|----|-------------|
| tp=1,ni=1,**sjf**,**maxr=128**,kv=3000,bs=32 | 6.39 | 15254 | 1 | 3000 | SJF+low-maxr in degraded cache |
| tp=1,ni=2,fcfs,**maxr=64**,kv=2000,bs=32 | 7.99 | 8202 | 2 | 2000 | Low-maxr multi-instance |
| tp=1,ni=2,**sjf**,**maxr=64**,kv=2000,bs=32 | 8.52 | 8480 | 2 | 2000 | SJF+low-maxr multi-instance |
| tp=2,ni=1,**sjf**,**maxr=128**,kv=3000,bs=32 | 11.63 | 7145 | 2 | 3000 | SJF+low-maxr in degraded cache |
| tp=4,ni=1,**sjf**,**maxr=128**,kv=3000,bs=32 | 19.57 | 3588 | 4 | 3000 | SJF+low-maxr in degraded cache |
| tp=8,ni=1,**sjf**,**maxr=128**,kv=3000,bs=32 | 29.26 | 1812 | 8 | 3000 | SJF+low-maxr in degraded cache |

**Root cause:** The iter-1 search explored scheduler and concurrency as independent refinements (Phase 4: SJF on existing Pareto configs; Phase 5: different maxr on Pareto configs). But the missed Pareto points emerge from the *interaction* of SJF × low-maxr in cache-degraded regimes. At kv=3000,bs=32 (96K tokens effective, moderate degradation), SJF+maxr=128 produces higher rps than FCFS+maxr=256 (e.g., 29.26 vs 28.64 at tp=8) by prioritizing shorter requests under preemption pressure. This is a different tradeoff point the independent exploration never reaches.

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags:** `--tp`, `--num-instances`, `--scheduler {fcfs,sjf}`, `--max-num-running-reqs`, `--total-kv-blocks`, `--block-size-in-tokens`, `--metrics-path`
- **Code evidence:**
  - `cmd/root.go:963` — `--tp` flag definition
  - `cmd/root.go:965` — `--num-instances` flag definition
  - `cmd/root.go:967` — `--total-kv-blocks` flag definition
  - `cmd/root.go:968` — `--block-size-in-tokens` flag definition (default=16)
  - `cmd/root.go:969` — `--max-num-running-reqs` flag definition
  - `cmd/root.go:791` — scheduler validation
  - `cmd/root.go:2078` — `--metrics-path` flag
- **Native output:** `--metrics-path` writes JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count` etc.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 1 --num-instances 1 --scheduler fcfs --max-num-running-reqs 256 \
  --total-kv-blocks 10000 --block-size-in-tokens 16 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Validated at rate=100: rps=7.00, ttft_p99=92.6ms, exit code 0. Validated at rate=50: rps=6.86, ttft_p99=82.2ms. Validated at rate=200: rps=7.07, ttft_p99=178.3ms. Each evaluation takes ~0.06s wall time. BLIS binary pre-built and confirmed working.

## Experimental Conditions

### h-main: Improved search with degraded-regime interaction phase
**Change from iter-1 search:** Add a new adaptive phase after the initial cache sweep that specifically explores SJF × {64, 128} at cache-degraded configurations (where Phase 2 results show >5% rps degradation from ceiling). This directly targets the structural gap: scheduler×concurrency interaction effects that only manifest under preemption pressure.

The improved `search.py` will:
1. Keep Phases 1-3 unchanged (ceiling discovery, bs=32 cache sweep, bs=16 low-kv sweep)
2. Insert Phase 2.5: For each (tp,ni) combo where Phase 2 showed degradation (rps < 95% ceiling), test SJF × {64, 128} at the degraded kv/bs values (~16-24 evals)
3. Rebalance Phases 4-6 budget accordingly

**Measurement:** Run improved search at rate=100 with budget=200, compare against existing GT (1800 configs already enumerated). Report: unique tuple recall, precision, configs found.

### h-robustness: Rate generalization at rate=50 and rate=200
**Change from baseline:** Run full enumeration (1800 configs) at rate=50 and rate=200 to produce ground truth. Then run improved search at each rate with budget=200. Compare recall.

**Measurement:** For each rate: GT Pareto count, GT unique tuples, search recall, search precision. Test whether structural assumptions (TP dominance, cache equivalence, maxr plateau) hold at different rates.

## Success Criteria

1. **h-main:** Improved search achieves ≥90% unique Pareto tuple recall at rate=100 (up from 82.9% in iter-1), with ≥95% precision, using ≤200 evaluations.
2. **h-robustness:** Improved search achieves ≥80% unique Pareto tuple recall at both rate=50 and rate=200.

## Constraints

- Budget: ≤200 BLIS evaluations per search run
- Time: ≤3 minutes per search invocation
- search.py interface: `--model`, `--rate`, `--budget`, `--seed`, `--out`
- Standard library only (no numpy, scipy, etc.)
- Must not exhaustively enumerate the space

## Prior Knowledge

- **RP-1 (TP dominance):** Higher TP monotonically improves rps/ttft at fixed GPU count. Verified at rate=100.
- **RP-2 (Structural redundancy):** 124 Pareto configs → 35 unique tuples. Hierarchical search gets 82.9% recall.
- **RP-3 (Gradual cache degradation):** Throughput stays within 25% of ceiling even at 50% cache capacity.
- **RP-4 (maxr=256 plateau):** maxr=512 always matches maxr=256 at rate=100. Below-plateau configs (maxr=32,64,128) create Pareto diversity through concurrency-limiting tradeoffs.
