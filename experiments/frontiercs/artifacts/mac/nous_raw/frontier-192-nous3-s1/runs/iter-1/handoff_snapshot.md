# Handoff — Max-Cut (Problem 192), Iteration 1

## Goal

Implement and measure two Max-Cut strategies (FM partitioning vs trivial baseline) to establish which algorithmic mechanism drives high scores on the judge.

## Key Discoveries

- **Time limit is 1 second** per test case (`algorithmic/problems/192/config.yaml:2`). Solutions that exceed this score 0 per case.
- **30 test cases**, n ≤ 1000 vertices, m ≤ 20000 edges.
- **FM + greedy local search scored 87.2** in probe — already beats the reference `gpt5_high.cpp` (83.8).
- **Greedy-only local search scored 84.3** — FM passes add ~3 points by escaping local optima.
- **Simulated annealing scored 84.1** — no improvement over greedy; SA doesn't help within the 1s budget.
- **Trivial alternating scored 49.4** — confirms graph structure matters.
- **Output format:** exactly one line with n space-separated 0/1 integers. The first solution attempt (with `\n` at end) scored 0 — likely due to TLE from an overly generous time budget (4.5s vs 1s limit).

## System Interface

- **Build:** Automatic (frontier eval compiles C++17 internally).
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0–100).
- **Baseline result:** FM solution = 87.2.

## Code Map

- `solution.cpp:1` — The single file to edit. Everything goes here.
- `algorithmic/problems/192/config.yaml:2` — Time limit (1s) and case count (30).
- `algorithmic/problems/192/chk.cc` — Testlib checker computing c/m score.

## Code Targets

- **h-main:** `solution.cpp` — full FM + greedy local search implementation (validated, scored 87.2).
- **h-control-negative:** `solution.cpp` — replace with trivial `s[i] = i%2` (validated, scored 49.4).

## What I Tried That Didn't Work

- **Initial local search with 4.5s time budget:** Scored 0 — exceeded the 1s per-test limit.
- **Simulated annealing (T=2.0, cooling=0.9995):** Scored 84.1, no better than plain greedy. SA's random acceptance doesn't help when the greedy local optimum is already decent and time is tight.

## What I Excluded and Why

- **SDP relaxation (Goemans-Williamson):** Requires eigenvalue computation, likely too slow for n=1000 within 1s.
- **Genetic algorithms / population-based:** Too much overhead for 1s; restarts of FM are more effective.
- **Tabu search:** Could be explored in iter-2 if FM ceiling is hit.

## Evolution of Thinking

Started assuming 4-5s time budget was safe → first submission scored 0. Reading config.yaml revealed 1s hard limit. This forced tight time budgets (0.85-0.90s). Once time budget was fixed, greedy local search immediately scored 84. FM passes added ~3 points. SA was a dead end.

## Current Status

- **Validated:** FM + greedy at 87.2, greedy-only at 84.3, trivial at 49.4.
- **Uncertain:** Whether FM can go higher with better initialization (e.g., spectral or BFS-based).
- **Suggested next:** Try spectral initialization, tabu search, or edge-contraction heuristics to push beyond 87.

## Warnings & Constraints

- The 1s time limit is strictly enforced. Use 0.90s as the internal budget maximum.
- `frontier eval` compiles and runs internally — you cannot pass compiler flags.
- Time-based RNG seed means scores may vary slightly between runs (~±0.5 points).
