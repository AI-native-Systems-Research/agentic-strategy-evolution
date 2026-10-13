class Solution:
    def solve(self, spec_path: str = None) -> dict:
        # Read spec to understand configurations
        config_info = ""
        if spec_path:
            try:
                import json
                with open(spec_path) as f:
                    spec = json.load(f)
                config_info = json.dumps(spec)
            except:
                pass

        code = """import networkx as nx
import heapq
import json
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

CONFIG_INFO = '''""" + config_info + """'''

def compute_tree_edge_cost(paths, G):
    edges = set()
    for dst, path in paths.items():
        if path is None:
            return float('inf'), edges
        for i in range(len(path) - 1):
            edges.add((path[i], path[i+1]))
    return sum(G[u][v]['cost'] for u, v in edges), edges

def get_provider(node):
    return node.split(':')[0]

def estimate_transfer_time(paths, G, num_partitions, num_vms=2):
    # Count edges per node (in/out)
    node_out_edges = defaultdict(set)
    node_in_edges = defaultdict(set)
    edge_partitions = defaultdict(int)

    for dst, path in paths.items():
        if path is None:
            continue
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            node_out_edges[u].add((u, v))
            node_in_edges[v].add((u, v))
            edge_partitions[(u, v)] = num_partitions  # all partitions

    egress_limits = {'aws': 5, 'gcp': 7, 'azure': 16}
    ingress_limits = {'aws': 10, 'gcp': 16, 'azure': 16}

    max_time = 0
    partition_size_gb = 30  # assume default
    for (u, v), n_parts in edge_partitions.items():
        edge_thr = G[u][v].get('throughput', 1.0)

        u_prov = get_provider(u)
        u_egress = egress_limits.get(u_prov, 5) * num_vms
        n_out = len(node_out_edges[u])
        u_flow = u_egress / max(n_out, 1)

        v_prov = get_provider(v)
        v_ingress = ingress_limits.get(v_prov, 10) * num_vms
        n_in = len(node_in_edges[v])
        v_flow = v_ingress / max(n_in, 1)

        flow = min(edge_thr, u_flow, v_flow)
        if flow <= 0:
            flow = 0.001
        t = n_parts * partition_size_gb * 8 / flow
        max_time = max(max_time, t)

    return max_time

def dreyfus_wagner(src, dsts_list, G, nodes, node_idx):
    n_dsts = len(dsts_list)
    n_nodes = len(nodes)
    INF = float('inf')
    full_mask = (1 << n_dsts) - 1
    src_idx = node_idx[src]

    predecessors = defaultdict(list)
    for u, v, data in G.edges(data=True):
        if u in node_idx and v in node_idx:
            predecessors[node_idx[v]].append((node_idx[u], data['cost']))

    dp = [[INF] * n_nodes for _ in range(1 << n_dsts)]
    parent = [[None] * n_nodes for _ in range(1 << n_dsts)]

    def dijkstra_extend(mask):
        pq = []
        for vi in range(n_nodes):
            if dp[mask][vi] < INF:
                heapq.heappush(pq, (dp[mask][vi], vi))
        visited = [False] * n_nodes
        while pq:
            cost, vi = heapq.heappop(pq)
            if visited[vi]:
                continue
            if cost > dp[mask][vi]:
                continue
            visited[vi] = True
            for ui, w_uv in predecessors[vi]:
                new_cost = cost + w_uv
                if new_cost < dp[mask][ui]:
                    dp[mask][ui] = new_cost
                    parent[mask][ui] = ('edge', vi)
                    heapq.heappush(pq, (new_cost, ui))

    # Base: single destination
    for i, d in enumerate(dsts_list):
        mask = 1 << i
        di = node_idx.get(d)
        if di is not None:
            dp[mask][di] = 0
        dijkstra_extend(mask)

    # Larger subsets
    for size in range(2, n_dsts + 1):
        for mask in range(1, 1 << n_dsts):
            if bin(mask).count('1') != size:
                continue
            sub = (mask - 1) & mask
            while sub > 0:
                comp = mask ^ sub
                if sub < comp:
                    for vi in range(n_nodes):
                        val = dp[sub][vi] + dp[comp][vi]
                        if val < dp[mask][vi]:
                            dp[mask][vi] = val
                            parent[mask][vi] = ('split', sub)
                sub = (sub - 1) & mask
            dijkstra_extend(mask)

    if dp[full_mask][src_idx] >= INF:
        return None

    tree_edges = set()
    def extract(mask, vi):
        p = parent[mask][vi]
        if p is None:
            return
        if p[0] == 'split':
            sub = p[1]
            extract(sub, vi)
            extract(mask ^ sub, vi)
        elif p[0] == 'edge':
            nvi = p[1]
            tree_edges.add((nodes[vi], nodes[nvi]))
            extract(mask, nvi)

    extract(full_mask, src_idx)

    tree_graph = nx.DiGraph()
    for u, v in tree_edges:
        tree_graph.add_edge(u, v)

    result_paths = {}
    for dst in dsts_list:
        try:
            path = nx.shortest_path(tree_graph, src, dst)
            result_paths[dst] = path
        except:
            return None

    return result_paths

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)
    dsts_list = list(dsts)
    n_dsts = len(dsts_list)
    nodes = list(G.nodes())
    n_nodes = len(nodes)
    node_idx = {n: i for i, n in enumerate(nodes)}
    INF = float('inf')

    # All-pairs shortest paths
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

    # H1: Shortest paths
    sp_paths = {}
    for dst in dsts_list:
        if src in all_path and dst in all_path[src]:
            sp_paths[dst] = all_path[src][dst]
    sp_cost, _ = compute_tree_edge_cost(sp_paths, G)
    best_cost = sp_cost
    best_paths = dict(sp_paths)

    # DW exact Steiner tree
    if n_dsts <= 12 and n_nodes <= 80:
        dw_paths = dreyfus_wagner(src, dsts_list, G, nodes, node_idx)
        if dw_paths:
            dw_cost, _ = compute_tree_edge_cost(dw_paths, G)
            if dw_cost < best_cost:
                best_cost = dw_cost
                best_paths = dw_paths

    # H2: MST arborescence
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
        if all(d in mst_paths for d in dsts_list):
            c, _ = compute_tree_edge_cost(mst_paths, G)
            if c < best_cost:
                best_cost = c
                best_paths = mst_paths
    except:
        pass

    # H2b: MST with extra Steiner nodes
    for extra in nodes:
        if extra in set(terminals):
            continue
        if extra not in all_dist:
            continue
        ext_t = terminals + [extra]
        mc3 = nx.DiGraph()
        for t1 in ext_t:
            for t2 in ext_t:
                if t1 != t2 and t1 in all_dist and t2 in all_dist.get(t1, {}):
                    mc3.add_edge(t1, t2, weight=all_dist[t1][t2])
        try:
            arb3 = nx.minimum_spanning_arborescence(mc3, attr='weight')
            ch3 = defaultdict(list)
            for u, v in arb3.edges():
                ch3[u].append(v)
            ext_paths = {}
            def build_ext(nd, prefix):
                for child in ch3[nd]:
                    if nd in all_path and child in all_path[nd]:
                        seg = all_path[nd][child]
                        full = prefix[:-1] + seg
                        if child in dsts:
                            ext_paths[child] = full
                        build_ext(child, full)
            build_ext(src, [src])
            if all(d in ext_paths for d in dsts_list):
                c, _ = compute_tree_edge_cost(ext_paths, G)
                if c < best_cost:
                    best_cost = c
                    best_paths = ext_paths
        except:
            pass

    # H3: Greedy Steiner
    tree_nodes_set = {src}
    tree_edge_set = set()
    greedy_paths = {}
    remaining = list(dsts_list)
    while remaining:
        bd = None; bm = INF; bt = None; bs = None
        for dst in remaining:
            for tnode in tree_nodes_set:
                if tnode not in all_dist or dst not in all_dist[tnode]:
                    continue
                path = all_path[tnode][dst]
                m = sum(G[path[i]][path[i+1]]['cost'] for i in range(len(path)-1) if (path[i],path[i+1]) not in tree_edge_set)
                if m < bm:
                    bm = m; bd = dst; bt = tnode; bs = path
        if bd is None:
            break
        remaining.remove(bd)
        full = bs if bt == src else (all_path[src].get(bt, [bt])[:-1] + bs)
        greedy_paths[bd] = full
        for i in range(len(bs)-1):
            tree_edge_set.add((bs[i], bs[i+1]))
        tree_nodes_set.update(bs)
    if all(d in greedy_paths for d in dsts_list):
        c, _ = compute_tree_edge_cost(greedy_paths, G)
        if c < best_cost:
            best_cost = c
            best_paths = greedy_paths

    # H4: Single relay
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
        if c < best_cost:
            best_cost = c
            best_paths = cand

    # H5: Two-relay split
    relay_by_cost = []
    for node in nodes:
        if node in all_dist.get(src, {}) and node in all_dist:
            if all(d in all_dist[node] for d in dsts_list):
                relay_by_cost.append((all_dist[src][node], node))
    relay_by_cost.sort()
    top_relays = [n for _, n in relay_by_cost[:25]]
    for i in range(len(top_relays)):
        r1 = top_relays[i]
        for j in range(i+1, len(top_relays)):
            r2 = top_relays[j]
            cand = {}
            for dst in dsts_list:
                c1 = all_dist[src].get(r1, 0) + all_dist[r1].get(dst, INF)
                c2 = all_dist[src].get(r2, 0) + all_dist[r2].get(dst, INF)
                if c1 <= c2:
                    cand[dst] = all_path[src][r1][:-1] + all_path[r1][dst] if r1 != src else all_path[src][dst]
                else:
                    cand[dst] = all_path[src][r2][:-1] + all_path[r2][dst] if r2 != src else all_path[src][dst]
            c, _ = compute_tree_edge_cost(cand, G)
            if c < best_cost:
                best_cost = c
                best_paths = cand

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
