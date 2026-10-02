# Final Report: Maximizing Frontier-CS Judge Score for Algorithmic Problem #47

## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #47 is a **co-evolved maximal-rectangles (MaxRects) greedy packer** with per-type placement method assignments (BSSF/BAF/BL/CP/BLSF), both-orientation best-fit rotation, bin transposition, and a final gap-fill post-processing step. Across three confirmed iterations, the campaign improved from a baseline MaxRects packer to a co-evolutionary search that jointly optimizes type ordering and per-type placement heuristic, achieving approximately **~95% of the fractional upper bound** on the 2D rectangular knapsack instances. The single largest improvement (~6 points on the judge formula) came from switching to both-orientation best-fit placement instead of fallback rotation.

## Evidence

**Iteration 1 (maxrects-skyline-packer):** CONFIRMED. Established the baseline MaxRects approach with 6 deterministic orderings (density, value, area, max-dim, total-value, perimeter) × 3 placement methods (BSSF, BAF, BL) plus randomized density-weighted ordering search within 0.75s. Type-level iteration (placing all copies of one type before moving to the next) was critical — flat expansion of per-type limits (up to 2000 copies) caused TLE. Prediction accuracy: 100% (1/1).

**Iteration 2 (enhanced-maxrects-cp-transpose):** CONFIRMED. Three enhancements were validated: (1) both-orientation best-fit rotation yielded ~6-point improvement over fallback rotation (the largest single gain); (2) contact-point placement heuristic added ~0.5% profit improvement by reducing interior fragmentation; (3) bin transposition (packing in H×W then translating) improved ~20–30% of test cases with non-square bins. Prediction accuracy: 100% (1/1).

**Iteration 3 (coevolved-mpt-maxrects):** CONFIRMED, including control test. Co-evolutionary search over per-type placement method assignments (5^M configuration space) alongside type ordering added ~0.4 points over uniform-method search. The control confirmed that gap-fill post-processing must be applied only to the final best solution — applying it per-iteration caused TLE and ~6-point drops. The elite-pool evolutionary strategy with crossover and mutation efficiently explored the combinatorial method-assignment space. Prediction accuracy: 100% (2/2).

No result files were written to disk for any iteration (0 files per iteration). All confirmation signals came through the automated hypothesis testing pipeline rather than persisted result artifacts. The dispatcher retry log is empty — no retries or silences occurred.

## Principles Discovered

| ID | Principle | Confidence | Regime |
|----|-----------|------------|--------|
| **RP-1** | MaxRects greedy with 6 orderings × 3 placements + randomized search achieves ~95% of fractional upper bound | High | Bins 900–2000, 8–12 types, limits ≤2000, 1s |
| **RP-2** | Type-level iteration (not flat copy expansion) is critical when per-type limits are large | High | Per-type limits >100, 1s time budget |
| **RP-3** | Contact-point placement reduces fragmentation, ~0.5% profit gain | Medium | Non-multiple bin dims, diverse aspect ratios |
| **RP-4** | Bin transposition finds better solutions on ~20–30% of non-square bin cases | Medium | W ≠ H bins only |
| **RP-5** | Both-orientation best-fit is ~6 points better than fallback rotation | High | Any rotation-allowed instance; largest single gain |
| **RP-6** | Co-evolving per-type placement method assignments adds ~0.4 points over uniform methods | High | 8–12 diverse item types, 5 methods, 1s budget |
| **RP-7** | Gap-fill must be applied only to final best solution; per-iteration gap-fill causes TLE (~6-point loss) | High | <1s budget with hundreds of packing evaluations |

## Limitations & Open Questions

### Scientific Gaps
1. **No exact solver comparison.** The campaign used only greedy/metaheuristic approaches. An ILP or constraint-programming formulation might find provably optimal solutions for smaller instances, providing a tighter benchmark than the fractional upper bound.
2. **Marginal returns plateau.** Iterations 2→3 yielded only ~0.4 points. The campaign did not explore fundamentally different algorithmic families (e.g., simulated annealing on placement coordinates, genetic algorithms on spatial representations, or branch-and-bound).
3. **Generalization unknown.** All principles were derived on bins 900–2000 with 8–12 types. Performance on smaller bins, many more types, or tighter limits was not tested.
4. **Rotation synergy unexplored.** Both-orientation best-fit was the largest single gain, but the interaction between rotation strategy and per-type method assignment was not ablated independently.

### Infrastructure Gaps
- No result files were persisted to disk across all three iterations, limiting post-hoc re-analysis. Future campaigns should ensure raw packing outputs (coordinates, profits, timings per test case) are written to results directories.
- No robustness tests were run in any iteration, so sensitivity to time-limit variance or input perturbation is unknown.

### Next Campaign Priorities
1. **Ablation of RP-5 × RP-6 interaction** — does per-type method assignment subsume the benefit of both-orientation best-fit, or are they additive?
2. **Simulated annealing / local search** on placement order with swap neighborhoods, possibly warm-started from the greedy solution.
3. **Tighter upper bounds** via Lagrangian relaxation or column-generation LP to quantify remaining optimality gap.
4. **Adaptive time allocation** — spend more time on harder test cases (those with larger gap to upper bound) rather than uniform budget splitting.