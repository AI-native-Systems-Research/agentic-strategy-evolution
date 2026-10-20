# Problem Framing — Iteration 2

## Research Question

Is the preemption-induced `total_output_tokens` inflation in BLIS a real bug, and does the iter-1 fix (subtracting `OutputTokensLost` from `TotalOutputTokens` on preemption + clearing ITL slices) hold robustly across multiple seeds and KV cache pressure levels?

Iter-1 confirmed the root cause in a single-seed setting:
- **Root cause file:** `sim/batch_formation.go` — `preemptForTokens()` (line 238) resets `ProgressIndex=0` without decrementing `TotalOutputTokens`.
- **Counting site:** `sim/simulator.go` — `executeBatchStep()` (line 650) increments `TotalOutputTokens++` per decode step.
- **Accounting site:** `sim/simulator.go` — `scheduleBatch()` (line 590) now subtracts `p.OutputTokensLost` for each preempted request.
- **ITL fix:** `sim/batch_formation.go` (line 239) clears `ITL[:0]` on preemption.

Iter-2 (real mode) validates the fix at full scope: 5 seeds × 3 cache sizes (high/medium/zero preemption).

## System Interface

- **Build:** `go build -o blis main.go`
- **CLI flags:**
  - `--model <model>`: HuggingFace model path (`sim/cluster/config.go` parses it)
  - `--rate <float>`: Request arrival rate per second (`cmd/run.go`)
  - `--num-requests <int>`: Total requests to inject (`cmd/run.go`)
  - `--seed <int>`: RNG seed for determinism (`cmd/run.go`)
  - `--total-kv-blocks <int>`: Total KV cache blocks per instance (`cmd/run.go` → `sim/SimConfig.KVCacheConfig`)
- **Code evidence:**
  - `sim/batch_formation.go:42-45` — `PreemptedRequest` struct with `OutputTokensLost int64`
  - `sim/batch_formation.go:219` — `outputTokensLost` computed before ProgressIndex reset
  - `sim/batch_formation.go:238-239` — ProgressIndex reset + ITL clearing
  - `sim/simulator.go:590` — `sim.Metrics.TotalOutputTokens -= int(p.OutputTokensLost)` 
  - `sim/simulator.go:650` — `sim.Metrics.TotalOutputTokens++` (the counting site)
  - `sim/metrics.go:21` — `TotalOutputTokens int` field
  - `sim/metrics.go:126` — `tokens_per_sec = TotalOutputTokens / vllmRuntime`
- **Output:** JSON to stdout (deterministic), diagnostics to stderr

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000
```

## Baseline Validation

Ran the baseline command. Exit code 0. Output:
- `total_output_tokens: 105082`
- `preemption_count: 0`
- `tokens_per_sec: 5629.82`

## Experimental Conditions

### h-main: Multi-seed validation of the fix under high preemption

For each of 5 seeds (42, 123, 456, 789, 1337):
1. Run with `--total-kv-blocks 600` (high preemption, ~265–348 preemptions)
2. Run with `--total-kv-blocks 60000` (no preemption, ground truth)
3. Assert `total_output_tokens` is identical between the two runs

The fix (already applied) consists of the code changes from iter-1's h-main patch:
- `sim/batch_formation.go`: `OutputTokensLost` field + computation + ITL clearing
- `sim/simulator.go`: subtraction in `scheduleBatch`
- `sim/simulator_test.go`: regression test

### h-control-negative: Intermediate cache (moderate preemption) also correct

Same 5 seeds with `--total-kv-blocks 6000` (~72 preemptions at seed 42). Validates the fix is correct even at moderate preemption rates where some requests are preempted during prefill (OutputTokensLost should be 0) vs decode (OutputTokensLost > 0).

## Success Criteria

1. **Exact match:** For every seed and every cache size, `total_output_tokens` equals the zero-preemption ground truth for that seed.
2. **Regression test passes:** `TestPreemption_TotalOutputTokens_NoDoubleCount` passes (14 preemptions in unit-test regime).
3. **No existing test breakage:** `go test ./sim/...` exits 0.

## Constraints

- The fix must not alter output in zero-preemption runs (INV-6 determinism).
- The pre-existing `cmd/TestFetchHFConfig_Success` failure is unrelated (httptest server issue) and excluded.

## Prior Knowledge

- **RP-1 (active):** Any code path that resets per-request progress state must reverse all cumulative metrics. Confirmed by iter-1 with 9.1% inflation at 265 preemptions.
- **RP-2 (active):** Per-request slice metrics (ITL) must be cleared on preemption. Confirmed by iter-1.
- **Iter-1 h-main:** CONFIRMED — fix produces total_output_tokens=105082 at seed 42 across 600/6000/60000 blocks.
- **Iter-1 h-control-negative:** CONFIRMED — large-cache output byte-identical with/without fix.
