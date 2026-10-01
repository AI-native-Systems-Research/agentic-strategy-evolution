# Handoff — Iteration 2

## Goal

Push the 2D rectangular knapsack score beyond 94.84 by implementing simulated annealing over item orderings and a residual gap-filling pass in MaxRects packing.

## Key Discoveries

- Iter-1's hill-climbing adds ~0.4 points over permutation + random search (94.45 → 94.84), but stops at first local optimum
- The iter-1 h-main.patch at `runs/iter-1/patches/h-main.patch` contains the 94.84 solution — use it as starting point
- Item ordering is the dominant lever (RP-1); the packer heuristic matters less
- 4 heuristics work: BSSF (best short side fit), BAF (best area fit), BL (bottom-left), BLSF (best long side fit)
- `bits/stdc++.h` works server-side; do NOT try local compilation on macOS
- The judge runs 15 test cases; bins 900-2000, 8-12 types, 1s time limit per test

## System Interface

- **Build:** N/A (judge compiles server-side)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** `SCORE: <float>` on stdout
- **Baseline result:** 94.84 (iter-1 h-main)

## Code Map

- `solution.cpp` — the entire solution; replace with improved algorithm
- `runs/iter-1/patches/h-main.patch` — iter-1's best solution (94.84), use as reference/starting point
- Judge: `/Users/toslali/frontier/Frontier-CS/src/frontier_cs/runner/algorithmic_local.py` — submits to Docker judge

## Code Targets

- **h-main**: `solution.cpp` — write a new complete solution with these components:
  1. MaxRects packer with 4 heuristics (BSSF, BAF, BL, BLSF) — keep from iter-1
  2. Initial sorted orderings + greedy packing — keep from iter-1
  3. **NEW: Simulated annealing** replacing hill-climbing: start from best known ordering per heuristic, use swap/insert/reverse-subsequence neighborhoods, T₀ = 0.1 * bestProfit, α = 0.995
  4. **NEW: Gap-filling pass** after each ordered pack: iterate remaining free rectangles, try placing any item type with remaining copies (sorted by value density)
  5. Random perturbation restarts for remaining time
  
- **h-ablation**: Same solution but disable the gap-filling pass (just comment out or skip that function call)

## What I Tried That Didn't Work (from iter-1)

- Bitmask rotation exploration: too slow, reduced permutation budget (94.02)
- Interleaved packing: overhead reduced permutation budget (94.19)
- Skyline packer: less flexible than MaxRects (94.35)
- Contact perimeter heuristic: O(n²) per placement, too slow (RP-2)
- Local macOS compilation: `bits/stdc++.h` not available

## What I Excluded and Why

- ILP/exact methods: 1s time limit with 100-1000+ placements makes this infeasible
- Guillotine cutting: MaxRects is strictly more flexible
- Contact perimeter scoring: too slow per RP-2
- Column generation: complexity doesn't fit 1s budget

## Evolution of Thinking

Iter-1 proved ordering search is the dominant lever. Hill-climbing was the biggest single improvement (+0.4 points). The natural next step is SA (escape local optima) + gap filling (capture residual value). The gap filling is motivated by the observation that ordered packing processes types sequentially — once it moves past type A, free space that could still fit A copies is wasted.

## Current Status

- **Validated:** MaxRects + hill-climbing at 94.84 (iter-1)
- **Uncertain:** Whether SA provides meaningful improvement over hill-climbing for M=8-12 ordering space; whether gap filling captures meaningful residual value
- **Suggested next:** If score plateaus near 95, consider: (a) look-ahead rotation decisions, (b) partial repack (remove + reinsert items), (c) strip packing for large items, (d) problem-specific density-aware placement

## Warnings & Constraints

- Judge takes 30-60s per call — budget measurement calls carefully
- `bits/stdc++.h` only works server-side
- Time limit is 1s per test; solution must self-monitor elapsed time
- Large JSON output must use `printf` not `cout` for speed
- The current `solution.cpp` in worktree is the iter-1 design-phase version (94.46), NOT the executor's improved version (94.84). Use the iter-1 patch as reference.
