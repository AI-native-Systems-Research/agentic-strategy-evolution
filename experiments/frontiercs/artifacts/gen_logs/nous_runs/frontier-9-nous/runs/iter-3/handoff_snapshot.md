# Handoff — Frontier-CS #9: Tree Matching Sort (Iteration 3)

## Goal

Measure two variants of the tree matching sort algorithm: (1) h-main: greedy matching replacing tree DP (same DFS+array framework), expected to score ~99.4; (2) h-robustness: the proven DFS+DP+array solution, expected to score 100. Write each into solution.cpp and measure with `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`. Run 3 measurements per arm.

## Key Discoveries

1. **Tree DP is necessary for score 100 on bushy trees.** Greedy matching (two-pass: type-2 first, then type-1) uses 3.88n rounds on test 20 (bushy tree, n≈492, max_degree≈124) vs DP's 2.02n. Since score requires m ≤ 3n (scoring formula: s = (10n-m)/(7n), capped at 1.0), greedy exceeds the threshold and gets partial credit ~0.874 per sub-test on test 20.

2. **Greedy is comparable or better on low-degree trees.** On random trees (tests 2-5, n≈303), greedy uses 0.89-1.35n rounds vs DP's 1.01-1.48n. On paths (tests 7-8), identical round counts (0.04n). The DP's advantage is specific to high-degree nodes where multiple edges compete for the same parent.

3. **Leaf-to-root greedy is catastrophically bad (score 20).** Processing nodes from leaves to root and greedily matching each with its parent (regardless of weight) blocks optimal higher-level matches. Example: if edge(A,B) has weight 1 and edge(Root,A) has weight 2, leaf-to-root matches A-B first, blocking the better Root-A match. This is not just suboptimal — it fails to converge within 6n rounds on many tests.

4. **Round count data (complete, 20 tests):**
   - DP worst case: 2.02n on test 20
   - Greedy worst case: 3.88n on test 20
   - Greedy vs DP on test 19: 1.95n vs 1.42n (37% more rounds)
   - On most tests: within 10% of each other

5. **Score 99.37 for greedy is stable.** Measured 3/3 times consistently at 99.37 during exploration. The gap comes entirely from test 20's two sub-tests scoring ~0.874 instead of 1.0.

6. **The DFS+DP+array solution remains at 100.** Verified once in iter-3 exploration. Combined with iter-2's 3/3, iter-1's 5/5: consistently perfect.

## System Interface

- **Build:** `g++ -O2 -o solution solution.cpp`
- **Run / Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100
- **Baseline result:** DFS+DP+array version scores 100

## Code Map

- `solution.cpp` — The active solution file. Currently contains the DFS+DP+array version (iter-2 h-main). For h-main, replace DP functions with greedy matching. For h-robustness, run as-is.

- `solution.cpp:104-127` — `compute_dp_iterative()`. The tree DP that h-main replaces. Computes dp0[u] (don't match u with any child) and dp1[u] (match u with best child) for each node u in bottom-up BFS order. This is what makes the matching optimal on high-degree nodes.

- `solution.cpp:133-158` — `extract_iterative()`. Traces back DP decisions to build the matching array. Also replaced by greedy in h-main.

- `solution.cpp:32-33` — `dp0[MAXN], dp1[MAXN], best_ch[MAXN]`. DP arrays to remove in h-main.

- `solution.cpp:130-131` — `match_buf[MAXN], match_sz`. Output of matching function. Keep for both arms — greedy writes to same arrays.

- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/chk.cc:46` — Scoring formula. `s_i = max(0, (10n-m)/(7n))`, capped at 1.0 per sub-test.

- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/testdata/` — 20 test files. Test 20 is the critical case (bushy tree, max_degree≈124).

## Code Targets

### h-main: Greedy matching (replace DP)
In solution.cpp:
- **Remove:** `compute_dp_iterative()` function (lines 104-127), `extract_iterative()` function (lines 133-158), arrays `dp0[MAXN]`, `dp1[MAXN]`, `best_ch[MAXN]` (lines 32-33)
- **Add:** `greedy_matching()` function and `used_node[MAXN]` boolean array
- **greedy_matching() implementation:**
  ```
  void greedy_matching() {
      match_sz = 0;
      memset(used_node + 1, 0, sizeof(bool) * n);
      // First pass: type-2 edges (both elements benefit)
      for (int idx = 1; idx < n; idx++) {
          if (EW[idx] == 2) {
              int u = eu[idx], v = ev[idx];
              if (!used_node[u] && !used_node[v]) {
                  match_buf[match_sz++] = idx;
                  used_node[u] = used_node[v] = true;
              }
          }
      }
      // Second pass: type-1 edges (one element benefits)
      for (int idx = 1; idx < n; idx++) {
          if (EW[idx] == 1) {
              int u = eu[idx], v = ev[idx];
              if (!used_node[u] && !used_node[v]) {
                  match_buf[match_sz++] = idx;
                  used_node[u] = used_node[v] = true;
              }
          }
      }
  }
  ```
- **Modify main loop:** Replace `compute_dp_iterative(); extract_iterative(1);` with `greedy_matching();`
- **Keep unchanged:** DFS timestamps, array adjacency, anti-oscillation, pragma, output buffering, all other code

### h-robustness: Proven solution (no changes)
Run the existing solution.cpp as-is. No code changes needed.

## What I Tried That Didn't Work

1. **Leaf-to-root greedy (score 20).** Processing nodes from leaves to root, matching each with its parent if weight > 0 and both unmatched. This finds a maximal matching but NOT maximum-weight. Catastrophic on most tree types because it matches at lower levels first, blocking better higher-level matches. Round counts blow up to 6n (max limit) on many tests.

2. **Arbitrary-order greedy without weight priority (not tested separately).** The two-pass greedy (type-2 first, then type-1) already implements weight priority within the greedy framework. Testing without priority would be worse than 99.37.

## What I Excluded and Why

- **Weight scheme variations (type-2=10, type-1=1, etc.):** The weight scheme changes DP decisions at tie-breaks but doesn't affect scoring since all DP variants produce rounds well under 3n. Testing weight variations would show identical scores of 100.

- **Augmented matching / Edmonds' algorithm:** Exact maximum matching algorithms are overkill — the tree DP already finds the optimal matching in O(n) due to tree structure. And they'd be slower, making timing worse.

- **Cycle decomposition approaches:** Decomposing the permutation into cycles and routing along cycle paths. Excluded because: (a) the round count is already well under 3n with DP, and (b) cycle routing on trees doesn't naturally produce matchings.

- **3-color anti-oscillation:** More colors means more restrictive gating, which would increase round counts. Depth-parity 2-coloring is already optimal (RP-5).

- **Multi-hop lookahead matching:** Considering 2-step-ahead benefits per matching edge. Excluded because it would increase per-round computation without clear round-count benefit (current rounds are already very efficient).

## Evolution of Thinking

1. **Started by asking what's left to explore.** Score is 100, algorithm is well-characterized. The remaining untested component is the matching strategy (DP vs alternatives).

2. **Probed arbitrary-order greedy (99.37).** Surprisingly close to 100 — the DP matters only on bushy trees. This motivated a deeper investigation.

3. **Probed leaf-to-root greedy (20).** Expected this to be better (classic greedy matching algorithm on trees). It was catastrophically worse because it doesn't consider weights.

4. **Analyzed complete round count data.** Discovered that the DP-vs-greedy gap is concentrated on test 20 (bushy tree, 3.88n vs 2.02n). On random and path trees, greedy is comparable or even better.

5. **Concluded:** The tree DP's value is in resolving weight conflicts at high-degree internal nodes. This is a specific, testable claim that the h-main arm validates.

## Current Status

- **Validated:** DFS+DP+array=100 (iter-1 5/5, iter-2 3/3, iter-3 1/1). Greedy=99.37 (3/3). Leaf-greedy=20 (1/1).
- **Uncertain:** Whether a smarter greedy (e.g., with parent-deferral heuristic) could match DP's round counts on bushy trees. Not tested because it would require complex heuristics that approach the DP's logic.
- **Suggested next:** If iter-4 is needed: (a) explore whether the algorithm generalizes to non-tree graphs; (b) test whether the round-count ceiling of 2.02n on bushy trees can be reduced with a different routing strategy; (c) characterize the relationship between tree max-degree and round counts.

## Warnings & Constraints

1. **solution.cpp must be overwritten completely for h-main.** The greedy version removes DP functions and arrays. For h-robustness, use the current solution.cpp unchanged.

2. **Reset between arms.** Use `git checkout -- solution.cpp` between arms to restore the baseline for h-robustness, or overwrite completely.

3. **Judge scoring variance.** System load can cause ±5 point variance on borderline solutions. The DP version (score 100) is not borderline. The greedy version (score 99.37) is also stable — its loss comes from round counts, not timing.

4. **Greedy probe files in worktree.** The exploration created `solution_greedy_probe.cpp` and `solution_leaf_greedy.cpp` in the worktree root. These are probe files, not experiment inputs. The executor should write fresh code based on the Code Targets above.

5. **Test 20 is the critical differentiator.** If round counts on test 20 change significantly from the probed values, the score will change. The DP's 2.02n is robust; the greedy's 3.88n is also robust (3/3 consistent at 99.37).
