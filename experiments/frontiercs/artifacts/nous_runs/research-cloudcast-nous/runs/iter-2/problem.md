# Problem Framing — Iteration 2

## Research Question

Can a directed Steiner arborescence (exact DP) improve broadcast cost over the undirected Steiner tree approximation from iter-1, by accounting for asymmetric edge costs in the directed graph?

Key source files:
- `evaluator.py:80-134` — evaluates search algorithm across 5 configs, sums costs
- `simulator.py:106-160` — `__construct_g()`: builds evaluation graph, line 119-120 uses partition set to count edge usage
- `simulator.py:203-223` — `__total_cost()`: egress + instance cost
- `simulator.py:170-201` — `__transfer_time()`: bottleneck edge determines transfer time
- `resources/utils.py:42-79` — `make_nx_graph()`: builds directed graph from CSV profiles

## System Interface

- **Build:** None (pure Python)
- **CLI flags:** `bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py` — prints `SCORE: <float>`
- **Code evidence:**
  - `evaluator.py:187-191` — argparse for `--solution`, `--spec`, `--out`
  - `simulator.py:119` — `g[src][dst]["partitions"] = set()` — partition SET behavior (key to cost model)
  - `simulator.py:207-208` — egress = `len(partitions) * partition_vol * cost`
  - `simulator.py:217` — instance = `num_vms * (cost_per_hr / 3600) * runtime_s` per node
- **Output:** Single line `SCORE: <float>` on stdout (higher is better)

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py
```

## Baseline Validation

- Exit code: 0
- Output: `SCORE: 0.09552371980292827`
- This is the Dijkstra shortest-path-tree baseline from iter-1.

## Experimental Conditions

### Condition 1: Directed Steiner Arborescence (h-main)
Replace `search_algorithm` in solution.py with a Dreyfus-Wagner exact DP that computes the minimum-cost directed Steiner arborescence from src to all destinations. This accounts for asymmetric edge costs (up to 7.3x ratio, 3708/4970 edges asymmetric) that the undirected Steiner tree ignores.

Key code change: implement the Dreyfus-Wagner DP operating on the directed graph G directly, with states dp[S][v] = minimum cost to reach all terminals in S from node v, using directed shortest paths and edge relaxation.

Validated probe score: **0.1594**

### Condition 2: Undirected Steiner Tree — clean implementation (h-control-negative)
Clean re-implementation of the undirected Steiner tree approach from iter-1. Uses `nx.algorithms.approximation.steiner_tree` on an undirected version of G, then converts back to directed paths via BFS from src.

Purpose: establish clean baseline for undirected approach and validate that the directed optimization's improvement is due to asymmetry handling, not implementation bugs in iter-1.

Expected score: ~0.154 (probe: 0.1539)

## Success Criteria

- h-main score > h-control-negative score (directional prediction: directed Steiner beats undirected)
- Both h-main and h-control-negative > baseline (0.0955)
- The improvement gap is attributable to inter-cloud configs (where asymmetry is highest)

## Constraints

- Algorithm must complete within reasonable time for 71-node graph with 7-8 terminals per config
- Must produce valid BroadCastTopology with paths for all (destination, partition) pairs
- Score measured exclusively via fmeasure_cloudcast.sh

## Prior Knowledge

- **RP-1**: Steiner tree routing outperforms Dijkstra SPT because shared edges are free (partition sets are unions). Confirmed in iter-1.
- **RP-2**: Instance cost from relay nodes partially offsets egress savings. Investigated in iter-2 probes: instance cost is only ~$10 out of ~$650 total (~1.5%), so the offset is negligible. The iter-1 score discrepancy (0.134 vs 0.154) was likely an implementation issue, not instance cost dominance.

### Key iter-2 discoveries:
1. Edge costs are highly asymmetric: 3708/4970 edges have different forward/reverse costs, ratio up to 7.3x
2. The undirected Steiner tree picks min(forward, reverse) cost per edge pair, but routing from src must follow directed edges. For intra_aws: undirected tree cost $0.12 but directed routing cost $0.19 (58% penalty from the src→hub edge being in the expensive direction)
3. Egress dominates cost (99%+). Instance cost is ~$10 total. Optimizing transfer time has negligible impact.
4. Partition splitting provably cannot reduce egress below the optimal single-tree cost (each partition must reach all destinations; splitting creates more unique edges without reducing per-edge partition counts)
5. The directed Steiner arborescence (Dreyfus-Wagner exact DP) is computationally feasible for 71 nodes, 7 terminals: O(3^7 × 71 + 2^7 × 71^2) ≈ 800k operations per config
