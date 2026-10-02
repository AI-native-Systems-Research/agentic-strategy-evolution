# Handoff — Iter 1

## Goal

Implement a high-performance SA-based solution for problem #44 (TSP with 10%-step penalty for non-prime source cities) in `solution.cpp`, measure it with the judge, and record the score.

## Key Discoveries

- **Sequential tour scores 0** — it IS the baseline the judge compares against. The cities are sorted by x-coordinate, so visiting in order is the trivial solution.
- **NN + limited SA scored 33.5** — nearest-neighbor construction + SA with segment-capped 2-opt (max segment 500). Main bottleneck was O(N²) NN construction eating time budget.
- **Primes < 200K: 17,984; penalty positions at max N: 20,000** — ratio 0.90, so ~10% of penalty positions can't be covered by primes.
- **Penalty mechanics**: step t (1-indexed), if t % 10 == 0 AND source city P[t-1] is NOT prime, edge cost × 1.1. Positions in tour array that matter: indices 9, 19, 29, ... (0-indexed).
- **Time budget is tight**: 2 seconds, N up to 200K. O(N²) algorithms (brute-force NN, full-recompute 2-opt) are too slow. Must use O(1) incremental evaluation.
- **`bits/stdc++.h` works inside the judge** (it compiles with g++) but NOT on the local macOS clang. The judge handles compilation.

## System Interface

- **Build:** No separate build — `frontier eval` compiles solution.cpp internally.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** Stdout: `SCORE: <n>` where n ∈ [0, 100].
- **Baseline result:** Sequential = 0, NN+SA = 33.456.

## Code Map

- `solution.cpp:1` — the only file to edit. Judge compiles this with g++ and runs it against multiple test cases.
- `fmeasure_44.sh:5` — calls `frontier eval algorithmic 44 "$1" --json`, parses the JSON for the score field.

## Code Targets

- **h-main → `solution.cpp`**: Complete rewrite. Implement grid-based NN construction, SA with Or-opt/2-opt mixed moves (incremental delta), prime-scheduling post-pass. The entire file is replaced.

## What I Tried That Didn't Work

- **Naive 2-opt with full tour recompute**: Only scored 17.6. Too slow — recomputing O(N) cost per move means few iterations.
- **Large segment 2-opt in SA**: Segment length > 500 makes penalty recomputation too expensive. Capped at 500 in the probe.
- **Compiling locally with `bits/stdc++.h`**: Fails on macOS clang. The judge uses g++ so it works there. Don't try to compile locally — just submit to the judge.

## What I Excluded and Why

- **Exact TSP solvers** (Concorde, branch-and-bound): N=200K is far too large.
- **Lin-Kernighan heuristic**: Complex to implement within the solution file, and the penalty structure complicates LK's gain computation. SA with simple moves is more robust.
- **Genetic algorithms**: Crossover operators for TSP are complex and unlikely to outperform SA within 2 seconds.

## Evolution of Thinking

Started thinking standard 2-opt would be sufficient. Discovered that (a) full-recompute makes 2-opt too slow, (b) the penalty structure means reversing segments changes which cities sit at penalty positions, making delta computation more complex than standard TSP. Shifted to Or-opt (relocate) as the primary move because it only touches 3 edges and affects at most 1-2 penalty positions. Added prime scheduling as a separate post-pass because interleaving it with SA adds complexity without clear benefit.

## Current Status

- **Validated:** Judge scoring works, sequential=0, NN+limited-SA=33.5, output format confirmed.
- **Uncertain:** Whether grid-based NN construction can run fast enough for N=200K to leave >1.5s for SA. Whether prime scheduling adds meaningful score improvement over plain SA.
- **Suggested next:** If iter-1 scores plateau around 50, try: (1) LK-style moves, (2) segment-specific penalty optimization, (3) different construction heuristics (Christofides-like), (4) larger-segment 2-opt with lazy penalty recomputation.

## Warnings & Constraints

- **Do NOT try to compile locally** — `bits/stdc++.h` is not available on macOS clang. The judge compiles with g++. Just write the code and submit to `fmeasure_44.sh`.
- **Time limit is 2 seconds** — budget construction at ~0.2s max, leave 1.7s+ for SA.
- **Output format is strict**: first line is N+1, then N+1 lines each with one city ID. No spaces, no extra lines.
- **The judge runs multiple test cases** — the score is averaged. Optimizing for one size may hurt on others.
