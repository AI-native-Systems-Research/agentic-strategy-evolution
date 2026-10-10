# Problem Framing — Frontier-CS #9: Tree Matching Sort

## Research Question

What algorithm maximizes the Frontier-CS judge score for problem #9 — sorting a permutation on a tree using minimum matching-swap operations?

The core challenge: given a tree T=(V,E) with permutation p on vertices, find a sequence of matchings M_1, M_2, ... such that swapping along each matching eventually sorts the permutation (p_i = i for all i), minimizing the number of matchings (rounds). Scoring is continuous: `s_i = max(0, (10n - m) / (10n - 3n))` where m = rounds used.

Key source files:
- Checker: `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/9/chk.cc` — validates matchings, computes score via base_value/best_value from .ans file
- Measurement: `/home/ubuntu/frontier/gen_logs/fmeasure_9.sh` — compiles and runs solution against all test cases
- Solution: `/home/ubuntu/frontier/gen_logs/frontier_9_nous_ws/solution.cpp`

## System Interface

- **Build command:** `g++ -O2 -o solution solution.cpp`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp`
  - Prints `SCORE: <n>` where n is 0-100 (higher is better)
- **Output format:** stdout with matching count m, then m lines each describing a matching
- **Time limit:** 1 second per test case
- **Memory limit:** 1024 MB
- **Constraints:** n ≤ 1000, sum of n² ≤ 10^6, multiple test cases per input

**Code evidence:**
- Scoring formula: `chk.cc` reads `base_value` and `best_value` from `.ans` file, computes `max(0, (base_value - m) / (base_value - best_value))` capped at 1.0
- Test structure: Tests 1-6 have random trees (n~300, diameter~20), Tests 7-19 have path graphs (diameter=n-1), Test 20 has bushy trees (diameter=6, max_degree~124)

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_9.sh $PWD/solution.cpp
```

## Baseline Validation

Ran v2 solution (solution.cpp = solution_v2.cpp). Exit code 0. **Score: 99.37**. All 20 test cases produce valid output with correct matchings and sorted permutations.

## Experimental Conditions

### Condition: h-main (Next-step routing + tree DP max-weight matching + alternating anti-oscillation)

Algorithm:
1. **All-pairs BFS:** Compute D[u][v] for all vertex pairs (O(n²) time, within sum-n² ≤ 10^6 constraint)
2. **Root tree at vertex 1:** Assign edge colors by depth parity of child endpoint (depth(child) % 2). This ensures adjacent parent-child edges have different colors.
3. **Each round:** Classify edges by swap benefit:
   - **Type-2 (weight 2):** Both P[u] and P[v] move closer to their targets by swapping. Always allowed (no oscillation risk — both elements benefit).
   - **Type-1 (weight 1):** Only one element benefits. Only allowed when edge_color matches current round's color (round % 2). This alternating constraint prevents period-2 oscillation.
   - **Type-0 (weight 0):** Neither element benefits. Excluded.
4. **Max-weight matching via tree DP:** O(n) per round. dp0[u] = max weight without matching u to parent; dp1[u] = max weight with matching u to parent.
5. **Execute matching:** Swap elements along selected edges.
6. **Repeat up to 6n rounds** or until sorted.

Changes from naive greedy: Tree DP optimal matching replaces greedy; next-step routing replaces "don't displace correct" heuristic; alternating coloring prevents oscillation.

### Condition: h-control-negative (Naive greedy without tree DP or anti-oscillation)

The original stub solution or a simple greedy (pick first beneficial swap per round). Expected score: ~5 (observed in earlier experiments with greedy + no anti-oscillation).

## Success Criteria

- **h-main score ≥ 90:** The tree DP + alternating approach achieves high partial credit across all test structures.
- **h-main significantly outperforms h-control-negative:** Demonstrates that the combination of optimal matching and anti-oscillation is necessary for competitive performance.
- **All test cases produce valid output:** No wrong-answer verdicts from the checker.

## Constraints

- 1 second time limit per test case — O(n² × rounds) must fit. With n ≤ 1000 and rounds ≤ 6000, the all-pairs BFS is the bottleneck at O(n²).
- sum(n²) ≤ 10^6 across test cases within a single input file.
- Memory limit 1024 MB — D[MAXN][MAXN] with MAXN=1005 uses ~4 MB (int arrays), well within limit.

## Prior Knowledge

This is iteration 1. No prior principles exist.

Key insights discovered during exploration:
1. **Oscillation is the killer:** Without anti-oscillation logic, the algorithm loops indefinitely on some test cases, producing wrong answers (observed: score dropped to 5 with v1/solution_main.cpp).
2. **Depth-parity coloring prevents period-2 oscillation:** Adjacent edges in the tree (parent-child edges sharing a vertex) have different colors, so the same type-1 swap can't recur in consecutive rounds.
3. **Type-2 swaps are always safe:** Both elements benefit, so there's no oscillation risk regardless of coloring.
4. **Path graphs and bushy trees have different characteristics:** Paths have diameter n-1 (many routing hops), bushy trees have diameter ~6 but max_degree ~124 (bottleneck at hub vertices). The alternating approach handles both, though bushy trees use slightly more rounds proportionally.
5. **Failed approaches:** Exclude-previous (v3) failed on bushy trees. Hybrid exclude-previous + alternating (v4, v5) didn't improve and caused wrong answers. Centroid rooting (v6) scored worse (90 vs 99.37).
