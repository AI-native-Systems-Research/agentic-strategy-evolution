# Handoff — Iter 3

## Goal

Push judge score above 78.8 (iter-2 h-ablation best) by extending Or-opt to multi-city segments (1-3), adding grid-guided insertion for Or-opt, rebalancing move mix, and tuning SA temperature.

## Key Discoveries

- **Iter-2 h-ablation scores 78.8** (measured: 78.819). This is the baseline to beat.
- **Double-bridge HURTS** (RP-4): iter-2 h-main with double-bridge scored lower (75.7 mean) than h-ablation without it (76.7 mean). Do NOT use perturbation.
- **Or-opt currently only relocates single cities** (solution.cpp lines 206-234). Segments of 2-3 find improvements that single-city misses — standard TSP technique.
- **Or-opt shift range is only 15 positions** — for N=200K this is tiny. Increasing to 50 or using grid-guided insertion should find better targets.
- **Move mix is 70/15/15** (grid 2-opt / random short 2-opt / Or-opt). Or-opt gets relatively few tries despite being cheaper per iteration.
- **Score variance ±5 points** due to machine load on 2s time limit. Multiple runs needed to distinguish signal from noise.
- **Cannot compile locally** — `bits/stdc++.h` only on judge's g++.

## System Interface

- **Build:** None — judge compiles internally.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout.
- **Baseline result:** 78.819 (iter-2 h-ablation).

## Code Map

- `solution.cpp` — the only file. Start from iter-2 h-ablation patch.
- `runs/iter-2/patches/h-ablation.patch` — the 78.8-scoring solution. Apply first, then modify.
- Key functions in iter-2 h-ablation:
  - `buildGrid()` (line 44) — builds spatial grid for NN construction and neighbor selection.
  - `constructNN()` (line 65) — grid-based nearest-neighbor tour construction.
  - `gridNeighbor()` (line 89) — picks a random city from nearby grid cells. **Reuse for Or-opt insertion guidance.**
  - `twoOptDeltaFast()` (line 107) — penalty-aware O(1 + seg/10) delta. Keep as-is.
  - SA loop (line 164) — main optimization. **Modify move mix and add multi-city Or-opt here.**
  - Or-opt section (line 206) — single-city relocate. **Extend to segments of 1-3.**
  - Prime scheduling (line 240) — post-pass. Keep as-is.

## Code Targets

### h-main → `solution.cpp`
Start from iter-2 h-ablation patch, then:

1. **Or-opt extension (lines 206-234)**: Currently relocates single city at `tour[i2]`. Extend to handle segments of k=1,2,3 cities starting at `tour[i2..i2+k-1]`. For each:
   - Remove the k cities from their current position
   - Reinsert them at target position j
   - Delta: recompute edges at cut points (before/after removed segment) and insert points (where segment lands), plus any penalty positions in the shifted range
   - Use `memmove` for the array shift, update `pos[]` for affected positions

2. **Grid-guided insertion**: For Or-opt, compute the centroid of the removed segment. Call `gridNeighbor()` with the centroid to get a target city. Use `pos[target_city]` as the insertion position. This focuses Or-opt on spatially productive targets.

3. **Move mix (line 171-173)**: Change `mv<70` to `mv<55` for grid 2-opt, `mv<85` to `mv<65` for random short 2-opt, remainder (35%) for Or-opt.

4. **Or-opt shift range (line 208)**: Change `maxS=min(15,N/3)` to `maxS=min(50,N/3)`.

5. **SA temperature (line 161)**: Change `curCost/(N*2.0)` to `curCost/(N*3.0)`.

### h-control-negative → `solution.cpp`
Apply iter-2 h-ablation patch unchanged. No modifications.

## What I Tried That Didn't Work (accumulated)

- **Sequential tour**: Scores 0 — it IS the baseline (iter-1).
- **Naive 2-opt with full recompute**: Only 17.6 (iter-1).
- **Large segment 2-opt without fast delta**: Too slow (iter-1).
- **Double-bridge perturbation**: Hurts within 2s for N=200K (iter-2, RP-4).
- **Compiling locally with `bits/stdc++.h`**: Fails on macOS clang.

## What I Excluded and Why

- **LK-style moves**: Complex to implement correctly with penalty structure. Deferred to iter-4 if Or-opt extension plateaus.
- **3-opt**: Similar complexity concern. Double-bridge (a form of non-sequential 3-opt) was already shown to hurt.
- **Population-based methods**: Would require maintaining multiple tours; memory and complexity concern within 2s.
- **Different construction heuristics**: NN construction takes only ~0.1s and produces reasonable starting tours. Improvement from better construction is marginal compared to SA improvement.
- **KNN precomputation**: RP-3 shows grid-guided is better under tight time limits.

## Evolution of Thinking

Iter-1 established grid-guided 2-opt + penalty delta as the core (69.5→78.8). Iter-2 tried diversification via double-bridge but it hurt (RP-4). The lesson: within 2s, maximizing productive local search iterations beats trying to escape local optima. Iter-3 follows this by enriching the local search moves (multi-city Or-opt) rather than adding perturbation. The hypothesis is that the current solution is limited by Or-opt quality (single-city only, random insertion), not by being stuck in a local optimum.

## Current Status

- **Validated:** Iter-2 h-ablation scores 78.8. Grid-guided 2-opt + penalty delta + Or-opt is the proven core. Judge interface confirmed.
- **Uncertain:** Whether multi-city Or-opt adds enough vs the per-move cost increase. Whether grid-guided insertion for Or-opt is better than random shift. Whether cooler SA start helps.
- **Suggested next:** If iter-3 plateaus, consider: (1) LK-style sequential moves with backtracking, (2) adaptive segment size for 2-opt based on progress, (3) temperature recalibration based on acceptance rate monitoring.

## Warnings & Constraints

- **Do NOT compile locally** — `bits/stdc++.h` not available on macOS. Submit directly to judge.
- **Time limit 2 seconds** — all computation must fit. Leave 0.2s margin (use tl=1.78).
- **Output format strict**: N+1 on first line, then N+1 city IDs, one per line.
- **Score variance ±5 points** — run each arm at least once but be aware a single measurement may not be conclusive. The judge averages over multiple test cases internally.
- **Or-opt delta for multi-city segments**: Must account for all penalty positions in the shifted range, not just endpoints. The brute-force recompute approach (loop over ec(s) for affected positions) works correctly if the range [lo..hi] covers all affected steps.
- **memmove for segment relocation**: When removing k cities and reinserting them, careful with overlap in memmove. Test the logic mentally for j>i2 and j<i2 cases.
