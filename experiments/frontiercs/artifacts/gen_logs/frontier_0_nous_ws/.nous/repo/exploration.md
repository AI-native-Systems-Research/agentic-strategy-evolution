# Handoff — Polyomino Packing (Iteration 5)

## Goal

Measure the judge score for two algorithmic strategies: (1) v12 — skyline packer with precomputed maxHiP1, orientation-level skip, 5 orderings, and culprit repair (h-main), and (2) v10 — the established iter-4 baseline (h-control-negative). Copy the respective `.cpp` files from `inputs/` to `solution.cpp` and run the judge once per arm per seed. Run arms in alternating order to control for system load drift.

## Key Discoveries

- **v12 improvements are composite, not single-mechanism:** Four changes from v10: (a) precomputed maxHiP1 in Trans struct eliminates inner-loop recomputation, (b) orientation-level skip avoids evaluating entire orientations when lower bound exceeds current best, (c) 5 orderings instead of 3, (d) culprit repair that defers height-boundary pieces. The speed improvements (a, b) enable more width exploration; the quality improvements (c, d) improve packing at each width.
- **K=n for small instances HURTS performance:** v11 used K=n for n≤500, which slowed pack() calls significantly for medium instances (n=300-500), reducing width exploration. v12 reverts to K=n/4 for all instances. This was validated: v12 scored 82.72 vs v11's 81.95 in the same session.
- **System load variance is extreme in this session:** v10 ranged from 79.00 to 82.70 (3.70 point range) vs iter-4's 0.21 range. v12 ranged from 78.78 to 86.54. Paired comparisons are ESSENTIAL — v12 beat v10 by +6.29 and +3.84 in back-to-back pairs.
- **Reference solution scores ~83-85 on current hardware:** The human-best reference (Shang Zhou) scored 83.72 and 84.98 in two runs. It uses a simpler structure (no Phase 2/3, single ordering) but identical core algorithm. v12 sometimes beats it, sometimes doesn't, depending on load.
- **The packing score formula:** `score = totalCells / area` per test case, averaged over 70 test cases. A 1-row height reduction on a W=50 instance saves 50 area → score improves by totalCells/50 relative.

## System Interface

- **Build:** Handled internally by judge (g++ -O2 -std=c++17)
- **Run:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100, higher is better)
- **Baseline result:** v10 = 79.00-82.70 (current session), 82.71 ± 0.11 (iter-4 mean±std)

## Code Map

- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()`: CW rotation. Check here if placements are invalid.
- `algorithmic/problems/0/chk.cc:107-137` — Validation: reflect→rotate→translate, bounds, overlap. Check here if score is 0.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`. Check here for scoring formula.
- `algorithmic/problems/0/config.yaml:4-5` — Time (2s) and memory (256MB) limits.
- `algorithmic/problems/0/examples/reference.cpp:62-207` — Reference packer (Shang Zhou, human best).

## Code Targets

### h-main (v12: speed-optimized + 5 orderings + culprit repair)
- **Source:** `inputs/h-main-solution.cpp` → copy to `solution.cpp`
- **Precomputed maxHiP1:** Lines 34 (struct field), 102-104 (computation during orientation generation)
- **Orientation-level skip:** Lines 199-203 (check in inner loop)
- **5 orderings:** Lines 117-152 (added orderDecDim, orderAscK)
- **Phase 2 with 4 alt orderings:** Lines 399-418
- **Culprit repair:** Lines 429-459 (identifies height-boundary pieces, repacks with them deferred)
- **Phase 3 random restart:** Lines 462-477

### h-control-negative (v10: iter-4 baseline)
- **Source:** `inputs/h-control-negative-solution.cpp` → copy to `solution.cpp`
- **This is the unmodified iter-4 v10 solution.** No changes needed.

## What I Tried That Didn't Work

- **K=n for small instances (v11 approach):** Used K=n instead of K=n/4 for n≤500. Scored 81.95 vs v12's 82.72 in same session. The increased lookahead quality doesn't compensate for the reduced width exploration from slower pack() calls. **Dead end — do not retry.**
- **Coarse-to-fine width search (K=1 scout):** Scored 68.10 in iter-4 design. K=1 quality doesn't predict K=n/4 quality. **Dead end.**
- **Gap-filling (iter-3 v8):** +0.50 points mean, p>>0.05. Not significant. **Dead end.**
- **Post-placement gravity compaction (iter-3):** Added ~300ms overhead for no reliable improvement.
- **GPT5 shelf packing:** Scored 0 — invalid output. NFDH paradigm is fundamentally inferior for irregular polyominoes.

## What I Excluded and Why

- **Stochastic tiebreaking (from reference):** The reference solution has a `randtie` parameter that's actually dead code (never activated). Implementing it for our random restart phase was considered but dropped because: (a) ties on all 6 criteria (gg, deltaSum, localH, roughDelta, y0, x0) are extremely rare for non-identical pieces, (b) the random restart already provides diversity via shuffled orderings.
- **Bottom-left (BL) bitmap packing:** O(W*H*k) per placement, way too slow for large instances. For n=10000: ~15-20 seconds per pack() call vs our ~200-500ms. Not feasible within 2s time limit.
- **Adaptive width search (golden section, Bayesian):** Score-vs-width landscape may be multimodal. Risk of getting stuck at local minimum.
- **Beam search:** Maintaining B parallel partial packings. Feasible for small instances but memory/time prohibitive for n=10000.
- **Reference solution as-is:** Considered using the reference directly. It scores ~83-85 on our hardware with a simpler structure (no Phase 2/3). However, v12 adds early termination and Phase 2/3 improvements that should outperform on average. Using the reference wouldn't represent an original contribution.

## Evolution of Thinking

Started by testing the v11 solution from a prior interrupted attempt. Found that K=n for small instances actually hurt performance by slowing pack() and reducing width exploration. Created v12 by reverting K to n/4 while keeping the other v11 improvements.

Discovered that system load is extremely variable in this session (score ranges of 7+ points for both v12 and v10). This made single-run comparisons unreliable, but paired back-to-back comparisons showed v12 consistently beating v10 by 4-6 points.

Tested the reference solution for calibration. It scored 83.72-84.98, overlapping with v12's range (78.78-86.54). The reference's simpler structure (no Phase 2/3) might be more load-resistant, but v12's speed optimizations should give it an edge on average.

Key insight: **we may be approaching the hardware-limited ceiling.** The reference (human best) scores ~83-85 on our hardware. v12 overlaps this range. Further improvements likely require either fundamentally faster pack() operations or a different algorithm paradigm (local search, constraint programming).

## Current Status

- **Validated:** Both v12 and v10 compile, produce valid output, and score in expected ranges.
- **Uncertain:** Whether v12's improvement over v10 is statistically significant given the high load variance. Paired comparisons suggest yes (+3.84 to +6.29), but only 2 pairs were tested.
- **Suggested next (iter-6):**
  1. **Deterministic speed measurement:** Profile pack() call times for v12 vs v10 on specific test cases to quantify the speed improvement independent of load.
  2. **Hybrid approach:** Use v12's structure for large instances (where width exploration dominates) and the reference's simpler structure for small instances (where Phase 2/3 alt orderings add value without time cost).
  3. **Local search post-processing:** After greedy, try repositioning the worst-scoring pieces (those contributing most to height). This is a fundamentally different mechanism that could break through the ~85 plateau.
  4. **Instance-adaptive width search:** Analyze which of the 70 test cases have the worst packing ratios and design width ranges specifically for those instance sizes.

## Warnings & Constraints

- **Judge call takes ~60-75s.** Budget ~5 minutes per full run (3 seeds × 2 arms = 6 runs ≈ 7-8 minutes total).
- **The judge compiles internally.** Don't compile separately — the judge uses g++ -O2 -std=c++17.
- **Transform order matters.** Checker: reflect (F=1 → negate x) → rotate (R CW rotations) → translate (add X,Y). Both solutions use CW rotation matching the checker's convention.
- **Score depends on system speed.** Both solutions use time management (1980ms budget). Load-induced variance is currently ~7 points (much higher than iter-4's ~0.21 for v10).
- **Back-to-back comparison is essential.** Run v12 and v10 alternately (v12-seed42, v10-seed42, v12-seed43, ...) to control for system load drift. Do NOT run all v12 seeds first then all v10 seeds.
- **v12's `goto phase3` label:** The alt-ordering block uses `goto phase3` to jump to the culprit repair / random restart phase when time runs out. This is correct but may look unusual.
- **Column compaction correctness.** Relies on 4-connected polyominoes having contiguous column projections. Mathematically guaranteed.