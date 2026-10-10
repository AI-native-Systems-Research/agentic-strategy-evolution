# Handoff — Iteration 2

## Goal
Maximize the judge score for Frontier-CS problem #47 (2D rectangular knapsack with optional 90° rotations) by replacing `solution.cpp` with the enhanced MaxRects packer (v9) that scored 95.35.

## Key Discoveries
- **Contact-point (CP) heuristic**: Adding a 4th placement method that scores positions by wall contact length improved score from ~94.5 to ~95.35. The CP method excels on test cases with near-prime bin dimensions where BL/BSSF/BAF produce fragmented layouts.
- **Bin transposition**: Packing in H×W (instead of W×H) then translating coordinates back exposes different placement opportunities because BL heuristic fills bottom-left first — swapping axes changes which items get priority positions. This added ~0.3-0.5 points.
- **Both-orientation best-fit**: Always trying both rotations and picking the better fit (vs. iter-1's fallback rotation) improved score by ~6 points (88.78 → ~94.5).
- **Ordering local search**: Pairwise swaps on the best deterministic ordering add ~0.2 points. Most improvement comes in the first 1-2 passes.
- **Free-rect cap at 500**: Prevents quadratic pruning blowup without measurable quality loss, enabling more random iterations.
- **Gap-fill phase is a trap**: Adding gap-fill (fill remaining space with any fitting item after type-level greedy) caused severe TLE on large inputs, dropping score to 89.

## System Interface
- **Build:** `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp` (local); judge uses GCC/Docker
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` (0-100)
- **Baseline result:** 95.35 (v9)

## Code Map
- `solution.cpp` — entire solution. Key structures:
  - `MaxRectsBin` struct: maintains free rectangle list, `findBest()` tries both orientations, `tryOri()` implements 4 methods (BSSF/BAF/BL/CP), `place()` splits + prunes + caps at 500
  - `greedyMaxRects()`: type-level greedy packing
  - `greedyTransposed()`: packs in H×W bin, translates coords back
  - `main()`: 3-phase approach: deterministic (64 combos) → local search (swap-based) → randomized search (6 strategies)

## Code Targets
- `solution.cpp`: Replace entirely with v9 solution (solution_v9.cpp or solution_final.cpp in the workspace).

## What I Tried That Didn't Work
- **v3 (static arrays + multi-round greedy)**: Scored 74.59 — multi-round greedy (cycling through types with a budget) was far worse than exhausting one type at a time. Static array with 2048 cap also seemed to hurt.
- **v4 (gap-fill in deterministic phase)**: Scored 94.16 — gap-fill adds overhead without commensurate benefit because the type-level greedy already fills space well.
- **v7 (too many orderings + 3-opt)**: Scored 94.89 — adding 2 more orderings and 3-opt moves ate into random search time.
- **v10 (gap-fill everywhere)**: Scored 89.05 — gap-fill in all 96 deterministic runs caused TLE.
- **Interleaved greedy** (pick best single item across all types at each step): marginally helpful as a deterministic strategy but not worth the overhead in random search.
- **Strip packing** (horizontal strips per type): No improvement over MaxRects.

## What I Excluded and Why
- **Simulated annealing / placement-level local search**: Would require tracking all placed items and re-evaluating feasibility. Too complex for the 1s time budget with 1000+ placements.
- **ILP / branch-and-bound**: Infeasible at this scale (up to 24000 items).
- **Guillotine cutting**: Different packing paradigm; would require rewriting the entire placement engine. Possible future direction.
- **LP-relaxation for type selection**: The fractional upper bound K already represents this; guiding greedy with LP weights would add complexity without clear benefit since the type ordering search already explores this space.

## Evolution of Thinking
Started iter-2 by measuring iter-1's code on current test set (88.78, down from iter-1's measured 94.82 — test suite likely changed). Found the single biggest improvement was both-orientation best-fit (+6 points). Then discovered CP heuristic and transposition each added small but consistent gains. Learned that overhead management is critical: adding strategies that are individually helpful can hurt if they reduce random search time. The final v9 balances diversity of deterministic strategies with ample random search time.

## Current Status
- **Validated:** v9 at 95.35, stable across reruns
- **Uncertain:** Whether the remaining ~5% gap is from specific hard test cases or systemic fragmentation
- **Suggested next:** (1) Per-test analysis if judge provides per-case scores, (2) Hybrid approach: use LP relaxation to bound type counts, then pack within those bounds, (3) Adaptive time allocation: detect if a test case is "easy" (high area utilization) early and spend less time on random search for it

## Warnings & Constraints
- The judge uses Docker with GCC — code must compile with standard C++17. `#include <bits/stdc++.h>` works in Docker but not on macOS.
- **Time budget is the critical constraint**: each additional deterministic strategy costs ~1ms per test but reduces random search iterations. v10 proved that too many strategies cause TLE (score dropped from 95 to 89).
- **Transposed bin coordinate translation**: `greedyTransposed` swaps (px, py) to map back to the original bin. If item dimensions are also swapped, the rotation flag stays the same. Verify this logic if modifying.
- **Free-rect cap at 500**: reducing below ~400 starts losing quality; increasing above ~600 slows pruning noticeably.
