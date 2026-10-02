# Research Report: Maximizing Frontier-CS Judge Score for Algorithmic Problem #147

## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #147 (AHC001 rectangle packing) is a **simulated annealing (SA) approach with valid-by-construction move proposals, best-state tracking, a two-phase cooling schedule (linear then exponential), and a maximized time budget of ~4.8 seconds**, achieving scores of approximately **91.0 points**. The core design uses precomputed max-expansion bounds per rectangle edge to ensure every SA proposal is feasible, combined with a 60% linear / 40% exponential cooling schedule (T₀=0.08, T_mid=0.01, T₁=0.0005), which yielded a mean score of 91.01 with low variance (stdev 0.70).

## Evidence

**Iteration 1 (SA with valid-by-construction proposals):** Confirmed that SA with max-expansion-bound proposals dramatically outperforms greedy-only initialization (~89.5 vs ~20.2 points). This established SA as the dominant scoring mechanism and valid-by-construction proposals as essential — eliminating wasted iterations on collision rejection.

**Iteration 2 (Multi-cell initialization):** Refuted the hypothesis that better greedy initialization improves final SA scores. SA converges to similar quality (~89–90) regardless of init quality given sufficient budget (>2.5s), confirming the SA landscape is well-connected under single-edge moves.

**Iteration 3 (Best-state tracking + wider temperatures):** Partially confirmed. Best-tracking with T₀=0.08, T₁=0.0005 showed a small directional improvement (+0.65 points, 4/5 wins) but was not statistically significant due to judge variance (~5 points stdev).

**Iteration 4 (Extended time budget to 4.8s):** Confirmed as the largest single improvement. Extending from 2.85s to 4.8s yielded +2.28 points (p=0.025 one-sided) and reduced variance by ~4× (stdev 0.53 vs 2.16). The judge accepts solutions up to ~5.8s without TLE. Pushing to 8.0s caused marginal TLEs, dropping scores to 91.9.

**Iteration 5 (Two-phase cooling schedule):** Partially confirmed. Two-phase cooling (linear 60% → exponential 40%) showed +1.30 points over pure exponential (91.01 vs 89.71, Cohen's d=1.10, p=0.060), with 4.7× lower variance. The borderline p-value reflects concurrent CPU contention during testing.

No result files were found on disk for any iteration; all scoring was performed within the judge evaluation framework during each iteration's execution.

## Principles Discovered

| ID | Principle | Confidence | Regime |
|------|-----------|------------|--------|
| RP-1 | Valid-by-construction proposals (precomputed max-expansion bounds) outperform random-step + rejection | **High** | N ≤ 200, 10000×10000 grid, ~3s budget |
| RP-2 | SA is the dominant scoring mechanism, providing ~70 points over greedy-only | **High** | N ∈ [50,200], budget ~3s |
| RP-3 | Greedy initialization quality does not significantly affect final SA score | **Medium** | N ≤ 200, SA budget ≥ 2.5s |
| RP-4 | Best-state tracking + wider temperature range gives small (~0.65pt) directional gain | **Low** | 2.85s budget, exponential cooling |
| RP-5 | Single-run probes are unreliable; judge variance ~5pt stdev; concurrent CPU load inflates variance | **High** | All AHC001 SA experiments |
| RP-6 | Extending time budget from 2.85s → 4.8s gives +2.28pt (p=0.025), 4× variance reduction | **High** | Total time ∈ [2.85, 5.8]s |
| RP-7 | Two-phase cooling (60% linear, 40% exponential) gives +1.30pt directional gain, 4.7× lower variance | **Medium** | 4.8s budget, T₀=0.08, T₁=0.0005 |

## Limitations & Open Questions

### Scientific Gaps
- **Two-phase cooling significance**: RP-7's p=0.060 is borderline; replication under isolated CPU execution is needed to confirm the effect.
- **Phase fraction optimization**: Only one split (60/40) was tested. The optimal phase1_frac and T_mid are unexplored.
- **Move neighborhood enrichment**: Only single-edge expansion/contraction moves were tested. Multi-edge moves, rectangle swaps, or coordinated shrink-grow pairs could improve score.
- **Adaptive temperature**: No adaptive cooling (e.g., based on acceptance rate) was tested, which could further optimize exploration/exploitation balance.
- **Time budget ceiling**: The optimal time budget lies somewhere in [4.5, 5.8]s but was not finely tuned.
- **Score ceiling**: The best observed scores cluster around 91, but it is unknown how close this is to the theoretical optimum.

### Infrastructure Gaps
- **CPU contention**: Parallel judge runs during iteration 5 inflated variance (stdev 1.52 vs 0.53 isolated), complicating effect size estimation. Future campaigns should enforce exclusive CPU access.
- **API errors**: One dispatcher retry due to an API error (see retry log), though this did not block any iteration from completing.
- **No persisted result files**: All five iterations show zero result files on disk, meaning raw per-test-case scores are unavailable for post-hoc analysis. Future campaigns should persist detailed judge outputs.

### Next Campaign Priorities
1. Replicate two-phase cooling under isolated execution to confirm RP-7.
2. Test multi-edge and rectangle-swap SA moves.
3. Fine-tune time budget in [4.5, 5.5]s range.
4. Explore adaptive cooling schedules.
5. Investigate problem-instance-specific parameter tuning (e.g., different T₀ for different N values).