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

    # Build a Steiner tree approximation using shortest-path cost
    # Step 1: Find shortest cost paths from src to all destinations
    dst_paths = {}
    for dst in dsts:
        try:
            path = nx.dijkstra_path(G, src, dst, weight="cost")
            dst_paths[dst] = path
        except nx.NetworkXNoPath:
            continue

    # Step 2: Build Steiner tree by iteratively adding cheapest destination
    # Start from src, greedily add nearest unconnected destination
    steiner_nodes = {src}
    steiner_edges = set()
    remaining = list(dsts)
    steiner_dst_paths = {}

    # Compute all-pairs shortest paths from steiner nodes to remaining dests
    while remaining:
        best_dst = None
        best_path = None
        best_cost = float('inf')

        for dst in remaining:
            # Find cheapest path from any steiner node to this dst
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

        # Record the full path from src through the Steiner tree to this dst
        # We need path from src to dst through the Steiner tree
        # Build subgraph of steiner edges and find path
        steiner_sub = nx.DiGraph()
        for u, v in steiner_edges:
            steiner_sub.add_edge(u, v, **G[u][v])
        try:
            steiner_path = nx.dijkstra_path(steiner_sub, src, best_dst, weight="cost")
            steiner_dst_paths[best_dst] = steiner_path
        except nx.NetworkXNoPath:
            # Fallback to direct shortest path
            steiner_dst_paths[best_dst] = dst_paths.get(best_dst, [src, best_dst])

    # For any destination not in steiner tree, use direct shortest path
    for dst in dsts:
        if dst not in steiner_dst_paths:
            if dst in dst_paths:
                steiner_dst_paths[dst] = dst_paths[dst]

    # Step 3: Assign all partitions to the Steiner tree paths
    for dst in dsts:
        if dst not in steiner_dst_paths:
            continue
        path = steiner_dst_paths[dst]
        edges = []
        for i in range(len(path) - 1):
            if G.has_edge(path[i], path[i+1]):
                edges.append([path[i], path[i+1], G[path[i]][path[i+1]]])
        for p in range(num_partitions):
            bc_topology.set_dst_partition_paths(dst, p, list(edges))

    return bc_topology
'''
        return {"code": code}
