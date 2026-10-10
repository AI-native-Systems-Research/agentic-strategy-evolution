# Handoff — Iteration 3

## Goal

Verify that adding break-and-extend for very sparse graphs (avg_deg < 4) improves the Hamiltonian Path score from 82 to 83, with the gain coming from test 10.

## Key Discoveries

1. **Break-and-extend achieves k=25777 on test 10** (n=100K, avg_deg=3), crossing the 23333 threshold for 1 point. Previous approaches (rotation-only) were stuck at ~21000. The mechanism works because ~99% of path vertices have unvisited out-neighbors, but rotation can't access them since they're not at the tail.

2. **Multi-restart with short budget (0.2s) outperforms fewer long attempts** on very sparse graphs. 15-16 attempts in 3.1s produces better results than 6-7 attempts at 0.5s each. This is because construction + break-extend each take ~0.1s, and additional time per attempt has diminishing returns.

3. **Phase 1 timing is critical for test 7.** Reducing Phase 1 below 3.0s causes test 7 to regress from k=4000 (10/10) to k=3805 (5/10). The standard path MUST preserve the exact Phase 1/Phase 2 structure from v12 (iter-2 h-main).

4. **Phase 2 start vertex selection affects test 7.** The v12 Phase 2 uses `(rng_md()%N)+1` for ALL attempts. Using predefined start vertices from the starts[] array changes the RNG state inside solveRotation, causing different results on test 7.

5. **avg_deg < 4 is the correct branching threshold.** Test 10 (avg_deg=3) benefits from break-and-extend. Test 8 (avg_deg=5.44) and test 7 (avg_deg=6) need the standard Phase 1/2 pipeline. No test with avg_deg >= 4 benefits from break-and-extend.

6. **The solution is deterministic.** Score of 83 is perfectly stable across 5 consecutive runs. No timing variance observed.

## System Interface

- **Build:** `g++ -O2 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <float>` on stdout
- **Baseline result:** SCORE: 83 (stable across 5 runs)

## Code Map

- `solution_iter3.cpp:24-199` — `solveRotation()`: linked-list Pósa rotation with greedyMode parameter. Check here if tests 1-9 regress.
- `solution_iter3.cpp:201-303` — `solveBreakExtend()`: the new break-and-extend solver. Check here if test 10 underperforms.
- `solution_iter3.cpp:270-303` — Break loop: finds nearest escape vertex from tail, truncates, redirects, re-extends. This is the core mechanism under test.
- `solution_iter3.cpp:306-539` — `solveDAG()`: SCC decomposition via iterative Kosaraju. Check here if test 4 regresses.
- `solution_iter3.cpp:581` — Branching condition `avgDeg < 4.0 && N > 2000`. If a test unexpectedly takes the wrong branch, check avg_deg.
- `solution_iter3.cpp:596` — Per-attempt budget `0.2`. If test 10 drops below 23333, try increasing this.
- `solution_iter3.cpp:601-623` — Standard path: Phase 1 (seed 42 to 3.0s) + Phase 2 (max-degree to 3.5s). MUST remain identical to v12 to avoid regressions.

## Code Targets

### h-main: solution_iter3.cpp → solution.cpp
- Copy `solution_iter3.cpp` to `solution.cpp` — the file already contains all changes
- The diff from iter-2 solution is: +`solveBreakExtend()` function + modified `main()` with adaptive branching
- The standard path (tests 1-9) is byte-identical to iter-2 main()

### h-control-negative: Use the original solution.cpp from iter-2
- The v12 solution (iter-2 h-main) is stored at the start of this iteration
- It scores 82 consistently (verified in iter-2)

## What I Tried That Didn't Work

1. **Early exit from Phase 1 based on coverage < 80%** — caused test 7 regression (k=3805 vs k=4000). Test 7 has only 38% coverage at 1.5s, triggering early exit, which changes Phase 2's timing and misses the restart that finds k=4000.

2. **Using starts[] array for Phase 2 start vertices** — changed RNG state inside solveRotation, causing different results on test 7 vs v12. Must use `(rng_md()%N)+1` for all Phase 2 attempts.

3. **0.5s per-attempt budget for break-and-extend** — only 7 attempts in 3.5s, best result k=19767. Reducing to 0.2s gives 15+ attempts and k=25777.

4. **Full N-vertex scan in break loop** — O(N) per break iteration is too expensive for N=100K. Replaced with tracking removed vertices (O(dist) per iteration, where dist is typically small).

5. **Kick-and-restart (random path puncture)** — probe_kick.cpp: removing random tail vertices and restarting is too destructive (k=5596 vs k=6414 baseline on test 8).

## What I Excluded and Why

- **Test 8 optimization:** k=5638, needs 6977 for next threshold (3/10). Gap is 1339 vertices (~15%). Would require a fundamentally different approach (possibly 2-opt or Lin-Kernighan style moves). Excluded because the marginal gain (1 point) requires significant complexity.
- **Break-and-extend for test 8 (avg_deg=5.44):** Tested in probes — max-degree restarts are more effective at this density. Break-and-extend doesn't help because escape vertices are more common (higher degree), making the truncate-redirect less impactful.
- **Deeper rotation optimization:** RP-5 establishes a rotation ceiling. No amount of rotation tuning will break through on tests 8/10.

## Evolution of Thinking

Started with the assumption that break-and-extend could be integrated as a Phase 3 after Phase 1/2 (with ~0.5s remaining). Discovered this doesn't work because: (a) break-and-extend needs >2s for good results on N=100K, and (b) modifying Phase 1 timing to free up time causes test 7 regression.

Shifted to an adaptive branching approach: sparse graphs (avg_deg < 4) take an entirely different code path, skipping Phase 1/2 entirely. This preserves the proven Phase 1/2 pipeline for tests 1-9 while giving break-and-extend the full time budget for test 10.

Key insight: the per-attempt budget matters more than total time. Short attempts (0.2s) with many restarts beat long attempts (0.5s) with fewer restarts because the greedy construction is fast (~0.02s) and diminishing returns set in quickly within each attempt.

## Current Status

- **Validated:** Score 83, stable across 5 runs. No regression on any test. Break-and-extend reliably achieves k>=25000 on test 10.
- **Uncertain:** Whether break-and-extend can push test 10 to k>=54154 (threshold a_2) — would need ~54% coverage, currently at ~26%. Likely requires a qualitatively different approach for that level.
- **Suggested next:**
  1. Test 8 is the best remaining target: k=5638, needs 6977 for +1 point. Investigate whether deeper search (2-opt, segment reversal) can bridge the 1339-vertex gap.
  2. Test 10 a_2 (54154) is aspirational but would require 2× current coverage — likely needs graph-specific preprocessing or community detection to guide construction.
  3. Consider whether combining break-and-extend with rotation (hybrid approach) could help test 8 at avg_deg=5.44.

## Warnings & Constraints

- **DO NOT modify Phase 1 timing for the standard path.** Phase 1 must run seed 42 to 3.0s. Any change (early exit, reduced time) risks test 7 regression. This is the #1 footgun.
- **DO NOT use starts[] array for Phase 2 start vertices.** Must use `(rng_md()%N)+1` to match v12's RNG progression.
- **4-second hard time limit per test.** IO for test 10 (100K vertices, 300K edges) takes ~0.15s. Effective compute budget is ~3.85s.
- **fmeasure_5.sh reports float scores** — 82.99999999999999 means 83. Always check the integer floor.
