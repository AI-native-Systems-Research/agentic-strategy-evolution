# Handoff — iter-1

## Goal
Implement and score two rectangle-packing algorithms for AHC001 (problem #147): a greedy+SA approach (h-main) and a greedy-only control (h-control-negative). Measure each with `fmeasure_147.sh`.

## Key Discoveries
- The judge compiles on Linux g++ 11 in Docker. Do NOT use `bits/stdc++.h` — use standard includes. Avoid `max(int, long long)` — use explicit casts.
- The scoring is normalized: `(raw - baseline) / (best - baseline)`. Baseline ~750M, best ~993M across test cases. A raw score of ~950M maps to ~85 on the 0-100 scale.
- The satisfaction function `p_i = 1 - (1 - min(r_i,s_i)/max(r_i,s_i))^2` is symmetric: being 2× too big is equally bad as 2× too small. Both expansion and shrinkage matter.
- Point containment check uses `x1 <= x && x < x2` (half-open intervals), per `chk.cc:48`.
- `maxExp(idx, d)` computes the exact expansion limit by scanning all N rects for those in the perpendicular band. This is O(N) per call but N≤200 so it's fast.
- Greedy with small steps (max 150) + canPlace converges in ~100-300 rounds, taking ~1.5-2s.
- SA with linear cooling T=0.01→0 over ~7s achieves ~85 score. The "expand-to-limit" (move 6) and "target-aware" (move 7) moves are the high-impact SA moves.

## System Interface
- **Build:** Not needed locally — judge compiles server-side.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** Stdout line `SCORE: <n>` (0-100).
- **Baseline result:** h-main scored 84.70.

## Code Map
- `chk.cc:12-14` — `intersect()` overlap check. Reference for understanding what constitutes valid output.
- `chk.cc:48` — Point containment: `r.x1 <= xs[i] && xs[i] < r.x2`. The rect must contain the grid cell, not just the integer coordinate.
- `chk.cc:56-59` — Satisfaction formula implementation. Verify against this if scores seem wrong.
- `chk.cc:63-67` — Normalization: `baseline_value` and `best_value` from `.ans` files.
- `config.yaml:6` — Time limit: 10s.
- `testdata/1.in` — Example input: N=143, coordinates and target areas.
- `testdata/1.ans` — `778049231\n993157405` (baseline and best raw scores for test 1).

## Code Targets
- **h-main** (`solution.cpp`): Full implementation with greedy expansion + SA. The solution.cpp in the worktree already contains this implementation.
- **h-control-negative** (`solution.cpp`): Remove the SA while-loop (everything from `// SA` comment to the end of that loop). Output `rects[i]` directly instead of `best_rects[i]`.

## What I Tried That Didn't Work
- **Two-rect SA moves** (shrink one rect, grow its blocker): Added overhead without improving score (83.35 vs 85.31). The O(2N) overlap checks per move halve the iteration count.
- **Weighted rect selection in SA** (bias toward worst-satisfaction rects): Scored 83.98, slightly worse than uniform random. The overhead of weight computation isn't worth the marginal targeting benefit.
- **Aggressive greedy with maxExp-based full expansion**: Rects grow too large in the greedy phase (overshooting target areas), then SA must shrink them back. Small-step greedy that stops at target area is better.
- **Geometric cooling** (T0*pow(T1/T0, progress)): Scored worse than linear cooling. Linear from 0.01 seems well-tuned for this problem.
- **`bits/stdc++.h`**: Not available on the judge's g++ 11 setup. Use explicit includes.

## What I Excluded and Why
- **Multi-restart SA**: Could help but 10s is tight; a single long SA run seems better than multiple short ones given the convergence behavior observed.
- **Space partitioning** (BSP/Voronoi): More complex initialization; the simple greedy+SA already achieves 85.
- **Aspect ratio optimization**: Rects with extreme aspect ratios might be suboptimal, but the satisfaction function only cares about area, not shape.

## Evolution of Thinking
Started with a simple greedy expansion + SA and got 80.42. Tried to improve with more sophisticated moves (two-rect swaps, weighted selection, maxExp-based greedy) — all scored worse. The lesson: for this problem, the SA's iteration throughput matters more than move sophistication. The simpler the per-iteration work, the more iterations fit in 7 seconds, and the better the result.

## Current Status
- **Validated:** Greedy+SA scores 84-85 consistently. Compiles on judge. Output format correct.
- **Uncertain:** Whether different SA parameters (higher T0, different move distribution) could push past 90.
- **Suggested next:** Try alternative initial placements (k-d tree partitioning, weighted Voronoi), or SA with restart on plateaus. Also worth trying a completely different approach like constraint programming or ILP relaxation.

## Warnings & Constraints
- The judge takes ~2-3 minutes to evaluate (100 test cases × 10s timeout each). Budget accordingly.
- Type mismatches `max(int, long long)` cause compile errors on g++ 11 — always use explicit casts.
- The fmeasure_147.sh script changes directory to the Frontier-CS repo — pass absolute paths for solution.cpp.
- Score variance between runs is ±1-2 points due to test-case-level variation in how well the algorithm fits each instance.
