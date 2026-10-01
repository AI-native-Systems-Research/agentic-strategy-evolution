# Problem Framing — Iter 3

## Research Question

Can multi-city Or-opt (segments of 1-3 cities) with grid-guided insertion point selection, combined with SA parameter tuning, push the judge score beyond iter-2's 78.8 for penalty-aware TSP?

The current best solution (`runs/iter-2/patches/h-ablation.patch`) uses:
- Grid-guided 2-opt (70%), random short 2-opt (15%), single-city Or-opt (15%)
- Penalty-aware fast delta for 2-opt
- Grid-based NN construction + prime scheduling post-pass

Key files: `solution.cpp` (only file). Mechanism: `twoOptDeltaFast()` at line 107, SA loop at line 164, Or-opt at line 206, prime pass at line 240.

## System Interface

- **Build:** None — judge compiles internally with g++ and `bits/stdc++.h`.
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` on stdout.
- **Code evidence:** `solution.cpp:170` — SA inner loop (3000 iterations per time check). `solution.cpp:173` — move type selection (70/15/15 mix). `solution.cpp:207-234` — single-city Or-opt with random shift ≤15.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

With the iter-2 h-ablation patch applied.

## Baseline Validation

Ran iter-2 h-ablation patch: exit code 0, output `SCORE: 78.81899999999999`. This confirms the baseline works and produces expected output.

## Experimental Conditions

### h-main: Multi-city Or-opt + SA tuning
Starting from iter-2 h-ablation code, make these changes to `solution.cpp`:

1. **Multi-city Or-opt (segments 1-3)**: Extend the Or-opt move to relocate segments of 1, 2, or 3 consecutive cities. For segment size k at position i, remove cities tour[i..i+k-1] and reinsert them at position j. Delta touches 2*(k+1) edges at cut/insert points plus penalty positions in the affected range.

2. **Grid-guided insertion for Or-opt**: Instead of random shift, pick a target position by finding a grid neighbor of the segment's centroid. Insert the segment next to that neighbor's tour position.

3. **Move mix rebalance**: Change from 70/15/15 (grid 2-opt / random 2-opt / Or-opt) to 55/10/35 to give Or-opt more opportunities.

4. **Increase Or-opt shift range**: From max 15 to max 50 for wider search.

5. **SA temperature tuning**: Start temp at `curCost/(N*3.0)` instead of `curCost/(N*2.0)` for a cooler start that wastes less time on bad moves.

### h-control-negative: Single-city Or-opt (iter-2 baseline)
The iter-2 h-ablation patch exactly as-is. Confirms the baseline score hasn't changed due to judge variance.

## Success Criteria

h-main scores higher than h-control-negative (iter-2 baseline of ~78.8) consistently across runs.

## Constraints

- 2-second time limit per test case, N up to 200K.
- Cannot compile locally (`bits/stdc++.h` is g++-only).
- Double-bridge perturbation refuted (RP-4) — do not use.
- Score variance of ±5 points due to machine load (observed in iter-2).

## Prior Knowledge

- RP-1: Grid-guided 2-opt + penalty delta + Or-opt + pos[] is the winning combo (~78.8 vs ~69.5).
- RP-2: Penalty structure contributes <1% to total cost; prime scheduling adds <1 point.
- RP-3: Grid-guided neighbor selection outperforms KNN under tight time limits.
- RP-4: Double-bridge hurts within 2s for N=200K — do NOT use.
