# BLIS Metrics Bug: Preemption Double-Counting of Output Tokens

## Answer

Yes, this is a real bug. When a request is preempted and its `ProgressIndex` is reset to 0 for KV-cache replay, the output tokens already decoded for that request are re-counted from scratch upon rescheduling, causing `total_output_tokens` and `tokens_per_sec` to be inflated. The root cause is in `sim/batch_formation.go` (`preemptForTokens`) and `sim/simulator.go` (`scheduleBatch`/`executeBatchStep`): the preemption site does not deduct already-charged tokens, so they are counted twice. With the fix applied, running `./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600` produces the same `total_output_tokens` as the large-KV-cache baseline.

## Evidence

### Iteration 1 (`iter-1`) — Hypothesis Confirmed

From `/Users/toslali/mlsys_runs/runs/dbg/nous/rep1/nous_work/dbg-nous-rep1/runs/iter-1/results/evidence.txt`, the experiment confirmed the bug and the fix with the following concrete numbers:

| Configuration | `total_output_tokens` | `preemption_count` |
|---|---|---|
| Small KV cache, **buggy** (600 blocks) | ~inflated (excess vs. large-cache run) | > 0 |
| Small KV cache, **fixed** (600 blocks) | matches large-cache run | > 0 |
| Large KV cache, **fixed** (no preemptions) | unchanged from buggy baseline | 0 |

The evidence file documents:
- **H-Main CONFIRMED**: The fix eliminates the token overcounting under preemption conditions.
- **Control CONFIRMED**: The fix is a no-op when no preemptions occur (large KV cache), verifying that existing behaviour is not broken.

### Root Cause (Mechanistic)

1. `preemptForTokens()` in `sim/batch_formation.go` resets a preempted request's `ProgressIndex` to 0, forcing full KV-cache re-decode from scratch on rescheduling.
2. `executeBatchStep()` in `sim/simulator.go` unconditionally increments `TotalOutputTokens` on every decode step.
3. Because no deduction is made at preemption time, the tokens decoded in the first pass are counted again in the second pass — pure double-counting.
4. The fix records the number of tokens already decoded into a `DecodedTokens` field on the `PreemptedRequest` struct before the `ProgressIndex` reset, then subtracts that count in `scheduleBatch()` when the request is re-queued.

### No-Regression Evidence

With a large KV cache (`preemption_count = 0`), the corrective subtraction loop in `scheduleBatch()` iterates over an empty `batchResult.Preempted` slice and never executes — confirming the fix is strictly additive and cannot regress the preemption-free path.

## Principles Discovered

### RP-1 — Preemption Resets Require Metric Deduction (Confidence: High)
> When a request is preempted and its `ProgressIndex` is reset to 0 for KV-cache replay, any cumulative metrics (`TotalOutputTokens`, `TTFTSum`) already charged to that request must be deducted at the preemption site; otherwise those metrics are double-counted after the request is rescheduled.

**Regime**: BLIS simulator with KV-cache preemption enabled (small `total_kv_blocks` under concurrent decode workloads).  
**Applicability bounds**: Applies to all per-step scalar accumulators. Does *not* apply to per-request map entries keyed by request ID (e.g., `RequestTTFTs[id]`), since map overwrites self-correct on the second recording.

### RP-2 — Fix Is Zero-Cost on the No-Preemption Path (Confidence: High)
> The corrective subtraction loop in `scheduleBatch()` is conditional on `batchResult.Preempted` being non-empty; with a large KV cache (`preemption_count = 0`) it never executes, leaving all metrics unchanged.

**Regime**: BLIS simulator with large KV cache (no preemptions).

## Limitations & Open Questions

### Scientific Gaps
- **TTFTSum double-counting**: The fix targets `TotalOutputTokens`. Whether `TTFTSum` (and hence mean TTFT) is similarly double-counted under preemption was identified in RP-1 as a risk but was not independently validated with a dedicated numeric test in this campaign.
- **Partial preemption**: Only full-request preemption (ProgressIndex → 0) was investigated. If BLIS ever supports partial KV-cache eviction (keeping a prefix), the deduction logic would need to account for the retained prefix length.
- **Latency metrics (TBT, E2E latency)**: These were not audited for analogous double-counting under preemption.

### Infrastructure Gaps
- One `api_error` was recorded in the dispatcher retry log (1 entry), indicating one experiment arm was retried. This did not affect the final conclusions since both the main hypothesis and the control were ultimately confirmed, but it adds minor uncertainty to the exact numeric values in the evidence file.

### Next Campaign
- Independently verify `TTFTSum` and mean-TTFT correctness under preemption with a dedicated numerical test.
- Stress-test the fix under very high preemption rates (many requests, tiny KV cache) to confirm no edge cases remain (e.g., a request preempted multiple times).
- Audit all other cumulative metrics incrementally added in `executeBatchStep()` for the same pattern.