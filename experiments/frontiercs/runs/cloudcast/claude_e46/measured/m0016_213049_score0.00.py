class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = """import networkx as nx
import heapq
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
        if path is None:
            return float('inf'), edges
        for i in range(len(path) - 1):
            edges.add((path[i], path[i+1]))
    return sum(G[u][v]['cost'] for u, v in edges), edges

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)
    dsts_list = list(dsts)
    n_dsts = len(dsts_list)
    nodes = list(G.nodes())
    n_nodes = len(nodes)
    node_idx = {n: i for i, n in enumerate(nodes)}
    INF = float('inf')

    # Pre-compute all-pairs shortest paths and path costs
    all_dist = {}
    all_path = {}
    for node in nodes:
        try:
            d = dict(nx.single_source_dijkstra_path_length(G, node, weight='cost'))
            p = dict(nx.single_source_dijkstra_path(G, node, weight='cost'))
            all_dist[node] = d
            all_path[node] = p
        except:
            pass

    # Build adjacency list for reverse graph (for extension phase)
    # In original G: edge (u, v) with cost w
    # For extension: dp[S][u] can be improved to dp[S][v] + w(u, v)
    # i.e., for predecessor u of v: dp[S][u] = min(dp[S][u], dp[S][v] + w(u, v))
    predecessors = defaultdict(list)  # predecessors[v_idx] = [(u_idx, w(u,v))]
    for u, v, data in G.edges(data=True):
        if u in node_idx and v in node_idx:
            predecessors[node_idx[v]].append((node_idx[u], data['cost']))

    # Dreyfus-Wagner exact Steiner tree
    if n_dsts <= 14:
        # dp[mask][node_idx] = min cost Steiner tree rooted at node reaching terminals in mask
        full_mask = (1 << n_dsts) - 1
        dp = [[INF] * n_nodes for _ in range(1 << n_dsts)]
        parent = [[None] * n_nodes for _ in range(1 << n_dsts)]
        # parent[mask][v] = either ('split', mask1) or ('edge', u_idx) for backtracking

        # Base case: single destination subsets
        for i, d in enumerate(dsts_list):
            mask = 1 << i
            di = node_idx.get(d)
            if di is not None:
                dp[mask][di] = 0
            # Extension phase for single-destination masks
            # Use Dijkstra to propagate dp[mask] backwards
            pq = []
            for vi in range(n_nodes):
                v = nodes[vi]
                if v in all_dist and d in all_dist[v]:
                    dp[mask][vi] = all_dist[v][d]
                    heapq.heappush(pq, (dp[mask][vi], vi))

            visited = [False] * n_nodes
            while pq:
                cost, vi = heapq.heappop(pq)
                if visited[vi]:
                    continue
                visited[vi] = True
                # For each predecessor u of v in G
                for ui, w_uv in predecessors[vi]:
                    new_cost = cost + w_uv
                    if new_cost < dp[mask][ui]:
                        dp[mask][ui] = new_cost
                        parent[mask][ui] = ('edge', vi)
                        heapq.heappush(pq, (new_cost, ui))

        # Process subsets of increasing size
        for size in range(2, n_dsts + 1):
            for mask in range(1, 1 << n_dsts):
                if bin(mask).count('1') != size:
                    continue

                # Phase 1: Split
                # Enumerate subsets using the "subset enumeration" trick
                sub = (mask - 1) & mask
                while sub > 0:
                    comp = mask ^ sub
                    if sub < comp:  # avoid counting each split twice
                        for vi in range(n_nodes):
                            val = dp[sub][vi] + dp[comp][vi]
                            if val < dp[mask][vi]:
                                dp[mask][vi] = val
                                parent[mask][vi] = ('split', sub)
                    sub = (sub - 1) & mask

                # Phase 2: Extension (Dijkstra on reverse graph)
                pq = []
                for vi in range(n_nodes):
                    if dp[mask][vi] < INF:
                        heapq.heappush(pq, (dp[mask][vi], vi))

                visited = [False] * n_nodes
                while pq:
                    cost, vi = heapq.heappop(pq)
                    if visited[vi]:
                        continue
                    visited[vi] = True
                    for ui, w_uv in predecessors[vi]:
                        new_cost = cost + w_uv
                        if new_cost < dp[mask][ui]:
                            dp[mask][ui] = new_cost
                            parent[mask][ui] = ('edge', vi)
                            heapq.heappush(pq, (new_cost, ui))

        # Extract optimal tree from DP
        src_idx = node_idx.get(src)
        if src_idx is not None and dp[full_mask][src_idx] < INF:
            # Backtrack to find the tree structure
            tree_edges = set()

            def extract_tree(mask, vi):
                if mask == 0:
                    return
                p = parent[mask][vi]
                if p is None:
                    return
                if p[0] == 'split':
                    sub = p[1]
                    comp = mask ^ sub
                    extract_tree(sub, vi)
                    extract_tree(comp, vi)
                elif p[0] == 'edge':
                    next_vi = p[1]
                    tree_edges.add((nodes[vi], nodes[next_vi]))
                    extract_tree(mask, next_vi)

            extract_tree(full_mask, src_idx)

            # Build paths from src to each destination through tree edges
            tree_graph = nx.DiGraph()
            for u, v in tree_edges:
                tree_graph.add_edge(u, v, cost=G[u][v]['cost'])

            dw_paths = {}
            for dst in dsts_list:
                try:
                    path = nx.shortest_path(tree_graph, src, dst)
                    dw_paths[dst] = path
                except nx.NetworkXNoPath:
                    pass

            if all(d in dw_paths for d in dsts_list):
                dw_cost, _ = compute_tree_edge_cost(dw_paths, G)
            else:
                dw_cost = INF
                dw_paths = None
        else:
            dw_cost = INF
            dw_paths = None
    else:
        dw_cost = INF
        dw_paths = None

    # Heuristic approaches as fallback

    # Approach H1: Individual shortest paths
    sp_paths = {}
    for dst in dsts_list:
        if src in all_path and dst in all_path[src]:
            sp_paths[dst] = all_path[src][dst]
    sp_cost, _ = compute_tree_edge_cost(sp_paths, G)

    # Approach H2: MST arborescence on terminals
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
        def build_arb(node, prefix):
            for child in children[node]:
                if node in all_path and child in all_path[node]:
                    seg = all_path[node][child]
                    full = prefix[:-1] + seg
                    if child in dsts:
                        mst_paths[child] = full
                    build_arb(child, full)
        build_arb(src, [src])
        mst_cost = compute_tree_edge_cost(mst_paths, G)[0] if all(d in mst_paths for d in dsts_list) else INF
    except:
        mst_cost = INF
        mst_paths = {}

    # Approach H3: Greedy Steiner
    tree_nodes_set = {src}
    tree_edge_set = set()
    greedy_paths = {}
    remaining = list(dsts_list)
    while remaining:
        best_dst = None
        best_marginal = INF
        best_tnode = None
        best_seg = None
        for dst in remaining:
            for tnode in tree_nodes_set:
                if tnode not in all_dist or dst not in all_dist[tnode]:
                    continue
                path = all_path[tnode][dst]
                marginal = sum(G[path[i]][path[i+1]]['cost'] for i in range(len(path)-1) if (path[i], path[i+1]) not in tree_edge_set)
                if marginal < best_marginal:
                    best_marginal = marginal
                    best_dst = dst
                    best_tnode = tnode
                    best_seg = path
        if best_dst is None:
            break
        remaining.remove(best_dst)
        full = best_seg if best_tnode == src else (all_path[src].get(best_tnode, [best_tnode])[:-1] + best_seg)
        greedy_paths[best_dst] = full
        for i in range(len(best_seg) - 1):
            tree_edge_set.add((best_seg[i], best_seg[i+1]))
        tree_nodes_set.update(best_seg)
    greedy_cost = compute_tree_edge_cost(greedy_paths, G)[0] if all(d in greedy_paths for d in dsts_list) else INF

    # Approach H4: Single relay
    single_relay_cost = INF
    single_relay_paths = None
    for relay in nodes:
        if relay not in all_dist.get(src, {}):
            continue
        if relay not in all_dist:
            continue
        if not all(d in all_dist[relay] for d in dsts_list):
            continue
        cand = {}
        for dst in dsts_list:
            cand[dst] = all_path[src][relay][:-1] + all_path[relay][dst] if relay != src else all_path[src][dst]
        c, _ = compute_tree_edge_cost(cand, G)
        if c < single_relay_cost:
            single_relay_cost = c
            single_relay_paths = cand

    # Pick the best approach
    best_cost = sp_cost
    best_paths = sp_paths

    for cost, paths in [(mst_cost, mst_paths), (greedy_cost, greedy_paths),
                         (single_relay_cost, single_relay_paths),
                         (dw_cost, dw_paths)]:
        if paths and cost < best_cost:
            best_cost = cost
            best_paths = paths

    # Route all partitions
    for dst in dsts_list:
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
