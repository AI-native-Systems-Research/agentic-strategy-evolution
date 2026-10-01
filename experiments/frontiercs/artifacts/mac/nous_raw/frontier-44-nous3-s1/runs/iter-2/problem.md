# Problem Framing — Iteration 2

## Research Question
What algorithm maximizes the Frontier-CS judge score for problem #44 (penalized TSP with carrot constraint)? Iteration 1 established grid NN + limited 2-opt at 78.43. This iteration explores whether candidate-list 2-opt with KNN, finer grid resolution, and ILS with double-bridge perturbation can push past 79.

Key code: `solution.cpp:1` — entire solution, single file.

## System Interface
- **Build:** Handled by judge (C++17, -O2)
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` (0–100, higher is better)
- **Code evidence:** `fmeasure_44.sh` invokes `frontier eval algorithmic 44`

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation
With iter-1's grid NN + window 2-opt (N≤10K only): SCORE: 78.428 (consistent across 4 runs).

## Experimental Conditions

### h-main: Candidate-list 2-opt + ILS
Replace solution.cpp with an optimized algorithm:
1. Grid NN construction with G=sqrt(N/2.5) cells per dimension (finer than iter-1's sqrt(N/4))
2. Precompute K=15 nearest neighbors per city using dist² and grid (avoids sqrt in build)
3. Candidate-list 2-opt with DLB (don't-look bits): for each city, try 2-opt with its K nearest neighbors. Position lookup via pos[] array. Edge cache with zero-sqrt updates (interior edges reverse their order, boundary edges precomputed).
4. Window-based 2-opt as secondary phase (catches tour-position-adjacent improvements)
5. ILS with double-bridge perturbation: swap middle two segments of a random 4-cut partition, then re-optimize with candidate-list 2-opt. Keep best tour seen.
6. Time-guarded at 1900ms total (100ms safety margin).

Predicted score: >79 (vs 78.43 baseline).

## Success Criteria
Score > 78.43 (iter-1 baseline). Target: ≥79.

## Constraints
- 2-second time limit per test case
- 512 MB memory limit
- N up to 200,000
- Must handle all test case sizes without TLE

## Prior Knowledge
- RP-1: Grid NN construction dominates tour quality (~78.2/100)
- RP-2: Penalty (carrot constraint) is ~1% of total cost; penalty-aware optimizations yield negligible improvement
- RP-3: Fast 2-opt delta for penalized TSP can be computed in O(1) Euclidean + O(segment/10) penalty
- Iter-1 findings: 2-opt only ran for N≤10000; larger N got no local search. Or-opt, SA, ILS (v7 with destructive double-bridge) all failed or were unstable.
