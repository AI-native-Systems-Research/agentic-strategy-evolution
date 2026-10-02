# Problem Framing — Max-Cut (Problem 192), Iteration 2

## Research Question
Can linear-cooling simulated annealing with time-proportional temperature scheduling improve Max-Cut scores beyond the geometric-cooling SA baseline (iter-1 best: 87.2)?

The mechanism is implemented entirely in `solution.cpp`. The judge evaluates 30 test cases (n≤1000, m≤20000, 1s time limit each) via `algorithmic/problems/192/chk.cc`.

## System Interface
- **Build:** Automatic (frontier eval compiles C++17 internally).
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` (0–100).
- **Code evidence:** Time limit 1s at `algorithmic/problems/192/config.yaml:2`. Checker computes c/m at `algorithmic/problems/192/chk.cc`.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp
```

## Baseline Validation
The current `solution.cpp` (greedy + geometric SA + restarts) scored consistently ~86.7 across 5 runs (86.70, 86.73, 86.68, 86.68, 86.69). Exit code 0.

## Experimental Conditions

### h-main: Linear-cooling SA with time-proportional restarts
Replace the geometric-cooling SA (T=2.0, cooling=0.9995) with linear-cooling SA where temperature is proportional to remaining time within each restart's 0.10s budget. T0=3.0, Tf=0.001. Uses batched time checks (every 256 iterations) to reduce syscall overhead. Each restart gets greedy optimization followed by a 0.10s SA phase with linear cooling.

**Probed result:** Scored 87.57, 84.95, 87.60, 87.57, 87.55 across 5 runs. Peak 87.6, median 87.55.

### h-ablation: Original geometric-cooling SA (baseline reference)
The iter-1 solution: greedy + SA (T=2.0, cooling=0.9995, cap 200k iterations per restart). Many fast restarts (~1000+) due to quick SA convergence.

**Probed result:** Scored 86.70, 86.73, 86.68, 86.68, 86.69 across 5 runs. Consistent ~86.7.

## Success Criteria
- h-main score > h-ablation score (directional: linear cooling outperforms geometric cooling)
- h-main score > 87.0 (improving on iter-1 best of 87.2)

## Constraints
- 1s per-test time limit (use 0.90s internal budget)
- Output format: exactly one line with n space-separated 0/1 integers
- No external libraries; single-file C++17

## Prior Knowledge
- RP-1: FM/greedy with SA restarts achieves ~87 (confirmed iter-1)
- RP-2: RNG-seed variance causes ~5-point score drops (confirmed iter-1)
- Dead ends from iter-1: SA-only (84.1), simulated annealing with T=2.0/cooling=0.9995 doesn't help beyond greedy
- Dead ends from iter-2 exploration: KL passes (high variance), tabu search (too expensive), LAHC (worse), pure greedy restarts (81), greedy construction (84.4), spectral init (no consistent improvement)
