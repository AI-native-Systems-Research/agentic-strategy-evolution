# Handoff — Polyomino Packing (Iteration 4)

## Goal

Measure the judge score for two algorithmic strategies: (1) v10 — skyline packer with unified time allocation, position-level early termination, fast I/O, and random-restart ordering diversity (h-main), and (2) v7 — the established skyline packer with 60/40 time split (h-control-negative). Copy the respective `.cpp` files from `inputs/` to `solution.cpp` and run the judge once per arm per seed.

## Key Discoveries

- **Unified time allocation vs 60/40 split:** v7 reserves 40% of the 2s budget for Phase 2 (alt orderings at bestWidth ±3). For big instances (totalCells > 7000), each pack() call takes ~200-500ms, so this 40% reservation costs 2-4 width-sweep opportunities. v10 eliminates this reservation, giving the primary sweep access to ~66% more time.
- **Position-level early termination works:** Two checks in the inner placement loop (h-main-solution.cpp:185-199) skip expensive deltaSum and roughDelta computation for ~40% of positions where `max(maxH, y0 + maxHiP1) > bestScore2`. This makes each pack() call ~10-20% faster.
- **Random restart is a new mechanism:** After the primary width sweep and 2 fixed alt orderings, v10 uses remaining time for shuffled-ordering restarts at bestWidth ±1 (h-main-solution.cpp:397-418). For small instances (n≤300, ~5ms/pack), this gives ~250+ restarts. For big instances, no time remains so no overhead.
- **Score variance is ~6 points** due to system load affecting the time-managed width sweep (RP-3). This makes the marginal improvement from v10 (predicted +1-3 points) hard to detect in single measurements.
- **Design probes were inconclusive on direction:** v10 scored 81.45, 82.73; v7 scored 82.56, 82.33 in back-to-back pairs. Both are within noise. The experiment needs 3 seeds with paired comparison to detect a reliable signal.
- **Gap-filling (iter-3) was not significant.** v10 does NOT include gap-filling.
- **Coarse-to-fine was harmful.** A K=1 scout pass to pre-screen widths scored 68.10 — the K=1 quality doesn't predict K=n/4 quality. Removed from v10.

## System Interface

- **Build:** Handled internally by judge (g++ -O2 -std=c++17)
- **Run:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100)
- **Baseline result:** v7 = 82.56, 82.33 (two runs during design); v10 = 81.45, 82.73

## Code Map

- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()`: CW rotation. Check here if placements are invalid.
- `algorithmic/problems/0/chk.cc:107-137` — Validation: reflect→rotate→translate, bounds, overlap. Check here if score is 0.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`. Check here for scoring formula.
- `algorithmic/problems/0/config.yaml:6-7` — Time (2s) and memory (256MB) limits.
- `algorithmic/problems/0/examples/reference.cpp:62-207` — Reference packer (Shang Zhou, human best).

## Code Targets

### h-main (v10: unified sweep + early termination + random restart)
- **Source:** `inputs/h-main-solution.cpp` → copy to `solution.cpp`
- **Fast I/O:** Lines 10-24 (custom fread-based scanner)
- **Early termination:** Lines 174-199 (quick check + exact check in inner loop)
- **Unified sweep:** Lines 353-369 (all time for primary ordering)
- **Random restart:** Lines 397-418 (mt19937 shuffle at bestWidth ±1)

### h-control-negative (v7: 60/40 time split baseline)
- **Source:** `inputs/h-control-negative-solution.cpp` → copy to `solution.cpp`
- **This is the unmodified iter-2/iter-3 baseline.** No changes needed.

## What I Tried That Didn't Work

- **Coarse-to-fine width search (K=1 scout):** Quick-evaluate all widths with K=1 lookahead, then concentrate full K=n/4 on the best candidates. Scored 68.10 (vs v7's ~80). The K=1 packing quality doesn't correlate with K=n/4 quality — the best K=1 width was often the worst K=n/4 width. **Dead end — do not retry.**
- **Gap-filling (iter-3 v8):** Bitmap-based gap scan during placement. +0.50 points mean, p>>0.05. Not significant. Adds per-call overhead.
- **Post-placement gravity compaction (iter-3):** Added ~300ms overhead for no reliable improvement.
- **Extra orderings (6 instead of 3, iter-3):** Diluted time budget without gains.
- **GPT5 shelf packing (gpt5.cpp in examples/):** Scored 0 — produces invalid output. The shelf/NFDH paradigm is fundamentally inferior for this problem because it can't fill irregular gaps.

## What I Excluded and Why

- **Simulated annealing / local search:** After greedy placement, perturb placements. Too complex for 2s, and greedy+lookahead is already near-optimal for k=1-10.
- **Full BL bitmap packing:** O(W*H*k) per piece, too slow for n=10000. Could work for small instances but adds code complexity.
- **Low-point targeting (valley-only position search):** Only try placing pieces at skyline valleys instead of all positions. Could provide ~6x speedup for big instances. Not implemented due to risk of quality loss (some non-valley positions are better). **Highest-priority suggestion for iter-5.**
- **Adaptive width search (golden section, Bayesian):** Replace linear sweep with smarter width optimization. Could reduce the number of pack() calls needed to find the optimal width. Not attempted due to complexity and the risk that the score-vs-width landscape is multimodal.
- **Instance-adaptive strategy switching:** Use totalCells to choose between different algorithms (e.g., BL for small, skyline for large). Not attempted due to the investment needed to implement a second algorithm.

## Evolution of Thinking

Started iter-4 by comparing v7 and the reference solution. Found them algorithmically identical — the reference scores ~86 on faster systems, ~79-82 on ours. The gap is purely time-budget-driven.

Focused on time efficiency: unified allocation (removing the 60/40 split) and early termination (skipping expensive computations for unpromising positions). These are constant-factor speedups that translate directly to more widths explored in the time budget.

Added random restart as a novel mechanism — shuffled orderings explore a different part of the search space than the 3 fixed orderings. The lookahead provides some ordering robustness (K=n/4 means 25% of remaining pieces are examined), but random ordering can still produce different lookahead windows at each step.

Key insight: **we are in diminishing returns territory for greedy skyline packing.** The iter-1→iter-2 jump was +11 points (lookahead). The iter-2→iter-3 jump was +0.50 points (gap-filling, not significant). Iter-4 targets another marginal improvement. To break out of the ~83 plateau, a fundamentally different approach (local search, constraint programming, or population-based methods) would be needed, but the 2s time limit severely constrains such approaches.

## Current Status

- **Validated:** Both solutions compile, produce valid output, and score in expected range (80-84).
- **Uncertain:** Whether v10's composite optimization produces a detectable improvement over v7. Design probes show both in the same range.
- **Suggested next (iter-5):**
  1. **Low-point targeting:** Reduce the inner-loop position search to skyline valleys plus a small margin. This could provide ~6x speedup for big instances, enabling dramatically more width exploration and reducing load-induced variance. This is the highest-leverage remaining optimization.
  2. **Partial-sort ordering:** Instead of sorting all n pieces, maintain a priority queue of the K best candidates. This reduces orientation-generation overhead.
  3. **Instance-class analysis:** Profile which of the 70 test cases contribute most to score loss. Optimize the algorithm for the worst-performing cases (likely the largest n=10000 instances).

## Warnings & Constraints

- **Judge call takes ~60-75s.** Budget ~5 minutes per full run (3 seeds × 2 arms = 6 runs ≈ 7-8 minutes total).
- **The judge compiles internally.** Don't compile separately.
- **Transform order matters.** Checker: reflect (F=1 → negate x) → rotate (R CW rotations) → translate (add X,Y). Both solutions use CW rotation matching the checker's convention.
- **Score depends on system speed.** Both solutions use time management (1980ms budget). Load-induced variance is ~6 points (RP-3).
- **Back-to-back comparison is essential.** Run v10 and v7 alternately (not sequentially) to control for system load drift.
- **v10's `goto phase3` label:** The alt-ordering block uses `goto phase3` to jump to the random restart phase when time runs out. This is correct but may look unusual.
- **Column compaction correctness.** Relies on 4-connected polyominoes having contiguous column projections. Mathematically guaranteed.
