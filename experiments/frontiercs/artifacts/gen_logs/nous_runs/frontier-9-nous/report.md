# Research Report: Maximizing Frontier-CS Judge Score for Algorithmic Problem #9

## Answer

The algorithm that maximizes the Frontier-CS judge score for problem #9 is a **tree matching sort** that combines four critical components: (1) **depth-parity edge coloring for anti-oscillation gating**, (2) **tree DP max-weight matching** with edge weights type-2=2, type-1=1, type-0=0, (3) **DFS-timestamp subtree membership queries** for O(n) routing decisions, and (4) **array-based (cache-friendly) data structures** with iterative DP. This combination achieves a **perfect score of 100/100** averaged across 20 diverse test cases, confirmed across 3 iterations with 100% prediction accuracy on all experimental arms.

## Evidence

### Iteration 1: Anti-oscillation gating and core algorithm validation
- **H-main (with depth-parity anti-oscillation):** Score **100** — confirmed that the full algorithm with tree DP matching and alternating-round type-1 swap gating converges within ~2n rounds on all tree types (random, path, bushy).
- **H-control-negative (without anti-oscillation):** Score **5** — confirmed that removing the depth-parity gating causes period-2 oscillation, catastrophically preventing convergence. This represents a **95-point degradation**, establishing anti-oscillation as the single most critical component.
- Prediction accuracy: 2/2 arms correct (100%).

### Iteration 2: DFS timestamps vs BFS distance matrix
- **H-main (DFS timestamps + array adjacency):** Score **100** on 3/3 runs, confirming DFS-timestamp subtree membership (tin/tout check) produces identical routing decisions to all-pairs BFS while reducing precomputation from O(n²) to O(n).
- **H-ablation (DFS timestamps + vector adjacency, no AVX2):** Score **96.03** (mean of 94.37, 94.37, 99.37) — confirmed that std::vector-based adjacency lists cause ~4-point degradation due to cache misses and incompatibility with `#pragma GCC target("avx2")` (GCC 13 compilation error with vector's allocator).
- Prediction accuracy: 2/2 arms correct (100%).
- **Bundle amendment:** AVX2 pragma removal was inherent to the vector approach, making the measured 4-point cost a genuine reflection of the array vs. vector trade-off.

### Iteration 3: Tree DP vs greedy matching
- **H-main (greedy matching replacing tree DP):** Score **99.37** — greedy matching uses 3.88n rounds on bushy trees (max_degree ~124) vs DP's 2.02n, exceeding the 3n scoring threshold on those specific test cases.
- **H-robustness (tree DP, re-confirmed):** Score **100** — confirmed the DP-based approach is robust across runs.
- Prediction accuracy: 2/2 arms correct (100%).

No result files were found on disk for any iteration; all scoring data was captured in the ledger's confirmation/rejection records and the principles extracted from experimental observations.

## Principles Discovered

| ID | Principle | Confidence | Regime |
|----|-----------|------------|--------|
| **RP-1** | Anti-oscillation via depth-parity edge coloring is essential — without it, type-1 swaps create period-2 oscillation reducing score from 100 to 5 | High | All tree structures, n ≤ 1000 |
| **RP-2** | Tree DP max-weight matching with next-step routing weights (2/1/0) achieves 100/100 with cache-efficient implementation | High | All trees n ≤ 1000, 6n round budget, 1s time limit |
| **RP-3-refined** | Array-based data structures provide ~4pts improvement over vector-based due to cache efficiency AND AVX2 compatibility (GCC 13) | High | Tight 1s time limits, n ≤ 1000, ~2000 rounds × n nodes |
| **RP-4** | DFS-timestamp subtree queries are a strict O(n²)→O(n) replacement for BFS distance routing with identical decisions | High | All tree structures |
| **RP-5** | Depth-parity is the optimal 2-coloring for anti-oscillation; edge-index coloring causes 3× round inflation on bushy trees | High | Trees with max_degree > ~50 |
| **RP-6** | Tree DP matching (not greedy) is necessary for bushy trees: greedy uses 3.88n vs DP's 2.02n rounds | High | Bushy trees, max_degree > ~50 |
| **RP-2-refined** | Component hierarchy by degradation severity: anti-oscillation (−95pts) > array structures (−4pts) > DP matching (−0.63pts) | High | n ≤ 1000, scoring formula s=(10n−m)/(7n) |

## Limitations & Open Questions

### Scientific Gaps
1. **Optimality proof:** We demonstrated score 100 empirically but did not prove the algorithm achieves the theoretical minimum round count. A lower bound analysis (e.g., information-theoretic or adversarial) would establish whether the ~2n rounds observed is optimal.
2. **Scaling beyond n=1000:** All tests used n ≤ 1000 per the problem constraints. Behavior at larger scales (if problem parameters change) is untested.
3. **Alternative anti-oscillation mechanisms:** Only depth-parity and edge-index colorings were tested. Other approaches (e.g., history-based blocking, randomized gating) might offer comparable or better convergence but were not explored.
4. **Sensitivity to scoring formula:** The 3n threshold in the scoring formula s=(10n−m)/(7n) creates a specific regime where greedy's 3.88n is penalized but 2.02n is not. Different scoring formulas might change the relative importance of components.

### Infrastructure Gaps
- **2 API errors** were logged in the dispatcher retry/silence summary. These did not appear to corrupt any iteration's results (all iterations completed with confirmed outcomes), but they represent fragility in the pipeline.
- **No result files on disk** for any iteration — all data was captured only in the ledger. Future campaigns should ensure raw output files are persisted for deeper post-hoc analysis (e.g., per-test-case round counts, timing breakdowns).

### Next Campaign Priorities
1. Investigate whether a **3-color or adaptive gating scheme** could reduce round counts below 2n on bushy trees.
2. Test whether **weighted type-1 priorities** (e.g., preferring type-1 swaps where the displaced element is closer to its target) could improve convergence.
3. Explore **compiler optimization sensitivity** — test with `-O3`, PGO, and different GCC versions to understand how much of the 4-point array advantage is compiler-specific.