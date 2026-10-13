class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = """import networkx as nx
from collections import defaultdict
from itertools import combinations

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
        if path is None:
            return float('inf'), edges
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

    dsts_list = list(dsts)

    # Helper: build paths using relay assignment
    def build_relay_paths(relay_assignment):
        # relay_assignment: {dst: relay_node}
        candidate = {}
        for dst, relay in relay_assignment.items():
            if relay == src:
                if src in all_path and dst in all_path[src]:
                    candidate[dst] = all_path[src][dst]
                else:
                    return None
            else:
                src_to_relay = all_path.get(src, {}).get(relay)
                relay_to_dst = all_path.get(relay, {}).get(dst)
                if src_to_relay is None or relay_to_dst is None:
                    return None
                candidate[dst] = src_to_relay[:-1] + relay_to_dst
        return candidate

    # Approach 1: Individual shortest paths
    sp_paths = {}
    for dst in dsts:
        if src in all_path and dst in all_path[src]:
            sp_paths[dst] = all_path[src][dst]
    sp_cost, _ = compute_tree_edge_cost(sp_paths, G)
    best_cost = sp_cost
    best_paths = dict(sp_paths)

    # Approach 2: Minimum spanning arborescence on terminals
    terminals = [src] + dsts_list
    mc = nx.DiGraph()
    for t1 in terminals:
        for t2 in terminals:
            if t1 != t2 and t1 in all_dist and t2 in all_dist.get(t1, {}):
                mc.add_edge(t1, t2, weight=all_dist[t1][t2])
    try:
        arb = nx.minimum_spanning_arborescence(mc, attr='weight')
        children = defaultdict(list)
        for u, v in arb.edges():
            children[u].append(v)

        mst_paths = {}
        def build_arb_paths(node, prefix):
            for child in children[node]:
                if node in all_path and child in all_path[node]:
                    seg = all_path[node][child]
                    full = prefix[:-1] + seg
                    if child in dsts:
                        mst_paths[child] = full
                    build_arb_paths(child, full)

        build_arb_paths(src, [src])
        if all(d in mst_paths for d in dsts):
            mst_cost, _ = compute_tree_edge_cost(mst_paths, G)
            if mst_cost < best_cost:
                best_cost = mst_cost
                best_paths = mst_paths
    except:
        pass

    # Approach 3: Try MST with each non-terminal node added as extra terminal
    non_terminals = [n for n in G.nodes() if n not in set(terminals)]
    for extra in non_terminals:
        if extra not in all_dist:
            continue
        ext_terminals = terminals + [extra]
        mc2 = nx.DiGraph()
        for t1 in ext_terminals:
            for t2 in ext_terminals:
                if t1 != t2 and t1 in all_dist and t2 in all_dist.get(t1, {}):
                    mc2.add_edge(t1, t2, weight=all_dist[t1][t2])
        try:
            arb2 = nx.minimum_spanning_arborescence(mc2, attr='weight')
            ch2 = defaultdict(list)
            for u, v in arb2.edges():
                ch2[u].append(v)

            ext_paths = {}
            def build_ext(node, prefix):
                for child in ch2[node]:
                    if node in all_path and child in all_path[node]:
                        seg = all_path[node][child]
                        full = prefix[:-1] + seg
                        if child in dsts:
                            ext_paths[child] = full
                        build_ext(child, full)

            build_ext(src, [src])
            if all(d in ext_paths for d in dsts):
                ext_cost, _ = compute_tree_edge_cost(ext_paths, G)
                if ext_cost < best_cost:
                    best_cost = ext_cost
                    best_paths = ext_paths
        except:
            pass

    # Approach 4: Greedy Steiner tree
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
        if best_tnode == src:
            full_path = best_seg_path
        else:
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

    # Approach 5: Single relay (try ALL nodes)
    for relay in G.nodes():
        if relay not in all_dist.get(src, {}):
            continue
        if relay not in all_dist:
            continue
        if not all(d in all_dist[relay] for d in dsts):
            continue
        candidate = {}
        for dst in dsts:
            if relay == src:
                candidate[dst] = all_path[src][dst]
            else:
                candidate[dst] = all_path[src][relay][:-1] + all_path[relay][dst]
        cost, _ = compute_tree_edge_cost(candidate, G)
        if cost < best_cost:
            best_cost = cost
            best_paths = candidate

    # Approach 6: Two-relay split (try top relay candidates)
    # Rank nodes by cost from source
    relay_candidates = []
    for node in G.nodes():
        if node in all_dist.get(src, {}) and node in all_dist:
            if all(d in all_dist[node] for d in dsts):
                relay_candidates.append((all_dist[src][node], node))
    relay_candidates.sort()
    top_relays = [n for _, n in relay_candidates[:20]]

    for i in range(len(top_relays)):
        r1 = top_relays[i]
        for j in range(i+1, len(top_relays)):
            r2 = top_relays[j]
            # Assign each dst to the relay with lower total cost
            candidate = {}
            for dst in dsts:
                c1 = all_dist[src].get(r1, 0) + all_dist[r1].get(dst, float('inf'))
                c2 = all_dist[src].get(r2, 0) + all_dist[r2].get(dst, float('inf'))
                if c1 <= c2:
                    if r1 == src:
                        candidate[dst] = all_path[src][dst]
                    else:
                        candidate[dst] = all_path[src][r1][:-1] + all_path[r1][dst]
                else:
                    if r2 == src:
                        candidate[dst] = all_path[src][dst]
                    else:
                        candidate[dst] = all_path[src][r2][:-1] + all_path[r2][dst]

            cost, _ = compute_tree_edge_cost(candidate, G)
            if cost < best_cost:
                best_cost = cost
                best_paths = candidate

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
