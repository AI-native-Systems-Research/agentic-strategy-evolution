# Problem Framing — Iteration 1

## Research Question

What algorithm maximizes the Frontier-CS judge score for problem #47 (2D Rectangular Knapsack with optional 90° rotations)?

The problem requires packing axis-aligned rectangles of given item types into a bin to maximize total profit, subject to per-type limits, non-overlap, and boundary constraints. Scoring is continuous 0–100 based on `(V - B) / (K - B)` averaged over 15 hidden test cases.

Key implementation file: `solution.cpp` in the worktree root.

## System Interface

- **Build:** Compilation happens server-side via the judge (Docker). The solution uses `#include <bits/stdc++.h>` which is available in the judge's GCC environment.
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` where n is 0–100.
- **Time limit:** 1 second per test case, 15 test cases.
- **Memory limit:** 512 MB.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp
```

## Baseline Validation

- Exit code: 0
- Output: `SCORE: 94.45574`
- The baseline uses MaxRects bin packing with multiple heuristics (BSSF, BAF, BL), sorted orderings (density, value, area, height, width), global greedy, multi-pass, permutation exhaustion for M≤10, and random search within 0.88s wall time.

## Experimental Conditions

### h-main: MaxRects multi-heuristic with permutation search
The current v5 solution implementing:
1. MaxRects packer with 3 heuristics (Best Short Side Fit, Best Area Fit, Bottom-Left)
2. 7 sorting strategies for item ordering
3. Global greedy packing (density, value, density-weighted-by-position, value-weighted-by-position)
4. Multi-pass packing (high-density first, fill gaps, then lower-density)
5. Full permutation exhaustion for M≤10 (up to 3.6M orderings × 3 heuristics)
6. Random shuffle search for remaining time budget
7. Best-of-both-orientations rotation handling

**Code change:** Replace the stub `solution.cpp` with the full MaxRects implementation.

## Success Criteria

- Score > 90 (well above baseline heuristic B)
- Target: maximize score toward 100

## Constraints

- 1 second time limit per test case
- 512 MB memory
- Solution must produce valid JSON output
- 15 test cases, bins 900–2000 in each dimension, 8–12 item types

## Prior Knowledge

First iteration — no prior principles.
