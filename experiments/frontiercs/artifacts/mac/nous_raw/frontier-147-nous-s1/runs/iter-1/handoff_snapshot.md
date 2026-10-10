# Handoff — Iter 1

### Goal
Implement two solution variants for AHC001 rectangle packing (problem #147) and measure their judge scores: (1) SA with coordinated neighbor moves, (2) greedy-only baseline.

### Key Discoveries
- **Trivial 1×1 scores 0**: The satisfaction formula yields ~0 when area=1 vs desired areas averaging 500K.
- **Greedy expansion scores ~20.5**: Expanding rectangles by 1 cell per direction per iteration, 500 iterations.
- **Basic SA scores ~85.1**: Greedy init (2000 iters, ~1s) + SA with single-edge moves (1.8s) using T0=0.05→T1=0.001. This is the validated strong baseline.
- **N ≤ 200**: O(N) overlap checks per SA move are fast enough (~200 comparisons × millions of moves in 2s).
- **Time limit is ~3s** per test case. Budget: <1s greedy init, ~1.8s SA, 0.2s margin.
- **Output format**: N lines, `a b c d` per line. The judge is strict on format.
- **`bits/stdc++.h` works**: The judge's compiler supports it even though local macOS clang doesn't.

### System Interface
- **Build:** Judge compiles automatically; no local build needed.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** stdout prints `SCORE: <n>` where n is 0–100.
- **Baseline result:** SA approach scored 85.1.

### Code Map
- `solution.cpp:1` — The only file. Contains entire solution. Executor replaces this per arm.
- Scoring: `p_i = 1 - (1 - min(r,s)/max(r,s))^2`. Key insight: even 50% area match gives p_i=0.75. Getting within 2x of desired area is most of the score.

### Code Targets
- **h-main** (`solution.cpp`): Rewrite to add coordinated neighbor moves. When edge of rect i moves, detect adjacent rect j and expand j simultaneously. Add area-sorted greedy init. Keep the SA framework (T schedule, timer, edge moves).
- **h-control-negative** (`solution.cpp`): Strip out SA phase entirely. Keep only greedy expansion loop.

### What I Tried That Didn't Work
- Local compilation with `g++` fails on macOS (no `bits/stdc++.h`). Must use the judge for testing. Each judge call takes ~30-60s.

### What I Excluded and Why
- **BSP/Voronoi initial placement**: More complex to implement, and the greedy init already gives SA a reasonable starting point. Could explore in iter 2 if SA improvements plateau.
- **Rectangle swaps**: Swapping two companies' rectangles is complex with overlap constraints. Deferred.
- **Multi-edge moves**: Moving two edges of the same rectangle simultaneously. Could help but adds complexity. Deferred.

### Evolution of Thinking
Started expecting greedy to score maybe 50+. It only scored ~20.5 because single-cell expansion is very slow to fill large areas. SA was the key breakthrough — it can both grow and shrink rectangles, enabling efficient reallocation. The main score lever is area matching, not point containment (containment is easy).

### Current Status
- **Validated:** Judge pipeline works. Basic SA scores 85.1. Greedy scores 20.5.
- **Uncertain:** How much coordinated moves improve over independent edge moves. Whether better init (area-sorted) matters once SA runs long enough.
- **Suggested next:** If SA with coordinated moves hits 87+, explore (iter 2) temperature tuning or multi-point restart. If it plateaus at ~85, try fundamentally different init (BSP partition).

### Warnings & Constraints
- Judge calls take 30-60s. Each arm = one judge call. Budget accordingly.
- Cannot compile locally on macOS — `bits/stdc++.h` not available. If you need local testing, replace with individual includes.
- The timer in the solution uses wall clock. Judge runs on server — calibrate `time_limit` conservatively (2.8s used).
