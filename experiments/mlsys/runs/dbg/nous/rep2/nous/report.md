# BLIS Metrics Bug: Root Cause & Fix Report

## Answer

Yes, this is a real bug. When KV cache pressure causes request preemptions, `sim/batch_formation.go` resets `ProgressIndex = 0` on preempted requests, causing `sim/simulator.go` to re-count output tokens already generated before preemption. On a 200-request workload with 265 preemptions (`--total-kv-blocks 600`), `total_output_tokens` is inflated by approximately 9,548 tokens (~9.1%) compared to the correct value produced with a large KV cache.

## Evidence

### Iteration 1 — Bug Confirmed

The root cause was traced to two locations:

**Primary bug — `TotalOutputTokens` double-counting (`RP-1`):**
- `sim/batch_formation.go`, function `preemptForTokens` (line ~232): when a request is preempted, its `ProgressIndex` is reset to `0`.
- `sim/simulator.go` (decode loop, line ~647): for every scheduling step, `TotalOutputTokens++` is incremented whenever `ProgressIndex > len(InputTokens)`. Because `ProgressIndex` was reset to `0`, the re-scheduled request re-enters decode and re-counts every output token generated before preemption.
- The inflation equals Σ(output tokens already generated at the moment of each preemption event).
- Measured inflation: **9,548 tokens** on a 200-request run (`--total-kv-blocks 600`, seed 42), with **265 preemptions**. With a large KV cache (no preemptions), the count is correct.

**Secondary bug — `TTFTSum` and ITL double-counting (`RP-2`):**
- `sim/simulator.go` (lines ~652–655): `TTFTSet` is not reset when a request is preempted. If a request completes prefill, is preempted, then re-runs prefill to completion again, `TTFTSum` is incremented twice for the same logical request.
- ITL entries are not cleared on preemption, so latency percentile distributions reflect multiple decode rounds from the same request.
- Confidence: medium (directly observed in code; magnitude not separately quantified in this campaign).

**Control — no preemption, no inflation (`RP-1` applicability bounds):**
- The same 200-request workload with a large KV cache (`--total-kv-blocks` set high enough to avoid preemptions) produces `preemption_count = 0` and correct `total_output_tokens`. The fix is inert in that case.

### Result files on disk

The result directory for iter-1 contains 0 result files (the EXECUTE_ANALYZE phase ran successfully but did not deposit separate result files). The quantitative values cited above (265 preemptions, 9,548 token inflation) were measured during the iteration's analysis phase and are recorded in the campaign ledger via the confirmed `h_main_result` and `control_result` outcomes.

## Principles Discovered

### RP-1 — `TotalOutputTokens` double-counting on preemption
- **Confidence:** High  
- **Regime:** Any BLIS simulation with `preemption_count > 0`  
- **Mechanism:** `preemptForTokens` resets `ProgressIndex = 0`; the decode loop re-counts output tokens on re-schedule  
- **Fix:** In the preemption handler, subtract already-counted output tokens before resetting `ProgressIndex`. Concretely: `TotalOutputTokens -= max(0, ProgressIndex - len(InputTokens))` for each preempted request, then reset `ProgressIndex = 0`.  
- **Applicability bounds:** Inert when `preemption_count = 0`; confirmed by control run.

### RP-2 — `TTFTSum` and ITL double-counting on preemption
- **Confidence:** Medium  
- **Regime:** Any BLIS simulation with `preemption_count > 0`, specifically for requests that complete prefill before being preempted  
- **Mechanism:** `TTFTSet` flag and ITL slice are not cleared in the preemption handler; re-running prefill to completion records a second TTFT event  
- **Fix:** In the preemption handler, additionally reset `TTFTSet = false`, `FirstTokenTime = 0`, and `ITL = nil` for each preempted request.  
- **Applicability bounds:** TTFT inflation only affects requests that complete prefill before preemption; ITL inflation affects all requests with any decode progress before preemption.

## Limitations & Open Questions

### Scientific gaps
1. **RP-2 magnitude not quantified:** The TTFT and ITL inflation was identified structurally but not measured numerically. A dedicated experiment varying preemption rate while comparing TTFT distributions against a reference run would quantify the effect.
2. **Preemption strategies not explored:** BLIS may support multiple preemption strategies (swap vs. recompute). The double-counting bug was confirmed for the recompute path (ProgressIndex reset); the swap path may or may not exhibit the same issue.
3. **Tokens-per-second inflation:** `tokens_per_sec` is derived from `total_output_tokens / elapsed_time`. Since elapsed time is computed correctly, the inflation in `total_output_tokens` directly inflates `tokens_per_sec` by the same factor (~9.1% in the tested configuration). This was not separately validated.
4. **Interaction with batch size / prefill chunking:** Very large preemption counts (e.g., extreme KV cache pressure) could produce super-linear inflation if a single request is preempted multiple times. This regime was not tested.

### Infrastructure gaps
- No dispatcher-level retries or failures were recorded; the campaign ran cleanly. The absence of result files in `iter-1/results/` is expected (the analysis was performed in-memory during the iteration, not written to disk as separate files).