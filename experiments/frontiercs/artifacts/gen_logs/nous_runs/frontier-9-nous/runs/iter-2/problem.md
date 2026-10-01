# Problem Framing — Iteration 2

## Research Question

What algorithm maximizes the Frontier-CS judge score for problem #9 — sorting a permutation on a tree using minimum matching-swap operations?

Iteration 1 established the tree DP + alternating depth-parity anti-oscillation algorithm, achieving 100/100 with cache-efficient implementation. Iteration 2 tests whether replacing all-pairs BFS (O(n²)) with DFS-timestamp subtree-membership queries (O(n)) provides a strictly superior approach: same correctness, fewer resources, more robust timing.

Key source files:
- `solution.cpp` — the active solution file in the worktree
- `solution_v2.cpp` — iter-1 BFS-based reference (score 99.37 with vectors, 100 with arrays+short)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/chk.cc` — checker: `s_i = max(0, (base_value-m)/(base_value-best_value))`, capped at 1.0. base_value=10n, best_value=3n per subtask.

## System Interface

- **Build command:** `g++ -O2 -o solution solution.cpp` (or with `#pragma GCC optimize("O3,unroll-loops")` embedded)
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100.
- **Code evidence:**
  - Checker scoring formula: `chk.cc:46` — `score_unbounded=max(0.0,1.0*(base_value-m)/(base_value-best_value))`
  - Per-test score cap: `chk.cc:56` — `sum+=min(1.0,sub_score)`
  - Edge coloring in v2: `solution_v2.cpp:43` — `edge_color[idx] = depth_node[v] % 2`
  - Edge weight computation: `solution_v2.cpp:99-111` — type-2=2, type-1=1 (if color matches), else 0
  - Tree DP matching: `solution_v2.cpp:50-61` — dp0/dp1 with backtracking via best_ch

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp
```

## Baseline Validation

The iter-1 optimized BFS solution (with pragma + array adjacency + short D[][] + iterative DP) scores **100** consistently (5/5 runs). The DFS timestamps version (h-main candidate) also scores **100** consistently (5/5 runs). The v2 reference (vector + recursive DP) scores **99.37**.

Round counts are identical between BFS and DFS versions on all 20 test cases:
- Test 1: 0 rounds (identity permutation)
- Tests 2-6: 1.0-1.5n rounds (random trees, n≈303)
- Tests 7-8: 0.02-0.05n rounds (path graphs, n≈493)
- Tests 9-19: 0.2-1.5n rounds (various trees, n≈494)
- Test 20: 2.0n rounds (bushy tree, n≈492, max_degree≈124)

All under the 3n threshold for full score.

## Experimental Conditions

### h-main: DFS timestamps approach
Replace all-pairs BFS distance precomputation with DFS timestamps for O(1) subtree membership queries. The routing check `D[v][a] == D[u][a] - 1` (which asks "is v one step closer to a's target?") is mathematically equivalent to `is_in_subtree(v, a)` for rooted trees. This eliminates:
- O(n²) BFS precomputation
- The entire D[MAXN][MAXN] distance matrix (~2-4MB memory)

All other components remain: array adjacency, iterative tree DP, depth-parity coloring, output buffering.

**Implementation:** Write solution.cpp with the DFS timestamps algorithm. The complete solution uses compute_dfs_timestamps() (O(n)) instead of all-pairs bfs() (O(n²)), and replaces distance comparisons with is_in_subtree() calls using tin[]/tout[] arrays.

### h-ablation: DFS timestamps with vector adjacency
Same DFS timestamps algorithm, but using `std::vector<pair<int,int>>` for adjacency lists instead of array-based adjacency. This tests whether the DFS improvement (eliminating D[][] cache pressure) compensates for the vector overhead in per-round DP iteration.

**Implementation:** Write solution.cpp with vector-based adjacency but same DFS timestamps routing.

## Success Criteria

- **h-main CONFIRMED if:** Score ≥ 100 (matching or exceeding iter-1 baseline)
- **h-ablation isolates array importance if:** Score ≤ 99.4 (vector overhead persists despite DFS improvement)

## Constraints

- 1-second time limit per test case
- 1024MB memory limit
- n ≤ 1000, sum of n² ≤ 10^6
- Must produce valid matchings and sort the permutation

## Prior Knowledge

### Active Principles
- **RP-1:** Anti-oscillation gating is essential (score 5 without, 100 with). The depth-parity coloring scheme is optimal for 2-coloring trees.
- **RP-2:** Tree DP max-weight matching with next-step routing and weight scheme (type-2=2, type-1=1) achieves optimal sorting.
- **RP-3:** Implementation efficiency is critical for scoring under tight time limits. Specific finding from iter-2 exploration: array-based adjacency lists are the single most impactful optimization (vector→array: 99.37→100), more than short D[][] or iterative DP.

### Iter-1 Dead Ends (do not revisit)
- Edge-index coloring: catastrophic failure on bushy trees (6.0n rounds = hit limit)
- Endgame relaxation (unrestricted type-1 when stuck): creates oscillation on bushy trees
- Centroid rooting (v6): score 90, worse than vertex-1 rooting
- Exclude-previous approach (v3): fails on bushy trees (period-3+ oscillation)
- Hybrid alternating+exclude (v4, v5): no improvement or broken
