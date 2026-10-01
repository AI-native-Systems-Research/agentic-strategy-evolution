# Handoff — Frontier-CS #9: Tree Matching Sort (Iteration 3)

## Goal

Measure two variants of the tree matching sort algorithm: (1) h-main: greedy matching replacing tree DP (same DFS+array framework), expected to score ~99.4; (2) h-robustness: the proven DFS+DP+array solution, expected to score 100. Write each into solution.cpp and measure with `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`. Run 3 measurements per arm.

## Key Discoveries

1. **DFS timestamps are mathematically equivalent to BFS distances for tree routing.** For edge (u,v) where v is u's child in a rooted tree, element a at u wants to cross to v iff a's target is in v's subtree. This replaces `D[v][a] == D[u][a] - 1` with `tin[v] <= tin[a] <= tout[v]`. Verified: round counts are identical on all 20 test cases.

2. **The DFS approach eliminates O(n²) precomputation and ~2MB memory.** All-pairs BFS computes D[1005][1005] (short) = 2MB. DFS timestamps use tin[1005]+tout[1005] = 8KB. This is the main speedup.

3. **Array-based adjacency is the critical per-round optimization.** Array adj + DFS/DP: 100 (consistent). Vector adj: 96-99.37 (consistently below 100). The vector→array transition matters because the per-round DP iterates over ch[u] for each node in each of ~2000 rounds.

4. **Tree DP is necessary for score 100 on bushy trees.** Greedy matching (two-pass: type-2 first, then type-1) uses 3.88n rounds on test 20 (bushy tree, n≈492, max_degree≈124) vs DP's 2.02n. Since score requires m ≤ 3n, greedy exceeds the threshold and scores ~99.37 (partial credit on test 20).

5. **Greedy is comparable or better on low-degree trees.** On random trees (tests 2-5, n≈303), greedy uses 0.89-1.35n rounds vs DP's 1.01-1.48n. On paths (tests 7-8), identical round counts (0.04n).

6. **Leaf-to-root greedy is catastrophically bad (score 20).** Matches at lower levels first, blocking optimal higher-level matches. Not usable.

7. **Depth-parity coloring is optimal for trees.** Edge-index coloring was catastrophic (6.0n rounds). Anti-oscillation via depth-parity is essential (RP-1, RP-5).

8. **The score formula: s_i = max(0, (10n-m)/(7n)).** Score 1.0 requires m ≤ 3n per subtask. All sub-tests well within 3n for DP (max 2.02n).

## System Interface

- **Build:** `g++ -O2 -o solution solution.cpp`
- **Run / Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100
- **Baseline result:** DFS+DP+array+pragma version scores 100 (iter-1 5/5, iter-2 3/3, iter-3 1/1)

## Code Map

- `solution.cpp` — Active solution. Currently DFS+DP+array version (iter-2 h-main). Score 100.

- `solution.cpp:104-127` — `compute_dp_iterative()`. Tree DP matching. h-main replaces this with greedy.

- `solution.cpp:133-158` — `extract_iterative()`. DP extraction. Also replaced by greedy in h-main.

- `solution.cpp:32-33` — `dp0[MAXN], dp1[MAXN], best_ch[MAXN]`. DP arrays. Remove in h-main.

- `solution.cpp:77-95` — `compute_dfs_timestamps()`. O(n) DFS precomputation. Keep in both arms.

- `solution.cpp:99-101` — `is_in_subtree()`. O(1) routing check. Keep in both arms.

- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/chk.cc:46` — Scoring formula.

- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/testdata/` — 20 test files. Test 20 is the critical differentiator (bushy tree).

## Code Targets

### h-main: Greedy matching (replace DP)
In solution.cpp:
- **Remove:** `compute_dp_iterative()` (lines 104-127), `extract_iterative()` (lines 133-158), `dp0[]`, `dp1[]`, `best_ch[]` arrays (lines 32-33)
- **Add:** `greedy_matching()` function with `used_node[MAXN]` boolean array
- **Modify main loop:** Replace `compute_dp_iterative(); extract_iterative(1);` with `greedy_matching();`
- **Keep everything else unchanged**

### h-robustness: Proven solution (no changes)
Run the existing solution.cpp as-is.

## What I Tried That Didn't Work

1. **Edge-index coloring (idx%2):** Catastrophic on bushy trees (6.0n rounds). Depth-parity is correct.
2. **Endgame relaxation:** Oscillation on bushy trees even with few displaced elements.
3. **int D[][] instead of short D[][]:** Score 95 from cache pressure. Moot with DFS.
4. **Vector adjacency with DFS:** Score 99.37. Vector overhead in per-round DP loop.
5. **Centroid rooting:** Score 90, worse than vertex-1.
6. **Leaf-to-root greedy matching:** Score 20. Blocks optimal higher-level matches.
7. **Arbitrary-order greedy (without DP):** Score 99.37. Fails on bushy trees (3.88n rounds > 3n threshold).

## What I Excluded and Why

- **Weight scheme variations:** type-2=10 vs type-2=2 wouldn't change scores (DP rounds are well under 3n).
- **Cycle decomposition:** Doesn't naturally produce matchings on trees.
- **Multi-hop lookahead:** Increased per-round cost without clear round-count benefit.
- **3-color schemes:** More restrictive than 2-color, would increase rounds.
- **Augmented matching algorithms:** Overkill — tree DP already optimal for trees.

## Evolution of Thinking

1. **Iter-1:** Established core algorithm (DP + anti-oscillation). Naive control scored 5.
2. **Iter-2:** Confirmed DFS timestamps (equivalent, O(n) precomp). Confirmed array adjacency (necessary for timing).
3. **Iter-3:** Probed matching strategy dimension. Discovered greedy matching scores 99.37 (consistently), with the gap concentrated on bushy trees (test 20). The tree DP resolves weight conflicts at high-degree internal nodes that greedy cannot.

## Current Status

- **Validated:** DFS+DP+array=100 (11 total runs across iters). Greedy=99.37 (3/3). Leaf-greedy=20 (1/1). Complete round-count data for all 20 tests.
- **Uncertain:** Whether a smarter greedy heuristic (parent-deferral) could match DP on bushy trees.
- **Suggested next:** If iter-4 needed: (a) generalization to non-tree graphs; (b) reducing round-count ceiling on bushy trees; (c) characterizing max-degree vs round-count relationship.

## Warnings & Constraints

1. **solution.cpp must be overwritten for h-main.** Reset between arms with `git checkout -- solution.cpp`.
2. **Judge scoring has ±5 point system-load variance** on borderline solutions. DP version is not borderline. Greedy version (99.37) is stable — loss is from round counts, not timing.
3. **ch_arr[MAXN][MAXN] uses ~4MB global memory.** Within 1024MB limit.
4. **Test 20 is the critical differentiator.** Greedy: 3.88n rounds. DP: 2.02n rounds. Threshold: 3n.
