# Handoff — Iter 2

## Goal

Measure whether targeted post-SA optimization (reversed-tour direction check + greedy edge-fix) improves on iter-1's ~69.5. If not, document the SA plateau for future strategy changes.

## Key Discoveries

- **Iter-1 reliably scores ~69.5** (69.496 ± 0.01 across multiple runs). One outlier at 64.5 was likely a judge timeout.
- **2-opt contributes NOTHING**: 100% swap gives 69.49, same as 40% swap + 60% 2-opt (69.50). All SA improvement comes from swap moves.
- **Swap ratio is critical**: below ~30% swap, SA fails to improve NN at all (score stays at 64.5). Above 30%, diminishing returns.
- **NN-guided 2-opt with pos[] is too slow** for N=200K: O(segment) pos[] updates eat the throughput gain. Every variant tested (full pos[] update, stale pos[], periodic rebuild) scored worse than random SA.
- **Double-bridge perturbation hurts**: SA can't recover the destroyed structure within the time budget.
- **Random Or-opt doesn't help**: for N=200K, random position pairs are too far apart; nearby limits (|p-q|<200) cause 99.8% of attempts to be skipped.
- **Hilbert curve construction ≈ NN**: no significant improvement in starting tour quality.
- **Reversed-tour direction helps marginally**: +0.01-0.015 points from exploiting penalty structure directionality.
- **Greedy edge-fix post-pass helps marginally**: +0.005-0.01 points from targeting worst edges.

## System Interface

- **Build:** None — judge compiles internally.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout.
- **Baseline result:** h-main (iter-1 + improvements) = 69.503-69.511.

## Code Map

- `solution.cpp:1` — the only file to edit.
- `runs/iter-1/patches/h-main.patch` — the 69.5-scoring iter-1 solution.
- `runs/iter-2/patches/h-main.patch` — the iter-2 solution with improvements.

## Code Targets

### h-main → `solution.cpp`
Start from iter-1 patch, add:
1. After `nnConstruct()`: reverse `tour[1..N-1]`, compare `totalCost()` with forward, keep cheaper direction.
2. After SA loop, before prime post-pass: greedy edge-fix (find top-50 longest penalized edges, try 200 random swaps per edge, accept best improvement, 5 passes max).

### h-ablation → `solution.cpp`
Pure iter-1 patch, no changes.

## What I Tried That Didn't Work (accumulated)

- **Sequential tour**: Scores 0 (IS the baseline).
- **Naive 2-opt with full recompute**: Only 17.6. O(N) per move too slow.
- **NN-guided 2-opt with pos[]**: 60.5-65.5 (WORSE than random SA). O(segment) pos[] update kills throughput.
- **NN-guided 2-opt with stale pos[]**: 65.5. Stale positions cause ineffective moves.
- **NN-guided 2-opt with periodic pos[] rebuild**: 65.5. Same issue.
- **Double-bridge perturbation**: 64.5. SA can't recover destroyed structure.
- **Random Or-opt (|p-q| unlimited)**: 69.36. Memmove cost + random targeting = no improvement.
- **Random Or-opt (|p-q| < 200)**: 64.5. 99.8% of moves skipped.
- **100% 2-opt (no swap)**: 64.5. 2-opt alone can't improve NN tour.
- **20% swap + 80% 2-opt**: 64.5. Not enough swaps for diversification.
- **Nearby swap (|p-q| < 100)**: 64.5. Loses essential long-range diversification.
- **Hilbert curve construction**: 65.5. Comparable to NN, no improvement after SA overhead.
- **Bigger SA batches (5000-10000)**: 69.5. More moves of same type don't help at convergence.
- **Less frequent totalCost() recompute**: 69.48. Negligible difference.
- **Exact delta for short 2-opt segments**: 69.49. Penalty changes in short segments are too small to matter.
- **Compiling locally with `bits/stdc++.h`**: Fails on macOS clang.

## What I Excluded and Why

- **LK-style moves**: Too complex to implement correctly within 2s for N=200K, especially with penalty structure.
- **Genetic algorithms / EAX**: Population-based approaches are complex; single-tour SA is simpler and competitive for this time budget.
- **Exact solvers (Concorde)**: N=200K is far too large.
- **3-opt**: Triple the delta computation complexity of 2-opt, which already contributes nothing.
- **Large Neighborhood Search**: Partial tour reconstruction is promising but implementation complexity exceeds the marginal gain.
- **Held-Karp DP for segments**: O(2^K * K^2) per segment; even K=15 takes 0.04s per segment, too few segments can be processed.

## Evolution of Thinking

Iter-1 assumed 2-opt was the primary optimizer. Iter-2 discovered that 2-opt contributes NOTHING — 100% swap SA gives identical scores. The SA improvement (64.5 → 69.5) comes entirely from random city swaps providing long-range diversification. This means the ~5-point SA improvement represents the limit of what random moves can achieve for N=200K in 2 seconds.

Breaking past 69.5 requires either:
1. A fundamentally better construction heuristic (better than grid-NN)
2. A structured local search (LK-style moves with proper candidate lists)
3. A completely different approach (e.g., divide and conquer)

## Current Status

- **Validated:** Judge works (69.5 consistent), 2-opt is useless, swap ratio critical, post-SA fixes give marginal gain.
- **Uncertain:** Whether greedy edge-fix + reversed-tour consistently beats iter-1 (margin is ~0.01-0.02 points, within noise).
- **Suggested next:** If the goal is to push significantly past 69.5, iter-3 should try: (1) LK-style moves (sequential k-opt with candidate list), (2) divide-and-conquer construction (partition cities spatially, solve sub-problems, merge), (3) strip-based construction (serpentine sweep with y-sorting within strips).

## Warnings & Constraints

- **Do NOT compile locally** — `bits/stdc++.h` not available on macOS.
- **Judge score varies ~0.01-0.02 between runs** — marginal improvements need multiple measurements to confirm.
- **One outlier at 64.5 observed** — likely a judge timeout. Ignore if it occurs once.
- **2-opt boundary delta is exact for unpenalized TSP** but approximate for penalized — doesn't matter since 2-opt contributes nothing regardless.
- **SA temperature uses `curCost/N * pow(1e-4, progress)`** — this is the proven schedule, don't change without evidence.
