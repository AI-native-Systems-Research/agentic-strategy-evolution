# Handoff — Iteration 3

## Goal

Push the 2D rectangular knapsack score beyond 95.21 by expanding the MaxRects heuristic set from 4 to 8, adding per-item rotation mode as an SA dimension, and tuning SA cooling/restart strategy.

## Key Discoveries

- Expanding from 4 to 8 heuristics provides ~+0.4 points (95.21 → 95.61)
- Per-item rotation mode adds ~+0.07 points (95.61 → 95.68)
- SA cooling rate is critical: T*=0.995 dramatically outperforms T*=0.9995 (+0.8 points), suggesting iter-2's SA was under-exploiting
- 3 SA restarts outperform 2 restarts (96.47 vs 96.37)
- 10 heuristics is worse than 8 — dilutes the search space (96.28 vs 96.47)
- Slower cooling (T*=0.9997) and faster cooling (T*=0.99) both hurt; 0.995 is the sweet spot
- Best probed score: 96.55 (range 96.3-96.5 across runs)

## System Interface

- **Build:** N/A (judge compiles server-side)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** `SCORE: <float>` on stdout
- **Baseline result:** 95.21 (iter-2), probed h-main: ~96.47

## Code Map

- `solution.cpp` — the entire solution; replace with improved algorithm
- `runs/iter-2/patches/h-main.patch` — iter-2's solution (95.21)
- `runs/iter-3/patches/h-main.patch` — iter-3's h-main solution (~96.47)
- Judge: `/Users/toslali/frontier/Frontier-CS/src/frontier_cs/runner/algorithmic_local.py`

## Code Targets

- **h-main**: `solution.cpp` — apply `runs/iter-3/patches/h-main.patch` (already validated, ~96.47)
- **h-control-negative**: `solution.cpp` — same as h-main but change `NH = 8` to `NH = 4` and remove heuristic cases 4-7 from the switch statement. Keep all other SA improvements (cooling, restarts, rotation mode).

## What I Tried That Didn't Work

- **10 heuristics**: Score dropped to 96.28 from 96.47 — too many heuristics dilutes SA search
- **Slower SA cooling (T*=0.9997)**: 95.57, worse than T*=0.9995 baseline
- **Faster SA cooling (T*=0.99)**: 96.31, worse than T*=0.995
- **Complete rewrite** with separate rotation handling: Scored 6.38 — catastrophic regression; must build incrementally from iter-2
- **2 SA restarts**: 96.37, worse than 3 restarts at 96.47
- All iter-1 dead ends still apply: bitmask rotation, interleaved packing, skyline packer, contact perimeter, local macOS compilation

## What I Excluded and Why

- **Per-item rotation as SA dimension for non-rotation tests**: When `allow_rotate=false`, rotation moves fallback to heuristic changes (handled in code)
- **Ruin-and-recreate**: Would require fundamentally different SA move structure; deferred to iter-4 if needed
- **Different packing algorithms** (guillotine, shelf): MaxRects + SA remains the dominant approach
- **More SA dimensions** (per-item max-copies limit): Would add complexity without clear mechanism

## Evolution of Thinking

Started by writing a completely new solution (catastrophic failure at 6.38). Learned that incremental modifications to the proven iter-2 code are essential. The key insight was that SA cooling rate matters far more than expected — going from 0.9995 to 0.995 (10x faster cooling per iteration) gained almost 1 full point. This suggests iter-2's SA was doing too much random exploration and not enough exploitation. Combined with the expanded heuristic space (8 vs 4), the SA has more to exploit.

The rotation mode dimension was a smaller but real improvement (~0.07 points), confirming that even per-item rotation choice can be suboptimal when decided greedily.

## Current Status

- **Validated:** 8 heuristics + rotation mode + SA tuning = ~96.47 (range 96.3-96.55)
- **Uncertain:** Whether the new heuristics or SA tuning is the primary driver (h-control-negative will answer this)
- **Suggested next:** If score plateaus near 96.5, consider: (a) ruin-and-recreate moves in SA, (b) problem-specific strip packing for tall/wide items, (c) multi-resolution packing (coarse then fine), (d) learning item-type-specific heuristic preferences from initial probes

## Warnings & Constraints

- Judge takes 30-60s per call — budget measurement calls carefully
- `bits/stdc++.h` only works server-side; do NOT try local macOS compilation
- Time limit is 1s per test; must self-monitor elapsed time
- Score varies by ~0.2 points across runs due to server-side timing differences
- CRITICAL: Do not rewrite the solution from scratch — always start from the iter-2/iter-3 patch and modify incrementally
- The `NH` constant must match the array sizes for `heurBest[]` and `heurBestPerm[]`
