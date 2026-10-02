# Problem Framing — Iteration 2

## Research Question
Can multi-restart simulated annealing with randomized greedy initialization improve the judge score beyond the single-run SA baseline (~84) for AHC001 rectangle packing?

The key mechanism is that randomized greedy ordering creates diverse starting configurations. Different orderings give different companies priority in claiming space, leading to structurally different rect layouts. SA then refines from each starting point, and the best result across restarts is kept. This should escape local optima that trap a single long SA run.

Relevant source: `solution.cpp` (current worktree) — greedy expansion phase (lines 72-98) and SA phase (lines 100-190).

## System Interface
- **Build:** Not needed locally — judge compiles server-side with g++ 11.
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Code evidence:** The measure script (`fmeasure_147.sh:5`) calls `frontier eval algorithmic 147 "$1" --json`, which compiles and runs the solution against ~100 test cases.
- **Output:** Single line `SCORE: <n>` (0-100 scale). Native output; no redirect needed.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh /Users/toslali/frontier/gen_logs/frontier_147_nous-s2_ws/solution.cpp
```

## Baseline Validation
Ran the baseline command successfully. Exit code 0. Output: `SCORE: 84.51930000000004`. The current single-run greedy+SA solution scores ~84-85 on the judge.

## Experimental Conditions

### h-main: Multi-restart SA
Replace the single greedy+SA pipeline with 3 restarts. Each restart:
1. Initializes all rects to 1×1 around their point.
2. Runs greedy expansion with a **shuffled** processing order (different each restart).
3. Runs SA for ~3s with linear cooling T=0.01→0.
4. The best solution across all 3 restarts is output.

Key differences from baseline:
- `shuffle(order)` before each greedy phase creates diverse starting configs
- Larger greedy steps (`sqrt(ratio)*5`, max 300) for faster convergence (~0.3s per greedy)
- 3 independent SA runs of ~2.5s each instead of one 7s run
- Best-of-3 selection

### h-ablation: Single-run SA (baseline)
The current `solution.cpp` with one greedy pass (fixed order) + one long SA run (7s). This is the iter-1 approach, kept unchanged as the ablation arm.

## Success Criteria
- h-main scores consistently higher than h-ablation (directional: multi-restart > single-run).
- Score improvement of ≥1 point average across judge evaluations would indicate the restart mechanism is effective beyond measurement noise (judge variance is ±2 points per run).

## Constraints
- 10s time limit per test case.
- N ≤ 200 companies on 10000×10000 grid.
- Must use standard C++17 includes (no `bits/stdc++.h`).
- Explicit casts for `max(int, long long)`.

## Prior Knowledge
- **RP-1 (iter-1):** SA with boundary-shift moves nearly doubles score over greedy alone (81.6 vs 46.8). SA is the dominant component.
- **Iter-1 dead ends:** Two-rect SA moves (83.4), weighted selection (84.0), aggressive greedy (worse), geometric cooling (worse). Simpler SA = more iterations = better.
- **Probing results this iteration:**
  - BSP initialization: 72.5 (much worse — area mismatch between BSP cells and targets)
  - Sorted greedy + lower temp (T0=0.008): 83.6 (worse)
  - Higher temp alone (T0=0.02): 84.6 (marginal)
  - 3 restarts with randomized greedy: 86.6 (best observed)
  - 5 restarts: 86.0 (diminishing returns — less SA time per restart)
  - Quick restarts + long final SA: 86.4 (not better than pure restarts)
