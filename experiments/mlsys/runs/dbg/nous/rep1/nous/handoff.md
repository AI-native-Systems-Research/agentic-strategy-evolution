# Handoff Snapshot — Iteration 1

## Goal

Fix the double-counting of `total_output_tokens` (and `tokens_per_sec`) when KV cache preemptions occur in BLIS. The bug is confirmed, the fix is implemented and tested.

## Key Discoveries

1. **Root cause confirmed**: `sim/batch_formation.go:232` resets `ProgressIndex = 0` on preemption. `sim/simulator.go:647` increments `TotalOutputTokens` on every decode step. After rescheduling, the same output tokens are generated and counted again.
2. **Three metrics affected**: `TotalOutputTokens` (primary), `ITL` entries (appended per decode, never cleared on preemption), and `TTFTSum` (added on each prefill completion, re-added after restart). `RequestTTFTs[id]` uses map-overwrite so its final value is correct.
3. **Magnitude**: With seed 42, rate 20, 200 requests: 105082 tokens (correct) vs 114630 with 265 preemptions (9% inflation) vs 106385 with 72 preemptions (1.2% inflation).
4. **Fix verified**: After the fix, all three KV cache sizes produce identical `total_output_tokens = 105082`.
5. **All existing tests pass** (`go test ./sim/...` and `go test ./sim/cluster/...`). The `cmd/` test failure (`TestFetchHFConfig_Success`) is pre-existing and unrelated (httptest port issue).

## System Interface

- **Build:** `go build -o blis main.go`
- **Run baseline:** `./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000`
- **Output format:** JSON metrics to stdout, bracketed by `=== Simulation Metrics ===`
- **Baseline result:** `total_output_tokens = 105082` (0 preemptions)

## Code Map

- `sim/batch_formation.go:198-244` — `preemptForTokens()`: the preemption loop. **This is where ProgressIndex is reset to 0 (line 232)**. The fix adds DecodedTokens computation before the reset, and clears ITL/TTFTSet.
- `sim/batch_formation.go:41-44` — `PreemptedRequest` struct: extended with `DecodedTokens` and `HadTTFT` fields.
- `sim/simulator.go:584-588` — `scheduleBatch()` preemption processing loop: the fix subtracts DecodedTokens from TotalOutputTokens and deducts TTFTSum here.
- `sim/simulator.go:645-649` — `executeBatchStep()`: where `TotalOutputTokens++` happens per decode step. Not modified.
- `sim/simulator.go:651-656` — TTFT recording on prefill completion. Not modified (TTFTSet reset on preemption handles re-recording correctly).
- `sim/metrics.go:126` — where `tokens_per_sec` is derived from `TotalOutputTokens`. Not modified.

## Code Targets

### h-main arm changes (already implemented):
1. `sim/batch_formation.go:42-44` — Added `DecodedTokens int64` and `HadTTFT bool` to `PreemptedRequest`
2. `sim/batch_formation.go:217-225` — Compute `decodedTokens` before ProgressIndex reset; populate new fields
3. `sim/batch_formation.go:245-246` — Clear `ITL = nil` and `TTFTSet = false` on preemption
4. `sim/simulator.go:584-595` — Subtract `DecodedTokens` from `TotalOutputTokens`; deduct `TTFTSum` if `HadTTFT`
5. `sim/simulator_test.go` (end) — Regression test `TestPreemption_TotalOutputTokens_NoDoubleCount`

## What I Tried That Didn't Work

- Initial regression test with 50 KV blocks and small requests (30 input / 20 output) did not trigger preemptions — requests completed sequentially without contention.
- Had to use 30 blocks with 5 concurrent requests (64 input / 50 output arriving at time 0) to reliably trigger preemptions in unit tests.

## What I Excluded and Why

- **Per-request E2E and ITL metrics correction**: `RequestE2Es` and `RequestITLs` are map-keyed by request ID, so the final value (on completion) is correct even without explicit correction. Only the aggregate `AllITLs` would have extra entries — the ITL nil-reset on preemption handles this.
- **TTFT per-request correction**: `RequestTTFTs[id]` overwrites on the second recording, so the final value is correct. Only `TTFTSum` needed correction.

## Evolution of Thinking

Initially suspected only `TotalOutputTokens` was affected. Reading the code revealed that `ITL` entries and `TTFTSum` are also affected by the same preemption-restart pattern. `RequestTTFTs[id]` uses map-overwrite so it self-corrects. The fix addresses all three metrics.

## Current Status

- **Validated:** Fix is implemented, all tests pass, regression test added, before/after evidence collected.
- **Uncertain:** Whether extremely high preemption rates (e.g., thrashing) could cause TotalOutputTokens to go negative (unlikely but not tested — would require a request to be preempted after generating some but not all output tokens, which is the normal case).
- **Suggested next:** Consider auditing other metrics for similar preemption-related issues (e.g., scheduling delay being re-recorded).

## Warnings & Constraints

- The `PreemptedRequest.ProgressIndex` is already 0 by the time `scheduleBatch()` sees it — the DecodedTokens field is necessary because this info is lost after FormBatch.
- The `cmd/TestFetchHFConfig_Success` test failure is pre-existing (httptest port panic) — not related to this fix.
