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

    # Precompute shortest paths from src to all reachable nodes
    try:
        src_lengths, src_paths = nx.single_source_dijkstra(G, src, weight="cost")
    except:
        src_lengths, src_paths = {}, {}

    # Also precompute shortest paths from all nodes to help with Steiner
    # (reverse graph for "to any node" queries)
    G_rev = G.reverse()

    # For each destination, get the direct shortest path
    direct_paths = {}
    for dst in dsts:
        if dst in src_paths:
            direct_paths[dst] = src_paths[dst]

    # --- Greedy Steiner tree (rooted at src) ---
    # Maintain a set of "reachable" nodes (nodes already in the Steiner tree)
    # At each step, add the destination whose connection to the tree is cheapest

    # Precompute: from every node in graph, shortest path cost to each dst
    # This is expensive for large graphs, so instead we compute on-demand

    steiner_nodes = {src}
    steiner_edges = set()
    steiner_dst_paths = {}
    remaining = list(d for d in dsts if d in direct_paths)

    # Precompute from each potential intermediate node
    # Instead: compute from each node already in tree to remaining dsts
    # Use incremental approach

    # Cache: shortest path from node to dst through original graph
    # Start with src's shortest paths
    node_to_dst_cost = {}
    node_to_dst_path = {}
    for dst in remaining:
        if dst in src_lengths:
            node_to_dst_cost[(src, dst)] = src_lengths[dst]
            node_to_dst_path[(src, dst)] = src_paths[dst]

    while remaining:
        best_dst = None
        best_path = None
        best_cost = float('inf')
        best_connector = None

        for dst in remaining:
            for sn in list(steiner_nodes):
                key = (sn, dst)
                if key not in node_to_dst_cost:
                    try:
                        length, path = nx.single_source_dijkstra(G, sn, target=dst, weight="cost")
                        node_to_dst_cost[key] = length
                        node_to_dst_path[key] = path
                    except:
                        node_to_dst_cost[key] = float('inf')
                        node_to_dst_path[key] = None

                cost = node_to_dst_cost[key]
                if cost < best_cost:
                    best_cost = cost
                    best_path = node_to_dst_path[key]
                    best_dst = dst
                    best_connector = sn

        if best_dst is None or best_path is None:
            break

        remaining.remove(best_dst)

        # Add edges of best_path to Steiner tree
        new_nodes = set()
        for i in range(len(best_path) - 1):
            steiner_edges.add((best_path[i], best_path[i+1]))
            new_nodes.add(best_path[i])
            new_nodes.add(best_path[i+1])
        steiner_nodes.update(new_nodes)

        # For new nodes added, precompute their distances to remaining dsts
        for new_node in new_nodes:
            if new_node == src:
                continue
            for dst in remaining:
                key = (new_node, dst)
                if key not in node_to_dst_cost:
                    try:
                        length, path = nx.single_source_dijkstra(G, new_node, target=dst, weight="cost")
                        node_to_dst_cost[key] = length
                        node_to_dst_path[key] = path
                    except:
                        node_to_dst_cost[key] = float('inf')
                        node_to_dst_path[key] = None

    # Build Steiner subgraph and find paths from src to each dst
    steiner_sub = nx.DiGraph()
    for u, v in steiner_edges:
        steiner_sub.add_edge(u, v, **G[u][v])

    for dst in dsts:
        if dst not in direct_paths:
            continue
        try:
            path = nx.dijkstra_path(steiner_sub, src, dst, weight="cost")
            steiner_dst_paths[dst] = path
        except nx.NetworkXNoPath:
            steiner_dst_paths[dst] = direct_paths[dst]

    # --- Try to improve: for each dst, check if direct path is cheaper ---
    # Compare per-destination: Steiner path cost vs direct path cost
    # But also account for shared edges
    final_paths = {}
    for dst in dsts:
        steiner_path = steiner_dst_paths.get(dst)
        direct_path = direct_paths.get(dst)

        if steiner_path is None and direct_path is not None:
            final_paths[dst] = direct_path
        elif steiner_path is not None and direct_path is None:
            final_paths[dst] = steiner_path
        elif steiner_path is not None and direct_path is not None:
            # Use Steiner by default (it shares edges with other dsts)
            final_paths[dst] = steiner_path
        # else: no path available

    # --- Build topology: all partitions use the same path per dst ---
    for dst in dsts:
        path = final_paths.get(dst)
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
