# Handoff Snapshot — Iteration 2

## Goal

Implement and measure the enhanced metric closure MST algorithm (h-main: perturbed restarts + relay reassignment + degree-3 hub insertion) and its ablation (h-ablation: restarts only), comparing both against the iter-1 baseline score of 86.951.

## Key Discoveries

1. **Perturbed MC MST restarts are the biggest single improvement.** Adding noise ε ∈ [0.002, 0.102] to metric closure weights and rebuilding MST via Kruskal's explores alternative tree topologies. On tests 3 and 8 (largest gaps), this yielded ~47-50K cost savings in probe measurements. The approach works because many near-equal-weight MSTs exist, and different topologies lead to different relay assignments after subgraph MST + prune + greedy insert.

2. **Relay reassignment provides small but real gains on tests 5 and 10.** For each used relay (especially degree-3+ hubs), checking all unused alternatives found improvements of 4,341 (test 5) and 11,936 (test 10). Only useful for relays with degree ≥ 3, where the position tradeoff across multiple neighbors matters.

3. **Degree-3 hub insertion uses the Steiner subtree formula correctly.** For unused relay c connecting robots r1, r2, r3: savings = pm_max + pm_min - (d(c,r1) + d(c,r2) + d(c,r3)), where pm values are pairwise path-max bottleneck costs. This was validated to find genuine savings: test 3 (28,986), test 5 (10,307), test 8 (48,747), test 10 (16,898). These are different from and additive with greedy degree-2 insertion.

4. **Tests 1 and 2 are structurally capped.** With K=10 relays and exhaustive 2^K enumeration, test 1 is at optimal relay selection (6.987/10). Test 2 (N=100, K=10) scores 1.475/10, structurally limited by relay scarcity. No algorithmic improvement can fix these.

5. **Tests 4, 6, 7, 9 already score perfect 10.0.** These tests are solved by the iter-1 approach alone.

6. **Combined probe measurement: 87.162 (+0.211 over iter-1 baseline).** The improvement comes entirely from tests 3, 5, 8, 10. Each improvement mechanism contributes independently.

7. **Prim's O(N²) subgraph MST is optimal for this problem.** Much faster than Kruskal's O(E log E) for the dense subgraph. No KD-tree acceleration needed since brute-force metric closure takes <3s.

## System Interface

- **Build:** `g++ -O2 -o sol solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100, sum of 10 test cases × 10 pts each).
- **Baseline result:** Iter-1 = 86.951. Enhanced (h-main probe) = 87.162.
- **Judge runtime:** ~22-30 seconds total across all 10 test cases.

## Code Map

- `chk.cc:29-45` — `dist_cost()`: edge cost rules. Check if edge costs seem wrong.
- `chk.cc:75-108` — `base_mst()`: robot-only MST. Scoring baseline.
- `chk.cc:313-337` — Scoring: `base_cost = d/9*8`, `zero_cost = d`, linear interpolation.
- `solution.cpp:8-16` — `ecost()`: must return 1e18 for C-C pairs.
- `solution.cpp:43-280` (approx) — `build_solution()`: subgraph MST + prune + greedy insert + reassign + hub3.
- `solution.cpp:290-330` (approx) — Main: MC computation + Kruskal MST + perturbation loop.

## Code Targets

### h-main (Enhanced MC MST)
- **File:** `solution.cpp` (full rewrite)
- **Key additions over iter-1:**
  1. **Perturbation loop** (in `main()`, after original MST): time-limited while loop, perturb mc_edge weights, re-sort, Kruskal, full build_solution, keep best. ε from 0.002 to 0.102, LCG seed 54321.
  2. **Relay reassignment** (in `build_solution()`, after greedy insert): for each relay node with degree ≥ 1, check all unused relays as replacements.
  3. **Degree-3 hub insertion** (in `build_solution()`, after reassignment): BFS for tree structure, LCA path-max for bottleneck computation, Steiner savings formula, edge removal + hub connection.
  4. **Unlimited greedy rounds** (in `build_solution()`): `round < 100` instead of `round < 3`.
- **The probe-validated solution is at the current HEAD of the worktree's solution.cpp.**

### h-ablation (Restarts Only)
- **File:** `solution.cpp` (modified version of h-main)
- **Change:** Remove the relay reassignment block and the degree-3 hub insertion block from `build_solution()`. Keep everything else identical.
- **Location:** The relay reassignment starts after `// Relay reassignment` comment; the degree-3 hub starts after `// Degree-3 hub insertion` comment. Remove both sections.

## What I Tried That Didn't Work

1. **Non-adjacent relay insertion (LCA path-max):** For each unused relay and each pair of non-adjacent robots, checked if inserting the relay would improve cost via path-max bottleneck replacement. Found 0 improvements on all tests. The tree is locally optimal for all degree-2 operations — greedy insertion already captures all degree-2 opportunities.

2. **Edge-swap with unused relays:** For the top 200 most expensive tree edges, checked if any unused relay provides a cheaper cross-component connection. Found 0 improvements. This is redundant with greedy insertion.

3. **Prim-based perturbation (matrix form):** Storing the full Nr×Nr metric closure matrix and running Prim's O(Nr²) per trial. Slightly worse than Kruskal-based perturbation (87.127 vs 87.162) despite running more trials. The Kruskal sort step, while slower per trial, may produce more diverse tree structures.

4. **Screening + selective build:** Running many fast Prim trials, keeping top-20 by MC MST cost, then building full solutions only for the best candidates. Same score as direct Prim perturbation. The proxy (MC MST cost) doesn't perfectly correlate with final solution cost.

## What I Excluded and Why

1. **Multi-relay paths / relay chaining:** C-C edges are forbidden (RP-2), so relay paths are always exactly 2 hops. Multi-relay paths are structurally impossible.

2. **Exhaustive relay selection for large tests:** 2^1500 is infeasible. The metric closure approach implicitly handles relay selection.

3. **Simulated annealing / genetic algorithms:** The time budget (9s within 10s limit) is too tight for complex metaheuristics. The perturbation loop is the simplest effective randomized approach.

4. **KD-tree acceleration:** Brute-force metric closure takes <3s. KD-tree would save ~2s but adds implementation complexity with no score benefit.

## Evolution of Thinking

Started by validating iter-1's suggestion to add top-K relay reconstruction. RP-2 warned this hurts performance, which I confirmed: it's a dead end.

Pivoted to three orthogonal improvement strategies: (1) exploring alternative MST topologies via perturbation, (2) post-processing relay positions, (3) adding degree-3 hubs. Each targets a different source of suboptimality:
- Perturbation: the MST topology might not be globally optimal for the downstream pipeline.
- Reassignment: greedy insertion chose relays one-at-a-time, missing global relay position optimization.
- Degree-3 hubs: greedy insertion only does degree-2 (splits one edge); hubs connecting 3 nodes save more.

Key insight: these improvements are small individually but stack because they address independent suboptimalities. The total is about +0.21 points, primarily from perturbation.

## Current Status

- **Validated:** Enhanced algorithm scores 87.162 (probe). Build succeeds. Output valid on all tests.
- **Uncertain:** Whether the judge server's CPU speed affects perturbation trial count (time-limited loop). The 9s budget might yield fewer trials on slower hardware.
- **Suggested next:**
  - Try Steiner tree local search (3-opt, edge relocation) for more aggressive topology improvement.
  - Investigate whether different perturbation distributions (e.g., log-normal, per-edge independent) yield better diversity.
  - Consider randomized greedy insertion order (not just by savings magnitude) to escape local optima.
  - The remaining score gap is ~12.84 points. Tests 1,2 account for ~11.54 of that (structurally irreducible). Tests 3,5,8,10 have only ~1.3 points of remaining improvable gap.

## Warnings & Constraints

1. **The `ecost()` function MUST return 1e18 for C-C pairs.** All code paths that create edges (greedy insertion, hub insertion, reassignment) call ecost, which prevents C-C edges.
2. **The degree-3 hub insertion can disconnect the tree if bottleneck edge removal is buggy.** The edge removal must find the EXACT edge (not just the cost) using LCA walk. The code uses `find_bottleneck_edge()` which walks the tree path and tracks the highest-cost edge.
3. **After hub insertion, a final prune pass is needed** to remove any relay leaves that became disconnected.
4. **The par[] union-find array is reused.** Must reset `par[i] = i` before each Kruskal's MST call.
5. **The perturbation seed (54321) is deterministic.** Different seeds may yield different scores. The LCG quality is sufficient for noise generation.
6. **Memory:** mc_edges vector (~1.12M entries × 40 bytes) uses ~45MB. drc matrix (~2.25M entries × 8 bytes) uses ~18MB. Total well under 512MB.
