# Problem Framing — Iteration 1

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #211 (Communication Robots)?

The problem is a **constrained Steiner Minimum Tree** in the Euclidean plane with squared-distance edge costs, type-dependent multipliers, and fixed optional Steiner points (relay stations). The key source files are:

- `chk.cc` (checker): Implements scoring as `(zero_cost - actual_cost) / (zero_cost - base_cost)`, where `base_cost = MST_robots * 8/9` and `zero_cost = MST_robots` (`chk.cc:313-337`).
- `solution.cpp` (our solution file): C++17, stdin/stdout I/O.

## System Interface

- **Build command:** `g++ -O2 -o sol solution.cpp`
- **Run (per test case):** `./sol < testdata/N.in`
- **Measure score (judge):** `bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp`
  - Prints `SCORE: <n>` where n ∈ [0, 100].
  - Runs all 10 test cases internally.
- **Code evidence:**
  - Scoring formula: `chk.cc:313-337` — `base_cost = d/9*8`, `zero_cost = d`, linear interpolation.
  - Edge cost: `chk.cc:29-45` — RS/SR/SS → 0.8×D; CC → 1e18 (forbidden); all else → 1×D.
  - Output format: `chk.cc:236-307` — line 1: relay IDs separated by `#` (or `#` if none); line 2: edges as `id-id` separated by `#`.
- **Time limit:** 10 seconds per test case. **Memory limit:** 512 MB.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp
```

## Baseline Validation

Ran the metric closure MST approach. Exit code 0. Output: `SCORE: 86.951`. The solution produces valid output for all 10 test cases (verified on test case 1: output matches the expected answer file format). Timing on the largest test case (N=K=1500): 3.0 seconds.

## Experimental Conditions

### h-main: Metric Closure MST with Steiner Relay Integration

**Algorithm:**
1. For each pair of robots (i,j), compute the "metric closure" edge weight: `min(direct_cost(i,j), min_C(cost(i,C) + cost(C,j)))` over all relay stations C.
2. Build MST of robots using metric closure weights (Kruskal's).
3. Reconstruct actual edges: replace virtual edges with relay-mediated paths.
4. Build subgraph MST on the induced subgraph (robots + used relays) with all valid edges.
5. Prune relay leaves iteratively.
6. Greedy insertion of unused relays into remaining robot-robot edges.

**Key insight:** Since C-C edges are forbidden, the shortest path between any two robots via relays is at most 2 hops (robot → relay → robot). So the metric closure captures ALL shortest paths exactly. Furthermore, for squared-distance costs, the optimal relay for pair (i,j) is the one nearest to their midpoint.

This approach finds the optimal robot connectivity structure FIRST (via metric closure MST), then resolves relay sharing via subgraph MST, giving better results than a full MST of all nodes.

**Validated score:** 86.951/100.

### h-ablation: Full MST + Prune (no metric closure)

**Algorithm:**
1. Build all valid edges (robot-robot and robot-relay, excluding C-C).
2. Run Kruskal's MST on the full graph (all N+K nodes).
3. Prune relay leaf nodes iteratively.
4. Remove unprofitable degree-2 relays (replace with direct robot-robot edges when cheaper).
5. Greedy insertion of unused relays into robot-robot edges.

This tests whether the metric closure is necessary by using the simpler "MST of full graph + prune" Steiner tree heuristic.

**Validated score:** 62.148/100.

## Success Criteria

- h-main achieves score > 80 (directional: higher is better).
- h-main outperforms h-ablation, confirming that the metric closure approach is superior to the naive full MST + prune heuristic.

## Constraints

- 10 seconds per test case, 512 MB memory.
- N ≤ 1500, K ≤ 1500 (up to 3000 nodes total).
- The metric closure computation is O(N²·K) ≈ 3.375 billion operations for the largest cases, fitting within the time limit (~3s observed).
- C-C edges are forbidden — no relay-to-relay direct connections.

## Prior Knowledge

This is the first iteration. No prior principles exist. The problem is a constrained Steiner tree problem, which is NP-hard in general. Our heuristic (metric closure MST) is a well-known 2-approximation adapted to this specific problem structure.
