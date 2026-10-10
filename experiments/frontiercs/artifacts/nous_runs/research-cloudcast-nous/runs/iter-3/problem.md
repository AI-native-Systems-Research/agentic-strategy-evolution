# Problem Framing — Iteration 3

## Research Question
Can a throughput-aware directed Steiner arborescence outperform a cost-only directed Steiner arborescence for multi-cloud broadcast routing? The hypothesis is that among equally-cost-optimal tree topologies, selecting edges with higher throughput reduces transfer time (and thus instance cost) without increasing egress cost.

Key source files:
- `evaluator.py:60-134` — evaluation loop: calls `search_algorithm()` per config, sums costs across 5 configs
- `resources/simulator.py:106-160` — `__construct_g()`: builds directed graph from topology, enforces bandwidth constraints via equal flow split (`1/len(out_edges)`)
- `resources/simulator.py:170-201` — `__transfer_time()`: T = max over (dst, partition, edge) of `|P_e| × partition_vol × 8 / flow_e`
- `resources/simulator.py:203-223` — `__total_cost()`: egress + instance; instance = `|V| × num_vms × $0.54/3600 × T`
- `resources/utils.py:42-79` — `make_nx_graph()`: builds directed graph from cost.csv and throughput.csv

## System Interface
- **Build:** None (pure Python)
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py`
- **Code evidence:** `evaluator.py:92` calls `search_algorithm(src, dsts, graph, num_partitions)`. `evaluator.py:118` computes `cost_score = 1.0 / (1.0 + total_cost)`. `simulator.py:207-208` computes per-edge egress as `len(partitions) * partition_data_vol * cost`. `simulator.py:142-158` enforces bandwidth by `flow_proportion = 1 / len(list(out_edges))`.
- **Output:** Single line `SCORE: <float>` on stdout (0-100, higher is better)

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_cloudcast.sh $PWD/solution.py
```

## Baseline Validation
Dijkstra baseline: exit 0, SCORE: 0.0955 (total_cost ≈ $946).
Directed Steiner (cost-only): exit 0, SCORE: 0.1595 (total_cost ≈ $625.83).
Directed Steiner (throughput tiebreak): exit 0, SCORE: 0.1601 (total_cost ≈ $623.75).

## Experimental Conditions

### h-main: Directed Steiner with throughput-aware tiebreaking
Modified Dreyfus-Wagner DP edge weight: `cost + ε/throughput` (ε=1e-9). This breaks cost-ties in favor of high-throughput edges, reducing transfer time and instance cost while preserving optimal egress cost.

### h-control-negative: Per-destination Dijkstra (baseline)
Standard Dijkstra shortest-path from src to each destination, all partitions on the same per-destination paths. No Steiner tree optimization.

### h-ablation: Directed Steiner (cost-only, no tiebreaking)
Dreyfus-Wagner DP with edge weight = cost only. This is the iter-2 approach — optimal for egress but ignores throughput.

## Success Criteria
- h-main score > h-ablation score (throughput tiebreaking helps)
- h-main score > h-control-negative score (Steiner optimization helps)
- h-ablation score > h-control-negative score (directed Steiner beats Dijkstra)

## Constraints
- Score = 100/(1+total_cost), total_cost summed across 5 configs
- Egress dominates cost (~99%). Instance cost ≈ $5-8 total.
- Theoretical maximum score ≈ 0.1616 (zero instance cost, optimal egress $618)
- Edge costs range $0.01-$0.19/GB. Minimum cost gap = $0.0005.
- Throughput range 0.33-67.3 Gbps (with 2 VMs). Equal bandwidth sharing at congested nodes.

## Prior Knowledge
- RP-1 (iter-1): Steiner tree routing outperforms per-destination Dijkstra due to shared edges.
- RP-3 (iter-2): Directed Steiner arborescence outperforms undirected Steiner on inter-cloud configs by 6.6% per-config due to asymmetric edge costs (75% of edges differ by up to 7.3x between forward/reverse).
- Iter-2 proved partition splitting cannot reduce egress below single-tree optimum.
- Instance cost is <2% of total cost across all configs.
