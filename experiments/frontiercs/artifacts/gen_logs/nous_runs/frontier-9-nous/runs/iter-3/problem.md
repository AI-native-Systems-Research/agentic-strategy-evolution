# Problem Framing — Iteration 3

## Research Question

Is tree DP max-weight matching the necessary matching strategy for achieving score 100, or can a simpler greedy matching suffice?

Iterations 1-2 established the full algorithm: tree DP max-weight matching + DFS timestamps + array adjacency + depth-parity anti-oscillation + pragma optimizations = consistent score 100. This iteration ablates the tree DP matching component specifically, replacing it with a two-pass greedy matching (type-2 first, then type-1), to determine whether the DP's optimal weight resolution is the critical differentiator.

Key source files:
- `solution.cpp` — current DFS+DP+array solution (score 100, iter-2 validated)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/chk.cc:46` — scoring: `s_i = max(0, (base_value-m)/(base_value-best_value))`, capped at 1.0. base_value=10n, best_value=3n.
- `chk.cc:56` — per-test cap: `sum += min(1.0, sub_score)`

## System Interface

- **Build command:** `g++ -O2 -o solution solution.cpp`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100.
- **Code evidence:**
  - Tree DP matching in current solution: `solution.cpp:104-127` — `compute_dp_iterative()`, bottom-up DP on BFS order computing dp0/dp1/best_ch per node.
  - DP extraction: `solution.cpp:133-158` — `extract_iterative()`, traces back DP decisions to build matching.
  - Edge weight computation: `solution.cpp:202-219` — type-2=2, type-1=1 (on correct color), type-0=0.
  - DFS timestamps: `solution.cpp:77-95` — `compute_dfs_timestamps()`, O(n) precomputation.
  - Subtree membership: `solution.cpp:99-101` — `is_in_subtree()`, O(1) routing check.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp
```

## Baseline Validation

The DFS+DP+array solution scores **100** consistently (verified 1/1 in iter-3 exploration, plus 3/3 in iter-2 execution and 5/5 in iter-2 exploration). Round counts on all 20 test files:
- Test 1: 0 rounds (identity permutation, n=998)
- Tests 2-6: 1.01-1.48n rounds (random trees, n≈303, T=3)
- Tests 7-8: 0.02-0.05n rounds (path graphs, n≈493, T=2)
- Tests 9-19: 0.20-1.50n rounds (various trees, n≈494, T=2)
- Test 20: 2.02n rounds (bushy tree, n≈492, max_degree≈124, T=2)

All 44 sub-tests well under the 3n threshold for full score (1.0).

Greedy matching probe (iter-3 exploration) scores **99.37** consistently (3/3 runs). Key round count comparison on critical test cases:
- Test 20 (bushy): Greedy 3.88n vs DP 2.02n (greedy EXCEEDS 3n threshold)
- Test 19: Greedy 1.95n vs DP 1.42n (both within 3n)
- Tests 7-8 (paths): Identical round counts (0.04n)
- Tests 2-5 (random): Greedy sometimes LOWER than DP (0.89n vs 1.14n)

## Experimental Conditions

### h-main: Greedy matching replaces tree DP
Replace `compute_dp_iterative()` and `extract_iterative()` with a two-pass greedy matching function: first pass scans edges 1 to n-1 and includes type-2 edges where both endpoints are unmatched; second pass includes type-1 edges similarly. This is the standard greedy weighted matching — O(n) per round with smaller constant factor than DP.

All other components unchanged: DFS timestamps, array adjacency, depth-parity anti-oscillation, pragma optimizations, output buffering.

**Implementation:** Replace the DP and extraction functions with `greedy_matching()`. Add `used_node[MAXN]` boolean array. Remove `dp0`, `dp1`, `best_ch` arrays.

### h-robustness: Verified DFS+DP+array solution
Run the proven solution unchanged (no code changes). Verify consistent score of 100 in the iter-3 judging environment. This provides the comparison point for h-main.

## Success Criteria

- **h-main CONFIRMED if:** Score consistently < 100 (specifically ~99.4), demonstrating DP is necessary.
- **h-main REFUTED if:** Score reaches 100, meaning greedy suffices and DP adds no value.
- **h-robustness CONFIRMED if:** Score = 100 consistently, verifying the baseline.

## Constraints

- 1-second time limit per test case
- 1024MB memory limit
- n ≤ 1000, sum of n² ≤ 10^6
- Must produce valid matchings that sort the permutation

## Prior Knowledge

### Active Principles (all confirmed in iter-1 and iter-2)
- **RP-1:** Anti-oscillation gating is essential (depth-parity coloring, alternating type-1 by round)
- **RP-2:** Tree DP max-weight matching with weights (type-2=2, type-1=1) achieves optimal sorting
- **RP-3:** Implementation efficiency (array adjacency, iterative DP) is critical for timing
- **RP-3-refined:** Array-based data structures enable both cache efficiency and AVX2 vectorization
- **RP-4:** DFS timestamps replace BFS distances with identical routing, O(n) vs O(n²)
- **RP-5:** Depth-parity coloring is optimal 2-coloring for anti-oscillation on trees

### Iter-1 & Iter-2 Dead Ends (do not revisit)
- Edge-index coloring: catastrophic on bushy trees (6.0n rounds)
- Endgame relaxation: oscillation on bushy trees
- Centroid rooting (v6): score 90, worse than vertex-1
- Vector adjacency: consistent 96-99.37 (iter-2 h-ablation confirmed)
- int D[][] instead of short D[][]: score 95 (cache pressure)
