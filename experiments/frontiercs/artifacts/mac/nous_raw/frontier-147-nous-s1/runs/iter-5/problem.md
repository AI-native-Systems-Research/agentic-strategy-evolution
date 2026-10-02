# Problem Framing — Iteration 5

## Research Question
Does a two-phase cooling schedule (linear exploration phase + exponential convergence phase) improve SA score compared to pure exponential cooling, when both use the confirmed 4.8s time budget?

The mechanism under study is the temperature schedule shape in `solution.cpp:111-128`. The current exponential schedule T = T0·(T1/T0)^progress drops temperature rapidly early — by 50% elapsed time, T ≈ 0.006 (vs T0=0.08). A two-phase schedule that cools linearly from T0=0.08 to T_mid=0.01 over the first 60%, then exponentially from T_mid to T1=0.0005 over the last 40%, maintains T ≈ 0.022 at the midpoint — 3.5× higher — enabling more exploration before converging.

References:
- `solution.cpp:111` — T0, T1 constants
- `solution.cpp:128` — exponential cooling: `T = T0 * pow(T1 / T0, progress)`
- `solution.cpp:122-188` — SA main loop

## System Interface
- **Build:** None — judge compiles automatically with C++17.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** Stdout prints `SCORE: <n>` (0–100).
- **Code evidence:**
  - `solution.cpp:111` — `double T0 = 0.08, T1 = 0.0005;`
  - `solution.cpp:113` — `double total_time = 2.85;` (changed to 4.8 for both arms)
  - `solution.cpp:128` — `T = T0 * pow(T1 / T0, progress);` (replaced with two-phase for h-main)

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```
Where `solution.cpp` has `total_time = 4.8` (the iter-4 confirmed setting).

## Baseline Validation
Ran 4.8s baseline this session: SCORE: 90.43 (exit 0). Consistent with iter-4 mean of 91.52 ± 0.53 (single probes are noisy per RP-5). Also probed two-phase cooling: SCORE: 91.01 (exit 0). Both within expected judge variance.

## Experimental Conditions

### h-main: Two-phase cooling at 4.8s
Modify `solution.cpp` to replace the exponential cooling with a two-phase schedule:
- Phase 1 (progress 0–0.6): Linear from T0=0.08 to T_mid=0.01
- Phase 2 (progress 0.6–1.0): Exponential from T_mid=0.01 to T1=0.0005
- `total_time = 4.8` (unchanged from iter-4 confirmed)

### h-control-negative: Pure exponential cooling at 4.8s
Use the iter-4 confirmed solution: `T0=0.08, T1=0.0005, total_time=4.8`, exponential cooling throughout.

## Success Criteria
h-main (two-phase) scores consistently higher than h-control (exponential) across 5 judge runs. Given iter-4 showed ±0.53 stdev at 4.8s, an effect of ≥1.0 points should be detectable with 5 runs per arm (one-sided t-test p < 0.05).

## Constraints
- Judge calls take 60-90s each. 10 total calls (5 per arm) ≈ 10-15 minutes.
- Judge variance ~5 points stdev per RP-5. Multiple runs required.
- TLE boundary at ~5.8s per RP-6. 4.8s is safely within limits.
- Cannot compile locally on macOS (`bits/stdc++.h` unavailable).

## Prior Knowledge
- **RP-1** (high): Valid-by-construction SA proposals are effective.
- **RP-2** (high): SA dominates for this problem (~70 pts over greedy).
- **RP-3** (medium): Greedy init quality doesn't affect final SA score.
- **RP-4** (low): Best-state tracking gives small directional improvement.
- **RP-5** (high): Single-run probes are unreliable; judge variance ~5 pts.
- **RP-6** (high): 4.8s time budget confirmed +2.28 pts over 2.85s (p=0.025).

Iter-4 handoff suggested: "tune T0/T1 for the 4.8s budget" and "try non-exponential cooling." This experiment tests the latter directly.
