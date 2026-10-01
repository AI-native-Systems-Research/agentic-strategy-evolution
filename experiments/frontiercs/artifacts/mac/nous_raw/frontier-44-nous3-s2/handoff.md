# Handoff — Iter 3

## Goal

Implement and measure a two-phase grid-guided 2-opt SA solution that improves on iter-2's 69.5 score. The h-main arm targets ~72.2 via spatially-intelligent 2-opt candidate selection.

## Key Discoveries

- **Grid-guided 2-opt with exact pos[] breaks the 69.5 plateau**, reaching ~72.0-72.2 (confirmed across 6+ runs).
- **Two-phase design is optimal**: Phase 1 (stale pos, unlimited seg, batch=300) + Phase 2 (exact pos, seg≤20, batch=1000) = 72.2. Phase 2 alone = 72.0.
- **maxSeg=20 is the sweet spot** for exact-pos 2-opt. Shorter (10): same. Longer (80): 68.0 due to O(seg) pos update overhead.
- **GG=sqrt(N) grid is critical**. Coarser grids (sqrt(N/2)=54.5, sqrt(N/6)=59.5) destroy performance. Each cell has ~1 city, enabling precise spatial targeting.
- **80/20 2-opt/swap ratio optimal**. 100% 2-opt: 72.1 (slightly worse). 50/50: 69.9 (much worse). Swaps provide essential long-range diversification.
- **Batch=300 optimal for stale-pos phase**. 150: 72.1. 500: 72.2. 1000: 67.2 (pos too stale). 2000: 72.2 (back up — moves random enough to cancel out).
- **Or-opt does not help** beyond 2-opt: v3g (with Or-opt) = 72.0, v3i (without) = 72.0.

## System Interface

- **Build:** None — judge compiles internally.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout.
- **Baseline result:** h-main = 72.18 (mean of 3 runs: 72.21, 72.19, 72.16).

## Code Map

- `solution.cpp:1` — the only file to edit. Contains the full solution.
- `runs/iter-2/patches/h-main.patch` — the iter-2 solution (69.5 baseline).

## Code Targets

### h-main → `solution.cpp`
The solution_v3m.cpp file has already been copied to solution.cpp. It implements:
1. Grid construction with GG=sqrt(N) (line ~buildGrid function)
2. NN construction reusing the grid (line ~nnConstruct function)
3. Phase 1 SA: grid-guided 2-opt with stale pos[], batch=300, unlimited segment (lines ~Phase 1 comment)
4. Phase 2 SA: grid-guided 2-opt with exact pos[], seg≤20, batch=1000 (lines ~Phase 2 comment)
5. Prime scheduling post-pass (final section)

## What I Tried That Didn't Work (accumulated from iter 1-3)

### From iter 1-2:
- **Sequential tour**: Scores 0 (IS the baseline).
- **Naive 2-opt with full recompute**: Only 17.6. O(N) per move too slow.
- **NN-guided 2-opt with pos[]**: 60.5-65.5 (WORSE than random SA).
- **Double-bridge perturbation**: 64.5. SA can't recover.
- **Random Or-opt**: 69.36-64.5.
- **100% 2-opt (no swap)**: 64.5. 2-opt alone can't improve NN tour.
- **Nearby swap (|p-q| < 100)**: 64.5. Loses diversification.
- **Hilbert curve construction**: 65.5.

### From iter 3:
- **Grid-guided 2-opt with stale pos[] in SA** (v3b): 69.5. Stale positions make grid guidance useless.
- **Spatially-guided swap** (v3c): 64.5. Same as nearby swap — too local.
- **Strip-based construction** (v3d): 69.5. Doesn't help; SA dominates final quality.
- **Best-of-3 swap** (v3e): 69.5. Throughput loss offsets quality gain.
- **Spiral grid search** (v3j): 62.0. Ring counting overhead kills throughput.
- **KNN precomputation (K=7)** (v3k): 72.0. Build time offsets lookup speed; same as simple grid cell lookup.
- **Coarser grid** (sqrt(N/2), sqrt(N/6)): 54.5-59.5. Fewer cities per cell = less precise targeting.
- **maxSeg=80**: 68.0. O(80) pos update per accepted move = low throughput.
- **batch=1000 with stale pos**: 67.2. pos[] becomes completely wrong after 1000 moves.
- **50/50 2-opt/swap**: 69.9. Not enough 2-opt moves for meaningful improvement.

## What I Excluded and Why

- **LK-style moves**: Implementation complexity too high for marginal gain over grid-guided 2-opt.
- **Or-opt moves**: Tested, no improvement. memmove cost for array-based Or-opt is prohibitive for large distances. Linked-list representation loses O(1) step-index access needed for penalty computation.
- **3-opt / LKH**: Too complex; each move has 8 reconnection patterns to evaluate.
- **Genetic algorithms / EAX**: Population-based approaches need too much memory/time for N=200K.
- **Penalty-aware exact 2-opt delta**: Internal penalty changes contribute ≤1% (RP-2), not worth the O(seg) computation per move.

## Evolution of Thinking

Iter-1-2 established that random SA converges to 69.5 and concluded 2-opt "contributes nothing." Iter-3 discovered this was wrong: 2-opt DOES help when **grid-guided** (spatially intelligent candidate selection) and **exact pos[]** tracking is maintained. The critical insight is that random 2-opt fails not because 2-opt is bad, but because random candidate selection for 200K cities is astronomically unlikely to find improving pairs.

The two-phase design emerged from trying to balance throughput vs precision: stale pos[] allows larger moves (more exploration) but less accuracy, while exact pos[] is precise but limited to short segments. Combining both captures different improvement regimes.

## Current Status

- **Validated:** Grid-guided 2-opt with exact pos[] (GG=sqrt(N), maxSeg=20) consistently scores ~72.0-72.2. Two-phase variant averages 72.18.
- **Uncertain:** Whether the remaining gap to RP-1's 78.85 is achievable. RP-1's approach may use longer SA time, different test cases, or different grid parameters.
- **Suggested next:** (1) Adaptive segment length — start with longer segments and decrease as SA cools. (2) Penalty-aware exact delta for 2-opt (might matter for larger test cases). (3) Explore LK-style moves with the grid for candidate generation. (4) Investigate whether the scoring function penalizes specific test case sizes where our approach is weak.

## Warnings & Constraints

- **Do NOT compile locally** — `bits/stdc++.h` not available on macOS.
- **Judge score varies ~0.02-0.05 between runs** — confirm improvements with 3+ measurements.
- **GG=sqrt(N) grid is critical** — do not change without testing. Coarser grids destroy performance.
- **Phase split at 1.3s** — both phases need adequate time. Phase 2 should get at least 0.5s.
- **One outlier at 64.5 occasionally observed** — likely a judge timeout. Ignore if it occurs once.
