# Handoff — Iteration 3

## Goal

Measure whether or-opt1 (single-city relocation with KNN candidate lists) improves the judge score for penalized TSP problem #44 beyond the iter-2 baseline of 2-opt + ILS (v25, ~78.93).

## Key Discoveries

- **Or-opt1 gives ~0.04 point improvement.** v32 (with or-opt1) scores 78.97 vs v25 at 78.93. The improvement is small but consistent across multiple judge runs.
- **Or-opt2 and or-opt3 cause TLE.** Pair (seg=2) and triple (seg=3) relocation were implemented with efficient memmove edge updates, but the total time for all or-opt phases pushes large N test cases past 2s. Only or-opt1 is safe.
- **dist² early rejection helps.** Adding `dist2(a,c) >= threshold*threshold` before eucl() in 2-opt_candidate avoids sqrt for most non-improving candidates. Minor speedup but contributes to TLE avoidance.
- **Cyclic 2-opt↔or-opt doesn't help.** Running 2-opt and or-opt in a loop until neither improves causes TLE on large N (v31 scored 73.97). Sequential phases with strict time budgets work better.
- **Time allocation is critical.** Giving ≥50% to initial 2-opt is essential. Or-opt1 needs only 6-8% of budget. More time for or-opt2/3 steals from 2-opt with net negative effect.
- **Or-opt1 works via memmove.** After removing a city from position idx and inserting at position ins, use memmove for tour[] and ed[] arrays, then recalculate only 3 boundary edges. This is O(|idx-ins|) but typically O(sqrt(N)) with KNN candidates.

## System Interface

- **Build:** Handled by judge (C++17, -O2)
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout
- **Baseline result:** v25=78.93, v32=78.97

## Code Map

- `solution.cpp:1` — Entire solution. Replace with `inputs/solution_v32.cpp` for h-main or `inputs/solution_v25.cpp` for h-control-negative.
- `inputs/solution_v32.cpp:105` — `do_2opt_candidate`: 2-opt with dist² rejection + DLB.
- `inputs/solution_v32.cpp:148` — `do_2opt_window`: Window 2-opt.
- `inputs/solution_v32.cpp:171` — `do_oropt1`: Or-opt1 relocation with KNN candidates and memmove.
- `inputs/solution_v25.cpp` — Iter-2 baseline (no or-opt, no dist² rejection).
- `fmeasure_44.sh` — Judge script. Do not modify.

## Code Targets

- **h-main → solution.cpp**: Copy `inputs/solution_v32.cpp` to `solution.cpp`. Implementation is complete and validated.
- **h-control-negative → solution.cpp**: Copy `inputs/solution_v25.cpp` to `solution.cpp`.

## What I Tried That Didn't Work

| Version | Approach | Score | Why it failed |
|---------|----------|-------|---------------|
| v30 | or-opt1 + or-opt2 (O(N) for-loop edge recalc) | 79.00 / 78.45 | or-opt2 with for-loop edge recalc is TLE-unstable |
| v31 | Cyclic 2-opt↔or-opt loop | 73.97 | Loop doesn't converge within budget for large N → TLE |
| v33 | Efficient or-opt2 (memmove) + dist² + or-opt after window | 74.00 | Total time for all phases exceeds 2s on large N |
| v34 | or-opt1 + dist² + memcpy ILS + more initial 2-opt time | 78.92 | Slightly worse than v32 despite optimizations; time allocation not optimal |
| v35 | or-opt1 + or-opt2 + or-opt3 (all efficient memmove) | 78.94 | Multi-segment or-opt steals time from 2-opt with net negative effect |

## What I Excluded and Why

- **Greedy edge-insertion construction**: Could give ~5% shorter initial tour for random instances, but for x-sorted cities the NN is already quite good. Implementation complexity is high (union-find, fallback for disconnected components) with uncertain payoff.
- **3-opt / Lin-Kernighan**: O(N*K²) per pass = 45M candidates × 6+ reconnections for N=200K. Infeasible in 2s even with aggressive pruning.
- **Simulated annealing**: Each step is O(1) but O(N²) steps needed for convergence on N=200K. Not enough time.
- **Penalty-aware optimization**: RP-2 confirmed penalty is ~1% of cost. Or-opt for penalty positions yields <0.1 points.
- **Or-opt with reversed pairs/triples**: Implemented and tested (v33, v35) but the time cost exceeds the marginal benefit.
- **Hilbert curve construction**: For x-sorted cities, NN construction is already near-optimal; Hilbert curve would likely be worse.

## Evolution of Thinking

1. Started by implementing or-opt1 (single-city relocation) with efficient memmove updates. Initial results promising: +0.07 in one run (v30).
2. Tried extending to or-opt2 (pair relocation). First implementation used O(N) for-loop for edge recalc → TLE. Second implementation used efficient memmove (only 3 eucl calls per move) but total time for all or-opt phases still exceeded 2s on large N.
3. Tried cyclic 2-opt↔or-opt convergence — too slow, causes TLE.
4. Discovered that the improvement from or-opt is fundamentally small (~0.04 points) because after 2-opt convergence, few cities benefit from relocation. The removal_gain check filters out ~95% of cities.
5. Settled on v32: or-opt1 only, with strict time budgets, as the best risk/reward trade-off. The dist² early rejection in 2-opt is a free speedup.
6. Realized that for larger improvements, fundamentally different approaches (LK, better construction) are needed but are too complex to implement reliably within the 2s time limit.

## Current Status

- **Validated:** v32 scores 78.97 consistently (4+ runs without TLE). v25 baseline scores 78.93 consistently.
- **Uncertain:** Whether the ~0.04 improvement survives across all judge test case distributions. Whether a more aggressive ILS schedule (more double-bridge iterations) with or-opt1 in recovery could push higher.
- **Suggested next:** (1) Implement greedy edge-insertion construction using KNN edges to get a better starting tour. (2) Try simplified Lin-Kernighan (sequential search depth 2) as the primary local search instead of 2-opt. (3) Investigate whether larger K (K=20) with the dist² speedup can avoid TLE while finding more improvements. (4) Consider alternative perturbation strategies in ILS (random segment insertion instead of double-bridge).

## Warnings & Constraints

- **Or-opt2/3 cause TLE.** Even with efficient memmove implementation. The cumulative time of multiple or-opt phases exceeds 2s for N=200K. Only or-opt1 is safe.
- **Time budgets must be strict percentages.** Do NOT use convergence-based stopping for or-opt on large N — a single or-opt pass can take 100ms+ for N=200K.
- **The improvement from or-opt1 is small (~0.04 points).** This is at the edge of measurement noise (single judge run variance is ~0.01 points for non-TLE runs).
- **ILS double-bridge allocates newtour each iteration in v25.** v32 uses preallocated newtour for slightly faster ILS.
- **v32 has a second 2-opt pass after or-opt (lines ~180).** This catches improvements created by or-opt changes. Removing it loses ~0.02 points.
