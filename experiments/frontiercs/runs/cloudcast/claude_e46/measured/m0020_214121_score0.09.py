class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = """import networkx as nx
from itertools import islice
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

    for dst in dsts:
        # Find 2 shortest paths
        try:
            paths = list(islice(nx.shortest_simple_paths(G, src, dst, weight='cost'), 2))
        except:
            paths = []
        if not paths:
            try:
                paths = [nx.dijkstra_path(G, src, dst, weight='cost')]
            except:
                continue

        for partition_id in range(num_partitions):
            # Spread: even partitions on path 0, odd on path 1
            if len(paths) >= 2:
                path = paths[partition_id % 2]
            else:
                path = paths[0]
            for i in range(len(path) - 1):
                edge_data = G[path[i]][path[i + 1]]
                bc_topology.append_dst_partition_path(
                    dst, partition_id,
                    [path[i], path[i + 1], edge_data])

    return bc_topology
"""
        return {"code": code}
