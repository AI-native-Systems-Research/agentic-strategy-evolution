class Solution:
    def solve(self, spec_path=None):
        code = r'''
import networkx as nx
from collections import defaultdict

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

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)

    # --- Approach: Improved Steiner tree with edge sharing ---
    # Build distance metric for Steiner construction
    # For each destination, compute shortest path from src
    direct_paths = {}
    direct_costs = {}
    for dst in dsts:
        try:
            path = nx.dijkstra_path(G, src, dst, weight="cost")
            cost = sum(G[path[i]][path[i+1]]["cost"] for i in range(len(path)-1))
            direct_paths[dst] = path
            direct_costs[dst] = cost
        except nx.NetworkXNoPath:
            continue

    # Steiner tree via metric closure approach:
    # 1. Build metric closure graph on terminals (src + dsts)
    # 2. Find MST on metric closure
    # 3. Map MST edges back to actual shortest paths
    terminals = [src] + [d for d in dsts if d in direct_paths]

    # Compute all-pairs shortest paths between terminals
    terminal_dist = {}
    terminal_paths = {}
    for t in terminals:
        try:
            lengths, paths = nx.single_source_dijkstra(G, t, weight="cost")
            for t2 in terminals:
                if t2 != t and t2 in lengths:
                    terminal_dist[(t, t2)] = lengths[t2]
                    terminal_paths[(t, t2)] = paths[t2]
        except:
            pass

    # Build metric closure graph
    mc = nx.Graph()
    for (t1, t2), cost in terminal_dist.items():
        if mc.has_edge(t1, t2):
            if mc[t1][t2]["weight"] > cost:
                mc[t1][t2]["weight"] = cost
        else:
            mc.add_edge(t1, t2, weight=cost)

    # Find MST of metric closure
    try:
        mst = nx.minimum_spanning_tree(mc, weight="weight")
    except:
        mst = mc

    # Extract actual paths from MST edges, build Steiner subgraph
    steiner_edges = set()
    for u, v in mst.edges():
        path = terminal_paths.get((u, v)) or terminal_paths.get((v, u))
        if path:
            for i in range(len(path) - 1):
                steiner_edges.add((path[i], path[i+1]))

    # Build Steiner subgraph
    steiner_sub = nx.DiGraph()
    for u, v in steiner_edges:
        if G.has_edge(u, v):
            steiner_sub.add_edge(u, v, **G[u][v])

    # Find paths in Steiner subgraph from src to each destination
    steiner_dst_paths = {}
    for dst in dsts:
        if dst not in direct_paths:
            continue
        try:
            path = nx.dijkstra_path(steiner_sub, src, dst, weight="cost")
            steiner_dst_paths[dst] = path
        except nx.NetworkXNoPath:
            steiner_dst_paths[dst] = direct_paths[dst]

    # --- Compare Steiner tree paths vs direct paths ---
    # Use whichever gives lower total cost per destination
    # But Steiner tree shares edges, so we need global comparison

    # Option A: All Steiner tree paths
    steiner_all_edges = set()
    steiner_all_nodes = set()
    steiner_egress = 0
    for dst in dsts:
        path = steiner_dst_paths.get(dst, direct_paths.get(dst))
        if path:
            for i in range(len(path) - 1):
                e = (path[i], path[i+1])
                steiner_all_edges.add(e)
                steiner_all_nodes.add(path[i])
                steiner_all_nodes.add(path[i+1])
    for u, v in steiner_all_edges:
        steiner_egress += G[u][v].get("cost", 0)

    # Option B: All direct shortest paths
    direct_all_edges = set()
    direct_all_nodes = set()
    direct_egress = 0
    for dst in dsts:
        path = direct_paths.get(dst)
        if path:
            for i in range(len(path) - 1):
                e = (path[i], path[i+1])
                direct_all_edges.add(e)
                direct_all_nodes.add(path[i])
                direct_all_nodes.add(path[i+1])
    for u, v in direct_all_edges:
        direct_egress += G[u][v].get("cost", 0)

    # Instance cost is proportional to |V|, egress proportional to sum(c_e * num_partitions)
    # Each edge carries num_partitions when all partitions use same tree
    # Choose the one with lower estimated total
    # total ~ num_partitions * sum(c_e) * s_partition + |V| * 2 * 0.54/3600 * t_transfer
    # t_transfer ~ max_e(num_partitions * s_partition * 8 / throughput_e)
    # For comparison: egress dominates when data is large, instance dominates when network is big

    # Simple heuristic: compare (egress_sum * num_partitions + node_count * congestion_proxy)
    def estimate_cost(all_edges, all_nodes, paths_map):
        total_egress_per_part = sum(G[u][v].get("cost", 0) for u, v in all_edges)
        max_congestion = 0
        for u, v in all_edges:
            thr = G[u][v].get("throughput", 1.0)
            congestion = num_partitions / max(thr, 0.01)
            max_congestion = max(max_congestion, congestion)
        return total_egress_per_part * num_partitions + len(all_nodes) * max_congestion * 0.1

    steiner_est = estimate_cost(steiner_all_edges, steiner_all_nodes, steiner_dst_paths)
    direct_est = estimate_cost(direct_all_edges, direct_all_nodes, direct_paths)

    if steiner_est <= direct_est:
        chosen_paths = steiner_dst_paths
    else:
        chosen_paths = direct_paths

    # Ensure we have paths for all destinations
    for dst in dsts:
        if dst not in chosen_paths:
            if dst in direct_paths:
                chosen_paths[dst] = direct_paths[dst]
            elif dst in steiner_dst_paths:
                chosen_paths[dst] = steiner_dst_paths[dst]

    # --- Assign all partitions to the chosen paths ---
    for dst in dsts:
        path = chosen_paths.get(dst)
        if path is None:
            continue
        edges = []
        for i in range(len(path) - 1):
            if G.has_edge(path[i], path[i+1]):
                edges.append([path[i], path[i+1], G[path[i]][path[i+1]]])
        for p in range(num_partitions):
            bc_topology.set_dst_partition_paths(dst, p, list(edges))

    return bc_topology
'''
        return {"code": code}
