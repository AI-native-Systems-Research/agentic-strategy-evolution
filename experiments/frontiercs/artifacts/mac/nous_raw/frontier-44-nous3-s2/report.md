## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #44 is a **grid-guided simulated annealing with 2-opt and single-city Or-opt**, achieving approximately **78.8 points**. The key components are: (1) greedy nearest-neighbor construction using a spatial grid, (2) SA-based optimization using grid-guided spatial neighbor selection for 2-opt moves with penalty-aware exact delta evaluation, (3) single-city Or-opt (relocate) moves, and (4) a position-tracking array for O(1) lookups. Attempts to improve beyond ~78.8 via iterated local search with double-bridge perturbation or multi-city Or-opt segments were unsuccessful within the 2-second time constraint.

## Evidence

**Iteration 1 (SA penalty-aware TSP — CONFIRMED):** Established the core algorithm scoring ~78.8 points. Grid-guided 2-opt with penalty-aware fast delta + Or-opt + position tracking outperformed a random-swap baseline scoring ~69.5 by approximately 9 points. This confirmed that spatially-guided move selection and exact penalty delta computation are critical.

**Iteration 2 (Iterated LS with double-bridge — REFUTED):** Attempted to add double-bridge perturbation (non-sequential 4-opt) as an iterated local search wrapper. The hypothesis was refuted: the O(N) tour recomputation overhead after each perturbation (~5ms at N=200K), combined with shortened SA phases, yielded fewer productive iterations than continuous SA. However, the ablation confirmed that grid-guided spatial neighbor selection outperforms both precomputed KNN lists (which consume 15–25% of the 2s budget at N=200K) and random selection.

**Iteration 3 (Multi-city Or-opt tuning — REFUTED):** Tested whether multi-city Or-opt (segments of 1–3 cities) with grid-guided insertion could improve beyond single-city Or-opt. The main hypothesis was refuted with an effect below 0.2 points. The control confirmed the baseline remained stable at ~78.8.

No result files were present on disk for any iteration (0 files across all three iterations), so all metrics are drawn from the ledger's hypothesis outcomes and the principles extracted during analysis.

## Principles Discovered

| ID | Principle | Confidence | Regime |
|----|-----------|------------|--------|
| **RP-1** | Grid-guided 2-opt with penalty-aware fast delta + Or-opt + position tracking outperforms random swap + approximate boundary-only 2-opt by ~9 points (78.8 vs 69.5). Three synergistic mechanisms: spatial neighbor guidance, exact O(1 + segment/10) penalty delta, and O(1) position lookup. | High | TSP, N≤200K, 2s limit, penalty at every 10th position |
| **RP-2** | The penalty structure (10% surcharge on every 10th step for non-prime cities) contributes at most ~1% to total tour cost. Prime scheduling captures most savings but adds <1 point. | High | N≤200K, ~18K primes, ~N/10 penalty positions |
| **RP-3** | Grid-guided spatial neighbor selection for 2-opt outperforms both precomputed KNN lists (too expensive to build) and random selection, because it provides spatial guidance without startup cost. | High | N=200K, 2s limit |
| **RP-4** | Double-bridge perturbation does NOT improve score within 2s at N=200K due to O(N) recomputation overhead and truncated SA phases. | High | N=200K, 2s, SA-based optimization |
| **RP-5** | Multi-city Or-opt (segments 1–3) does not measurably improve beyond single-city Or-opt at this tour quality level (effect <0.2 points). | Medium | N=200K, 2s, baseline ~78.8 |

## Limitations & Open Questions

### Scientific Gaps
1. **Alternative move operators not explored:** Lin-Kernighan style 3-opt moves, or restricted 3-opt (e.g., only non-sequential moves), were never tested. These could potentially break through the 78.8 plateau.
2. **Adaptive temperature schedules:** Only a single SA cooling schedule was tested. Reheating strategies or non-monotonic schedules may yield improvements.
3. **Penalty-aware construction heuristics:** The greedy NN construction does not account for penalties. A construction phase that pre-assigns primes to every 10th position might start SA from a better initial tour.
4. **Population-based methods:** Genetic algorithms or evolutionary strategies with edge-assembly crossover were not tested.
5. **Score ceiling unknown:** Without knowing the optimal tour cost, it's unclear how much headroom remains above 78.8.

### Infrastructure Gaps
- No result files were written to disk across all three iterations, limiting post-hoc analysis of score distributions, convergence curves, and per-instance breakdowns.
- Only 3 iterations were completed, constraining the hypothesis space explored. A next campaign should investigate LK-style moves, adaptive SA schedules, and penalty-aware construction as the highest-priority axes.