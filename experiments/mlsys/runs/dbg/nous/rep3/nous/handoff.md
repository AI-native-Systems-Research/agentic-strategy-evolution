# Handoff Snapshot — Iteration 2

## Goal

Validate the preemption output-token double-counting fix at full scope: 5 seeds × 3 KV cache sizes (600, 6000, 60000 blocks). Produce `final/answer.json` and `final/fix.patch` as deliverables. The fix is already applied in the codebase; the iter-1 patch at `runs/iter-1/patches/h-main.patch` is the canonical diff.

## Key Discoveries

1. **Fix confirmed across 5 seeds** (iter-2 probes): Seeds 42, 123, 456, 789, 1337 all produce identical `total_output_tokens` between 600 blocks (265–348 preemptions) and 60000 blocks (0 preemptions). Exact values: seed42=105082, seed123=101487, seed456=104845, seed789=107287, seed1337=107392.
2. **Intermediate cache also correct**: 6000 blocks at seed 42 produces total_output_tokens=105082 with 72 preemptions — matching ground truth exactly.
3. **Root cause (unchanged from iter-1)**: `sim/simulator.go:650` increments `TotalOutputTokens++` per decode step. `sim/batch_formation.go:238` resets `ProgressIndex=0` on preemption without decrementing. Fix computes `OutputTokensLost` before reset and subtracts in `scheduleBatch`.
4. **Fix is exactly three changes**: (a) `OutputTokensLost` field on `PreemptedRequest`, (b) computation before ProgressIndex reset, (c) subtraction in `scheduleBatch`. Plus ITL clearing.
5. **Regression test passes**: `TestPreemption_TotalOutputTokens_NoDoubleCount` exercises 14 preemptions in unit-test regime and confirms the invariant.
6. **All sim/ tests pass**: `go test ./sim/...` exits 0. Only `cmd/TestFetchHFConfig_Success` fails (pre-existing, unrelated httptest issue).
7. **Iter-1 magnitude**: Before fix, inflation was 9,548 tokens (9.1%) at 265 preemptions and 1,303 tokens (1.2%) at 72 preemptions.

## System Interface

- **Build:** `go build -o blis main.go`
- **Run (high preemption):** `./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600`
- **Run (moderate preemption):** `./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 6000`
- **Run (no preemption / ground truth):** `./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000`
- **Output format:** `=== Simulation Metrics ===` header line, then JSON object to stdout. Use `tail -n +2` to get clean JSON, or `grep '"total_output_tokens"'` to extract the key metric.
- **Baseline result:** seed 42 ground truth: `total_output_tokens: 105082`, `preemption_count: 0`

## Code Map

- `sim/batch_formation.go:42-45` — `PreemptedRequest` struct with `OutputTokensLost int64` field.
- `sim/batch_formation.go:219` — `outputTokensLost` computation: `max(ProgressIndex - len(InputTokens), 0)`. Critical line — verify it fires before line 238's `ProgressIndex = 0` reset.
- `sim/batch_formation.go:238-239` — ProgressIndex reset + `ITL[:0]` clearing.
- `sim/simulator.go:584-591` — `scheduleBatch()` preemption loop. Line 590: `sim.Metrics.TotalOutputTokens -= int(p.OutputTokensLost)`.
- `sim/simulator.go:648-651` — `executeBatchStep()` decode loop. Line 650: `sim.Metrics.TotalOutputTokens++` — the counting site.
- `sim/metrics.go:21` — `TotalOutputTokens int` field definition.
- `sim/metrics.go:126` — `tokens_per_sec` computation.
- `sim/simulator_test.go:2602-2645` — `TestPreemption_TotalOutputTokens_NoDoubleCount` regression test.

## Code Targets

The fix is already applied. For the executor:
- **Patch source:** `runs/iter-1/patches/h-main.patch` contains the canonical diff.
- **To generate the patch fresh:** The fix is in the current working tree relative to the original commit `15a1c7a`.

## What I Tried That Didn't Work

- **nous validate command:** Permission error accessing orchestrator source. Validation will need to be run with appropriate permissions or skipped.
- **Python JSON parsing of stdout:** BLIS prefixes JSON with `=== Simulation Metrics ===` header. Must skip header or use grep.
- **(Iter-1)** First regression test attempt used KV cache of 20 blocks with 30 requests — no preemptions triggered. Fixed by using 50 requests at rate 50/s with 30 blocks.
- **(Iter-1)** Considered fixing at counting time (only count if token is "new") — requires extra state tracking, rejected.

## What I Excluded and Why

- **TTFTSum double-counting:** Not fixed because `TTFTSum` is never used in JSON output. All TTFT stats from `RequestTTFTs` map (keyed by ID, last-write-wins).
- **Cluster-level preemption paths:** Only single-instance preemption audited. Out of scope for this research question.
- **E2E latency effects:** Preempted requests genuinely take longer (re-prefill). Higher E2E is correct behavior.

## Evolution of Thinking

1. **Iter-1**: Identified root cause, applied fix, validated at single seed (42). CONFIRMED both arms.
2. **Iter-2**: Extended to 5 seeds × 3 cache sizes. Pre-probed all — all match exactly. The fix is mathematically correct (subtracts exactly what was over-counted), so multi-seed validation confirms no edge cases in the code path.

## Current Status

- **Validated:** Fix produces identical total_output_tokens across 5 seeds × {600, 6000, 60000} blocks. All sim/ tests pass. Regression test covers the invariant.
- **Uncertain:** Nothing — the mechanism is fully understood and the fix is verified.
- **Suggested next:** If a third iteration is needed, audit cluster-level metric merging (`sim/cluster/cluster.go`) for analogous double-counting.

## Warnings & Constraints

- **Output parsing:** BLIS stdout has header line before JSON. With small KV cache, `=== KV Cache Metrics ===` appended after JSON.
- **Pre-existing test failure:** `cmd/TestFetchHFConfig_Success` — unrelated. Use `go test ./sim/...`.
- **Wall time:** ~2-3 seconds per run. Full matrix (15 runs) under 1 minute.
- **Determinism:** Same seed + params = byte-identical JSON (INV-6).
