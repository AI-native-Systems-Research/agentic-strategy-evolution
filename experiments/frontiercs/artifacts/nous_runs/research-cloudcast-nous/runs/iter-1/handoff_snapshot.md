# Handoff — Iteration 1

## Goal

Implement and measure a Steiner tree routing algorithm for the cloudcast broadcast optimization problem, comparing it against the Dijkstra shortest-path baseline. The Steiner tree should score higher by reducing total unique edge cost (egress).

## Key Discoveries

1. **Egress cost dominates total cost** (~99% for baseline). Egress = 300 × Σ(unique_edge_costs_in_topology). Instance cost = nodes × 2 × $0.54/3600 × transfer_time.
2. **Shared edges are free**: `simulator.py:119` uses a Python SET of partition IDs. Since all destinations use partitions {0..9}, sharing an edge across destinations doesn't increase its partition count. This means total egress depends ONLY on the set of unique edges and their costs.
3. **Steiner tree cuts egress by ~47%**: Probe showed SPT egress $1035 vs Steiner $549 across all 5 configs. Biggest wins in intra_aws ($162→$36) and inter_gaz2 ($303→$141) where relay through cheap intermediate nodes eliminates expensive direct links.
4. **Baseline score = 0.0955, Steiner score = 0.154** (validated via fmeasure_cloudcast.sh).
5. **Graph: 71 nodes, 4970 edges.** Cost range $0.01-$0.19/GB. Intra-provider edges are generally cheaper ($0.01-$0.15) than inter-provider ($0.087-$0.19).
6. **Bandwidth constraints matter for instance cost**: Source with 6 outgoing edges (AWS, 10Gbps egress) gets 1.67Gbps per edge. Steiner tree with 2-3 branches from source gets 3.3-5Gbps each, but relay nodes add intermediate hops.

## System Interface

- **Build:** None (pure Python)
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py`
- **Output format:** `SCORE: <float>` on stdout
- **Baseline result:** SCORE: 0.0955

## Code Map

- `solution.py` — the file to edit. Contains `class Solution` with `solve()` returning `{"code": "..."}`.
- `evaluator.py:80-134` — `evaluate_search_algorithm()`: loads each config, builds graph, calls `search_algorithm()`, runs BCSimulator, sums costs across 5 configs.
- `simulator.py:106-160` — `__construct_g()`: builds evaluation graph from topology paths. Line 119: `g[src][dst]["partitions"].add(partition_id)` — the key SET behavior.
- `simulator.py:170-201` — `__transfer_time()`: max over (dst, partition) of max edge time. Edge time = `len(partitions) × partition_vol × 8 / flow`.
- `simulator.py:203-223` — `__total_cost()`: egress + instance cost.
- `resources/utils.py:43-78` — `make_nx_graph()`: builds NetworkX DiGraph from cost.csv and throughput.csv.
- `resources/examples/config/` — 5 JSON config files (intra_aws, intra_azure, intra_gcp, inter_agz, inter_gaz2).

## Code Targets

- **h-main (Steiner tree)**: `solution.py`, replace the `search_algorithm` function inside the code string. Use `from networkx.algorithms.approximation import steiner_tree`. Build undirected graph H from G with min-cost edges, compute `steiner_tree(H, [src]+dsts, weight='cost')`, BFS from src to get directed paths, route all partitions along tree paths. Use `G[u][v]` for edge data (fallback to `G[v][u]` if directed edge is reversed).

## What I Tried That Didn't Work

- **Partition splitting (Steiner + Dijkstra hybrid)**: Score dropped from 0.154 to 0.118. Splitting partitions across two paths adds unique edges, increasing egress cost. Egress dominance means any extra unique edge hurts.
- **Greedy directed Steiner heuristic**: Score 0.135, worse than undirected Steiner tree approximation (0.154). The undirected approach leverages NetworkX's Kou/Mehlhorn algorithm which finds a better global tree structure.
- **Relay routing for intra-AWS**: Cheapest 2-hop paths ($0.17/GB) are more expensive than direct 1-hop ($0.09/GB). No single-destination relay saves money; the Steiner tree's savings come from sharing common edges.

## What I Excluded and Why

- **Multi-path partition splitting**: Tested and found harmful (adds edges = more egress). Could revisit if egress is already minimized and instance cost becomes the bottleneck.
- **Congestion-aware routing**: Instance cost is ~1% of total; optimizing bandwidth utilization has negligible impact on score at current cost levels.
- **Custom Steiner tree heuristics**: NetworkX's built-in approximation is sufficient for iter-1. More sophisticated approaches (FLAC, Dreyfus-Wagner) could be explored in later iterations.

## Evolution of Thinking

Started assuming per-destination shortest paths are optimal. Then realized the partition-set sharing mechanism makes edge REUSE free, turning the problem into Steiner tree minimization. The key insight is that egress cost depends on the SET of unique edges, not the sum of per-destination path costs. This reframing from "minimize per-path cost" to "minimize total tree cost" is the core contribution of this iteration.

## Current Status

- **Validated:** Baseline (0.0955) and Steiner tree (0.154) scores confirmed via fmeasure. Cost structure understood via code analysis.
- **Uncertain:** Whether the Steiner tree's instance cost increase (more relay nodes = more transfer time) is significant enough to warrant optimization. Current Steiner tree has instance cost ~$100 vs baseline ~$11.
- **Suggested next:** (1) Try weighted Steiner tree that penalizes edge count/node count to reduce instance cost. (2) Explore k-shortest-path Steiner tree variants. (3) Investigate whether a Steiner tree that accounts for both egress cost AND transfer-time-induced instance cost could outperform the pure cost-minimizing tree.

## Warnings & Constraints

- The `steiner_tree()` function works on UNDIRECTED graphs. Must convert G to undirected (taking min cost of forward/reverse edges), then convert result back to directed paths. If an edge in the Steiner tree corresponds to a reverse direction in G, must use `G[v][u]` edge data.
- The evaluator's `__construct_g` (simulator.py:114) expects edge data as `[src_node, dst_node, edge_data_dict]` where edge_data_dict must have 'cost' and 'throughput' keys. Always pass `G[u][v]` (the original directed graph's edge data).
- The fmeasure script suppresses all stdout/stderr from the evaluator (`>/dev/null 2>&1`). Debug by running the evaluator directly if needed.
