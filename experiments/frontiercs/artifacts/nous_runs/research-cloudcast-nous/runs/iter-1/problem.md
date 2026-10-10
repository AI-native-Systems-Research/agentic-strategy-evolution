# Problem Framing: Cloudcast Broadcast Cost Minimization

## Research Question

What routing algorithm minimizes total broadcast cost (maximizes judge score) for the cloudcast multi-cloud broadcast problem?

The cost function has two components (`simulator.py:203-223`):
1. **Egress cost** (dominant): `Σ_edges(|partitions_on_edge| × partition_vol × edge_cost)` — the set of partition IDs sharing an edge determines egress; sharing an edge across destinations is free since the partition set {0..9} doesn't grow.
2. **Instance cost** (secondary): `|nodes| × num_vms × hourly_rate / 3600 × transfer_time` — depends on node count and max transfer time across all (dst, partition) pairs.

Key insight from code (`simulator.py:119`): `g[src][dst]["partitions"].add(partition_id)` — the partition set is a Python set of partition IDs. When multiple destinations share an edge, the partition set is the UNION of IDs. Since all destinations use partitions {0..9}, shared edges have `len(partitions) = 10` regardless of how many destinations use them. Therefore, **the total egress cost equals `10 × 30GB × Σ(edge_cost for unique edges in topology)`**. Minimizing the set of unique edges (weighted by cost) minimizes egress.

This is exactly the **Steiner tree problem**: find a minimum-weight tree connecting source to all destinations, potentially through relay (Steiner) nodes.

## System Interface

- **Build command:** None required (pure Python solution).
- **Run command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py`
- **Output format:** Single line `SCORE: <float>` on stdout. Score = 100/(1+total_cost), higher is better.
- **Code evidence:**
  - `evaluator.py:118-122` — score = 100 × 1/(1+total_cost)
  - `simulator.py:119` — partition set accumulation (key to shared-edge insight)
  - `simulator.py:203-223` — total cost = egress + instance
  - `simulator.py:170-201` — transfer time = max edge bottleneck
  - `simulator.py:126-160` — bandwidth constraint enforcement (equal split)
  - `utils.py:50-78` — graph construction from cost.csv and throughput.csv

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py
```

Where `solution.py` implements the default Dijkstra shortest-cost-path routing (all partitions on same per-destination cheapest path).

## Baseline Validation

- Exit code: 0
- Score: **0.0955** (total_cost ≈ $1046)
- Egress cost breakdown across 5 configs: intra_aws=$162, intra_azure=$144, intra_gcp=$159, inter_agz=$267, inter_gaz2=$303. Total SPT egress ≈ $1035.

## Experimental Conditions

### Condition 1: Baseline (Dijkstra shortest-cost path)
The existing `solution.py` — finds per-destination shortest-cost path via Dijkstra, routes all partitions along the same path. This minimizes per-destination path cost but does NOT minimize total unique edge cost (since shared edges are free).

### Condition 2: Treatment (Steiner tree routing)
Replace Dijkstra per-destination routing with a Steiner tree approximation (`networkx.algorithms.approximation.steiner_tree`). The Steiner tree finds a minimum-weight tree connecting source to all destinations, potentially through relay nodes. Because shared edges cost nothing extra (partition set stays {0..9}), minimizing the tree's total edge weight directly minimizes egress cost.

**Code change intent**: In `solution.py`, replace the `search_algorithm` function to:
1. Build an undirected cost graph from G (taking min cost of forward/reverse edges)
2. Compute Steiner tree on terminals = [src] + dsts
3. BFS from src on the tree to find directed paths to each destination
4. Route all partitions along each destination's tree path

Probe result: Steiner tree egress estimates — intra_aws=$36, intra_azure=$90, intra_gcp=$141, inter_agz=$141, inter_gaz2=$141. Total ≈ $549 vs baseline $1035 (47% reduction in egress).

## Success Criteria

- **h-main**: Steiner tree solution achieves a higher score than the Dijkstra baseline (score > 0.0955).
- Validated probe: Steiner tree score = **0.154** vs baseline **0.0955**.

## Constraints

- Solution must be a valid Python module with `class Solution` and `solve()` method.
- The returned code must define `BroadCastTopology` class and `search_algorithm` function.
- All partitions (0 to num_partitions-1) must have valid paths to each destination.
- Paths must start from source and end at destination, no self-loops.

## Prior Knowledge

This is iteration 1. No prior principles exist.
