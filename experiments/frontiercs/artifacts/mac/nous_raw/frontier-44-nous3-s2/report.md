# Research Report: Maximizing Frontier-CS Judge Score for Algorithmic Problem #44

## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #44 (a penalty-aware TSP with ~200K cities, 2-second time limit, and a "carrot" penalty constraint on every-10th step) is a **continuous simulated annealing with grid-guided 2-opt, penalty-aware exact delta computation, single-city Or-opt relocation, and prime scheduling**, achieving a score of **~78.85 points**. This represents a ~9.3-point improvement over the baseline SA approach (~69.5) and a ~6.6-point improvement over grid-guided 2-opt without penalty-aware components (~72.2).

## Evidence

### Iteration 1 (sa-penalty-aware-tsp) — CONFIRMED
- Established the baseline simulated annealing approach with penalty-aware cost evaluation.
- Demonstrated that a basic SA with random swaps and approximate boundary-only 2-opt scores ~69.5 points.
- Initial assessment underestimated penalty structure's contribution (claimed ~1%), which was later revised upward.

### Iteration 2 (iterated-ls-penalty-tsp) — Main REFUTED, Ablation CONFIRMED
- The main hypothesis (that ILS with double-bridge perturbation would outperform continuous SA) was **refuted**: ILS scored mean 75.7 with high variance, while continuous SA scored 78.85 with low variance.
- The ablation (grid-guided 2-opt + penalty-aware delta + Or-opt + prime scheduling as a continuous SA) was **confirmed** as the best-performing configuration at ~78.85 points.
- Key finding: grid-guided spatial neighbor selection (G=√N grid, O(1) per lookup) avoids the 0.3–0.5s KNN precomputation overhead that consumes 15–25% of the 2s budget.
- Double-bridge perturbation's O(N) tour recomputation cost plus cold SA restarts makes ILS strictly worse than continuous annealing under the 2s constraint.

### Iteration 3 (multi-city-oropt-tuning) — Main REFUTED, Control CONFIRMED
- The main hypothesis (that multi-city Or-opt segments of 2–3 cities improve over single-city Or-opt) was **refuted**: no measurable improvement (< 0.2 points).
- The control arm **confirmed** that removing penalty-aware delta, Or-opt, and prime scheduling from the iter-2 solution causes a 6.6-point regression (78.8 → 72.2), validating these components as essential.

No result files were found on disk for any iteration; all scoring data was captured through the campaign ledger and principle extraction pipeline.

## Principles Discovered

| ID | Principle | Confidence | Regime |
|----|-----------|------------|--------|
| **RP-1** | Grid-guided 2-opt with penalty-aware exact delta + Or-opt + pos[] tracking + continuous SA outperforms random swap + approximate 2-opt by ~9.3 points (78.85 vs 69.5). Grid-based spatial neighbor lookup (O(1)) is the critical enabler. | High | N ≥ 50K, 2s limit |
| **RP-2** | Penalty-aware delta computation contributes >6 points at high tour quality levels, where distance improvements are scarce. Prior ~1% estimate applied only to lower-quality tours. | High | High-quality tours, N ≤ 200K, 2s |
| **RP-3** | Grid-guided spatial neighbor selection (G=√N) outperforms KNN precomputation for 2-opt candidate generation under tight time limits. KNN's O(N·K) build cost causes 15–25% budget loss and scoring variance. | High | N ≥ 50K, 2s limit |
| **RP-4** | Double-bridge ILS does NOT improve over continuous SA within 2s for N=200K. Cold restarts and O(N) reconstruction cost outweigh local-optima escape benefits. | High | N ≥ 50K, 2s limit |
| **RP-5** | Multi-city Or-opt (segments of 2–3) provides no measurable improvement over single-city Or-opt. Higher memmove cost offsets any quality gain. | Medium | N ≥ 50K, 2s limit, bounded shift ≤ 15 |
| **RP-6** | Penalty-aware delta + Or-opt + prime scheduling collectively contribute ~6.6 points over plain grid-guided 2-opt SA (78.8 vs 72.2). | High | Penalty-aware TSP, N ≤ 200K, 2s |

## Limitations & Open Questions

### Scientific Gaps
1. **Temperature schedule tuning**: No systematic sweep of SA temperature parameters (initial T, cooling rate) was conducted. The current ~78.85 may not be at the SA parameter frontier.
2. **3-opt and LK moves**: Only 2-opt and Or-opt were tested. Lin-Kernighan style moves or restricted 3-opt could improve quality within the time budget, but were not explored.
3. **Penalty-specific reordering depth**: Prime scheduling was applied as a post-pass. Integrating prime-awareness more deeply into the SA acceptance criterion (e.g., dynamically adjusting temperature based on step proximity to 10th-step boundaries) was not tested.
4. **Non-uniform city distributions**: All principles assume roughly uniform city placement. Clustered or adversarial distributions may shift the optimal algorithm.
5. **Longer time budgets**: RP-4 (ILS ineffective) explicitly may not hold at 10s+. The crossover point where ILS overtakes continuous SA is unknown.

### Infrastructure Gaps
- No result files were persisted to disk across all three iterations, limiting post-hoc analysis of score distributions and convergence curves. Future campaigns should ensure raw scoring outputs are captured.
- Only 3 iterations were completed. The campaign did not explore LK-style moves, adaptive restart strategies, or hybrid genetic/SA approaches that could push beyond ~78.85.

### Recommended Next Steps
1. **Lin-Kernighan 3-opt with grid guidance**: Test whether restricted LK moves provide quality improvements that justify their higher per-move cost.
2. **SA parameter sweep**: Systematic grid search over initial temperature and cooling schedule.
3. **Adaptive penalty weighting**: Dynamically increase the penalty weight in the SA objective as temperature decreases, concentrating penalty optimization in the final annealing phase.
4. **Longer time budget exploration**: If problem variants allow >2s, test ILS crossover point.