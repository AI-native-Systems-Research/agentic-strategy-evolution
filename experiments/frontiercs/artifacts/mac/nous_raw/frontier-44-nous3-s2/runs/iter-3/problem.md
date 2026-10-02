# Problem Framing — Iter 3

## Research Question
Can grid-guided 2-opt with exact position tracking, combined with random swap SA, push the score beyond the 69.5 plateau established in iterations 1–2? The hypothesis is that spatially-intelligent 2-opt moves (using the NN construction grid for neighbor lookup) provide structured local search that random moves cannot.

Key source files: `solution.cpp:1` (the only file).

## System Interface
- **Build:** None — the judge compiles internally.
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` on stdout.
- **Code evidence:** The judge script at `fmeasure_44.sh` compiles and runs the solution against multiple test cases, averaging per-test scores.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation
Iter-2 solution (random swap + boundary 2-opt SA) scores 69.50 consistently (69.50 ± 0.01 across multiple runs). Exit code 0, output format `SCORE: 69.5025`.

## Experimental Conditions

### h-main: Two-phase grid-guided 2-opt SA
Changes from iter-2 baseline:
1. **Phase 1 (0–1.3s):** Grid-guided 2-opt SA with stale pos[], unlimited segment length, batch=300 with periodic pos[]/cost rebuild. 80% grid-guided 2-opt + 20% random swap.
2. **Phase 2 (1.3–1.85s):** Grid-guided 2-opt SA with exact pos[], short segments (≤20), lower temperature. 80% grid-guided 2-opt + 20% random swap.
3. **Grid:** GG=sqrt(N) for fine spatial resolution (~1 city/cell). Same grid used for NN construction and SA neighbor lookup.
4. **Mechanism:** Grid lookup finds spatially nearby cities in O(1). 2-opt between their tour positions uncrosses edges. Short segments keep pos[] update cost at O(20) in Phase 2.

### h-control-negative: Iter-2 baseline (for comparison)
The existing iter-2 solution: NN construction + random swap/2-opt SA. Expected score: ~69.5.

## Success Criteria
- h-main scores consistently above 71.0 (directional improvement over 69.5).
- The improvement is reproducible across multiple runs (not within judge noise of ±0.02).

## Constraints
- Time limit: 2 seconds per test case.
- Memory limit: 512 MB.
- No external compilation — judge compiles internally.
- Cannot use `bits/stdc++.h` locally (macOS), but the judge supports it.

## Prior Knowledge
- RP-1: Grid-guided 2-opt with penalty-aware exact delta + Or-opt + pos[] tracking + continuous SA outperforms random swap SA by ~9.3 points. Grid-based spatial neighbor lookup is the critical enabler.
- RP-2: Penalty structure contributes ≤1% to total tour cost. Prime scheduling adds <1 point.
- RP-3: Grid-guided (G=sqrt(N)) outperforms KNN and random for 2-opt candidate selection.
- RP-4: Double-bridge perturbation hurts within 2s time limit.
- RP-5: Multi-city Or-opt (segments 1-3) doesn't measurably improve beyond single-city.

### Iter-2 dead ends avoided:
- Random 2-opt contributes nothing (100% swap = 69.49, same as 40/60 mix)
- Nearby swap (|p-q|<100) loses diversification (64.5)
- NN-guided 2-opt with precomputed KNN is timing-sensitive
- Double-bridge destroys structure SA can't recover
- Or-opt with memmove is too expensive for large |p-q|

### New findings from iter-3 exploration:
- Grid-guided 2-opt with exact pos[] and short segments (≤20) scores ~72.0
- Two-phase approach (stale pos + exact pos) scores ~72.2
- maxSeg=20 is optimal (20: 72.02, 40: 72.0, 80: 68.0)
- Coarser grids (GG=sqrt(N/2)) destroy score (54.5)
- Batch=300 with rebuild every batch is optimal for stale-pos phase
- 80/20 2-opt/swap ratio is optimal (100% 2-opt: 72.1, 50/50: 69.9)
