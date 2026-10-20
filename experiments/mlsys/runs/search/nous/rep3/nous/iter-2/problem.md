# Problem Framing — Iteration 2

## Research Question

**Can we validate and improve the BLIS configuration-space search algorithm's quality by measuring it against exhaustive ground truth, and does explicit block_size=32 exploration improve Pareto recall?**

Iteration 1 established that a two-phase adaptive search finds 44–80 non-dominated configs from 200 evaluations, covering all 8 GPU tiers. But "near-complete" was never quantified against ground truth. This iteration:
1. Runs exhaustive enumeration (all 1800 configs) to establish the true Pareto front.
2. Measures the iter-1 search's Pareto recall against truth.
3. Tests whether adding balanced block_size={16,32} coverage in Phase 1 improves recall.
4. Validates that the structured search outperforms random sampling.

**Key finding from exploration:** block_size=32 is NOT negligible on the Pareto front. It shifts the KV preemption threshold to substantially lower block counts because total cache capacity is `kv_blocks × block_size_tokens`. At tp=2,ni=2: kv=3000,bs=32 (96K tokens cache) achieves 0 preemptions and rps=16.28, while kv=3000,bs=16 (48K tokens) has 108 preemptions and rps=13.53. The true Pareto front preferentially includes bs=32 configs with lower kv_blocks. The iter-1 search.py has only 3 of 78 Phase 1 configs (3.8%) using bs=32, covering just 3 of 15 GPU tiers — the remaining 12 tiers discover bs=32 only through Phase 2 neighbor expansion, which requires multi-step chains.

**Relevant source files:**
- `sim/config.go:10-11` — `TotalKVBlocks` and `BlockSizeTokens` in `KVCacheConfig` (per-instance)
- `sim/kvstore.go` — KV cache allocation using block-granularity; total cache tokens = `TotalKVBlocks * BlockSizeTokens`
- `cmd/root.go:964` — `--max-num-running-reqs` default (256)
- `cmd/root.go:2078` — `--metrics-path` flag definition
- `sim/metrics.go:127` — `ResponsesPerSec` computation

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags relevant to experiment:**
  - `--tp` (tensor parallelism): `cmd/root.go:908` — parsed as int
  - `--num-instances`: `cmd/root.go:918` — parsed as int
  - `--scheduler`: `cmd/root.go:936` — `fcfs` or `sjf`
  - `--max-num-running-reqs`: `cmd/root.go:964` — parsed as int, default 256
  - `--total-kv-blocks`: `cmd/root.go:970` — parsed as int
  - `--block-size-in-tokens`: `cmd/root.go:976` — parsed as int
  - `--metrics-path`: `cmd/root.go:2078` — native output flag, writes JSON dict
  - `--seed`: `cmd/root.go:954` — RNG seed for deterministic output (INV-6)
- **Code evidence:** All flags defined in `cmd/root.go` via cobra. Metrics written by `SaveResults()` at `cmd/root.go:1768`.
- **Native output:** `--metrics-path <path>` writes a JSON dict with keys `responses_per_sec`, `ttft_p99_ms`, `e2e_p99_ms`, `preemption_count`, `completed_requests`, `dropped_unservable`, etc.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin \
  --gpu-memory-utilization 0.9 \
  --tp 2 --num-instances 2 --scheduler fcfs --max-num-running-reqs 128 \
  --total-kv-blocks 5000 --block-size-in-tokens 16 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Exit code 0. Output file `results/baseline.json` contains:
- `responses_per_sec`: 16.28
- `ttft_p99_ms`: 39.18
- `completed_requests`: 200
- `preemption_count`: 0
- `dropped_unservable`: 0

Verified at 0.22s wall time.

## Experimental Conditions

### Ground Truth: Exhaustive Enumeration
Run all 1800 valid configurations at rate=100 for seeds {42, 123, 999}. Compute the true 4-objective Pareto front for each seed. This is the reference against which search quality is measured.

### h-main baseline (v1 search): Iter-1 search.py
Run the existing search.py (unchanged from iter-1) with budget=200 at rate=100 for seeds {42, 123, 999}. Measure Pareto recall against exhaustive ground truth.

### h-main treatment (v2 search): Improved search.py with bs=32 coverage
Modify search.py Phase 1 resource_profiles to include block_size=32 variants at threshold-appropriate kv_blocks values. Run with budget=200 at rate=100 for seeds {42, 123, 999}. Measure Pareto recall against exhaustive ground truth.

Code change intent: In search.py, expand the `resource_profiles` list to include 4 additional block_size=32 entries alongside the existing block_size=16 entries, with kv_blocks values adjusted downward to reflect the lower threshold when block_size doubles the tokens per block. Also expand the block_size=32 tier probes from 3 tiers to all 15 tiers.

### h-control-negative: Random sampling
Uniformly sample 200 random configs from the 1800-config space for seeds {42, 123, 999}. Compute Pareto front. Measure recall against exhaustive ground truth.

## Success Criteria

1. **h-main**: The improved search (v2) achieves strictly higher Pareto recall (fraction of true Pareto metric tuples found) than iter-1 search (v1) across all 3 seeds.
2. **h-control-negative**: Random sampling achieves lower Pareto recall than both v1 and v2 structured searches across all 3 seeds.
3. **Quality metric**: Both v1 and v2 Pareto recall values will be reported with their ratio to the evaluation fraction (200/1800 = 11.1%), demonstrating search efficiency.

## Constraints

- Each search.py run must complete within 3 minutes (180s wall time).
- Budget = 200 evaluations per search run.
- search.py must use Python 3 standard library only.
- Do not exhaustively enumerate the space within search.py.
- Fixed campaign flags must match campaign.yaml exactly.

## Prior Knowledge

- **RP-1** (high confidence): KV cache threshold is binary. Below threshold: preemptions spike TTFT by 100-250×. Above: TTFT = compute-only prefill latency.
- **RP-2** (high confidence): GPU count is dominant throughput factor; within each tier, KV blocks and max_running_reqs have threshold-gated effects.
- **RP-3** (high confidence): Two-phase search finds a Pareto front covering all GPU tiers in 200 evaluations (11% coverage).

**Refinement from iter-2 exploration (new):**
- The KV threshold is in total cache tokens (kv_blocks × block_size), not just blocks. kv=3000,bs=32 (96K tokens) crosses the threshold at tp=2,ni=2 where kv=3000,bs=16 (48K tokens) does not.
- block_size=32 is NOT negligible on the Pareto front — it enables lower-kv Pareto-optimal configs.
- The threshold also varies by num_instances: multi-instance configs (e.g., tp=1,ni=4) have much lower per-instance thresholds because requests are spread across instances via round-robin routing.
- The iter-1 search.py covers only 3 of 15 GPU tiers with bs=32 in Phase 1, relying on Phase 2's multi-step neighbor expansion to discover the rest.
