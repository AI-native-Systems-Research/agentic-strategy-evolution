import networkx as nx


def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)

    for dst in dsts:
        path = nx.dijkstra_path(G, src, dst, weight="cost")
        for i in range(len(path) - 1):
            edge_data = G[path[i]][path[i + 1]]
            for partition_id in range(num_partitions):
                bc_topology.append_dst_partition_path(
                    dst, partition_id,
                    [path[i], path[i + 1], edge_data]
                )

    return bc_topology
