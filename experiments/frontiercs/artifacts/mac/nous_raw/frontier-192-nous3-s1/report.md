# Research Report: Maximizing Frontier-CS Judge Score for Problem #192 (Max-Cut)

## Answer

A **linear-cooling simulated annealing (SA) algorithm with greedy initialization and multiple restarts** achieves the highest reliable score of **~87.5** on problem #192 (Max-Cut, n≤1000, m≤20000). The optimal configuration uses T₀=3.0, linear temperature decay proportional to remaining time, 0.10s SA budget per restart, within a 0.90s total time limit. Multiple algorithmic variants (geometric cooling, incremental gain tracking, varying restart depths) all converge to this same ~87.5 ceiling, suggesting this score represents a near-optimal bound for single-flip SA-based approaches on this problem's test instances.

## Evidence

### Iteration 1 — FM Local Search with Greedy Restarts
- **Score: ~87.0** (confirmed on judge), establishing the baseline for intelligent approaches.
- A trivial constant assignment scored ~50, confirming a ~37-point gap from local search.
- FM partitioning passes (flipping vertices in gain-ordered sequence, selecting best prefix) combined with random restarts achieved this result.
- RNG-seed variance was observed at ~5 points (81.5–87.0), indicating sensitivity to restart count within the time budget.

### Iteration 2 — Linear Cooling SA
- **Score: ~87.5** (confirmed on judge), a ~0.5-point improvement over iteration 1.
- Linear cooling (T = T₀ × (1 − t/budget)) outperformed geometric cooling (T × 0.9995) by ~1 point (87.5 vs 86.6).
- Key insight: geometric cooling exhausts productive exploration in ~0.5ms, wasting the remaining restart time, while linear cooling distributes exploration across the full 0.10s SA phase (~1.7M iterations).
- Seed variance dropped from ~5 points to ~0.05 points (std 0.03), confirming algorithmic stability.
- Ablation confirmed linear > geometric cooling.

### Iteration 3 — Incremental Gain Deep SA
- **Score: ~87.5** (partially confirmed; ablation refuted the depth-vs-breadth hypothesis).
- Incremental gain tracking (O(1) neighbor evaluation via maintained gain arrays) sped up SA iterations ~5× but did not raise the score ceiling.
- Deep restarts (0.30s × 3) and shallow restarts (0.03s × 30) both achieved ~87.5–87.6, showing the score is insensitive to restart budget allocation.
- This strongly suggests the ~87.5 ceiling is a property of the problem landscape, not the algorithmic configuration.

No result files were found on disk for any iteration; all scores were obtained from judge submissions and recorded in the campaign ledger. No dispatcher retries or failures occurred.

## Principles Discovered

| ID | Principle | Confidence | Regime |
|----|-----------|------------|--------|
| **RP-1** | FM partitioning + greedy local search + random restarts achieves ~87 on Max-Cut (n≤1000, m≤20000) within 1s | High | Sparse Max-Cut, 1s budget |
| **RP-2** | RNG-seed variance in FM+restarts causes ~5-point score drops due to restart count sensitivity | Medium | Tight time limits with chrono-based seeds |
| **RP-3** | Linear cooling SA (T₀=3.0, 0.10s/restart) outperforms geometric cooling by ~1 point (87.5 vs 86.6) | High | Max-Cut, greedy+SA+restarts framework |
| **RP-2-update** | Linear cooling reduces seed variance from ~5 points to ~0.05 points vs geometric cooling | Medium | Max-Cut, 1s budget |
| **RP-4** | Restart depth vs breadth tradeoff has no effect at this problem scale (~87.5 either way) | Medium | Max-Cut n≤1000, m≤20000 |
| **RP-5** | The ~87.5 score ceiling is robust across all SA configurations tested; further SA tuning is unlikely to break through | High | Problem 192 specifically |

## Limitations & Open Questions

### Scientific Gaps
- **Score ceiling origin**: The ~87.5 ceiling was not explained — it could stem from the problem's scoring function (ratio-based), the graph structure of test cases, or fundamental approximation limits. SDP-based rounding (Goemans-Williamson) could test whether a 0.878-approximation guarantee yields higher scores.
- **Multi-flip neighborhoods**: Only single-vertex-flip neighborhoods were explored. Multi-flip (e.g., 2-opt or cluster moves) or variable-neighborhood search could potentially escape deeper local optima.
- **Problem-specific structure**: No analysis of the test case graph structure (e.g., planted partition, community structure) was conducted. Exploiting structure could yield gains.
- **Hybrid approaches**: Combining SDP relaxation for initialization with SA refinement was not tested and represents the most promising direction for breaking the ceiling.

### Infrastructure Gaps
- No result files were persisted to disk, making post-hoc analysis of per-test-case performance impossible. Future campaigns should ensure raw output capture.
- Only 3 iterations were conducted; the diminishing returns pattern suggests the SA design space is exhausted, but fundamentally different algorithm families (SDP, genetic algorithms, breakout local search) remain untested.