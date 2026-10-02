# Problem Framing — Max-Cut (Problem #192), Iteration 3

## Research Question

What algorithm maximizes the Frontier-CS judge score for Max-Cut problem #192?

Specifically: can adaptive restart scaling (adjusting SA restart count based on graph size) eliminate TLE-induced score variance and push the score above the iter-2 baseline of 87.27 (which was inconsistently achieved)?

Key source files: `solution.cpp` is the only editable file — it reads a graph from stdin and outputs a binary partition.

## System Interface

- **Build command:** Not needed — the judge compiles `solution.cpp` internally.
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` on stdout, where n is 0–100 (higher is better).
- **Code evidence:** The judge evaluates solution.cpp via the `frontier eval algorithmic 192` CLI.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp
```

## Baseline Validation

Iter-2 SA+ILS solution (12 fixed restarts, seed=31415): measured 81.08, 84.41 across two runs — TLE-induced variance.

Proposed v8 solution (adaptive restarts, fixed-iter SA, 1.5M budget): measured 87.16, 87.16, 87.16 across three runs — fully consistent.

## Experimental Conditions

### h-main: Adaptive Budget SA+ILS
Replace `solution.cpp` with `inputs/solution_adaptive_sa_ils.cpp`. Key changes from iter-2:
1. **CSR adjacency format** — static arrays, flat adjacency list for cache locality
2. **Fixed iteration count SA** — total budget of 1.5M SA iterations, distributed across restarts. Geometric cooling computed from budget, not temperature thresholds. Eliminates timing uncertainty.
3. **Adaptive restart count** — scales with graph size: n≤100→20 restarts, n≤300→12, n≤600→8, n>600→5. Prevents TLE on large test cases.
4. **30 ILS perturbation cycles per restart** with varying perturbation strength (n/(15+p) vertices flipped).

### h-control-negative: Iter-2 SA+ILS (12 fixed restarts)
Use `inputs/sa_ils_solution.cpp` unchanged (from iter-2). This baseline uses temperature-based SA (T=3.0, alpha=0.99997, T_min=0.001) with 12 fixed restarts regardless of graph size, plus 12 ILS perturbation cycles.

## Success Criteria

- h-main achieves a higher and more consistent score than h-control-negative.
- h-main score ≥ 87.0 on repeated measurements.
- h-control-negative shows measurable variance across runs (evidence of TLE).

## Constraints

- Do not use chrono/clock-based timing (RP-2).
- Output must be exactly one line of n space-separated 0/1 integers.
- Per-test time limit is tight — solutions must not TLE on the largest test cases.
- Solution must be self-contained C++17 using `bits/stdc++.h`.

## Prior Knowledge

- RP-1: 20-restart SA scored 87.28 peak but with TLE variance (83-87 range).
- RP-2: Do not use chrono/clock for timing — use fixed iteration counts.
- RP-3: Judge is deterministic for deterministic solutions. Observed variance is from TLE, not judge randomness.
- Iter-2 discovered TLE is the main score bottleneck. ILS perturbation compensates for fewer restarts. 12 restarts scored 87.27 once but inconsistently.
- Iter-3 exploration showed: 1.5M total SA iterations is the safe budget ceiling. Adaptive restarts (scaling by n) give consistent 87.16 across 3 runs. Budgets above 1.5M cause TLE variance. 2-flip moves add too much overhead. Spectral initialization doesn't improve over greedy init. Fast RNG (xoshiro) produces worse scores than mt19937 for this problem.
