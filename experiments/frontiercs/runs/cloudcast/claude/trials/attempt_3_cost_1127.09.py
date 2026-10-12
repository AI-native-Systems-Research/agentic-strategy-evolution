class Solution:
    def solve(self, spec_path=None):
        code = r'''
import networkx as nx
from collections import defaultdict
import itertools

class BroadCastTopology:
    def __init__(self, src, dsts, num_partitions):
        self.src = src
        self.dsts = dsts
        self.num_partitions = int(num_partitions)
        self.paths = {dst: {str(i): None for i in range(self.num_partitions)} for dst in dsts}

    def append_dst_partition_path(self, dst, partition, path):
        partition = str(partition)
        if self.paths[dst][partition] is None:
            self.paths[dst][partition] = []
        self.paths[dst][partition].append(path)

    def set_dst_partition_paths(self, dst, partition, paths):
        partition = str(partition)
        self.paths[dst][partition] = paths

    def set_num_partitions(self, num_partitions):
        self.num_partitions = num_partitions

def _provider(node):
    return node.split(":")[0] if ":" in node else ""

def _get_k_shortest(G, src, dst, k, weight="cost"):
    """Get k shortest simple paths by cost."""
    paths = []
    try:
        for p in nx.shortest_simple_paths(G, src, dst, weight=weight):
            paths.append(p)
            if len(paths) >= k:
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass
    return paths

def _path_cost(G, path):
    """Sum of edge costs along a path."""
    return sum(G[path[i]][path[i+1]].get("cost", 0) for i in range(len(path)-1))

def _path_min_throughput(G, path):
    """Min throughput along a path (bottleneck bandwidth)."""
    if len(path) < 2:
        return float('inf')
    return min(G[path[i]][path[i+1]].get("throughput", 1.0) for i in range(len(path)-1))

def _path_edges(path):
    """Return set of (u,v) edges in a path."""
    return set(zip(path[:-1], path[1:]))

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)

    # --- Phase 1: Build Steiner tree for shared routing ---
    steiner_nodes = {src}
    steiner_edges = set()
    steiner_dst_paths = {}
    remaining = list(dsts)

    # Greedy Steiner: add cheapest-to-reach destination iteratively
    while remaining:
        best_dst = None
        best_path = None
        best_cost = float('inf')

        for dst in remaining:
            for sn in list(steiner_nodes):
                try:
                    path = nx.dijkstra_path(G, sn, dst, weight="cost")
                    cost = sum(G[path[i]][path[i+1]]["cost"] for i in range(len(path)-1))
                    if cost < best_cost:
                        best_cost = cost
                        best_path = path
                        best_dst = dst
                except nx.NetworkXNoPath:
                    continue

        if best_dst is None:
            break

        remaining.remove(best_dst)
        for i in range(len(best_path) - 1):
            steiner_nodes.add(best_path[i])
            steiner_nodes.add(best_path[i+1])
            steiner_edges.add((best_path[i], best_path[i+1]))

        steiner_sub = nx.DiGraph()
        for u, v in steiner_edges:
            steiner_sub.add_edge(u, v, **G[u][v])
        try:
            steiner_path = nx.dijkstra_path(steiner_sub, src, best_dst, weight="cost")
            steiner_dst_paths[best_dst] = steiner_path
        except nx.NetworkXNoPath:
            try:
                steiner_dst_paths[best_dst] = nx.dijkstra_path(G, src, best_dst, weight="cost")
            except:
                pass

    # Fallback for missed destinations
    for dst in dsts:
        if dst not in steiner_dst_paths:
            try:
                steiner_dst_paths[dst] = nx.dijkstra_path(G, src, dst, weight="cost")
            except:
                pass

    # --- Phase 2: Find diverse alternative paths per destination ---
    K = min(num_partitions, 5)
    dst_candidate_paths = {}

    for dst in dsts:
        candidates = []
        # Always include Steiner tree path
        if dst in steiner_dst_paths:
            candidates.append(steiner_dst_paths[dst])

        # Get k-shortest paths
        k_paths = _get_k_shortest(G, src, dst, K * 3, weight="cost")
        for p in k_paths:
            if p not in candidates:
                candidates.append(p)
            if len(candidates) >= K:
                break

        # Also try throughput-optimized paths
        try:
            # Weight by inverse throughput to find high-bandwidth paths
            tp_path = nx.dijkstra_path(G, src, dst,
                weight=lambda u, v, d: 1.0 / max(d.get("throughput", 1.0), 0.01))
            if tp_path not in candidates:
                candidates.append(tp_path)
        except:
            pass

        dst_candidate_paths[dst] = candidates[:K]

    # --- Phase 3: Greedy partition assignment minimizing estimated total cost ---
    # Track edge load (number of partitions using each edge)
    edge_load = defaultdict(int)
    edge_throughput = {}
    for u, v, d in G.edges(data=True):
        edge_throughput[(u, v)] = d.get("throughput", 1.0)

    # For each partition, for each destination, choose the path that minimizes
    # incremental cost considering both egress and congestion
    partition_assignments = {}  # (dst, partition) -> path_index

    # Read spec values for cost computation
    # We don't have direct access to spec, so estimate from graph
    # instance cost = |V| * n_vm * (r_instance/3600) * t_transfer
    # where t_transfer = max over edges of (P_e * s_partition * 8 / flow_e)
    # Egress cost = sum over edges of (P_e * s_partition * c_e)
    # s_partition = data_vol / num_partitions (unknown, but proportional)

    # Since we can't know data_vol, we optimize the relative structure
    # Key insight: egress_cost ~ sum_e(P_e * c_e) and
    # instance_cost ~ |V| * max_e(P_e / throughput_e)
    # We want to minimize both

    for p in range(num_partitions):
        for dst in dsts:
            candidates = dst_candidate_paths.get(dst, [])
            if not candidates:
                continue

            best_idx = 0
            best_score = float('inf')

            for idx, path in enumerate(candidates):
                edges = _path_edges(path)
                # Incremental egress cost
                inc_egress = sum(G[u][v].get("cost", 0) for u, v in edges)

                # Max congestion after adding this partition
                max_congestion = 0
                for e in edges:
                    load = edge_load[e] + 1
                    thr = edge_throughput.get(e, 1.0)
                    congestion = load / max(thr, 0.01)
                    max_congestion = max(max_congestion, congestion)

                # Also consider global congestion from all edges
                global_max = max_congestion
                for e, load in edge_load.items():
                    if e not in edges:
                        thr = edge_throughput.get(e, 1.0)
                        congestion = load / max(thr, 0.01)
                        global_max = max(global_max, congestion)

                # Number of new nodes (contributes to instance cost)
                new_nodes = set()
                for u, v in edges:
                    new_nodes.add(u)
                    new_nodes.add(v)

                # Weighted objective: egress + congestion penalty
                # Tune the weight to balance egress vs congestion
                score = inc_egress + 0.5 * global_max + 0.01 * len(new_nodes)

                if score < best_score:
                    best_score = score
                    best_idx = idx

            path = candidates[best_idx]
            partition_assignments[(dst, p)] = path
            for e in _path_edges(path):
                edge_load[e] += 1

    # --- Phase 4: Build topology ---
    for dst in dsts:
        for p in range(num_partitions):
            path = partition_assignments.get((dst, p))
            if path is None:
                # Fallback
                if dst in steiner_dst_paths:
                    path = steiner_dst_paths[dst]
                else:
                    try:
                        path = nx.dijkstra_path(G, src, dst, weight="cost")
                    except:
                        continue

            edges = []
            for i in range(len(path) - 1):
                if G.has_edge(path[i], path[i+1]):
                    edges.append([path[i], path[i+1], G[path[i]][path[i+1]]])
            bc_topology.set_dst_partition_paths(dst, p, edges)

    return bc_topology
'''
        return {"code": code}
