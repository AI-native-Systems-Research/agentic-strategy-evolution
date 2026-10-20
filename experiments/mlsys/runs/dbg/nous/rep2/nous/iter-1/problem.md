# Problem Framing: TotalOutputTokens Inflation Under KV Preemption

## Research Question

When KV cache is small enough that requests get preempted, does `total_output_tokens` in BLIS metrics output inflate beyond the correct value? If so, what is the root cause and correct fix?

**Root cause identified:** In `sim/batch_formation.go:preemptForTokens` (line 232), a preempted request's `ProgressIndex` is reset to 0, causing it to re-enter prefill+decode from scratch. However, `sim/simulator.go:647` already incremented `TotalOutputTokens` for each output token generated before preemption. On re-schedule, the same tokens are counted again.

**Key source files:**
- `sim/simulator.go:647` — `TotalOutputTokens++` in decode loop
- `sim/batch_formation.go:232` — `ProgressIndex = 0` on preemption
- `sim/batch_formation.go:234` — `delete(ctx.ComputedTokens, ...)` resets computed token tracking
- `sim/simulator.go:584-588` — preemption metrics recording (where the fix subtracts already-counted tokens)

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags:**
  - `--model` — model name (code: `cmd/root.go`)
  - `--rate` — request arrival rate (code: `cmd/root.go`)
  - `--num-requests` — total requests to simulate (code: `cmd/root.go`)
  - `--seed` — RNG seed for determinism (code: `cmd/root.go`)
  - `--total-kv-blocks` — KV cache capacity in blocks (code: `cmd/root.go`)
- **Output:** JSON metrics printed to stdout after `=== Simulation Metrics ===` header
- **Metrics of interest:** `total_output_tokens`, `tokens_per_sec`, `preemption_count`, `completed_requests`

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000
```

## Baseline Validation

- Exit code: 0
- Output: JSON to stdout
- Key metric: `total_output_tokens = 105082` with `preemption_count = 0`

## Experimental Conditions

### Condition 1: Baseline (no preemptions)
```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000
```
Expected: `total_output_tokens = 105082`, `preemption_count = 0`

### Condition 2: Tight KV cache (heavy preemptions) — BEFORE fix
```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600
```
Observed (pre-fix): `total_output_tokens = 114630`, `preemption_count = 265`
Inflation: 114630 - 105082 = 9548 tokens (9.1% over-count)

### Condition 3: Tight KV cache (heavy preemptions) — AFTER fix
Same command as Condition 2, with code changes applied.
Expected: `total_output_tokens = 105082` (matches baseline)

### Code Changes (the fix)

**File: `sim/batch_formation.go`**
- Add `OutputTokensGenerated int64` field to `PreemptedRequest` struct
- In `preemptForTokens`, before resetting `ProgressIndex`, compute how many output tokens were already generated and store in `PreemptedRequest.OutputTokensGenerated`

**File: `sim/simulator.go`**
- In `scheduleBatch`, when processing preempted requests, subtract `OutputTokensGenerated` from `TotalOutputTokens`
- Reset `TTFTSet = false` on preempted requests (fixes TTFTSum double-counting)
- Reset `ITL = nil` on preempted requests (fixes ITL entry duplication)

## Success Criteria

1. After fix, `total_output_tokens` with preemptions == `total_output_tokens` without preemptions (for same workload, all requests completing)
2. All existing tests pass (`go test ./sim/...`)
3. New regression test `TestSimulator_PreemptionDoesNotInflateTotalOutputTokens` passes

## Constraints

- Minimal change: only fix the double-counting, don't restructure metrics
- Don't break INV-1 (request conservation) or INV-6 (determinism)
- All existing golden dataset tests must continue to pass

## Prior Knowledge

This is iteration 1. No prior principles.
