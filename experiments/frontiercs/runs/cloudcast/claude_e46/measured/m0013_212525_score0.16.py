class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = """import networkx as nx
from collections import defaultdict, deque

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

    # Pre-compute all-pairs shortest paths
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

    terminals = [src] + list(dsts)

    # Approach 1: Individual shortest paths
    sp_paths = {}
    for dst in dsts:
        if src in all_path and dst in all_path[src]:
            sp_paths[dst] = all_path[src][dst]
    sp_cost, _ = compute_tree_edge_cost(sp_paths, G)

    best_cost = sp_cost
    best_paths = dict(sp_paths)

    # Approach 2: Metric closure MST → Steiner tree
    # Build complete graph on terminals
    mc = nx.DiGraph()
    for t1 in terminals:
        for t2 in terminals:
            if t1 != t2 and t1 in all_dist and t2 in all_dist[t1]:
                mc.add_edge(t1, t2, weight=all_dist[t1][t2])

    # Find minimum spanning arborescence rooted at src
    try:
        arb = nx.minimum_spanning_arborescence(mc, attr='weight')
        # Map arborescence edges back to actual paths
        mst_paths = {}
        # BFS from src on arborescence to build paths
        parent = {}
        for u, v in arb.edges():
            parent[v] = u

        for dst in dsts:
            # Walk from dst to src in arborescence
            chain = [dst]
            node = dst
            while node != src and node in parent:
                node = parent[node]
                chain.append(node)
            chain.reverse()

            if chain[0] != src:
                continue

            # Build actual path: for each arb edge (chain[i], chain[i+1]),
            # use shortest path in G
            full_path = [src]
            valid = True
            for i in range(len(chain) - 1):
                u, v = chain[i], chain[i+1]
                if u in all_path and v in all_path[u]:
                    segment = all_path[u][v]
                    full_path.extend(segment[1:])
                else:
                    valid = False
                    break

            if valid:
                mst_paths[dst] = full_path

        if all(d in mst_paths for d in dsts):
            mst_cost, _ = compute_tree_edge_cost(mst_paths, G)
            if mst_cost < best_cost:
                best_cost = mst_cost
                best_paths = mst_paths
    except:
        pass

    # Approach 3: Greedy Steiner tree with all-pairs distances
    tree_nodes = {src}
    tree_edges = set()
    steiner_paths = {}
    remaining = list(dsts)

    while remaining:
        best_dst = None
        best_marginal = float('inf')
        best_tnode = None
        best_seg_path = None

        for dst in remaining:
            for tnode in tree_nodes:
                if tnode not in all_dist or dst not in all_dist[tnode]:
                    continue
                path = all_path[tnode][dst]
                marginal = 0
                for i in range(len(path) - 1):
                    if (path[i], path[i+1]) not in tree_edges:
                        marginal += G[path[i]][path[i+1]]['cost']
                if marginal < best_marginal:
                    best_marginal = marginal
                    best_dst = dst
                    best_tnode = tnode
                    best_seg_path = path

        if best_dst is None:
            break

        remaining.remove(best_dst)

        # Build full path from src to dst
        if best_tnode == src:
            full_path = best_seg_path
        else:
            # Find path from src to tnode through existing tree
            # Reconstruct using parent pointers
            src_to_tnode = all_path[src].get(best_tnode)
            if src_to_tnode:
                full_path = src_to_tnode[:-1] + best_seg_path
            else:
                full_path = best_seg_path

        steiner_paths[best_dst] = full_path
        for i in range(len(best_seg_path) - 1):
            tree_edges.add((best_seg_path[i], best_seg_path[i+1]))
        for node in best_seg_path:
            tree_nodes.add(node)

    if all(d in steiner_paths for d in dsts):
        st_cost, _ = compute_tree_edge_cost(steiner_paths, G)
        if st_cost < best_cost:
            best_cost = st_cost
            best_paths = steiner_paths

    # Approach 4: Single relay hub (try ALL nodes)
    for relay in G.nodes():
        if src not in all_dist or relay not in all_dist.get(src, {}):
            continue
        if relay not in all_dist:
            continue
        if not all(d in all_dist[relay] for d in dsts):
            continue

        candidate = {}
        for dst in dsts:
            src_to_relay = all_path[src][relay]
            relay_to_dst = all_path[relay][dst]
            candidate[dst] = src_to_relay[:-1] + relay_to_dst

        cost, _ = compute_tree_edge_cost(candidate, G)
        if cost < best_cost:
            best_cost = cost
            best_paths = candidate

    # Approach 5: Two-relay split
    nodes_list = list(G.nodes())
    n = len(nodes_list)
    if n <= 80:
        for i in range(n):
            r1 = nodes_list[i]
            if src not in all_dist or r1 not in all_dist.get(src, {}):
                continue
            if r1 not in all_dist:
                continue
            for j in range(i+1, n):
                r2 = nodes_list[j]
                if r2 not in all_dist.get(src, {}):
                    continue
                if r2 not in all_dist:
                    continue

                candidate = {}
                valid = True
                for dst in dsts:
                    c1 = all_dist[r1].get(dst, float('inf'))
                    c2 = all_dist[r2].get(dst, float('inf'))
                    if c1 == float('inf') and c2 == float('inf'):
                        valid = False
                        break
                    if c1 <= c2:
                        candidate[dst] = all_path[src][r1][:-1] + all_path[r1][dst]
                    else:
                        candidate[dst] = all_path[src][r2][:-1] + all_path[r2][dst]

                if not valid:
                    continue

                cost, _ = compute_tree_edge_cost(candidate, G)
                if cost < best_cost:
                    best_cost = cost
                    best_paths = candidate

    # Approach 6: Chain routing via MST on destinations
    # Route: src -> dst_a -> dst_b -> ... using shortest inter-destination paths
    # This can share many edges
    try:
        dst_graph = nx.DiGraph()
        for d1 in dsts:
            if d1 in all_dist:
                for d2 in dsts:
                    if d1 != d2 and d2 in all_dist[d1]:
                        dst_graph.add_edge(d1, d2, weight=all_dist[d1][d2])
            if src in all_dist and d1 in all_dist[src]:
                dst_graph.add_edge(src, d1, weight=all_dist[src][d1])

        if src in dst_graph and all(d in dst_graph for d in dsts):
            arb = nx.minimum_spanning_arborescence(dst_graph, attr='weight')
            chain_paths = {}
            # BFS to build full paths from src
            children = defaultdict(list)
            for u, v in arb.edges():
                children[u].append(v)

            def build_paths(node, prefix):
                for child in children[node]:
                    if node in all_path and child in all_path[node]:
                        seg = all_path[node][child]
                        full = prefix[:-1] + seg if len(prefix) > 0 else seg
                        chain_paths[child] = full
                        build_paths(child, full)

            build_paths(src, [src])

            if all(d in chain_paths for d in dsts):
                ch_cost, _ = compute_tree_edge_cost(chain_paths, G)
                if ch_cost < best_cost:
                    best_cost = ch_cost
                    best_paths = chain_paths
    except:
        pass

    # Route all partitions along best paths
    for dst in dsts:
        path = best_paths.get(dst)
        if path is None:
            if src in all_path and dst in all_path[src]:
                path = all_path[src][dst]
            else:
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
