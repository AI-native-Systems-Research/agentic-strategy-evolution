# Problem Framing — 2D Rectangular Knapsack Packing

## Research Question
What algorithm maximizes the Frontier-CS judge score for problem #47 (2D rectangular knapsack with optional 90° rotations)? The task is to pack axis-aligned rectangles of given item types into a single bin, maximizing total profit. The judge scores solutions relative to a shelf-heuristic baseline (B) and a fractional upper bound (K), computing `ratio = clamp((V-B)/(K-B), 0, 1)` averaged over 15 test cases.

Key mechanism: the source file is `solution.cpp` in the working directory. The judge compiles it inside Docker, runs it on 15 hidden test cases (bin sizes 900–2000, 8–12 item types, limits up to 2000), and computes the average ratio.

## System Interface
- **Build command:** Compiled by the judge inside Docker (GCC, C++17). Local compilation: `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp`
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` where n is 0–100.
- **Code evidence:** `fmeasure_47.sh:5` invokes `frontier eval algorithmic 47 "$1" --json`. The solution reads JSON from stdin, writes JSON to stdout.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp
```

## Baseline Validation
- Exit code: 0
- Score: 94.79 (maximal-rectangles packer with 6 orderings × 3 placement methods + skyline packer + randomized search within 0.75s time budget)
- The solution correctly handles rotation, limits, and half-open geometry.

## Experimental Conditions

### h-main: Advanced MaxRects + Skyline Packer
The primary algorithm uses:
1. **Maximal-rectangles bin packing** with three placement heuristics (Best Short Side Fit, Best Area Fit, Bottom-Left)
2. **Skyline packing** as an alternative strategy
3. **Six deterministic type orderings** (by density, value, area, max-dimension, total-value, perimeter)
4. **Randomized search** using density-weighted noise to explore diverse orderings within the time budget (0.75s)
5. Best result across all strategies is selected

**Intent:** Replace the empty stub with this comprehensive packing algorithm. The code changes are in `solution.cpp`.

## Success Criteria
- Score > 0 (any valid packing beats the stub)
- Target: score ≥ 80 (significantly above the shelf-heuristic baseline B used by the judge)
- Observed: ~95, indicating the algorithm is close to the fractional upper bound K

## Constraints
- Time limit: 1 second per test case
- Memory limit: 512 MB
- 15 test cases, score is average ratio
- Bin: 900 ≤ W,H ≤ 2000; Items: 8–12 types, dims 7 to 0.6*max(W,H), limits 1–2000
- JSON I/O format must be exactly correct

## Prior Knowledge
This is iteration 1. No prior principles exist.
