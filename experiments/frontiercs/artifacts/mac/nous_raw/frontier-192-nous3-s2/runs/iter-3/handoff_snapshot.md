# Handoff — Max-Cut (Problem #192), Iteration 3

## Goal

Implement and measure two solutions: (1) adaptive budget SA+ILS (h-main at `inputs/solution_adaptive_sa_ils.cpp`) and (2) iter-2 fixed 12-restart SA+ILS (h-control-negative at `inputs/sa_ils_solution.cpp`). Copy each to `solution.cpp` and run the judge. Record scores.

## Key Discoveries

- **1.5M total SA iterations is the safe ceiling.** At 1.5M budget, the solution never TLE's (verified 3× at 87.16). At 1.7M, TLE variance returns. At 2.0M, score swings 82-87.
- **Adaptive restarts eliminate TLE variance.** Scaling restarts by n (20 for n≤100, 12 for n≤300, 8 for n≤600, 5 for n>600) distributes the 1.5M budget safely across all graph sizes.
- **CSR adjacency + static arrays provide ~constant speedup** but don't change the algorithm's quality ceiling — the score is 87.16 either way, just more consistent.
- **Fixed iteration count SA beats temperature-based SA** for this problem because timing is deterministic. T_start=3.0, T_end=0.001, geometric cooling ratio computed from budget.
- **30 ILS cycles is sufficient** — increasing to 30 from 12 doesn't improve the score (same 87.16), but the extra cycles are cheap and don't hurt.
- **Judge variance is purely from TLE.** For deterministic solutions, the judge produces identical scores across runs — unless some test cases time out.
- **Score 87.16 appears to be the practical ceiling** for SA+ILS given the time constraints. Near the GW 0.878 bound.

## System Interface

- **Build:** Not needed — judge compiles internally.
- **Run/measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout, where n is 0–100.
- **Baseline result:** Adaptive SA+ILS → 87.16 (consistent). Fixed 12-restart SA+ILS → 81-87 (inconsistent).

## Code Map

- `solution.cpp:1` — the only file to edit. Must read n/m/edges from stdin, output n space-separated 0/1 values on one line.
- `inputs/solution_adaptive_sa_ils.cpp` — the h-main solution (fully validated, 87.16 × 3).
- `inputs/sa_ils_solution.cpp` — the h-control-negative solution (iter-2 baseline, 81-87 range).

## Code Targets

- **h-main** → `solution.cpp`: Copy `inputs/solution_adaptive_sa_ils.cpp` directly. The implementation is fully validated.
- **h-control-negative** → `solution.cpp`: Copy `inputs/sa_ils_solution.cpp` directly.

## What I Tried That Didn't Work

- **2M total SA budget (v9):** 87.25/82.05 — TLE variance returned.
- **1.7M budget (v10):** 83.95 — also TLE.
- **100 greedy restarts, no SA (v6):** 84.67 — SA quality is needed.
- **2-flip neighborhood (v11):** 84.59 — O(m) per 2-flip pass adds too much overhead in ILS.
- **Spectral initialization (v18):** 87.14 — no improvement over greedy init.
- **Fast xoshiro128+ RNG (v14):** 84.21 — worse than mt19937 for this problem.
- **Input-dependent seed (v16):** 87.05 — seed 31415 is better on average.
- **Higher start temperature T=5.0 (v15):** 87.07 — T=3.0 is better tuned.
- **Skip best-tracking in SA (v19):** 84.48 — losing the best SA state hurts quality.
- **Deeper SA with fewer restarts (v4):** 79.09 — TLE.
- **Final refinement SA on global best (v13):** 84.62 — splitting budget between restarts and refinement hurts.

## What I Excluded and Why

- **SDP relaxation:** Too complex for competitive C++, likely too slow. Already near GW bound.
- **Graph coarsening (METIS-style):** Would require significant infrastructure (matching, coarsening, refinement). Diminishing returns at 87.16.
- **Population-based / genetic algorithms:** More complex, no clear advantage over multi-start SA+ILS for this graph size.
- **Efficient tabu search (bucket structures):** O(1) best-move lookup is complex to implement. Tried in iter-2, scored 44.4.

## Evolution of Thinking

Started iter-3 assuming the bottleneck was algorithmic quality (better SA, 2-flip moves, spectral init). Quickly discovered **TLE consistency** is the real challenge — the same solution scores 81 or 87 depending on whether large test cases time out. The key insight: **adaptive workload scaling** (fewer restarts for bigger graphs) gives consistent scores, while the iter-2 approach with fixed restarts is a coin flip. The solution quality at 87.16 is nearly at the GW theoretical ceiling; further gains require fundamentally different methods that are impractical given the time constraint.

## Current Status

- **Validated:** Adaptive SA+ILS scores 87.16 consistently (3× verified). Fixed 12-restart SA+ILS scores 81-87 (inconsistent).
- **Uncertain:** Whether the 87.16 score can be pushed to 87.5+ with more aggressive optimizations that stay within the time limit. Whether different RNG seeds could find marginally better solutions on specific test cases.
- **Suggested next:** (1) Try population-based crossover of top solutions from multiple restarts. (2) Try variable neighborhood descent (VND) with 1-flip, 2-flip, and 3-flip neighborhoods in sequence. (3) Profile the solution to find if any inner-loop optimization enables one more restart.

## Warnings & Constraints

- **Do NOT use chrono or clock() for timing.** Score goes to 0 (RP-2).
- **Output must be exactly one line** of n space-separated integers (0 or 1).
- **1.5M total SA iterations is the safe ceiling.** Going to 1.7M+ causes TLE variance.
- **bits/stdc++.h works** in the judge (Linux GCC).
- **mt19937 with seed 31415 produces better results** than xoshiro128+ or input-dependent seeds for this specific problem.
- **The judge produces deterministic scores** when the solution is deterministic (fixed RNG seed). Run-to-run variance = 0 when no TLE occurs.
