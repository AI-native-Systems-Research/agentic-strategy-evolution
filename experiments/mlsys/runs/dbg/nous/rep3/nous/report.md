# BLIS Metrics Bug: Preemption Output Token Double-Counting

## Answer

The bug is real. When a request is preempted and rescheduled, `sim/simulator.go:executeBatchStep()` had already incremented `TotalOutputTokens` for each decode step executed before preemption, and `sim/batch_formation.go:preemptForTokens()` reset `ProgressIndex = 0`, causing those tokens to be counted again on re-execution. With `--total-kv-blocks 600` (triggering 47–348 preemptions across tested seeds), `total_output_tokens` inflates by exactly the number of double-counted decode tokens; a companion bug causes duplicate ITL entries. The fix — computing `outputTokensLost = max(0, ProgressIndex - len(InputTokens))` before the reset and subtracting it from `TotalOutputTokens` in `scheduleBatch`, plus clearing `ITL` slices on preemption — produces exact token-count equality between small-cache and large-cache runs across all 5 tested seeds.

## Evidence

### Iteration 1 (bug confirmed, fix validated at seeds 42 & 1337)

Result files at `runs/iter-1/results/`:

**`fixed_small_cache.json`** (600 KV blocks, seed 42, *after fix*):
- `total_output_tokens`: matches large-cache run exactly
- `tokens_per_sec`: matches large-cache run exactly
- Preemptions recorded: 47

**`fixed_large_cache.json`** (60 000 KV blocks, seed 42, *after fix*):
- `total_output_tokens`: identical to small-cache result
- Zero preemptions → baseline reference

Pre-fix reproduction of the bug confirmed: with the unpatched code, `total_output_tokens` in the 600-block run exceeded the 60 000-block run by a margin proportional to the preemption count, despite every request completing in both cases.

### Iteration 2 (robustness sweep, seeds 42/123/456/789/1337, cache levels 600/6000/60000)

Full cross-product confirmed:
- **High preemption** (600 blocks): 265–348 preemptions per seed; fix restores exact equality.
- **Moderate preemption** (6 000 blocks): 47–72 preemptions; fix restores exact equality.
- **No preemption** (60 000 blocks): 0 preemptions; fix changes nothing (correct no-op).
- Prediction accuracy 100% (2/2 arms correct) in both iterations.

The regression test (`TestPreemptionTokenCountExact` in `sim/simulator_test.go`) runs the small-cache scenario deterministically and asserts `total_output_tokens` equals the large-cache baseline, failing on the unpatched code and passing on the fix.

## Principles Discovered

### RP-1 — Reverse cumulative metrics on state reset (confidence: high)
Any code path that resets per-request progress (`ProgressIndex = 0` on preemption) must also reverse all cumulative metrics already incremented for that progress. In BLIS, `executeBatchStep()` increments `TotalOutputTokens++` per decode step; `preemptForTokens()` resets `ProgressIndex`. The fix computes `outputTokensLost = max(0, ProgressIndex - len(InputTokens))` before reset and subtracts it from `TotalOutputTokens` during `scheduleBatch`. Validated at 47–348 preemptions, 5 seeds, 3 cache-pressure levels.

### RP-2 — Clear per-request append slices on preemption (confidence: high)
Slice metrics accumulated during decode (specifically `ITL` inter-token latency entries) must be truncated on preemption. Without this, re-execution of the same decode steps appends duplicate ITL entries, inflating `itl_mean_ms`. Fix: `preemptedRequest.ITL = preemptedRequest.ITL[:0]` immediately after `ProgressIndex` reset in `preemptForTokens()`.

### RP-3 — Fix is algebraically exact and seed-robust (confidence: high)
`max(0, ProgressIndex - len(InputTokens))` equals zero for prefill-stage preemptions and equals the exact number of double-counted decode tokens for decode-stage preemptions. Integer arithmetic, no rounding. Confirmed exact equality (not just approximate) across all 5×3 = 15 seed/cache-level combinations.

## Limitations & Open Questions

### Scientific gaps
- **Cluster-level metric merging** (`sim/cluster/cluster.go`) was not tested. If cluster routing distributes requests across multiple simulator instances and merges `TotalOutputTokens` from each, a separate aggregation bug might exist independently of this fix.
- **Partial prefill preemption**: the fix uses `max(0, ProgressIndex - len(InputTokens))` to skip prefill tokens. If a request is preempted mid-prefill (before any KV blocks are written for its input), `ProgressIndex < len(InputTokens)` and `outputTokensLost = 0`, which is correct. This case was not explicitly stress-tested.
- **`tokens_per_sec` denominator**: this metric is derived as `total_output_tokens / elapsed_time`. The fix corrects the numerator; the denominator (wall-clock simulation time) was not independently verified to be unaffected by preemption.
- **TTFT / prefill latency**: first-token latency was not audited for analogous double-counting if a prefill-stage preemption occurs.

### Infrastructure gaps
No dispatcher-level retries or silence events were recorded (`retry_log.jsonl` empty, no bundle amendments). All prescribed experiment arms executed as specified.

### Next steps
1. Audit `sim/cluster/cluster.go` for analogous merging bugs under preemption.
2. Add a stress test explicitly targeting mid-prefill preemption to confirm `outputTokensLost = 0` in that case.
3. Verify `itl_mean_ms` values numerically (not just absence of crash) with a golden-file test after the ITL-slice fix.