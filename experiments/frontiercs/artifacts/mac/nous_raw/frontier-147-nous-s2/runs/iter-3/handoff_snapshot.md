# Handoff — iter-3

## Goal
Confirm multi-restart SA (v5) as the best strategy for AHC001 rectangle packing. Apply the v5 code changes to solution.cpp (h-main) and measure both arms.

## Key Discoveries
- **v5 scores 87.55 reliably** (two measurements: 87.57, 87.55). Single-run SA scores 85.44.
- **Iteration throughput is king.** Every modification that adds per-iteration overhead (spatial grid, neighbor-swap moves, weighted selection) scored worse than the vanilla SA.
- **Careful greedy matters more than SA time.** Small steps (sqrt(ratio)*3, max 150) produce much better initial states than large steps (sqrt(ratio)*5, max 300), even though they take longer. Score difference: ~4 points.
- **3 restarts is optimal.** 2 restarts (85.1) and 5 restarts (83.5-86.0) both score worse. 3 balances diversity vs SA convergence time.
- **T=0.01 is optimal.** T=0.015 scored 82.6 (too much exploration), T=0.02 scored 84.6 (iter-2). Linear cooling beats quadratic cooling.
- **Translation moves help.** Removing moves 4-5 (translate rect) scored 84.5 vs 87.55 with them. Even with low acceptance rate in crowded space, successful translations provide unique basin-crossing moves.
- **Judge variance is ~0.02 points** for deterministic solutions, not ±2 as previously believed. The ±2 range in iter-2 was comparing different algorithms, not repeat runs.

## System Interface
- **Build:** Not needed — judge compiles server-side.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` (single line, 0-100).
- **Baseline result:** 85.44 (solution.cpp), 87.55 (solution_v5.cpp).

## Code Map
- `solution.cpp:65-70` — Input parsing and initial 1x1 rects
- `solution.cpp:72-98` — Greedy expansion (fixed order, sqrt*3 max 150)
- `solution.cpp:100-190` — SA phase (8 moves, linear T=0.01→0)
- `solution_v5.cpp:65-97` — `doGreedy(rng)`: shuffled order, same expansion
- `solution_v5.cpp:99-193` — `doSA(rng, endTime)`: SA with time-bounded progress
- `solution_v5.cpp:195-223` — `main()`: 3-restart loop with global_best tracking

## Code Targets
- **h-main** (`solution.cpp`): Refactor into `doGreedy(rng)` + `doSA(rng, endTime)`. Add `global_best[210]`. Main loop: 3 restarts with `shuffle(order)`, `timePerRestart=9.0/3`, `restartEnd=min(9.3, (i+1)*timePerRestart+0.5)`. Keep `global_best`. Reference implementation: `solution_v5.cpp`.
- **h-ablation** (`solution.cpp`): No changes. Run as-is.

## What I Tried That Didn't Work
- **Neighbor-swap SA moves (v6, 85.2):** findNeighbor O(N) + double overlap check per move halves throughput.
- **Weighted rect selection (v7, 85.1):** 50% uniform / 50% weighted. Weight computation + cumulative search adds overhead without improving convergence.
- **Quadratic cooling (v8, 84.6):** Spends too long at high temp, too little at low temp for fine-tuning.
- **Recursive bisection init (v10, 30.2):** Split-point calculation fails when points cluster. Completely broken.
- **Spatial grid collision (v11, 84.7):** Grid maintenance (vector erase/insert) costs more than O(N) linear scan for N≤200.
- **2 restarts (v12, 85.1):** Less diversity than 3 restarts. Worse than even single-run SA.
- **No translation moves (v13, 84.5):** Translations provide rare but valuable basin-crossing moves.
- **5 restarts + fast greedy (v14, 83.5):** Fast greedy (sqrt*5, max 300) produces much worse initial states.
- **T0=0.015 (v15, 82.6):** Higher temp accepts too many bad moves.
- **Hybrid 3-short + finishing SA (v16, 85.0):** Finishing SA from best restart doesn't improve over letting each restart run longer.

## What I Excluded and Why
- **Constraint programming / ILP:** Too complex for 10s time limit with N≤200.
- **Force-directed placement:** Doesn't naturally produce axis-aligned rects.
- **Adaptive restart count:** Diminishing returns over fixed 3 restarts.
- **Better scoring function (non-quadratic penalty):** The problem statement fixes the scoring formula.

## Evolution of Thinking
Started iter-3 expecting to improve SA with smarter moves (neighbor swaps, weighted selection, spatial indexing). All of these added overhead that hurt the iteration count, which is the single most important factor. Then tried structural changes (bisection init, different restart counts, hybrid approaches). These all scored worse because: (1) the careful greedy produces surprisingly good initial states, and (2) 3 restarts is a well-calibrated balance between diversity and convergence time. The key insight: for N≤200, the problem is small enough that brute-force O(N) collision checking is optimal — no fancy data structure can beat it. The only real improvement over single-run SA is restart diversity via shuffled greedy ordering.

## Current Status
- **Validated:** v5 at 87.55 (two independent runs). solution.cpp at 85.44. Both consistent.
- **Uncertain:** Whether the ~2-point improvement is statistically significant given that each judge eval uses different test subsets (need to verify this). Also uncertain whether 4 restarts with more careful timing could beat 3.
- **Suggested next:** (1) Try fundamentally different approaches: LP relaxation, assignment-based formulation. (2) Implement proper recursive bisection with guaranteed point containment as SA initialization. (3) Investigate whether test-case-specific tuning (adaptive restart count based on N) helps.

## Warnings & Constraints
- Judge takes ~2-3 minutes per evaluation. Budget accordingly.
- Judge variance is ~0.02 points for identical solutions, not ±2 as previously stated.
- Type mismatches `max(int, long long)` cause compile errors on g++ 11.
- Don't use `bits/stdc++.h`.
- The fmeasure script `cd`s to the Frontier-CS repo — always pass absolute paths.
- sqrt(ratio)*3 max 150 greedy is CRITICAL — do not switch to sqrt(ratio)*5 max 300.
- The 8-move SA with uniform distribution is well-tuned. Don't change the move set.
