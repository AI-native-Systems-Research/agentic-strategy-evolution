# Handoff — Iteration 3

## Goal
Maximize the judge score for Frontier-CS problem #47 (2D rectangular knapsack) by replacing `solution.cpp` with the v20 solution featuring co-evolved per-type method assignment (MPT) + ordering search, scoring 95.73.

## Key Discoveries
- **Per-type method assignment (MPT)** is the key new discovery. Different item types benefit from different MaxRects placement heuristics (BSSF vs BAF vs BL vs CP vs BLSF). Co-evolving MPT alongside type ordering adds ~0.4 points over uniform-method search (95.73 vs 95.37).
- **Method local search** matters: after the deterministic phase, iterating over each type's method choice (5 options per type, 8-12 types) finds improvements the random search misses.
- **Gap-fill at the end only**: Adding gap-fill as a post-processing step on the single best solution is safe and adds ~0.02 points. Gap-fill in every packing call causes TLE (confirmed again: v12 scored 89.33).
- **Test suite changed**: Same iter-2 code (v9) now scores 89.02 instead of 95.35. The v20 improvements recover and exceed the original score.
- **Replay-based gap-fill is dangerous**: Replaying placements through MaxRectsBin to reconstruct bin state, then gap-filling, caused TLE in v16 (89.06). The safe approach is re-running the greedy from scratch with the best ordering+method.

## System Interface
- **Build:** `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp` (local); judge uses GCC/Docker
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` (0-100)
- **Baseline result:** 89.02 (current solution.cpp, iter-2 v9)
- **Treatment result:** 95.73 (v20, validated twice)

## Code Map
- `solution.cpp` — entire solution. Key structures:
  - `MaxRectsBin::tryOri()` — 5 placement methods via switch(method): BSSF(0), BAF(1), BL(2), CP(3), BLSF(4)
  - `greedyPackMixed()` — type-level greedy with per-type method vector `mpt[ti]`
  - `main()` Phase 1 — 10 orderings × 5 methods × 2 orientations = 100 deterministic combos
  - `main()` Phase 2 — local search: ordering swaps + per-type method changes
  - `main()` Phase 3 — 12-strategy random search co-evolving ordering+MPT with elite pool of 8
  - `main()` Phase 4 — gap-fill: re-run best, then fill by density (100 attempts max)

## Code Targets
- `solution.cpp`: Replace entirely with v20 solution (stored as `solution_v20.cpp` in the workspace)

## What I Tried That Didn't Work
- **v11 (10 orderings + BLSF + elite pool, no MPT)**: 95.35 — same as iter-2, extra orderings/methods didn't help without MPT
- **v12 (gap-fill in every greedyPack call)**: 89.33 — TLE, same failure as iter-2 v10
- **v13 (v11 + gap-fill at end only)**: 95.37 — marginal improvement from gap-fill
- **v14 (7 methods including MinWaste and BAF+BL)**: 95.36 — more methods eat random search time
- **v15 (interleaved greedy + knapsack-guided)**: 95.37 — no improvement from alternate packing paradigms
- **v16 (gap-fill via placement replay)**: 89.06 — TLE from replay overhead
- **v17 (free rect cap 600 instead of 500)**: 95.37 — no benefit from larger cap
- **v18 (first MPT attempt, 30% mixed in random)**: 95.66 — MPT works! 
- **v19 (40% mixed + deterministic mixed combos)**: 95.68 — more MPT slightly better

## What I Excluded and Why
- **Skyline packer**: Considered but not implemented. Would require parallel codebase and the MaxRects approach is already performant enough for the 1s budget.
- **Simulated annealing on placements**: Too expensive for 1000+ items within 1s.
- **Guillotine cutting**: Different paradigm, would require full rewrite with uncertain benefit.
- **LP relaxation for type selection**: The greedy ordering search already explores type quantity implicitly.

## Evolution of Thinking
Started by re-measuring iter-2's solution (89.02, down from 95.35 — test suite changed). Tried many variants of the same MaxRects approach (more orderings, more methods, gap-fill) with diminishing returns at 95.35-95.37. The breakthrough came from realizing that different item types should use different placement heuristics — the **per-type method assignment** opened a new search dimension (5^M = 390K-244M configurations) that was previously unexplored. Co-evolving MPT alongside ordering in the random search and local search pushed the score to 95.73.

## Current Status
- **Validated:** v20 at 95.73, stable across reruns
- **Uncertain:** Whether the MPT improvement generalizes or is specific to current test cases
- **Suggested next:** (1) Adaptive method selection — track which methods win per-type across random iterations and bias toward them, (2) Smarter gap-fill — try multiple methods for gap-fill not just BSSF, (3) Cross-pollination — combine MPT search with more aggressive ordering perturbation (3-opt, block moves)

## Warnings & Constraints
- The judge uses Docker with GCC. Code must compile with standard C++17. `#include <bits/stdc++.h>` works in Docker but not on macOS.
- **Gap-fill in every call = TLE**. Only gap-fill the final best solution.
- **Replay-based gap-fill = TLE**. Use re-run-from-scratch instead.
- **Time budget is critical**: 100 deterministic combos + local search + 12-strategy random search + gap-fill must fit in <1s total. The current allocation: ~120ms deterministic, ~100ms local search, ~620ms random, ~80ms gap-fill.
- **Free-rect cap at 500**: Reducing below 400 loses quality; increasing above 600 slows pruning.
