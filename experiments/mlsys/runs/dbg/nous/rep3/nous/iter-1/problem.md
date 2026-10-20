# Problem Framing: TotalOutputTokens Double-Counting on Preemption

## Research Question

When the KV cache is small enough to trigger preemptions, `total_output_tokens` and `tokens_per_sec` are inflated in the simulation output. Is this a real bug, what is the root cause, and what is the correct fix?

The mechanism under study is implemented in:
- `sim/batch_formation.go:preemptForTokens` (lines 201-244) — preemption logic that resets `ProgressIndex` to 0
- `sim/simulator.go:executeBatchStep` (lines 635-657) — decode loop that increments `TotalOutputTokens++`
- `sim/simulator.go:scheduleBatch` (lines 551-601) — where preemption results are processed

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags relevant to the experiment:**
  - `--model`: Model identifier (code: `cmd/run.go`)
  - `--rate`: Request arrival rate (code: `cmd/run.go`)
  - `--num-requests`: Number of requests (code: `cmd/run.go`)
  - `--seed`: RNG seed for determinism (code: `cmd/run.go`)
  - `--total-kv-blocks`: KV cache capacity in blocks (code: `cmd/run.go`, parsed into `SimConfig.KVCacheConfig`)
- **Code evidence:**
  - `sim/simulator.go:647` — `sim.Metrics.TotalOutputTokens++` in decode phase
  - `sim/batch_formation.go:232` — `preemptedRequest.ProgressIndex = 0` during preemption
  - `sim/batch_formation.go:233` — `ctx.KVCache.ReleaseKVBlocks(preemptedRequest)` frees blocks
  - `sim/batch_formation.go:234` — `delete(ctx.ComputedTokens, preemptedRequest.ID)` clears computed state
  - `sim/metrics.go:126` — `tokens_per_sec` computed from `TotalOutputTokens`
- **Output format:** JSON to stdout (deterministic), diagnostics to stderr

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000
```

## Baseline Validation

- Exit code: 0
- Output: JSON to stdout with `total_output_tokens: 105082`, `preemption_count: 0`, `tokens_per_sec: 5629.82`
- This serves as ground truth — no preemptions means no double-counting.

## Experimental Conditions

### Condition 1: Buggy behavior (before fix) — small KV cache
```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600
```
**Before fix:** `total_output_tokens: 114630`, `preemption_count: 265` — inflated by 9,548 tokens (9.1%) due to double-counting.

### Condition 2: Fixed behavior — code change
**Intent:** In `sim/batch_formation.go`, compute the number of decode tokens generated before preemption (`max(0, ProgressIndex - len(InputTokens))`) and store it in a new `OutputTokensLost` field on `PreemptedRequest`. Also clear the `ITL` slice on preemption. In `sim/simulator.go`, subtract `OutputTokensLost` from `TotalOutputTokens` for each preempted request.

### Condition 3: Regression test
Add `TestPreemption_TotalOutputTokens_NoDoubleCount` to `sim/simulator_test.go` that runs the same workload with large vs small KV cache and asserts `TotalOutputTokens` is identical.

## Success Criteria

- After fix: `total_output_tokens` is identical (105,082) for both `--total-kv-blocks 600` (265 preemptions) and `--total-kv-blocks 60000` (0 preemptions)
- All existing tests pass (`go test ./sim/...`)
- Regression test passes and validates the invariant

## Constraints

- Minimal change — only touch the preemption path and metrics accounting
- Do not break determinism (INV-6)
- Do not break request conservation (INV-1)

## Prior Knowledge

This is iteration 1. No active principles yet.
