# Handoff — iter-2

## Goal
Implement multi-restart SA for AHC001 rectangle packing (h-main) and compare against the single-run SA baseline (h-ablation). Measure each with `fmeasure_147.sh`.

## Key Discoveries
- **Multi-restart works.** 3 restarts with shuffled greedy ordering scored 86.6 in one probe (vs 84.5 baseline). Judge variance is ±2 points, so multiple runs recommended.
- **3 restarts is the sweet spot.** 5 restarts (86.0) and quick-restarts+long-final (86.4) both scored lower. The SA needs ~2.5s per restart to converge.
- **Faster greedy with larger steps.** Using `sqrt(ratio)*5, max 300` instead of `sqrt(ratio)*3, max 150` reduces greedy time to ~0.3s (from 1.5-2s). This is critical for fitting 3 restarts in 9s.
- **BSP initialization is bad.** Scored 72.5 — creates cells with wrong areas relative to targets. Don't revisit.
- **Temperature tuning is marginal.** T0=0.02 scored 84.6 vs T0=0.01 at 84.5. Not worth the complexity.
- **Judge variance is ±2 points.** Each `fmeasure_147.sh` call uses potentially different test subsets. Run each arm at least once but expect noise.

## System Interface
- **Build:** Not needed — judge compiles server-side.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` (0-100).
- **Baseline result:** 84.5 (current solution.cpp).

## Code Map
- `solution.cpp:72-98` — Greedy expansion phase. Fixed processing order. This is what gets shuffled in h-main.
- `solution.cpp:100-190` — SA phase. 8 moves, linear cooling T=0.01→0 over ~7s.
- `solution.cpp:46-63` — `maxExp()` function. O(N) per call. Used by SA moves 6 and 7.
- `solution_v5.cpp` — Working implementation of multi-restart SA (h-main). Can be used as reference.
- `chk.cc:48` — Point containment check: `r.x1 <= xs[i] && xs[i] < r.x2` (half-open).
- `chk.cc:56-59` — Satisfaction formula.

## Code Targets
- **h-main** (`solution.cpp`): Refactor into `doGreedy(rng, maxTime)` + `doSA(rng, endTime)`. Main loop: 3 restarts with `shuffle(order)` before each greedy. Keep `global_best` across restarts. Use `sqrt(ratio)*5, max 300` greedy steps. Reference implementation: `solution_v5.cpp`.
- **h-ablation** (`solution.cpp`): The current solution.cpp unchanged (single greedy + single SA). No code change needed — just run it.

## What I Tried That Didn't Work
- **BSP initialization (72.5):** Recursive space partitioning creates cells that don't match target areas at all. The partition is area-weighted but geometric constraints (splitting along one axis) create bad aspect ratios.
- **Sorted greedy by worst satisfaction (83.6):** Sorting adds O(N log N) overhead per round and calling sat() in the comparator is wasteful. Also combined with lower T0=0.008 which made SA too selective.
- **Weighted rect selection in SA (v2, 83.6):** Tournament selection (pick 2 random, choose worse-sat) adds overhead without improving convergence.
- **5 restarts (86.0):** Each restart only gets ~1.6s of SA time, not enough for convergence. Diminishing returns on diversity.
- **Quick restarts + long final SA (86.4):** Starting SA from a prior SA result doesn't help as much as starting from a fresh greedy.
- **T0=0.015 with different timing formula (84.3):** Something wrong with the timing — likely the greedy took too long with `sqrt(ratio)*3` steps.

## What I Excluded and Why
- **Spatial grid indexing for faster overlap checking:** Would increase iteration count but adds implementation complexity. With N≤200, the O(N) check takes ~200 comparisons which is fast enough. The restart strategy is a higher-level improvement.
- **Boundary-swap compound moves (solution_v3.cpp):** `findNeighbor()` adds O(N) work per move call. Combined with O(N) overlap checking for two rects, this roughly halves iteration throughput. Iter-1 showed that simple moves = more iterations = better score.
- **Different SA move distributions:** Uniform over 8 moves was best in iter-1. Biasing toward expand-to-limit or target-aware moves didn't help.
- **Constraint programming / ILP:** Too complex for the 10s time limit and N≤200 problem size.

## Evolution of Thinking
Started iter-2 looking for SA improvements (better moves, spatial indexing, BSP init). All targeted improvements to the SA inner loop performed worse — confirming iter-1's finding that iteration throughput is king. The breakthrough came from a higher-level structural change: instead of one long SA run, use multiple restarts with diverse starting points. The randomized greedy ordering is the simplest way to create diversity. This is analogous to random restarts in other metaheuristics — it explores multiple basins of attraction instead of drilling deep into one.

## Current Status
- **Validated:** Multi-restart SA (solution_v5.cpp) produces valid output, compiles on judge, scores 84-87 range. Single-run SA (solution.cpp) scores 84-85.
- **Uncertain:** Whether the ~2-point improvement from restarts is real or noise. Judge variance (±2) is comparable to the effect size. Multiple runs would help distinguish.
- **Suggested next:** (1) Longer runs or averaging to reduce judge variance. (2) Try SA with move that simultaneously shifts a boundary shared between two adjacent rects (properly implemented — not the v3 attempt). (3) Adaptive restart count based on score plateau detection. (4) Try fundamentally different approach: formulate as assignment problem + LP relaxation.

## Warnings & Constraints
- Judge takes ~2-3 minutes per evaluation. Budget accordingly.
- Judge variance is ±2 points — don't over-interpret single-run differences of <3 points.
- Type mismatches `max(int, long long)` cause compile errors on g++ 11.
- Don't use `bits/stdc++.h`.
- The fmeasure script `cd`s to the Frontier-CS repo — always pass absolute paths.
- The greedy step size matters: `sqrt(ratio)*5, max 300` converges in ~0.3s; `sqrt(ratio)*3, max 150` takes ~1.5s. This is critical for restart timing.
