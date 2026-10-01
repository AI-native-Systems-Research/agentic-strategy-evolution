# Handoff — Frontier-CS #9: Tree Matching Sort (Iteration 2)

## Goal

Implement and measure two variants of the tree matching sort algorithm: (1) h-main: DFS timestamps replacing all-pairs BFS for routing decisions, with array-based adjacency; (2) h-ablation: same DFS approach but with vector adjacency lists. Write each into solution.cpp and measure with `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`.

## Key Discoveries

1. **DFS timestamps are mathematically equivalent to BFS distances for tree routing.** For edge (u,v) where v is u's child in a rooted tree, element a at u wants to cross to v iff a's target is in v's subtree. This replaces `D[v][a] == D[u][a] - 1` with `tin[v] <= tin[a] <= tout[v]`. Verified: round counts are identical on all 20 test cases.

2. **The DFS approach eliminates O(n²) precomputation and ~2MB memory.** All-pairs BFS computes D[1005][1005] (short) = 2MB, requiring O(n²) = 10⁶ operations for n=1000. DFS timestamps use tin[1005]+tout[1005] = 8KB, requiring O(n) = 10³ operations. This is the main speedup.

3. **Array-based adjacency is the critical per-round optimization.** Tested 5 variants:
   - Array adj + DFS: 100 (5/5 with pragma, 4/5 without)
   - Array adj + BFS + short D: 100 (5/5 with pragma, 2/3 without)
   - Vector adj + DFS: 99.37 (5/5, consistently below 100)
   - Vector adj + BFS + short D: 99.37 (consistent)
   - Array adj + BFS + int D: 95 (consistent)
   
   The vector→array transition matters because the per-round DP iterates over ch[u] for each node in each of ~2000 rounds.

4. **Pragma GCC optimize provides marginal but consistent improvement.** With pragma: 5/5 at 100. Without: 4/5 at 100 (one run at 95 due to system load variance).

5. **Depth-parity coloring is optimal for trees.** Edge-index coloring (idx%2) was catastrophic on bushy trees (6.0n rounds = hit limit). Endgame relaxation (allowing all type-1 when stuck) also failed. The depth-parity scheme is the correct 2-coloring for anti-oscillation.

6. **All test cases are well within the 3n round budget.** Max observed: 2.02n on test 20 (bushy tree, max_degree≈124). Paths use only 0.04n. Random trees use 1.0-1.5n.

7. **The score formula: s_i = max(0, (10n-m)/(10n-3n)).** Score 1.0 requires m ≤ 3n operations per subtask. The algorithm consistently achieves this.

## System Interface

- **Build:** `g++ -O2 -o solution solution.cpp`
- **Run / Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100
- **Baseline result:** DFS+array+pragma version scores 100 (5/5 runs)

## Code Map

- `solution.cpp` — The active solution file. Currently contains the BFS-based optimized version from iter-1. Must be overwritten with the appropriate algorithm for each arm.

- `solution_v2.cpp` — Original BFS-based algorithm with vector adjacency. Score 99.37. Key routing check at line 102: `D[v][a] == D[u][a] - 1`.

- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/chk.cc` — Checker. Line 46: scoring formula. Line 56: per-test cap at 1.0. Line 23: reads base_value, best_value from .ans.

- `/home/ubuntu/frontier/gen_logs/fmeasure_9.sh` — Judge measurement script. Compiles, runs against all test cases, invokes checker, reports average score.

- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/testdata/` — 20 test files. Test 1: n=998, identity perm. Tests 2-6: random trees n≈303, T=3. Tests 7-8: paths n≈493, T=2. Tests 9-19: various trees n≈494, T=2. Test 20: bushy tree n≈492, max_deg≈124, T=2.

## Code Targets

### h-main: DFS timestamps + array adjacency
Write solution.cpp with the following algorithm:
- **Remove:** `bfs()` function, `D[MAXN][MAXN]` distance matrix
- **Add:** `tin[MAXN]`, `tout[MAXN]`, `dfs_timer`, `child_endpoint[MAXN]` arrays
- **Add:** `compute_dfs_timestamps(root)` — iterative DFS using a stack, computes tin/tout
- **Add:** `is_in_subtree(v, target)` — returns `tin[v] <= tin[target] && tin[target] <= tout[v]`
- **Modify routing check:** In the main loop, for each edge idx:
  - `v = child_endpoint[idx]` (the child in the rooted tree)
  - `u = (eu[idx] == v) ? ev[idx] : eu[idx]` (the parent)
  - `aw = (a != u) && is_in_subtree(v, a)` (a wants u→v)
  - `bw = (b != v) && !is_in_subtree(v, b)` (b wants v→u)
- **Keep:** Array adjacency (head_arr, nxt_arr, to_arr, eidx_arr), iterative DP, depth-parity coloring, output buffering, pragma GCC optimize

The complete working solution was validated during exploration and is available as a reference in the design probe at `/tmp/solution_dfs.cpp`.

### h-ablation: DFS timestamps + vector adjacency
Write solution.cpp with the same DFS timestamps algorithm but:
- **Replace:** Array adjacency with `vector<pair<int,int>> adj[MAXN]`
- **Replace:** `ch_arr[MAXN][MAXN]` / `nch[MAXN]` with `vector<int> ch[MAXN]`
- **Keep:** DFS timestamps, iterative DP, depth-parity coloring, output buffering, pragma GCC optimize

## What I Tried That Didn't Work

1. **Edge-index coloring (edge_color[idx] = idx%2):** Test 20 (bushy tree) hit 6.0n round limit and failed. All sibling edges at root get randomized colors but this doesn't match the tree's bipartite structure. Depth-parity is the correct 2-coloring.

2. **Endgame relaxation (allow all type-1 when no-progress streak ≥ 4):** Test 20 hit 6.0n limit. Unrestricted type-1 swaps create oscillation even with few displaced elements.

3. **int D[][] instead of short D[][] (with array adjacency):** Score drops to 95 consistently. The 4MB int matrix vs 2MB short matrix causes enough cache pressure to TLE. Moot for DFS version since D[][] is eliminated entirely.

4. **Vector adjacency with DFS timestamps:** Score 99.37 consistently. Vector overhead in per-round DP loop is the bottleneck, not precomputation.

## What I Excluded and Why

- **Multi-hop routing / lookahead:** Could consider 2-step-ahead benefit of each matching. Excluded because round counts are already well under 3n, and the computational cost of lookahead would increase per-round time.

- **Weighted type-2 by distance:** Could weight type-2 swaps by D[u][a]+D[v][b] to prioritize far-displaced elements. Excluded because it could reduce matching SIZE (fewer but higher-weight swaps), counterproductive.

- **3-color schemes:** Using 3 colors instead of 2 for anti-oscillation. Excluded because depth-parity 2-coloring is already optimal for bipartite tree structure and all tests score 100.

- **Different root selection per tree type:** Could detect bushy vs path and choose root accordingly. Excluded because vertex 1 rooting with depth-parity already works on all structures (max 2.02n rounds).

## Evolution of Thinking

1. **Started by exploring algorithmic improvements to beat iter-1's 99.37.** Discovered that iter-1's executor had already achieved 100 with cache-efficient implementation.

2. **Hypothesized edge-index coloring would help bushy trees.** Testing revealed it's catastrophically worse — depth-parity is optimal because it respects the tree's bipartite structure.

3. **Explored endgame relaxation.** Failed because oscillation can occur even with few displaced elements on bushy trees.

4. **Isolated which implementation optimizations matter.** Found array adjacency is the single most important factor (vector→array: 99.37→100). Short D[][] is second. Iterative DP is third.

5. **Discovered the DFS timestamps approach.** Realized that tree distance comparisons reduce to subtree membership on rooted trees. This is the cleanest improvement: same correctness, O(n) instead of O(n²), no D[][] needed.

6. **Verified mathematical equivalence.** Round counts identical on all 20 tests between BFS and DFS versions.

## Current Status

- **Validated:** DFS timestamps + array adjacency + pragma = 100 (5/5 runs). DFS + vector = 99.37 (5/5). BFS + array + short + pragma = 100 (5/5). All round counts identical between DFS and BFS.
- **Uncertain:** Whether the DFS improvement would matter on larger test cases (n > 1000). The O(n²) → O(n) precomputation saving grows with n.
- **Suggested next:** If iter-3 is needed, explore: (a) whether simpler code (without array adjacency, without pragma) can achieve 100 by further algorithmic improvements; (b) whether the algorithm generalizes to other graph structures (not trees); (c) whether cycle decomposition approaches can achieve better round counts than 2n on bushy trees.

## Warnings & Constraints

1. **solution.cpp must be overwritten completely for each arm.** The worktree's solution.cpp currently contains the BFS-based optimized version. Each arm needs a complete rewrite.

2. **Judge scoring has system-load variance of ~5 points.** The same code can score 95 or 100 across runs. Use the pragma version for maximum consistency.

3. **The vector adjacency version compiles with a warning about `always_inline` when pragma target("avx2") is present.** This doesn't prevent compilation but the pragma may not fully apply. The score (99.37) is consistent regardless.

4. **ch_arr[MAXN][MAXN] uses ~4MB stack/global memory.** This is within the 1024MB limit but large. The DFS version still needs this for array-based children storage.

5. **Between arms, `git checkout -- solution.cpp` to reset.** Or simply overwrite solution.cpp entirely.
