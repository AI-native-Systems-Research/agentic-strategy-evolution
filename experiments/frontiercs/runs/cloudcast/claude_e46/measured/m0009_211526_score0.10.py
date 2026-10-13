class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = """import networkx as nx

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

    # Try different alpha values for combined weight: cost + alpha / throughput
    # This balances egress cost vs transfer time (which drives instance cost)
    best_alpha = 0
    best_cost_estimate = float('inf')

    for alpha in [0, 0.01, 0.1, 1.0, 10.0]:
        # Set combined weights
        for u, v, data in G.edges(data=True):
            data['_w'] = data['cost'] + alpha / max(data['throughput'], 0.001)

        total_path_cost = 0
        min_throughput = float('inf')
        for dst in dsts:
            try:
                path = nx.dijkstra_path(G, src, dst, weight='_w')
                for i in range(len(path) - 1):
                    ed = G[path[i]][path[i+1]]
                    total_path_cost += ed['cost']
                    min_throughput = min(min_throughput, ed['throughput'])
            except nx.NetworkXNoPath:
                total_path_cost = float('inf')
                break

        if min_throughput <= 0:
            continue

        # Rough cost estimate: egress + instance
        # egress ~ num_partitions * partition_size * total_edge_cost
        # instance ~ transfer_time * num_nodes * rate
        # transfer_time ~ num_partitions * partition_size * 8 / min_throughput
        estimate = total_path_cost + alpha  # simplified proxy
        if total_path_cost < best_cost_estimate:
            best_cost_estimate = total_path_cost
            best_alpha = alpha

    # Use best alpha
    for u, v, data in G.edges(data=True):
        data['_w'] = data['cost'] + best_alpha / max(data['throughput'], 0.001)

    for dst in dsts:
        try:
            path = nx.dijkstra_path(G, src, dst, weight='_w')
        except nx.NetworkXNoPath:
            continue
        for i in range(len(path) - 1):
            edge_data = G[path[i]][path[i + 1]]
            for partition_id in range(num_partitions):
                bc_topology.append_dst_partition_path(
                    dst, partition_id,
                    [path[i], path[i + 1], edge_data])

    return bc_topology
"""
        return {"code": code}
