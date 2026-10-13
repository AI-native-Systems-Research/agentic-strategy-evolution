class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = """import networkx as nx
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

def compute_tree_edge_cost(paths, G):
    edges = set()
    for dst, path in paths.items():
        for i in range(len(path) - 1):
            edges.add((path[i], path[i+1]))
    return sum(G[u][v]['cost'] for u, v in edges), edges

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)

    # Pre-compute all-pairs shortest paths (nodes are ~20-50)
    all_dist = {}
    all_path = {}
    for node in G.nodes():
        try:
            d = dict(nx.single_source_dijkstra_path_length(G, node, weight='cost'))
            p = dict(nx.single_source_dijkstra_path(G, node, weight='cost'))
            all_dist[node] = d
            all_path[node] = p
        except:
            pass

    # Approach 1: Individual shortest paths
    sp_paths = {}
    for dst in dsts:
        if src in all_path and dst in all_path[src]:
            sp_paths[dst] = all_path[src][dst]
    sp_cost, sp_edges = compute_tree_edge_cost(sp_paths, G)

    best_cost = sp_cost
    best_paths = sp_paths

    # Approach 2: Try each node as relay hub
    # src -> relay (shortest) then relay -> dst_i (shortest)
    for relay in G.nodes():
        if src not in all_dist or relay not in all_dist.get(src, {}):
            continue
        if relay not in all_dist:
            continue

        relay_dist = all_dist[relay]
        relay_paths = all_path[relay]

        if not all(d in relay_dist for d in dsts):
            continue

        candidate_paths = {}
        for dst in dsts:
            src_to_relay = all_path[src][relay]
            relay_to_dst = relay_paths[dst]
            full = src_to_relay[:-1] + relay_to_dst
            candidate_paths[dst] = full

        cost, _ = compute_tree_edge_cost(candidate_paths, G)
        if cost < best_cost:
            best_cost = cost
            best_paths = candidate_paths

    # Approach 3: Greedy Steiner tree
    # Start with src, greedily add closest destination (by marginal cost)
    tree_nodes = {src}
    tree_edges = set()
    steiner_paths = {}
    remaining = set(dsts)

    while remaining:
        best_dst = None
        best_marginal = float('inf')
        best_path = None

        for dst in remaining:
            for tnode in tree_nodes:
                if tnode not in all_path or dst not in all_path[tnode]:
                    continue
                path = all_path[tnode][dst]
                marginal = 0
                for i in range(len(path) - 1):
                    if (path[i], path[i+1]) not in tree_edges:
                        marginal += G[path[i]][path[i+1]]['cost']
                if marginal < best_marginal:
                    best_marginal = marginal
                    best_dst = dst
                    best_path = (tnode, path)

        if best_dst is None:
            break

        tnode, path = best_path
        remaining.remove(best_dst)

        # Build full path from src through tree to tnode, then to dst
        if tnode == src:
            full_path = path
        else:
            # Find path from src to tnode via tree edges
            # Use BFS on tree edges
            src_to_tnode = all_path[src].get(tnode, [src, tnode])
            full_path = src_to_tnode[:-1] + path

        steiner_paths[best_dst] = full_path
        for i in range(len(path) - 1):
            tree_edges.add((path[i], path[i+1]))
        for node in path:
            tree_nodes.add(node)

    if all(d in steiner_paths for d in dsts):
        st_cost, _ = compute_tree_edge_cost(steiner_paths, G)
        if st_cost < best_cost:
            best_cost = st_cost
            best_paths = steiner_paths

    # Approach 4: Two-relay approach
    # Try pairs of relays for better tree structure
    nodes_list = list(G.nodes())
    if len(nodes_list) <= 100:
        for r1 in nodes_list:
            if src not in all_dist or r1 not in all_dist.get(src, {}):
                continue
            if r1 not in all_dist:
                continue
            r1_dist = all_dist[r1]
            r1_path_map = all_path[r1]
            for r2 in nodes_list:
                if r2 not in r1_dist or r2 not in all_dist:
                    continue
                r2_dist = all_dist[r2]
                r2_path_map = all_path[r2]

                # Try: half dsts via r1, half via r2
                # Split dsts by which relay is cheaper
                candidate_paths = {}
                valid = True
                for dst in dsts:
                    # Cost via r1
                    c1 = r1_dist.get(dst, float('inf'))
                    # Cost via r2
                    c2 = r2_dist.get(dst, float('inf'))

                    if c1 <= c2 and dst in r1_path_map:
                        src_to_r1 = all_path[src][r1]
                        r1_to_dst = r1_path_map[dst]
                        candidate_paths[dst] = src_to_r1[:-1] + r1_to_dst
                    elif dst in r2_path_map:
                        src_to_r2 = all_path[src][r2]
                        r2_to_dst = r2_path_map[dst]
                        candidate_paths[dst] = src_to_r2[:-1] + r2_to_dst
                    elif dst in r1_path_map:
                        src_to_r1 = all_path[src][r1]
                        r1_to_dst = r1_path_map[dst]
                        candidate_paths[dst] = src_to_r1[:-1] + r1_to_dst
                    else:
                        valid = False
                        break

                if not valid:
                    continue

                cost, _ = compute_tree_edge_cost(candidate_paths, G)
                if cost < best_cost:
                    best_cost = cost
                    best_paths = candidate_paths

    # Route all partitions along best paths
    for dst in dsts:
        path = best_paths.get(dst)
        if path is None:
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
