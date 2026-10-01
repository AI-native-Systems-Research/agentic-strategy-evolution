# Handoff — Iteration 1

## Goal

Implement and measure a MaxRects-based 2D bin packing algorithm for problem #47 that maximizes the judge score (0–100 continuous).

## Key Discoveries

- The judge compiles and runs solutions in Docker — `bits/stdc++.h` works server-side even though it fails on local macOS clang.
- Local compilation is NOT needed; just edit `solution.cpp` and run `fmeasure_47.sh`.
- The measure script takes ~30-60s per invocation (15 test cases).
- Bins are 900–2000 in each dimension, 8–12 item types, limits up to 2000 copies per type.
- MaxRects with exhaustive permutation search over M≤10 item orderings × 3 heuristics achieves ~94.5.
- Global greedy (per-placement item selection) adds marginal improvement over sorted-order packing.
- The scoring formula `(V-B)/(K-B)` means gains get harder as V approaches the fractional upper bound K.

## System Interface

- **Build:** N/A (judge compiles server-side)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** `SCORE: <float>` on stdout
- **Baseline result:** SCORE: 94.45574

## Code Map

- `solution.cpp:1` — the entire solution file; replace stub with algorithm
- Judge: `/Users/toslali/frontier/Frontier-CS/src/frontier_cs/runner/algorithmic_local.py:154` — evaluate() submits code to Docker judge

## Code Targets

- **h-main**: `solution.cpp` — replace the 3-line stub with the full MaxRects implementation (~350 lines). The file is in the worktree root.

## What I Tried That Didn't Work

- v1 (first attempt, simpler MaxRects + skyline): 94.35 — skyline packer was buggy, MaxRects alone was better
- v2 (cleaner MaxRects, rotation combos via bitmask): 94.02 — worse because bitmask rotation exploration was too slow, reducing time for permutation search
- v3 (interleaved packing + permutation): 94.19 — interleaved packing overhead reduced permutation budget
- Local compilation with clang on macOS fails due to missing `bits/stdc++.h` and C++ stdlib headers — don't bother, just use the judge

## What I Excluded and Why

- Simulated annealing / local search over placement positions: the 1-second time limit makes it hard to do both exhaustive ordering search AND local search. Ordering search empirically dominates.
- Guillotine cutting: MaxRects is strictly more flexible and the constraint set doesn't require guillotine cuts.
- ILP/exact solver: 1-second limit with potentially 1000+ placements makes exact methods infeasible.

## Evolution of Thinking

Started with skyline packing (simpler) but MaxRects proved much better due to its ability to track all free space. Discovered that item ordering is the primary lever — the same packer with different orderings can vary by 10+ points. Permutation exhaustion is key for M≤10 (covers 362K–3.6M orderings). For M=11-12, random shuffle search partially compensates.

## Current Status

- **Validated:** MaxRects + multi-heuristic + permutation search achieves 94.46 (v5)
- **Uncertain:** Whether the remaining 5.5 points are achievable within 1s — may need fundamentally different approaches (e.g., column generation, constraint programming)
- **Suggested next:** Try (1) smarter rotation decisions via lookahead, (2) strip-packing hybrid for large items, (3) simulated annealing over item orderings instead of exhaustive permutation, (4) problem-specific heuristics based on value-density clustering

## Warnings & Constraints

- The judge takes 30-60s per call — budget your measurement calls.
- `bits/stdc++.h` only works server-side; don't try to compile locally on macOS.
- Time limit is 1s per test case; the solution must self-monitor elapsed time and stop search early.
- Large JSON output (1000+ placements) must be printed efficiently — use `printf` not `cout`.
