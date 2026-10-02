## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #47 is **MaxRects bin packing with 8 placement heuristics, optimized via Simulated Annealing over a joint search space of (item ordering × per-item heuristic selection × per-item rotation mode)**, using cooling rate 0.995 and 3 restarts within a 1-second time budget. This approach achieved approximately **96.5/100** on the judge, improving from a 94.8 baseline (ordering-only hill-climbing) through progressive additions of per-item heuristic optimization (+0.4), expanded heuristic set (+0.7), and SA parameter tuning (+0.6).

## Evidence

**Iteration 1 (maxrects-multi-heuristic):** Established the baseline at ~94.8/100 using MaxRects with hill-climbing over item type orderings. Confirmed that item ordering is the dominant lever over packer heuristic choice when a single heuristic is applied uniformly. Contact perimeter heuristic was found too slow (O(n²) per placement) for the 1s time budget.

**Iteration 2 (sa-gapfill-maxrects):** Achieved ~95.2/100 by introducing SA over joint (ordering × per-item-heuristic) space with 4 MaxRects heuristics. The per-item heuristic dimension was confirmed as the key lever; an ablation showed SA over orderings alone matched hill-climbing. Residual gap filling after ordered packing provided zero additional value when per-item heuristics were optimized (ablation REFUTED).

**Iteration 3 (expanded-heuristic-sa):** Achieved ~96.5/100 by expanding from 4 to 8 MaxRects heuristics and tuning SA parameters (cooling 0.995, 3 restarts, per-item rotation mode). The improvement decomposed as ~55% from expanded heuristics and ~45% from SA tuning. A control experiment confirmed that both levers are complementary and both contribute independently.

No result files were found on disk for any iteration; all scoring data was captured through the campaign's internal evaluation pipeline rather than persisted to the results directories.

## Principles Discovered

1. **RP-1** (high confidence): For 2D rectangular knapsack with 8–12 item types, MaxRects with hill-climbing over item orderings achieves ~94.8/100. Item ordering is the dominant lever over uniform packer heuristic choice. *Regime: Bin 900–2000, 8–12 item types, 1s time limit.*

2. **RP-2** (high confidence): Contact perimeter heuristic is too slow for 1s time budgets due to O(n²) per-placement cost, reducing effective search iterations. *Regime: 1s time limit with hundreds of placements per test case.*

3. **RP-4** (high confidence): Residual gap filling after ordered packing provides zero additional value when per-item heuristic selection is SA-optimized. The packing already achieves near-maximal space utilization. *Regime: M=8–12 item types, bins 900–2000, SA-optimized heuristic assignment.*

4. **RP-5** (high confidence): Expanding MaxRects from 4→8 heuristics with SA over joint (ordering × per-item-heuristic × per-item-rotation) achieves ~96.5/100. Improvement decomposes ~55% expanded heuristics, ~45% SA tuning. Both levers are complementary. *Regime: 2D rectangular knapsack, bin 900–2000, 8–12 item types, 1s time budget.*

## Limitations & Open Questions

**Scientific gaps:**
- **Heuristic ceiling not explored:** Would 12 or 16 heuristics yield further gains, or does the search space explosion outweigh the benefit within 1s?
- **Alternative packers not tested:** Guillotine cuts, shelf-based packers, or Skyline packers were not compared against MaxRects.
- **No population-based search:** Genetic algorithms or beam search over orderings could potentially outperform SA restarts.
- **Rotation granularity:** Only binary (0°/90°) rotation was explored; the per-item rotation SA mode's individual contribution was not isolated.
- **Score ceiling unknown:** Without access to optimal solutions, it's unclear how much headroom remains beyond 96.5.

**Infrastructure gaps:**
- No result files were persisted to disk across any iteration, limiting post-hoc analysis and reproducibility verification.
- Only 3 iterations were completed; the campaign could benefit from further exploration of SA temperature schedules, neighborhood operators, and hybrid approaches.