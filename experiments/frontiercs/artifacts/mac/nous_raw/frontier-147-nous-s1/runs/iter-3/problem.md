# Problem Framing — Iteration 3

## Research Question

Can SA best-state tracking combined with a wider temperature schedule (T0=0.08, T1=0.0005) push the AHC001 rectangle-packing score above the iter-2 plateau of ~90? The mechanism is that wider temperatures explore more diverse configurations, while best-tracking captures the peak score encountered during the run rather than the final (potentially degraded) state.

Key source files:
- `solution.cpp:1` — entire solution in one file
- Satisfaction formula at lines ~35-42: `p_i = 1 - (1 - min(r,s)/max(r,s))^2`
- `max_expand_*` functions at lines ~44-80: O(N) per call, compute valid edge bounds
- SA loop at lines ~100-150: single-edge moves with exponential cooling

## System Interface

- **Build:** Handled by judge script (compiles automatically)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output:** Single line `SCORE: <n>` where n is 0-100

### Code evidence
- `solution.cpp` is the only editable file. The judge compiles it with `bits/stdc++.h` (not available locally on macOS).
- Timer uses `chrono::high_resolution_clock` (wall clock). Total budget set to 2.85s to be safe under judge's ~3s limit.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```

## Baseline Validation

- Iter-2 h-main (SA without best-tracking, T0=0.05, T1=0.001): scores 88.7–90.6 across runs (mean ~89.9)
- SA + best-tracking + T0=0.05, T1=0.001: scored 91.84
- SA + best-tracking + T0=0.08, T1=0.0005: scored 92.73 ← best observed
- SA + best-tracking + T0=0.1, T1=0.0002: scored 90.73 (too aggressive)

All commands exited successfully and produced valid output.

## Experimental Conditions

### h-main: SA with best-tracking + wider temperature schedule
Changes from iter-2 baseline:
1. Add best-state tracking: every 32K iterations, compute total_score() and save configuration if it's the best seen. Restore best configuration at end.
2. Widen temperature schedule: T0=0.08 (was 0.05), T1=0.0005 (was 0.001).

### h-control-negative: Iter-2 baseline SA (no best-tracking)
Identical to iter-2 h-main: T0=0.05, T1=0.001, no best-tracking. Expected to score ~89-90.

## Success Criteria

h-main should consistently score higher than h-control-negative across multiple judge runs. The directional prediction is: best-tracking + wider temps > no best-tracking + narrow temps.

## Constraints

- Each judge call takes 30-60s
- Score variance ~5 points between judge runs (different random test sets)
- Cannot compile locally (no `bits/stdc++.h` on macOS)
- Total time budget per test case: ~3s (using 2.85s to be safe)

## Prior Knowledge

- RP-1: Valid-by-construction proposals outperform random-step + rejection [confirmed iter-1]
- RP-2: SA is dominant mechanism, ~70 points over greedy-only [confirmed iter-1]
- RP-3: Init quality doesn't significantly affect final SA score [confirmed iter-2]
- New discovery (this iter's probes): Best-tracking + wider temperature synergize. Wider temps without best-tracking scored ~88.4 (neutral). Best-tracking alone scored 91.8. Combined scored 92.7. The interaction is super-additive.
