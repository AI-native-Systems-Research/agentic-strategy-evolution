# Handoff — Iteration 1

## Goal
Maximize the judge score for Frontier-CS problem #47 (2D rectangular knapsack with optional 90° rotations) by implementing an effective bin packing algorithm in `solution.cpp`.

## Key Discoveries
- The judge runs inside Docker with GCC. `#include <bits/stdc++.h>` works in the judge but not on macOS (use individual headers for local testing).
- Local compilation: `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp`
- The solution reads JSON from stdin, writes JSON to stdout. JSON parsing must handle the bin object and items array correctly.
- **Critical parsing detail:** Parse W and H from the full input string (searching for `"W"` and `"H"` keys). Extracting a bin sub-object via `find('}')` works but parsing from the full input is simpler and equally correct since W/H are unique keys.
- Item limits can be up to 2000, so expanding all copies into a flat list (limit × types) creates 24000+ candidates and causes TLE. **Use type-level greedy** (iterate over type ordering, place copies until limit or can't fit).
- The maximal-rectangles algorithm with multiple orderings (density, value, area, max-dim, total-value, perimeter) × 3 methods (BSSF, BAF, BL) scores ~95 on the judge.
- Skyline packing adds ~0 incremental improvement but doesn't hurt.
- Randomized search (density * uniform(0.1, 10.0) noise) within 0.65s time budget provides good exploration.

## System Interface
- **Build:** `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp` (local); judge uses GCC in Docker
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0–100)
- **Baseline result:** Score ~94.8

## Code Map
- `solution.cpp:1-end` — the entire solution. `MaxRectsBin` struct implements maximal-rectangles. `SkylineBin` implements skyline packing. `greedyMaxRects` and `greedySkyline` are the greedy packers. `main()` handles JSON I/O, runs strategies, and outputs best result.

## Code Targets
- `solution.cpp` — the only file. Replace entirely with the packing algorithm.

## What I Tried That Didn't Work
- **Expanding all copies into a flat candidate list** (limit copies × types): caused TLE on large inputs (24000+ items). Type-level greedy is much faster.
- **"Best rotation" selection** (trying both orientations and picking tighter fit): slightly worse score (~92–94 vs ~95) — the simple "try original first, rotate only if doesn't fit" approach works better, likely because it's more consistent across the packing.
- **Interleaved greedy** (pick best single item across all types at each step): too slow for large limits (O(M × placements × freeRects)).
- **Gap-filling phase** after main greedy: no improvement — the greedy already fills gaps during its pass.

## What I Excluded and Why
- **Simulated annealing / local search**: Would require a neighborhood structure (swap/remove/reinsert items) and feasibility checking, significantly more complex. Worth exploring in iter-2 if the greedy plateau (~95) needs to be broken.
- **Integer linear programming**: Too slow for 1s time limit with 2000-limit items.
- **Exact branch-and-bound**: Infeasible at this scale.

## Evolution of Thinking
Started with a simple maximal-rectangles packer scoring 79. Realized the item expansion was key — switching to type-level greedy jumped to 95. Tried to add skyline and rotation optimization but they didn't improve further. The ~95 score suggests the greedy is close to optimal for most test cases, with the remaining ~5% gap likely due to suboptimal type ordering on specific inputs.

## Current Status
- **Validated:** MaxRects + Skyline multi-strategy packer scoring ~95
- **Uncertain:** Whether the remaining ~5% gap is due to ordering, fragmentation, or fundamental limitation of greedy approaches
- **Suggested next:** (1) Try local search / simulated annealing to improve individual packings post-greedy, (2) Try column generation or Lagrangian relaxation for better item selection, (3) Consider strip decomposition for near-prime bin dimensions

## Warnings & Constraints
- The judge uses Docker — code must compile with standard GCC/C++17
- Time limit is 1 second per test case (15 cases total). Randomized search must respect this.
- JSON parsing is fragile with string::find — if type names contain quotes or special characters, parsing could break. Consider a proper JSON parser for robustness.
- The `pruneFreeRects` function is O(n²) in the number of free rectangles. For highly fragmented bins this could be slow.
