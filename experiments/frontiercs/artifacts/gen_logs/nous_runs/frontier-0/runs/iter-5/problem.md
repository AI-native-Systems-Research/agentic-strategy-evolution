# Problem Framing — Iteration 5

## Research Question

Does combining per-call pack() speed optimizations (precomputed maxHiP1, orientation-level skip) with increased ordering diversity (5 orderings) and targeted culprit repair produce a consistently higher judge score than the v10 baseline for the polyomino packing problem?

**Key source files:**
- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()` defining CW rotation for the checker.
- `algorithmic/problems/0/chk.cc:107-137` — Validation: reflect→rotate→translate, bounds, overlap checking.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`, reported as partial score.
- `algorithmic/problems/0/config.yaml:4-5` — Time (2s) and memory (256MB) limits.
- `algorithmic/problems/0/examples/reference.cpp:62-207` — Reference packer (human best by Shang Zhou).

## System Interface

- **Build command:** Handled internally by judge (g++ -O2 -std=c++17).
- **CLI:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout where n is the judge score (0-100, higher is better).
- **Time limit:** 2 seconds per test case (70 test cases).
- **Code evidence:**
  - `chk.cc:49-56` — rot90cw CW rotation used by checker.
  - `chk.cc:148` — `double score = (double) totalCells / (double) area;`
  - `chk.cc:150` — `quitp(score, ...)` outputs partial score in [0,1].
  - `config.yaml:4` — `time: 2s`
  - `config.yaml:5` — `memory: 256m`

## Baseline Command

```bash
cp inputs/h-control-negative-solution.cpp solution.cpp
bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp
```

## Baseline Validation

Ran v10 (control) multiple times during exploration:
- Run 1: SCORE: 81.25 (during initial testing)
- Run 2: SCORE: 79.00 (back-to-back pair 1)
- Run 3: SCORE: 82.70 (back-to-back pair 2)
- Iter-4 reference: mean 82.71, std 0.11 (3 seeds)

System load varies significantly during this session, causing score variance of ~4 points (vs iter-4's 0.21 range for v10). Back-to-back paired comparison is essential to control for load drift.

Also validated v12 (treatment):
- Run 1: 82.72, Run 2: 85.29, Run 3: 86.54, Run 4: 78.78
- Paired with v10: +6.29 (pair 1), +3.84 (pair 2) — both positive.

Reference solution (human best): 83.72, 84.98 in two runs.

## Experimental Conditions

### h-main: v12 (speed-optimized + ordering diversity + culprit repair)
Copy `inputs/h-main-solution.cpp` to `solution.cpp` and run the judge.

Changes from v10:
1. **Precomputed maxHiP1 in Trans struct** (h-main-solution.cpp:34, lines 102-104): Eliminates O(tw) recomputation per orientation per candidate per step. For large instances with dynLIM=30 and 8 orientations per piece, this saves ~7M operations per pack() call.
2. **Orientation-level skip** (h-main-solution.cpp:199-203): When a piece orientation's minimum possible height already exceeds the current best placement, the entire orientation is skipped. Saves full inner-loop evaluation.
3. **5 orderings** (h-main-solution.cpp:117-152): Adds orderDecDim (descending minimum dimension) and orderAscK (ascending cell count) to the 3 existing orderings. Phase 2 tries all 4 alt orderings at bestWidth±2.
4. **Culprit repair** (h-main-solution.cpp:429-459): After Phase 2, identifies up to 5 pieces touching the height boundary. For each, repacks with that piece deferred to the end of the ordering, potentially reducing height by 1+ rows.

### h-control-negative: v10 (iter-4 established baseline)
Copy `inputs/h-control-negative-solution.cpp` to `solution.cpp` and run the judge.

This is the unmodified iter-4 v10 solution: unified time allocation, position-level early termination, 3 orderings, random restart. No culprit repair, no precomputed maxHiP1.

## Success Criteria

- v12 (h-main) achieves a higher mean score than v10 (h-control-negative) across 3 seeds.
- Paired difference is positive in at least 2 of 3 seed pairs.
- Effect size is detectable above the load-induced variance (~4 points in current session).

## Constraints

- 2-second time limit per test case (70 test cases).
- 256MB memory limit.
- Judge call takes ~60-75 seconds. Budget 3 seeds × 2 arms = 6 runs ≈ 7-8 minutes.
- Run arms alternately (v12 seed42, v10 seed42, v12 seed43, ...) to control for load drift.

## Prior Knowledge

- **RP-1** (high confidence): Skyline greedy + multi-width sweep produces ~2x the score of naive strip packing.
- **RP-2** (high confidence): Transform parameter recovery (reflect→rotate→translate) must match checker convention exactly.
- **RP-3** (high confidence): Score variance from system load is ~6 points for v7, reduced to std 0.11 for v10 via unified time allocation. However, current session shows much higher variance, possibly due to heavier system load.
- **RP-4** (high confidence): Dynamic lookahead (K=n/4) is the dominant improvement mechanism, contributing ~63% of score improvement.
- **RP-5** (high confidence): Secondary improvements (roughness tiebreaker, column compaction, multi-ordering) contribute ~4 points.
- **RP-6** (medium confidence): Gap-filling during skyline packing produces no detectable improvement.
- **RP-7** (high confidence): Unified time allocation reduces run-to-run variance by ~25x.

Key dead ends from previous iterations:
- Gap-filling (iter-3): +0.50 points, not significant.
- Coarse-to-fine K=1 scout (iter-4 design): scored 68.10, fundamentally flawed.
- GPT5 shelf packing: scored 0, invalid output.
- K=n for small instances (v11): slows pack() without sufficient quality benefit.
