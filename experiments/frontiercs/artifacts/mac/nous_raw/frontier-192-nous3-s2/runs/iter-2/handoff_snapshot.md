# Handoff — Max-Cut (Problem #192), Iteration 2

## Goal

Implement the SA+ILS solution in `solution.cpp`, measure its score, and compare against the iter-1 SA-only baseline. The SA+ILS solution is fully written and validated at `inputs/sa_ils_solution.cpp` — copy it directly.

## Key Discoveries

- **TLE is the main score bottleneck.** The iter-1 solution (20 restarts) is at the TLE boundary — scores vary 83-87 across runs because large test cases sometimes time out. Reducing to 12 restarts eliminates TLE and scores consistently.
- **ILS perturbation compensates for fewer restarts.** After SA reaches a local optimum, flipping ~4-5% of vertices randomly and re-running greedy_improve finds nearby local optima cheaply. 12 perturbation cycles per restart add diversity without SA's computational cost.
- **Consistent 87.27.** The SA+ILS approach (12 restarts, 12 perturbation) scores 87.27 on repeated judge runs (verified 2× identical). The iter-1 baseline scores 83.9-87.3 (inconsistent).
- **KL (Kernighan-Lin) is too expensive.** O(n²) per pass due to linear scan for best unlocked vertex — drops score to 84.0 from TLE. Would need bucket/PQ optimization to be viable.
- **Tabu search is too slow.** O(n) per iteration for best-move scan makes it 44.4 with 15 restarts × 200k iterations.
- **More than 12 restarts causes TLE.** 15 restarts scores 84.4-84.5 consistently (some tests TLE). 20+ restarts causes 3-point variance.
- **Near the GW bound.** 87.27% is close to the theoretical Goemans-Williamson 0.878 approximation. Further gains would require fundamentally different approaches (SDP, spectral methods) or significant code optimization.

## System Interface

- **Build:** Not needed — the judge compiles `solution.cpp` internally.
- **Run/measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout, where n is 0–100.
- **Baseline result:** Iter-1 SA-only → 83.9-87.3 (inconsistent). SA+ILS → 87.27 (consistent).

## Code Map

- `solution.cpp:1` — the only file to edit. Must read n/m/edges from stdin, output n space-separated 0/1 values on one line.
- `inputs/sa_ils_solution.cpp` — the validated SA+ILS implementation. Copy directly to solution.cpp for h-main.

## Code Targets

- **h-main** → `solution.cpp`: Replace entire file with contents of `inputs/sa_ils_solution.cpp`. The implementation is fully validated and tested.
- **h-control-negative** → `solution.cpp`: Use the current solution.cpp unchanged (iter-1 SA v8 with 20 restarts, no perturbation).

## What I Tried That Didn't Work

- **KL refinement (solution_v6):** O(n²) per KL pass caused TLE, scoring 84.0. Not viable without bucket data structure.
- **Tabu search (solution_tabu):** O(n) per iteration for best-move scan → 44.4 score with 15 restarts × 200k steps.
- **SA with reheating (solution_reheat):** 3 temperature cycles × 8 restarts = too much total work, scored 84.0.
- **40 restarts with shorter SA (solution_v8):** More restarts but less SA depth → 84.4 (TLE + quality loss).
- **Gain-saving optimization (solution_fast5):** Saving gain during SA to avoid calc_state in perturbation backfired — vector copies during SA (on every improvement) added more overhead than they saved.
- **15 restarts + 8 perturbation (solution_fast2):** 84.4-84.5, borderline TLE.
- **Adaptive restarts by n (solution_v10):** 84.0, over-aggressive for small n.

## What I Excluded and Why

- **SDP relaxation (Goemans-Williamson exact):** Complex to implement in competitive C++, likely too slow. We're already at ~87.3% which is near the 87.8% GW bound.
- **Spectral initialization (Laplacian eigenvector):** Would require eigenvalue computation, heavy dependency. Could help for specific graph structures but unlikely to beat 87.3% overall.
- **Efficient tabu search with bucket structures:** Would need O(1) best-move lookup. Complex to implement correctly. Diminishing returns given we're near GW.

## Evolution of Thinking

Started iter-2 trying to improve SA quality (deeper SA, KL, tabu). Discovered the real bottleneck was **TLE inconsistency** — the iter-1 solution was flirting with time limits, causing 3-point score swings. The key insight shifted from "better algorithm" to "faster algorithm that still computes well." ILS perturbation is the perfect fit: it's O(n) per cycle (vs O(n²) for KL or O(n) per SA step), so it adds diversity cheaply.

## Current Status

- **Validated:** SA+ILS with 12 restarts scores 87.27 consistently. Output format correct. No TLE.
- **Uncertain:** Whether further micro-optimizations (loop unrolling, cache-friendly adjacency) could squeeze another 0.5 points. Whether the 87.27 score is the practical ceiling given time constraints.
- **Suggested next:** (1) Try O(1) bucket-based tabu search for potentially better quality, (2) Try pair-swap moves (flip u and v simultaneously) for escaping single-flip local optima, (3) Profile to find if any inner loop can be optimized to allow more restarts.

## Warnings & Constraints

- **Do NOT use chrono or clock() for timing.** Score goes to 0 (RP-2).
- **Output must be exactly one line** of n space-separated integers (0 or 1).
- **12 restarts is the safe maximum.** 15 restarts causes TLE on some runs. 20+ restarts causes major variance.
- **bits/stdc++.h works** in the judge (Linux GCC).
- **RNG seed matters.** Different seeds give slightly different scores (±0.1 within consistent range). seed=31415 validated.
