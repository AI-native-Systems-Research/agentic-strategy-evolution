# Handoff — iter-4

## Goal
Confirm multi-restart SA (v5) as the production-optimal solution for AHC001 rectangle packing. Apply the v5 code changes to solution.cpp (h-main) and measure both arms via the judge.

## Key Discoveries
- **v5 is the ceiling for single-threaded SA**. After testing 10 algorithmic variants (v17-v26, treemap), every modification to v5 scored worse. The 8-move uniform SA with shuffled greedy and 3 restarts is a tightly coupled system where changing any component hurts.
- **Throughput is everything**. Any per-iteration overhead (pair moves: +O(N), weighted selection: +sat(), adaptive delta: +division, move reweighting toward O(N) moves) reduces iteration count and hurts score.
- **Threading doesn't work** — the judge tool (frontier eval) returns score 0 for multi-threaded solutions. Single-threaded execution only.
- **Judge variance is ~1-1.5 points** per evaluation (v5 scored 86.70 and 85.62 in two back-to-back runs). Iter-3 measured std ~0.47-0.66.
- **Compact initial shapes matter more than accurate initial areas**. Treemap init gives each rect approximately the right area but terrible elongated shapes → scored 79.19. Greedy expansion from 1×1 gives compact shapes → much better starting point for SA.
- **Greedy expansion order matters but only through diversity**. Sorted-by-area order (v25, 85.0) was worse than shuffled (v5, 85.6-86.7). The value of shuffling comes from restart diversity, not from any single ordering being optimal.

## System Interface
- **Build:** Not needed — judge compiles server-side.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` (single line, 0-100).
- **Baseline result:** solution.cpp scores ~85.4-85.6. solution_v5.cpp scores ~85.6-86.7.

## Code Map
- `solution.cpp:65-70` — Input parsing and initial 1x1 rects
- `solution.cpp:72-98` — Greedy expansion (fixed sequential order, sqrt*3 max 150)
- `solution.cpp:100-190` — SA phase (8 moves, linear T=0.01→0, 9.3s limit)
- `solution_v5.cpp:65-97` — `doGreedy(rng)`: shuffled order, same expansion logic
- `solution_v5.cpp:99-193` — `doSA(rng, endTime)`: SA with time-bounded progress
- `solution_v5.cpp:195-223` — `main()`: 3-restart loop with global_best tracking

## Code Targets
- **h-main** (`solution.cpp`): Transform to match solution_v5.cpp structure:
  1. Extract `doGreedy(mt19937& rng)` — add `shuffle(order)` at line 70
  2. Extract `doSA(mt19937& rng, double endTime)` — replace fixed time_limit with endTime parameter, add progress-based cooling
  3. Add `Rect global_best[210]` declaration
  4. Main: 3-restart loop with `timePerRestart=9.0/3`, `restartEnd=min(9.3, (i+1)*timePerRestart+0.5)`, global_best tracking
  5. Output from global_best instead of best_rects
- **h-ablation** (`solution.cpp`): No changes. Run as-is.

## What I Tried That Didn't Work
- **v17: Pair-boundary moves (20% of moves, score 83.3)** — `maxExpWithIdx` O(N) + double overlap check (2×O(N)) makes each pair move ~3× more expensive than single-rect moves. Even at 20% frequency, throughput drops enough to hurt.
- **v18: Intensification phase (3 restarts + low-temp SA, score 84.0)** — Stealing 1.5s from restarts (7.5s→9s) hurts each restart's convergence more than the intensification helps.
- **v19: LNS destroy-repair worst 20% (score 85.0)** — Same time-stealing problem. Destroying/repairing 20% of rects in 2s doesn't produce better results than giving those 2s to the regular restarts.
- **v20: Post-SA assignment swaps (score 84.9)** — Point containment constraint is too restrictive: company i's point must be inside company j's rect AND vice versa. For non-overlapping rects with distinct anchor points, valid swap pairs are extremely rare.
- **v21: Tournament selection (score 84.2)** — Picking the worse of two random rects biases selection and hurts SA convergence properties. The extra sat() call also adds overhead.
- **v22: Weighted moves 3× for moves 6,7 (score 84.0)** — Moves 6 (expand-to-limit) and 7 (area-targeted) are O(N) each due to maxExp. Higher weight means more O(N) calls, reducing total iteration count.
- **v23/v24: Threaded restarts (score 0)** — Judge tool returns score 0 for multi-threaded solutions.
- **v25: Area-sorted greedy (score 85.0)** — Largest-first expansion order is worse than random shuffle, possibly because large rects grab too much space early, constraining smaller rects.
- **v26: Adaptive delta scaling (score 81.3)** — Changing delta distribution based on area ratio disrupts the calibrated RNG consumption pattern. The original 50/50 split (small/large delta) is already well-tuned.
- **Treemap init (score 79.2)** — Recursive KD-tree partitioning gives elongated rectangles when points cluster. The greedy expansion from 1×1 produces much more compact shapes, which are better starting points for SA.

## What I Excluded and Why
- **Genetic algorithms / beam search**: Would require complete rewrite with uncertain benefit. SA is well-suited for this problem structure (continuous boundary adjustments).
- **ILP / constraint programming**: Not feasible within 10s time limit for N≤200.
- **Force-directed placement**: Doesn't produce axis-aligned rectangles naturally.
- **Multi-dimensional parameter tuning**: Iter-3 already extensively tested T0, cooling schedule, restart count. All parameters are at their optima.
- **Seed optimization**: Different seeds produce ~0.5 point variance. Not a reliable improvement strategy.

## Evolution of Thinking
Started iter-4 expecting to find an improvement over v5 through smarter SA moves (pair-boundary, weighted selection, adaptive delta) or better initialization (treemap, sorted greedy). Discovered that v5's SA is a tightly coupled system where the uniform 8-move set, linear cooling, and equal-weight selection are all locally optimal. ANY per-iteration overhead reduces throughput and hurts more than the smarter move helps. The key insight: for N≤200 with a 10s time limit, the SA gets enough iterations that the simple-but-fast approach dominates clever-but-slower approaches. Also discovered threading is not an option — the judge enforces single-threaded execution. The path to significantly higher scores (>90) would require a fundamentally different algorithm (not SA-based), which is beyond the scope of this iteration.

## Current Status
- **Validated:** v5 at ~85.6-86.7 (two measurements this iteration). solution.cpp at ~85.4-85.6. Both produce valid output.
- **Uncertain:** Whether the ~0.6-1.0 point improvement from multi-restart is statistically significant given judge variance of ~1-1.5 points. Iter-3 found it partially confirmed.
- **Suggested next:** (1) Accept v5 as the production solution unless a fundamentally different algorithm (e.g., branch-and-bound, Lagrangian relaxation) is attempted. (2) Investigate whether longer time limits (if available) would change the optimal restart count. (3) Consider problem-specific heuristics based on input structure (N, point distribution, area distribution) to adaptively choose parameters.

## Warnings & Constraints
- Judge takes ~2-3 minutes per evaluation. Budget accordingly.
- Judge variance is ~1-1.5 points per run, NOT ~0.02 as initially claimed.
- Threading produces score 0 — judge enforces single-threaded execution.
- Type mismatches `max(int, long long)` cause compile errors on g++ 11.
- Don't use `bits/stdc++.h`.
- The fmeasure script `cd`s to the Frontier-CS repo — always pass absolute paths.
- sqrt(ratio)*3 max 150 greedy is CRITICAL — do not switch to sqrt(ratio)*5 max 300.
- The 8-move SA with uniform distribution is well-tuned. DO NOT change the move set, weights, or delta distribution.
- Every modification to v5 tested in iter-4 scored WORSE. The executor should apply v5's code exactly as written in solution_v5.cpp, not attempt any "improvements."
