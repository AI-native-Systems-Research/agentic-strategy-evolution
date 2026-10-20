# Problem Framing — Iteration 2

## Research Question

Can an improved Pareto search algorithm — informed by iter-1's structural discoveries (RP-1 through RP-4) — achieve ≥92% coverage of the true 4-objective Pareto front within 200 evaluations of the BLIS 6-knob configuration space?

Iter-1 established that the current `search.py` achieves 84.6% coverage (22/26 reference Pareto configs) with 200 evaluations. The 4 missed configs are at high-GPU topologies (tp=8/inst=1 and tp=4/inst=2) where mid-range `total_kv_blocks` values (3000, 4000) are Pareto-optimal but the search's Phase 2 (cache minimization) skipped them. The core mechanism: Phase 2 searches from low-kv upward and stops at the first ceiling match, missing intermediate kv values that are Pareto-optimal due to lower resource cost.

Key code files:
- `search.py` — the search algorithm deliverable (373 lines, 5-phase strategy)
- `cmd/run.go` — CLI flag definitions for BLIS run command
- `sim/kvcache/` — KV block allocation and preemption logic

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags relevant to experiment:** `--tp`, `--num-instances`, `--scheduler`, `--max-num-running-reqs`, `--total-kv-blocks`, `--block-size-in-tokens`, `--metrics-path` (JSON output), `--model`, `--rate`, `--seed`
- **Code evidence:**
  - `cmd/run.go` — all 6 knob flags defined via cobra flag registration
  - `sim/kvcache/kvcache.go` — KV block allocation/preemption logic
  - `sim/scheduler.go` — FCFS and SJF scheduling implementations
- **Native output:** `--metrics-path <path>` writes JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 4 --num-instances 2 --scheduler fcfs --max-num-running-reqs 256 \
  --total-kv-blocks 5000 --block-size-in-tokens 32 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Exit code 0. Output: `responses_per_sec=26.78`, `ttft_p99_ms=29.57`, `preemption_count=0`. File written at `results/baseline.json`.

## Experimental Conditions

### Reference Pareto front (ground truth)
Already computed: 180-config exhaustive evaluation of (15 topologies × 6 kv × 2 bs) with fcfs, maxrun=256. Produces a 26-config Pareto front. The reference data is at `/tmp/reference_pareto.json` and `/tmp/reference_all.json`.

Key structural findings from reference:
- **Max useful kv_blocks = 5000**: kv=5000 and kv=10000 produce byte-identical results for ALL 15 topologies (at bs=32). kv=7500 and kv=10000 are NEVER Pareto-optimal.
- **bs=32 dominates**: Only 1 of 26 Pareto configs uses bs=16, and it's dominated by the identical bs=32 config.
- **50% are preemption-regime**: 13/26 Pareto configs have preemption_count > 0. These trade TTFT for lower kv_blocks cost.
- **Pareto kv values are {2000, 3000, 4000, 5000}** only.

### h-main: Improved search algorithm
Modify `search.py` to use a 4-phase strategy:
1. **Phase 1 — Ceiling + cheapest scan** (30 evals): For each of 15 topologies, test kv=5000/bs=32 (ceiling) AND kv=2000/bs=32 (cheapest effective config). This identifies both the performance ceiling and whether the topology has a preemption regime.
2. **Phase 2 — Boundary mapping** (adaptive, ≤45 evals): For topologies with preemptions at kv=2000, test kv=3000 and kv=4000 to map the preemption boundary. For topologies without preemptions, skip. This covers the mid-range kv values that iter-1's search missed.
3. **Phase 3 — Sensitivity testing** (≤45 evals): For current Pareto candidates, test maxrun∈{32, 64, 128}, sjf, and bs=16 at kv=2000 to check for additional Pareto points.
4. **Phase 4 — Strategic fill** (remaining ≤80 evals): Explore kv=7500, kv=10000, remaining bs=16 combos, and (topology, kv, bs) combinations not yet tested, prioritizing topologies with existing Pareto candidates.

### h-dose-response: Budget-coverage relationship
Run the improved search at 4 budget levels: 50, 100, 150, 200. Measure Pareto coverage at each. Expected shape: saturating — large coverage gains from 50→100 as core topologies are mapped, diminishing returns 150→200 as sensitivity testing adds few new Pareto points.

## Success Criteria

- **h-main**: Improved search achieves ≥92% Pareto coverage (≥24/26 reference configs) within 200 evaluations. This is a directional improvement over iter-1's 84.6% (22/26).
- **h-dose-response**: Coverage-vs-budget curve follows saturating shape (coverage at budget=100 ≥ 80% of coverage at budget=200).

## Constraints

- Budget cap: 200 evaluations per search run
- Wall time cap: 3 minutes per search run
- search.py must use Python 3 standard library only
- Fixed flags per campaign specification
- No exhaustive enumeration of the 1800-config full space

## Prior Knowledge

- **RP-1**: KV cache has saturating effect (threshold at ~160k effective tokens for bs=32). Verified: kv=5000/bs=32 is sufficient ceiling for ALL topologies.
- **RP-2**: TP outperforms instance parallelism. Verified: tp=8/inst=1 (32 rps) >> tp=1/inst=8 (11.9 rps).
- **RP-3**: Iter-1 search found 84.6% coverage (not 41% as originally reported — the search.py was improved after findings). Remaining gap: mid-range kv at high-GPU topologies.
- **RP-4**: Topology selection > GPU count. Verified: tp=4/inst=1 (21.7 rps) > tp=1/inst=8 (11.9 rps) despite same 8 GPUs.
