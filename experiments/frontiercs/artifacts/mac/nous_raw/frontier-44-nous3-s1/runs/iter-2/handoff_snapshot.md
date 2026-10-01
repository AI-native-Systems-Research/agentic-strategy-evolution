# Handoff — Iteration 2

## Goal

Measure the score of a grid NN + candidate-list 2-opt + ILS solution for problem #44 (penalized TSP). The validated solution is at `inputs/solution_v25.cpp`. Copy it to `solution.cpp` and measure with the judge.

## Key Discoveries

- **Candidate-list 2-opt with KNN is the main improvement.** Precomputing K=15 nearest neighbors per city enables 2-opt for ALL N values, not just N≤10K. This is the single biggest change from iter-1.
- **Finer grid resolution helps.** G=sqrt(N/2.5) (~2.5 cities/cell) beats G=sqrt(N/4) (~4 cities/cell) by ~0.08 points. Finer grid means faster NN lookup and more precise KNN.
- **ILS with double-bridge adds ~0.1 points consistently.** Double-bridge perturbation (swap two middle segments of a 4-cut) creates moves unreachable by 2-opt. Must be time-guarded: only runs if ≥200ms remain after 2-opt.
- **Zero-sqrt edge updates:** After 2-opt reversal, interior edge distances reverse their order (no eucl() needed). Only 2 boundary edges need new eucl() calls. This makes accepted moves dramatically cheaper.
- **Euclidean-only delta beats penalty-aware.** Despite RP-3 suggesting penalty delta is computable, the speed cost (~30 extra eucl calls per penalty position) outweighs the ~1% accuracy gain. More 2-opt iterations from speed compensate for occasional wrong moves.
- **K=15 is the sweet spot.** K=5: 78.63, K=10: 78.72, K=15: 78.75, K=20: 78.73. Beyond K=15, KNN build overhead eats into 2-opt time.
- **G=sqrt(N/2.5) is the stable sweet spot for grid.** G=sqrt(N/2) scores 78.96 but is TLE-unstable with ILS. G=sqrt(N/2.5) scores 78.93 and is perfectly stable across 4+ runs.

## System Interface

- **Build:** Handled by judge (C++17, -O2)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout
- **Baseline result:** 78.93 (v25, 4 consecutive identical runs)

## Code Map

- `solution.cpp:1` — The entire solution. Replace with `inputs/solution_v25.cpp`.
- `fmeasure_44.sh:5` — Judge invocation. Do not modify.

## Code Targets

- **h-main → solution.cpp**: Copy `inputs/solution_v25.cpp` to `solution.cpp`. The implementation is complete and validated. No modifications needed.

## What I Tried That Didn't Work

| Version | Approach | Score | Why it failed/was worse |
|---------|----------|-------|------------------------|
| v2 | KNN precomputed for all N, K=7 | 67.4 | KNN build too slow (TLE on large N) |
| v4 | Grid-based 2-opt (on-the-fly lookup) | 78.51 | Grid search overhead per 2-opt candidate |
| v5 | 2-opt + or-opt (array erase/insert) | 67.1 | O(N) per or-opt move → TLE |
| v6 | DLB 2-opt, adaptive window | 78.40 | Window=30 for large N too narrow |
| v7 | ILS with full double-bridge, no initial window 2-opt | 74.5 | Double-bridge too destructive, insufficient recovery time |
| v9/v10/v15 | 2-opt + or-opt (linked list) | 78.59-78.73 | Or-opt takes time from more effective 2-opt |
| v16 | Pure candidate-list 2-opt (no window) | 78.61 | Misses tour-position-adjacent improvements that window 2-opt finds |
| v20 | K=20 with ILS | 78.88/73.88 | KNN build overhead → unstable |
| v21/v22/v24 | G=sqrt(N/2) + ILS | 78.96/73.96 | Fine grid makes KNN slower → TLE on some runs |

## What I Excluded and Why

- **Or-opt (relocate)**: Tested extensively (v5, v9, v10, v15). Always slower than allocating the same time to 2-opt. The O(N) array manipulation or linked-list overhead doesn't pay off when penalty is ~1%.
- **3-opt/LKH-style moves**: Too complex to implement correctly. O(N*K²) per pass is 225N for K=15 — 45M candidates × 8 reconnections × 6 eucl = ~43s per pass for N=200K. Infeasible in 2s.
- **Penalty-aware optimization**: RP-2 confirmed penalty is ~1% effect. Ignoring it in delta computation lets us run 2-3x more iterations.
- **Held-Karp exact DP for small N**: O(2^N * N) — feasible for N≤17. But unclear if judge has such small test cases, and the score improvement would be marginal.
- **Alternative constructions** (greedy, Christofides, savings): All either too slow for N=200K or produce worse tours than grid NN.

## Evolution of Thinking

1. Started by trying to extend iter-1's window 2-opt to all N. Discovered window=300 per pass is O(4.5s) for N=200K — can't even finish one pass.
2. Switched to candidate-list 2-opt with KNN. First attempt (v2) was slow due to upfront KNN build. Optimized with dist² (avoid sqrt) and ring-limited grid search.
3. Discovered that combining candidate-list AND window 2-opt beats either alone: they find improvements in different neighborhoods (spatial vs tour-positional).
4. Found that DLB (don't-look bits) dramatically speeds 2-opt convergence: after pass 1, subsequent passes only check ~10-20% of cities.
5. Discovered zero-sqrt edge updates: interior edge distances reverse order during 2-opt reversal, eliminating O(segment) eucl calls per accepted move.
6. ILS with double-bridge adds ~0.1 points but must be carefully time-guarded. Too-aggressive ILS causes TLE on large test cases.
7. Finer grid (G=sqrt(N/2.5) vs sqrt(N/4)) improves both NN construction quality and KNN precision, adding ~0.08 points.

## Current Status

- **Validated:** Solution v25 scores 78.93 consistently (4 identical runs). Compiles and runs within 2s time limit on all test cases.
- **Uncertain:** Whether more aggressive ILS (more iterations, different perturbation) could push past 79 if the judge machine is faster than local. Whether 3-opt moves would help if implementable within time budget.
- **Suggested next:** (1) Implement simplified Lin-Kernighan (sequential search depth 2) for 3-opt moves that 2-opt can't find. (2) Try segment-level or-opt (move chains of 2-3 cities) since single-city or-opt didn't help. (3) Investigate whether the judge uses a faster machine by measuring wall-clock time of construction vs local.

## Warnings & Constraints

- **ILS timing is critical.** If the ILS phase starts with < 200ms remaining, it can cause TLE on large N. The ILS must check `ms() < budget - 200` before each iteration.
- **G=sqrt(N/2) is TLE-unstable.** Finer grid + KNN build + ILS can exceed 2s on large N. Use G=sqrt(N/2.5) as the stable maximum.
- **Euclidean-only 2-opt delta is fine.** Despite iter-1's 32.0 score for "boundary-only delta" (which was a bug, not a penalty issue), Euclidean-only delta with proper 2-opt implementation works well. The penalty is ~1% of cost and doesn't materially affect move quality.
- **K=15 KNN is the sweet spot.** K<10 misses improvements, K>15 wastes time on KNN build without finding more improvements.
- **The window 2-opt secondary phase matters.** It catches improvements between tour-adjacent positions that KNN misses (KNN is spatial, not tour-ordered). Score drops ~0.13 points without it.
