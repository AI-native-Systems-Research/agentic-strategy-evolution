# Handoff Snapshot — Iteration 1

## Goal

Find and fix the metrics bug where `total_output_tokens` and `tokens_per_sec` are inflated when KV cache preemptions occur. Apply the fix, verify it works, and add a regression test.

## Key Discoveries

1. **Root cause confirmed:** `sim/batch_formation.go:232` resets `ProgressIndex = 0` on preemption, causing the request to re-enter decode and re-increment `TotalOutputTokens` at `sim/simulator.go:647`. The same output tokens are counted multiple times (once per scheduling round).

2. **Inflation scales with preemption count:** Pre-fix measurements:
   - 0 preemptions (60k blocks): `total_output_tokens = 105082`
   - 72 preemptions (6k blocks): `total_output_tokens = 106385` (+1303)
   - 265 preemptions (600 blocks): `total_output_tokens = 114630` (+9548)

3. **Three related metrics are affected by preemption double-counting:**
   - `TotalOutputTokens` (directly reported, user's complaint)
   - `TTFTSum` (incremented each time prefill completes — not checked by TTFTSet guard)
   - `ITL` array (not reset, so entries from preempted rounds accumulate)

4. **Fix approach:** Store `OutputTokensGenerated` in `PreemptedRequest` before `ProgressIndex` reset; subtract in simulator's preemption handler. Also reset `TTFTSet` and `ITL` on preemption.

5. **Post-fix verification:** `total_output_tokens = 105082` for ALL KV cache sizes (600, 6000, 60000 blocks), confirming the fix eliminates the inflation.

6. **All existing tests pass** including golden dataset tests and all sim/ package tests.

## System Interface

- **Build:** `go build -o blis main.go`
- **Run baseline:** `./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000`
- **Output format:** JSON to stdout after `=== Simulation Metrics ===` header
- **Baseline result:** `total_output_tokens = 105082` with 0 preemptions

## Code Map

- `sim/batch_formation.go:42-44` — `PreemptedRequest` struct. Added `OutputTokensGenerated` field.
- `sim/batch_formation.go:201-244` — `preemptForTokens()`. Line 232: `ProgressIndex = 0` reset. New code computes `OutputTokensGenerated` before the reset.
- `sim/simulator.go:584-598` — Preemption metrics handler in `scheduleBatch()`. New code subtracts `OutputTokensGenerated`, resets `TTFTSet` and `ITL`.
- `sim/simulator.go:647` — `TotalOutputTokens++` in decode loop of `executeBatchStep()`.
- `sim/simulator.go:651-656` — TTFT recording (affected by double-counting when TTFTSet not checked).
- `sim/simulator_test.go:2601+` — New regression test `TestSimulator_PreemptionDoesNotInflateTotalOutputTokens`.

## Code Targets

### h-main arm: Fix double-counting
1. `sim/batch_formation.go:42-44` — Add `OutputTokensGenerated int64` to `PreemptedRequest`
2. `sim/batch_formation.go:217-219` — Compute output tokens before ProgressIndex reset in `preemptForTokens`
3. `sim/simulator.go:584-588` — Subtract output tokens and reset TTFTSet/ITL in preemption handler
4. `sim/simulator_test.go` — Add regression test

## What I Tried That Didn't Work

- Nothing failed; the exploration path was direct. The bug was identified from the first code read.

## What I Excluded and Why

- **E2E latency double-counting**: ITL duplication also inflates E2E latency (`lat = FirstTokenTime + itlSum + overhead`). The ITL reset in the fix addresses this. Not explicitly tested because the user's report focused on `total_output_tokens`.
- **Per-request TTFT accuracy**: `RequestTTFTs[req.ID]` is overwritten (not accumulated) so per-request TTFT is correct. Only the aggregate `TTFTSum` was double-counted.
- **Cluster-level metrics**: `sim/cluster/cluster.go:1274` aggregates `TTFTSum` across instances. The per-instance fix propagates correctly.

## Evolution of Thinking

Initially considered counting output tokens at completion time instead of incrementally. Rejected because: (1) it would miss in-flight requests at simulation end, (2) it's a larger change. The subtraction-at-preemption approach is minimal and correct for all cases.

## Current Status

- **Validated:** Fix works for 0, 72, and 265 preemptions. All tests pass. Regression test added.
- **Uncertain:** Whether `AllITLs` (used for percentile computation) is also affected — ITL reset should fix it but not explicitly tested at the aggregate level.
- **Suggested next:** If further investigation needed, examine whether the ITL percentile metrics (P90, P95, P99) are now correct under preemption, and whether cluster-level TTFTSum aggregation handles the fix correctly.

## Warnings & Constraints

- The `cmd` package has a pre-existing test failure in `TestFetchHFConfig_Success` (httptest server panic). This is unrelated to the fix.
- The golden dataset tests in `sim/simulator_test.go:TestSimulator_GoldenDataset` passed, meaning the fix doesn't change behavior for test cases without preemptions.
