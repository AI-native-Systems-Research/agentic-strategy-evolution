# Problem Framing — AHC001 Rectangle Packing Optimization

## Research Question

What algorithm maximizes the judge score for problem #147 (AHC001: ad rectangle placement)? The problem requires placing n non-overlapping axis-aligned rectangles on a 10000×10000 grid, each containing a specified point, with areas as close as possible to target values. The scoring function is `p_i = 1 - (1 - min(r_i,s_i)/max(r_i,s_i))^2`, averaged and scaled to 1e9. The judge then maps raw scores to [0,100] via `(raw - baseline) / (best - baseline)`.

Key source: `chk.cc` lines 38-69 implement the scoring function, overlap checking, and the baseline/best normalization.

## System Interface

- **Build:** The judge server compiles C++17 on a Linux Docker container (g++ 11).
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` where n is 0-100.
- **Time limit:** 10 seconds per test case (config.yaml line 6).
- **Memory limit:** 256MB.
- **Code evidence:** `chk.cc:48` — point containment check: `r.x1 <= xs[i] && xs[i] < r.x2 && r.y1 <= ys[i] && ys[i] < r.y2`. `chk.cc:57-59` — satisfaction formula. `chk.cc:67` — final scoring ratio.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```

## Baseline Validation

The greedy+SA solution scored **84.70** (measured via fmeasure_147.sh). The solution compiles successfully on the judge's g++ 11 environment. 100 test cases evaluated in ~150s total.

## Experimental Conditions

### h-main: Greedy expansion + Simulated Annealing
The current solution.cpp implements:
1. **Greedy phase** (~2s): Initialize 1×1 rects at each point; expand in all 4 directions using small steps (sqrt(ratio)×3, max 150), verifying no overlap with O(n) canPlace.
2. **SA phase** (~7s): Random moves (boundary shifts, expand-to-limit via maxExp, target-aware expand/shrink). Linear cooling from T=0.01 to 0. Accept improving moves always; accept worsening moves with Boltzmann probability.

### h-control-negative: Greedy-only (no SA)
Same greedy expansion but skip the SA phase entirely. This isolates SA's contribution.
- **Change intent:** Remove the SA while-loop entirely, output greedy result directly.

## Success Criteria

- h-main score > 80 (validated at 84.70).
- h-main score significantly higher than h-control-negative, demonstrating SA's contribution.

## Constraints

- 10s time limit per test case; solution uses ~9.3s.
- 256MB memory; N≤200, well within limits.
- Must not overlap rectangles and must contain each point (checked by `chk.cc`).
- Output format: exactly n lines, each with `a_i b_i c_i d_i` space-separated.

## Prior Knowledge

First iteration — no prior principles.
