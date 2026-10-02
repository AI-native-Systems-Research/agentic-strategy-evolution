# Problem Framing — Iteration 2

## Research Question
What algorithm maximizes the Frontier-CS judge score for problem #47 (2D rectangular knapsack with optional 90° rotations)? Building on iter-1's maximal-rectangles greedy (~88.78 on current test set), can enhanced placement heuristics, bin transposition, and ordering optimization push past 95?

Key source files: `solution.cpp` (the only file; contains all packing logic).

## System Interface
- **Build:** `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp` (local); judge uses GCC in Docker with `#include <bits/stdc++.h>`.
- **Measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` (0–100).
- **Time limit:** 1 second per test case, 15 test cases.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp
```

## Baseline Validation
Iter-1 solution (maxrects + skyline + randomized search) scores 88.78 on the current test set. Exit code 0, produces valid JSON placements.

## Experimental Conditions

### h-main: Enhanced MaxRects with CP heuristic, transposition, and ordering optimization
Replace `solution.cpp` with an enhanced algorithm featuring:
1. **Contact-point (CP) placement heuristic** — new method 3 that scores free rectangles by wall contact length, reducing fragmentation
2. **Both-orientation best-fit** — always tries both rotations and picks the better fit (vs. iter-1's fallback approach)
3. **Bin transposition** — packs in both W×H and H×W orientations, translating coords back
4. **Local search on type ordering** — after deterministic strategies, iteratively improves the best ordering via pairwise swaps
5. **Broader randomized search** — 6 perturbation strategies (shuffle, density noise, best-order swap, segment reversal, total-value noise) across 4 methods
6. **Free rect capping at 500** — prevents quadratic blowup in pruning, enabling more iterations

Validated score: 95.35 (vs. 88.78 baseline).

## Success Criteria
Score ≥ 93 (significant improvement over iter-1's 88.78). Observed: 95.35.

## Constraints
- 1 second time limit per test case
- 512 MB memory limit
- Must produce valid JSON output matching the problem's schema exactly
- Must handle `allow_rotate: false` cases (rot must be 0)
- Per-type limits must not be exceeded

## Prior Knowledge
- RP-1: MaxRects greedy with multi-ordering search achieves ~95% of fractional upper bound
- RP-2: Type-level greedy (not flat expansion) is critical for avoiding TLE with large limits
