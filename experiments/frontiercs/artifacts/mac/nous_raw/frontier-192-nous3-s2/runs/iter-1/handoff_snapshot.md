# Handoff — Max-Cut (Problem #192), Iteration 1

## Goal

Implement a multi-start simulated annealing solution for Max-Cut in `solution.cpp`, measure its score via the fmeasure script, and record the result.

## Key Discoveries

- **Random baseline scores ~51.** Expected for Max-Cut (roughly half the edges are cut by chance).
- **Greedy local search alone scores ~80.** 50 restarts of random-init + flip-any-improving-vertex converge to shallow local optima.
- **SA + greedy scores ~87.** The best result (87.28) came from: greedy/random init → greedy local search → SA (T=3, alpha=0.99997) → re-greedy, with 20 restarts.
- **chrono-based timing causes score 0.** Version using `chrono::steady_clock` for time-based loop control scored exactly 0. Use fixed iteration counts instead.
- **Gain update must be ±2, not ±1.** When flipping vertex v, each neighbor w's gain changes by exactly ±2 (sign depends on whether v moved to/away from w's side). An earlier version with ±1 still worked (84.8) due to noisy exploration, but correct updates perform better.
- **The GW bound (~87.8%) appears to be the practical ceiling.** Our SA at 87.28 is close to the Goemans-Williamson 0.878-approximation ratio, suggesting we're near the heuristic limit without SDP.

## System Interface

- **Build:** Not needed — the judge compiles `solution.cpp` internally.
- **Run/measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout, where n is 0–100.
- **Baseline result:** Random → 51.0, SA v8 → 87.28.

## Code Map

- `solution.cpp:1` — the only file to edit. Must include `<bits/stdc++.h>`, read n/m/edges from stdin, output n space-separated 0/1 values on one line.
- `fmeasure_192.sh` — judge wrapper. Calls `frontier eval algorithmic 192 <solution.cpp> --json`, extracts score field.

## Code Targets

- **h-main** → `solution.cpp`: Replace entire file with the SA v8 algorithm from `inputs/sa_v8_solution.cpp`. The implementation is fully validated — copy it directly.

## What I Tried That Didn't Work

- **chrono::steady_clock for time-based loop** (sa_v3): Scored 0. The judge environment likely doesn't support chrono properly, or the overhead is too high. Use fixed iteration counts.
- **SA with 20 restarts × 2M fixed steps** (sa_v2): Scored 62 — too many total steps caused TLE on larger test cases.
- **Very aggressive SA (5M steps, alpha=0.9999)** with buggy gain updates (sa_v1): Scored 84.8 — worked accidentally because the gain bug created noise. Correct gains + tuned alpha does better.

## What I Excluded and Why

- **SDP relaxation (Goemans-Williamson):** Requires solving a semidefinite program, which is complex to implement in competitive C++ and likely too slow for the time limit. Deferred to iter-2 if SA plateau is confirmed.
- **Kernighan-Lin pair swaps:** More complex neighborhood; single-vertex flips with SA already reach ~87. Could be explored in iter-2.
- **Graph-structure-aware initialization (BFS 2-coloring):** Would help for bipartite subgraphs but adds complexity. Greedy construction partially captures this.

## Evolution of Thinking

Started assuming more SA steps = better score. Discovered that time limits are binding — too many steps cause TLE and score 0. The key insight is balancing restart count × steps-per-restart within the (unknown) time budget. Fixed iteration counts with alpha=0.99997 (yielding ~267k steps/restart) are safe. chrono/clock-based adaptive timing doesn't work in this judge.

## Current Status

- **Validated:** SA v8 approach scores 87.28. Output format is correct (one line, space-separated). Fixed iteration counts work within time limits.
- **Uncertain:** Exact time limit per test case (never stated in problem). Whether the ~87 plateau is due to local-search ceiling or time-limit ceiling.
- **Suggested next:** Try (1) even slower cooling with fewer restarts to check if quality improves with deeper SA, (2) Kernighan-Lin neighborhood for escaping local optima, (3) spectral initialization using eigenvector of Laplacian as starting partition.

## Warnings & Constraints

- **Do NOT use chrono or clock() for timing.** Score went to 0 when chrono was used. Stick to fixed iteration counts.
- **Output must be exactly one line** of n space-separated integers (0 or 1). Extra newlines or per-vertex lines will score 0.
- **bits/stdc++.h works** in the judge (Linux GCC), even though it doesn't compile on macOS clang.
