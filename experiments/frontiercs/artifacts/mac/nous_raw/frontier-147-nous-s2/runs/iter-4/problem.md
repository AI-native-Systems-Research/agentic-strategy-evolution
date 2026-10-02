# Problem Framing — Iteration 4

## Research Question
What algorithm maximizes the Frontier-CS judge score for AHC001 rectangle packing problem #147? Specifically: does multi-restart SA (v5, `solution_v5.cpp:195-223`) consistently outperform single-run SA (`solution.cpp:100-190`) when measured with full judge rigor?

After exhaustive exploration in this iteration (10 algorithmic variants tested), v5 remains the only approach that outperforms the baseline. This experiment confirms v5 as the production solution.

## System Interface
- **Build:** Not needed — judge compiles server-side.
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Code evidence:**
  - `solution.cpp:100-190` — Single-run SA with 8 move types, T0=0.01 linear cooling
  - `solution_v5.cpp:65-97` — `doGreedy(rng)` with shuffled expansion order
  - `solution_v5.cpp:99-193` — `doSA(rng, endTime)` with time-bounded progress
  - `solution_v5.cpp:195-223` — Main loop: 3 restarts, global_best tracking
- **Output:** Prints `SCORE: <n>` where n is 0-100.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```

## Baseline Validation
Ran solution.cpp (single-run SA): SCORE: 85.44 (iter-3), 85.62 (iter-4 probe).
Ran solution_v5.cpp (multi-restart SA): SCORE: 87.55 (iter-3), 86.70 (iter-4 probe), 85.62 (iter-4 probe).
Both produce valid output and exit 0. Judge variance is ~0.5-1.5 points per run.

## Experimental Conditions

### h-main: Multi-restart SA (v5)
Apply v5's code structure to solution.cpp:
1. Extract `doGreedy(rng)` with `shuffle(order)` (shuffled expansion order)
2. Extract `doSA(rng, endTime)` with time-bounded progress tracking
3. Add `global_best[210]` for cross-restart best tracking
4. Main: 3 restarts, `timePerRestart = 9.0/3`, each restart calls `doGreedy(rng)` then `doSA(rng, restartEnd)`
Reference: `solution_v5.cpp`

### h-ablation: Single-run SA (current)
Run solution.cpp as-is. No code changes.

## Success Criteria
h-main scores consistently higher than h-ablation. Given judge variance of ~1 point, a directional improvement across multiple test-case evaluations constitutes confirmation.

## Constraints
- 10-second time limit per test case
- Single-threaded execution (judge does not support threading — v23/v24 scored 0)
- N ≤ 200 companies on 10000×10000 grid
- Judge variance ~0.5-1.5 points per evaluation

## Prior Knowledge
### Active Principles
- RP-1: SA with boundary-shift moves nearly doubles score over greedy alone (81.6 vs 46.8)
- RP-2: Multi-restart SA provides small positive effect (~0.6 points) but benefit is not statistically significant with typical judge variance
- RP-3: Judge score variance is ~0.5-0.7 points (std dev) for deterministic solutions

### Exploration Results (this iteration)
All of the following modifications to v5 scored WORSE:
- v17 (pair-boundary moves at 20%): 83.3 — throughput loss from 2×O(N) checks
- v18 (3 restarts + intensification phase): 84.0 — stolen SA time from restarts
- v19 (LNS destroy-repair worst 20%): 85.0 — stolen SA time
- v20 (post-SA assignment swaps): 84.9 — point containment too restrictive
- v21 (tournament rect selection): 84.2 — biased selection hurts convergence
- v22 (3× weight for moves 6,7): 84.0 — expensive moves reduce throughput
- v23/v24 (threaded restarts): 0 — judge rejects multi-threaded solutions
- v25 (area-sorted greedy): 85.0 — sorted order is worse than shuffled
- v26 (adaptive delta scaling): 81.3 — disrupts tuned RNG sequence
- treemap init: 79.2 — elongated shapes from recursive splitting are worse than greedy
