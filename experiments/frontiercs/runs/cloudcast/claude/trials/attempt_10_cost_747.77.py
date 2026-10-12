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

def _provider(node):
    return node.split(":")[0] if ":" in node else ""

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)

    egress_limits = {"aws": 5, "gcp": 7, "azure": 16}
    ingress_limits = {"aws": 10, "gcp": 16, "azure": 16}
    n_vm = 2
    r_instance = 0.54
    data_vol = 300
    s_part = data_vol / num_partitions

    def compute_cost(dst_paths):
        """Compute total cost for a given set of paths (all partitions same path)."""
        if not dst_paths or any(d not in dst_paths for d in dsts):
            return float('inf')

        all_edges = set()
        all_nodes = set()
        for d in dsts:
            path = dst_paths[d]
            for i in range(len(path) - 1):
                all_edges.add((path[i], path[i+1]))
                all_nodes.add(path[i])
                all_nodes.add(path[i+1])

        egress = 0
        for u, v in all_edges:
            egress += num_partitions * s_part * G[u][v].get("cost", 0)

        node_out = defaultdict(int)
        node_in = defaultdict(int)
        for u, v in all_edges:
            node_out[u] += 1
            node_in[v] += 1

        max_time = 0
        for u, v in all_edges:
            edge_thr = G[u][v].get("throughput", 1.0)
            eg_lim = egress_limits.get(_provider(u), 5) * n_vm
            ig_lim = ingress_limits.get(_provider(v), 10) * n_vm
            eg_per = eg_lim / max(node_out[u], 1)
            ig_per = ig_lim / max(node_in[v], 1)
            actual_flow = min(edge_thr, eg_per, ig_per)
            time_e = num_partitions * s_part * 8 / max(actual_flow, 0.001)
            max_time = max(max_time, time_e)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance

    # --- Approach 1: Shortest Path Tree (SPT) ---
    def build_spt(weight_fn):
        try:
            lengths, paths = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None
        dst_paths = {}
        for d in dsts:
            if d in paths:
                dst_paths[d] = paths[d]
        return dst_paths if len(dst_paths) == len(dsts) else None

    # --- Approach 2: Greedy Steiner ---
    def build_greedy_steiner(weight_fn):
        try:
            src_lengths, src_paths = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None

        s_nodes = {src}
        s_edges = set()
        remain = [d for d in dsts if d in src_lengths]

        cache = {}
        for d in remain:
            cache[(src, d)] = (src_lengths[d], src_paths[d])

        while remain:
            best_d, best_p, best_c = None, None, float('inf')
            for d in remain:
                for sn in list(s_nodes):
                    key = (sn, d)
                    if key not in cache:
                        try:
                            l, p = nx.single_source_dijkstra(G, sn, target=d, weight=weight_fn)
                            cache[key] = (l, p)
                        except:
                            cache[key] = (float('inf'), None)
                    l, p = cache[key]
                    if l < best_c:
                        best_c, best_p, best_d = l, p, d

            if best_d is None or best_p is None:
                break
            remain.remove(best_d)
            for i in range(len(best_p) - 1):
                s_edges.add((best_p[i], best_p[i+1]))
                s_nodes.add(best_p[i])
                s_nodes.add(best_p[i+1])
            for nn in set(best_p):
                for d in remain:
                    key = (nn, d)
                    if key not in cache:
                        try:
                            l, p = nx.single_source_dijkstra(G, nn, target=d, weight=weight_fn)
                            cache[key] = (l, p)
                        except:
                            cache[key] = (float('inf'), None)

        sub = nx.DiGraph()
        for u, v in s_edges:
            sub.add_edge(u, v, **G[u][v])

        dst_paths = {}
        for d in dsts:
            try:
                dst_paths[d] = nx.dijkstra_path(sub, src, d, weight="cost")
            except:
                if d in src_paths:
                    dst_paths[d] = src_paths[d]
        return dst_paths if len(dst_paths) >= len(dsts) else None

    # --- Approach 3: Metric closure MST Steiner ---
    def build_mst_steiner():
        terminals = [src] + list(dsts)
        terminal_dist = {}
        terminal_paths = {}
        for t in terminals:
            try:
                lengths, paths = nx.single_source_dijkstra(G, t, weight="cost")
                for t2 in terminals:
                    if t2 != t and t2 in lengths:
                        terminal_dist[(t, t2)] = lengths[t2]
                        terminal_paths[(t, t2)] = paths[t2]
            except:
                pass

        mc = nx.Graph()
        for (t1, t2), cost in terminal_dist.items():
            if not mc.has_edge(t1, t2) or mc[t1][t2]["weight"] > cost:
                mc.add_edge(t1, t2, weight=cost)

        try:
            mst = nx.minimum_spanning_tree(mc, weight="weight")
        except:
            return None

        s_edges = set()
        for u, v in mst.edges():
            path = terminal_paths.get((u, v)) or terminal_paths.get((v, u))
            if path:
                for i in range(len(path) - 1):
                    s_edges.add((path[i], path[i+1]))

        sub = nx.DiGraph()
        for u, v in s_edges:
            if G.has_edge(u, v):
                sub.add_edge(u, v, **G[u][v])

        dst_paths = {}
        for d in dsts:
            try:
                dst_paths[d] = nx.dijkstra_path(sub, src, d, weight="cost")
            except:
                try:
                    dst_paths[d] = nx.dijkstra_path(G, src, d, weight="cost")
                except:
                    pass
        return dst_paths if len(dst_paths) >= len(dsts) else None

    # --- Generate all candidate solutions ---
    candidates = []

    def make_bal(a):
        def wf(u, v, d):
            return d.get("cost", 0) + a / max(d.get("throughput", 1.0), 0.001)
        return wf

    def make_cross(p):
        def wf(u, v, d):
            c = d.get("cost", 0)
            return c * (p if _provider(u) != _provider(v) else 1.0)
        return wf

    weight_fns = ["cost"]
    for a in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]:
        weight_fns.append(make_bal(a))
    for p in [1.1, 1.2, 1.5, 2.0, 3.0]:
        weight_fns.append(make_cross(p))

    for wf in weight_fns:
        for builder in [build_spt, build_greedy_steiner]:
            result = builder(wf)
            if result:
                candidates.append(result)

    # MST Steiner
    mst_result = build_mst_steiner()
    if mst_result:
        candidates.append(mst_result)

    # --- Evaluate and pick best ---
    best_cost = float('inf')
    best_paths = None

    for cand in candidates:
        cost = compute_cost(cand)
        if cost < best_cost:
            best_cost = cost
            best_paths = cand

    if best_paths is None:
        best_paths = {}
        for d in dsts:
            try:
                best_paths[d] = nx.dijkstra_path(G, src, d, weight="cost")
            except:
                pass

    # --- Local search: try replacing each destination's path ---
    improved = True
    while improved:
        improved = False
        for dst in dsts:
            current_path = best_paths[dst]
            current_cost = compute_cost(best_paths)

            # Try alternative paths for this dst
            for wf in weight_fns[:5]:  # limit to avoid timeout
                try:
                    alt_path = nx.dijkstra_path(G, src, dst, weight=wf)
                except:
                    continue
                if alt_path == current_path:
                    continue

                test_paths = dict(best_paths)
                test_paths[dst] = alt_path
                test_cost = compute_cost(test_paths)
                if test_cost < current_cost:
                    best_paths = test_paths
                    current_cost = test_cost
                    improved = True

    # --- Build topology ---
    for dst in dsts:
        path = best_paths.get(dst)
        if path is None:
            continue
        edges = []
        for i in range(len(path) - 1):
            if G.has_edge(path[i], path[i+1]):
                edges.append([path[i], path[i+1], G[path[i]][path[i+1]]])
        for p in range(num_partitions):
            bc_topology.set_dst_partition_paths(dst, p, list(edges))

    return bc_topology
'''
        return {"code": code}
