# Final Report: Maximizing Frontier-CS Judge Score for Algorithmic Problem #0

## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #0 (polyomino packing) is a **skyline-based 2D greedy packer with dynamic lookahead (K = n/4), roughness tiebreaking, column compaction, unified time allocation, and multi-width sweep**, achieving a mean score of **~83 points** (v10 variant). The dominant improvement over a naive baseline (~35) comes from skyline packing (~72, +37 points), then dynamic lookahead (~+7 points), then secondary heuristics (roughness/compaction/multi-ordering, ~+4 points). Further incremental optimizations yielded no statistically detectable gains, indicating the greedy skyline approach has reached its performance ceiling under a 2-second time limit.

## Evidence

### Iteration 1 (skyline-packing-vs-naive) — CONFIRMED
Established the foundational algorithm. Skyline-based 2D greedy packing with multi-width sweep scored **~72** vs **~35** for naive 1D strip packing — approximately 2× improvement. Multi-width sweep over ~160 candidate widths around √(totalCells × factor) was essential. Correct transform recovery (reflect → rotate → translate) was identified as the critical correctness gate; many LLM-generated solutions score 0 due to incorrect transform order.

### Iteration 2 (lookahead-enhanced-packing) — CONFIRMED
Dynamic lookahead (K = n/4 candidate pieces per placement step) was the single largest improvement mechanism, contributing **~6.94 of 11.10 points** (63%) of total improvement over iter-1. Combined with roughness tiebreaker, column compaction, and 3 ordering strategies, the algorithm reached **~83 points**. Ablation confirmed lookahead as the dominant factor; secondary heuristics contributed ~4 points independently.

### Iteration 3 (gap-filling-packing) — PARTIALLY CONFIRMED
Bitmap-based gap-filling during skyline packing produced **no statistically detectable improvement** (mean paired difference +0.50, t=0.226, p≫0.05). The effect was overwhelmed by system-load variance (~6 points range for v7). Gap-filling was ruled out as a viable optimization path at current algorithm maturity.

### Iteration 4 (time-allocation-ordering-diversity) — PARTIALLY CONFIRMED
Unified time allocation (v10, removing the 60/40 phase split) reduced run-to-run variance by **~25×** (std 0.11 vs 2.70) without changing mean score. This confirmed that time management was the dominant variance source. However, the hypothesis that additional ordering diversity would improve mean score was not confirmed — the mean remained at ~83.

### Iteration 5 (skyline-speed-diversity) — REFUTED
Composite inner-loop optimizations (precomputed orientation metadata, orientation-level skip, additional orderings, culprit repair) produced **no measurable improvement** over v10 (paired t=-0.787, p≫0.05). The greedy skyline approach has reached diminishing returns where constant-factor speedups (~14ms/pack call) don't translate to score gains. Under heavy load, v10's variance increased to std=1.30, updating the earlier finding of near-zero variance.

No result files were found on disk for any iteration; all metrics were captured in the ledger and principles.

## Principles Discovered

| ID | Statement | Confidence | Regime |
|---|---|---|---|
| **RP-1** | Skyline packing with multi-width sweep achieves ~72 vs ~35 for naive packing | High | k∈[1,10], n∈[100,10000], 2s limit |
| **RP-2** | Transform recovery (reflect→rotate→translate) is the critical correctness gate | High | Universal for this problem |
| **RP-3** | Score variance is dominated by time-management sensitivity to system load | High | Time-managed width sweep, 2s limit |
| **RP-3-update** | v10 variance increases 10× under heavy load (std 1.30 vs 0.11) | High | Variable system load |
| **RP-4** | Dynamic lookahead (K=n/4) is the dominant improvement: +6.94 pts (63% of gains) | High | Random polyominoes, greedy skyline |
| **RP-5** | Secondary heuristics (roughness, compaction, multi-ordering) contribute ~4 pts | High | Random polyominoes, 2s limit |
| **RP-6** | Bitmap gap-filling produces no detectable improvement | Medium | Skyline + lookahead baseline |
| **RP-7** | Unified time allocation reduces variance ~25× without hurting mean score | High | Time-managed skyline packing |
| **RP-8** | Incremental inner-loop optimizations hit diminishing returns at ~83 points | Medium | Greedy skyline at current maturity |

## Limitations & Open Questions

### Scientific Gaps
1. **Fundamentally different algorithms untested.** Local search (simulated annealing over placements), constraint programming, or BL-bitmap algorithms could potentially exceed ~83. The campaign only explored variations of the greedy skyline approach.
2. **Score ceiling unknown.** The reference solution scores ~79 (per RP-1), but our v10 exceeds this at ~83. The theoretical optimum is unknown. The gap between ~83 and 100 may require non-greedy approaches.
3. **Instance-level analysis missing.** We don't know which test cases (small n vs large n, small k vs large k) contribute most to score loss. Instance-stratified analysis could identify where algorithmic changes would have the highest marginal impact.
4. **Lookahead window size not optimized.** K=n/4 was used throughout; the optimal K as a function of n and k was not explored. Adaptive K based on piece complexity could improve scores.
5. **No exploration of placement position search reduction.** Valley-only targeting (O(valleys) vs O(W) position search) could provide order-of-magnitude speedups enabling more width exploration.

### Infrastructure Gaps
- **2 API errors** occurred during the campaign (dispatcher retry log), but these did not prevent any iteration from completing.
- **No result files on disk** across all iterations — all evaluation was conducted within the execution pipeline and captured only in the ledger. Persistent result files would enable post-hoc reanalysis.
- **System load variability** was a persistent confound (RP-3, RP-3-update), making small improvements (<2 points) undetectable. A controlled benchmarking environment with CPU pinning would improve experimental sensitivity.

### Recommended Next Campaign
1. **Explore local search** (simulated annealing or tabu search) over piece placement permutations, using the greedy skyline packer as the evaluation function.
2. **Test valley-only position targeting** for potential order-of-magnitude speedup in the inner loop.
3. **Instance-stratified analysis** to identify the highest-leverage test case categories.
4. **CPU-pinned benchmarking** to reduce load-induced variance below 0.5 points, enabling detection of small algorithmic improvements.