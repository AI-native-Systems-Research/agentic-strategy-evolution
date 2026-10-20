# Problem Framing: Preemption causes double-counting of output tokens

## Research Question

When the KV cache is small enough that requests get preempted, `total_output_tokens` and `tokens_per_sec` in BLIS metrics output are inflated. The root cause is in `sim/batch_formation.go:preemptForTokens()` (line 232): when a request is preempted, its `ProgressIndex` is reset to 0 but `Metrics.TotalOutputTokens` (incremented per decode step in `sim/simulator.go:647`) is never adjusted. The preempted request re-enters the wait queue, gets rescheduled, re-prefills, and re-decodes — counting every output token a second time.

Key source files:
- `sim/batch_formation.go:198-244` — `preemptForTokens()`: resets ProgressIndex to 0 on preemption without accounting for already-counted tokens
- `sim/simulator.go:645-649` — `executeBatchStep()`: increments `TotalOutputTokens` on each decode step
- `sim/simulator.go:584-588` — `scheduleBatch()`: processes preemption results but does not adjust token counts

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags:**
  - `--model` — model name (parsed in `cmd/run.go`)
  - `--rate` — arrival rate (parsed in `cmd/run.go`)
  - `--num-requests` — number of requests (parsed in `cmd/run.go`)
  - `--seed` — RNG seed for determinism (parsed in `cmd/run.go`)
  - `--total-kv-blocks` — KV cache size in blocks (parsed in `cmd/run.go`)
  - `--output` — JSON output path (native output mechanism)
- **Code evidence:**
  - `sim/simulator.go:647` — `sim.Metrics.TotalOutputTokens++` (per decode step)
  - `sim/batch_formation.go:232` — `preemptedRequest.ProgressIndex = 0` (reset on preemption)
  - `sim/metrics.go:126` — `output.TokensPerSec = float64(m.TotalOutputTokens) / vllmRuntime` (derived metric)

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000
```

## Baseline Validation

- Exit code: 0
- Output: JSON metrics to stdout
- Key metric: `total_output_tokens = 105082`, `preemption_count = 0`

## Experimental Conditions

### Condition 1: Control (no preemptions)
```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 60000
```
Expected: `total_output_tokens = 105082`, `preemption_count = 0`

### Condition 2: Treatment (with preemptions, before fix)
```bash
./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600
```
Observed before fix: `total_output_tokens = 114630`, `preemption_count = 265` (9548 extra tokens)

### Condition 3: Treatment (with preemptions, after fix)
Same command as Condition 2, with the code fix applied.
Expected: `total_output_tokens = 105082` (identical to control)

### Code change (fix):
- **File:** `sim/batch_formation.go`
  - **Intent:** Before resetting ProgressIndex to 0 on preemption, compute how many output tokens were already generated (ProgressIndex - len(InputTokens), if positive) and store in `PreemptedRequest.DecodedTokens`. Also clear `ITL` slice and reset `TTFTSet` to prevent metric contamination on re-decode.
  - **Rationale:** These values are needed by the simulator to subtract already-counted metrics.

- **File:** `sim/simulator.go`
  - **Intent:** In the preemption processing loop in `scheduleBatch()`, subtract `DecodedTokens` from `TotalOutputTokens` and deduct `FirstTokenTime` from `TTFTSum` if TTFT was previously recorded.
  - **Rationale:** Corrects the double-counting by removing metrics for tokens that will be regenerated.

## Success Criteria

1. `total_output_tokens` must be identical across all KV cache sizes when using the same seed/workload (105082 for the test configuration).
2. All existing tests must pass (`go test ./sim/...`).
3. Regression test `TestPreemption_TotalOutputTokens_NoDoubleCount` must pass.

## Constraints

- Minimal change: only modify the preemption path and metric accounting.
- Do not change the preemption mechanism itself (ProgressIndex reset is correct for KV cache behavior).
- Maintain determinism (INV-6).
- Maintain request conservation (INV-1).

## Prior Knowledge

This is the first iteration. No active principles.
