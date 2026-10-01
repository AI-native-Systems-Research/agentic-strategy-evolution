# Handoff Snapshot — Iteration 1

## Goal

Implement and measure two algorithmic strategies for the Communication Robots Steiner tree problem (#211): the metric closure MST approach (h-main) and the full MST + prune approach (h-ablation). Record the judge score for each.

## Key Discoveries

1. **Scoring formula is NOT what the problem statement says.** The checker (`chk.cc:313-337`) computes `base_cost = MST * 8/9` and `zero_cost = MST`. Score is linearly interpolated: `(zero_cost - actual) / (zero_cost - base_cost)`. Full score requires actual ≤ MST * 8/9. The problem statement's description of `min(1.0, base_cost / actual_cost)` is misleading.

2. **C-C edges are forbidden** (`chk.cc:38-44`). This means relay-mediated paths are exactly 2 hops: robot → relay → robot. No relay chaining. This makes the metric closure EXACT — no approximation.

3. **The 0.8 discount only applies to non-relay pairs with at least one S-type** (`chk.cc:38`). Specifically: RS, SR, SS get 0.8×D. All other valid pairs (RR, RC, CR, SC, CS) get 1.0×D. This means relays are most beneficial for long R-R edges (no discount to overcome).

4. **Test case sizes:** Test 1: N=10,K=10. Test 2: N=100,K=10. Tests 3-10: N=1500,K=1500. Type distribution is ~50% R, ~50% S among robots; all K nodes are relays.

5. **Squared-distance metric makes relays very valuable.** A relay at the midpoint of an edge of length L saves ~L²/2 (50% of edge cost). For the metric closure, the best relay for pair (i,j) is the one nearest to their midpoint in Euclidean distance.

6. **Metric closure MST scores 86.95; full MST + prune scores 62.15.** The metric closure approach is dramatically better because it first finds the optimal robot connectivity structure, then fills in relays. The full MST approach wastes capacity connecting relays before pruning.

7. **Timing:** The metric closure computation (O(N²·K)) takes ~3s on the largest test cases. Total per-case time is well under 10s.

## System Interface

- **Build:** `g++ -O2 -o sol solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout. Score is 0-100 (sum over 10 test cases, each 0-10).
- **Baseline result:** Metric closure MST → SCORE: 86.951.

## Code Map

- `chk.cc:29-45` — `dist_cost()` function: edge cost rules (0.8 for RS/SR/SS, 1e18 for CC, 1.0 otherwise). Check here if edge costs seem wrong.
- `chk.cc:75-108` — `base_mst()`: MST of robots only (no relays). Used as scoring baseline.
- `chk.cc:110-136` — `fitness()`: total cost of submitted network. Check here if score calculation seems off.
- `chk.cc:138-216` — `verify()`: validates solution (connectivity, no C-C edges, valid IDs).
- `chk.cc:313-337` — Scoring: `base_cost = d/9*8`, `zero_cost = d`, linear interpolation.
- `testdata/` — 10 test cases. Test 1 and 2 are small; tests 3-10 have N=K=1500.

## Code Targets

### h-main (Metric Closure MST)
- **File:** `solution.cpp` (full rewrite of the stub)
- **Algorithm steps:**
  1. Read input, separate robots and relays
  2. Precompute `drc[r][c]` = squared distance from robot r to relay c (flat array for cache efficiency)
  3. For each robot pair: find best cost = min(direct, min over relays of drc[i][c]+drc[j][c])
  4. Kruskal's MST on robots using metric closure weights
  5. Reconstruct: for each MST edge via relay, add relay to subgraph with both edges
  6. Build subgraph MST with ALL valid edges among subgraph nodes (handles relay sharing)
  7. Prune relay leaves
  8. Greedy insert unused relays into remaining robot-robot edges
- **Critical detail:** The metric closure inner loop must use raw pointers for cache efficiency: `const double* di = &drc[i * Nc]; ... double via = di[c] + dj[c];`

### h-ablation (Full MST + Prune)
- **File:** `solution.cpp` (different implementation)
- **Algorithm:** Build all valid edges (no C-C), Kruskal's MST on all N+K nodes, prune relay leaves, remove unprofitable degree-2 relays (only if both neighbors are non-relay), greedy relay insertion.
- **Critical detail:** The degree-2 relay removal MUST check that both neighbors are non-relay to avoid creating C-C edges.

## What I Tried That Didn't Work

1. **First attempt with full MST had C-C bug** — the `ecost()` function didn't return infinity for C-C pairs, causing the relay insertion step to create C-C edges. Score: 1.323. Fix: always return 1e18 for C-C in ecost.

2. **Robot-only MST + relay insertion** — Start with MST of robots only, then split robot-robot edges with relays. Score: 51.24. Misses relay hub opportunities (degree 3+).

3. **Hub extension (extending relay hubs to more robots via bottleneck replacement)** — BFS from each relay to find bottleneck edges, then extend by adding relay-robot edges and removing bottleneck. Score DROPPED to 77. The approach appears correct theoretically but introduced a regression — likely an interaction with the relay insertion step or the adj vector sizing. Abandoned.

## What I Excluded and Why

1. **KD-tree acceleration for metric closure** — The optimal relay for pair (i,j) is the one nearest to their midpoint. A KD-tree could find this in O(log K) instead of O(K). But the brute-force O(N²K) only takes ~3s, well within the 10s limit. Not worth the implementation complexity for iter-1.

2. **Top-K relays in reconstruction** — Adding the top-3 relays per MST edge (instead of just the best) to the subgraph would give the subgraph MST more options. Excluded for simplicity; could improve scores by 2-5%.

3. **Christofides/LKH-style Steiner tree improvements** — More sophisticated local search (edge swaps, relay repositioning) could improve by 5-10%. Excluded for complexity.

## Evolution of Thinking

Started with the assumption that "MST of all nodes + prune" is the standard Steiner tree heuristic. Discovered that for this problem (fixed Steiner points, no C-C edges), the metric closure approach is much better because it separates the connectivity decision (which robots to connect) from the relay assignment (which relay to use for each connection). The 2-hop path limitation (due to C-C forbidden) makes the metric closure exact, not approximate.

The biggest insight was understanding that the scoring formula is NOT `min(1, base/actual)` as stated, but rather a linear interpolation between MST and MST*8/9. This means saving ~11% of MST cost gives full marks.

## Current Status

- **Validated:** Both h-main (86.95) and h-ablation (62.15) produce valid output on all test cases. Timing is within limits.
- **Uncertain:** Why test case 2 (N=100, K=10) likely scores low — only 10 relays for 99 MST edges means most edges can't be improved. Unknown per-test-case breakdown.
- **Suggested next:**
  - Add top-K relay reconstruction (include 2nd-3rd best relays in subgraph)
  - Try KD-tree acceleration to free up time for more optimization rounds
  - Investigate per-test-case scores to identify which cases are below full marks
  - Try global edge-swap optimization (bottleneck replacement for unused relays connecting distant robot pairs)

## Warnings & Constraints

1. **The `ecost()` function MUST return 1e18 for C-C pairs.** Without this, any step that creates edges (insertion, reconstruction) can silently create invalid C-C edges that the checker rejects.
2. **The scanf format for type is `%s` not `%c`** — reading with `%c` misses whitespace handling.
3. **The par[] (union-find) array is reused** between the metric closure MST and the subgraph MST. Must reset `par[i] = i` before the second Kruskal's.
4. **The subgraph adj vector must grow** when new relays are added during the relay insertion step. Use `adj.push_back({})` or pre-size the vector.
5. **Memory:** The drc matrix (N×K doubles) uses ~18MB for N=K=1500. The mc_edges vector (~1.12M entries) uses ~36MB. Total is well under 512MB.
