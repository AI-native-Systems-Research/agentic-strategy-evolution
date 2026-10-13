class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = (
            "import networkx as nx\n"
            "\n"
            "def search_algorithm(src, dsts, G, num_partitions):\n"
            "    bc_topology = BroadCastTopology(src, dsts, num_partitions)\n"
            "    for dst in dsts:\n"
            "        path = nx.dijkstra_path(G, src, dst, weight='cost')\n"
            "        for i in range(len(path) - 1):\n"
            "            edge_data = G[path[i]][path[i + 1]]\n"
            "            for partition_id in range(num_partitions):\n"
            "                bc_topology.append_dst_partition_path(\n"
            "                    dst, partition_id,\n"
            "                    [path[i], path[i + 1], edge_data])\n"
            "    return bc_topology\n"
        )
        return {"code": code}
