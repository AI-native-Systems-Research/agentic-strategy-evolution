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

    def compute_cost(dst_paths, data_vol):
        if not dst_paths or any(d not in dst_paths for d in dsts):
            return float('inf')

        s_part = data_vol / num_partitions
        all_edges = set()
        all_nodes = set()
        for d in dsts:
            path = dst_paths[d]
            for i in range(len(path) - 1):
                all_edges.add((path[i], path[i+1]))
                all_nodes.add(path[i])
                all_nodes.add(path[i+1])

        egress = sum(num_partitions * s_part * G[u][v].get("cost", 0) for u, v in all_edges)

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
            actual_flow = min(edge_thr, eg_lim / max(node_out[u], 1), ig_lim / max(node_in[v], 1))
            time_e = num_partitions * s_part * 8 / max(actual_flow, 0.001)
            max_time = max(max_time, time_e)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance

    def build_greedy_steiner(weight_fn):
        try:
            src_l, src_p = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None

        s_nodes = {src}
        s_edges = set()
        remain = [d for d in dsts if d in src_l]
        cache = {(src, d): (src_l[d], src_p[d]) for d in remain}

        while remain:
            best_d, best_p, best_c = None, None, float('inf')
            for d in remain:
                for sn in list(s_nodes):
                    k = (sn, d)
                    if k not in cache:
                        try:
                            l, p = nx.single_source_dijkstra(G, sn, target=d, weight=weight_fn)
                            cache[k] = (l, p)
                        except:
                            cache[k] = (float('inf'), None)
                    l, p = cache[k]
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
                    k = (nn, d)
                    if k not in cache:
                        try:
                            l, p = nx.single_source_dijkstra(G, nn, target=d, weight=weight_fn)
                            cache[k] = (l, p)
                        except:
                            cache[k] = (float('inf'), None)

        sub = nx.DiGraph()
        for u, v in s_edges:
            sub.add_edge(u, v, **G[u][v])
        dp = {}
        for d in dsts:
            try:
                dp[d] = nx.dijkstra_path(sub, src, d, weight="cost")
            except:
                if d in src_p:
                    dp[d] = src_p[d]
        return dp if len(dp) >= len(dsts) else None

    def build_spt(weight_fn):
        try:
            _, paths = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None
        dp = {d: paths[d] for d in dsts if d in paths}
        return dp if len(dp) == len(dsts) else None

    # Weight functions
    def make_bal(a):
        def wf(u, v, d):
            return d.get("cost", 0) + a / max(d.get("throughput", 1.0), 0.001)
        return wf
    def make_cross(p):
        def wf(u, v, d):
            return d.get("cost", 0) * (p if _provider(u) != _provider(v) else 1.0)
        return wf
    def make_hop(h):
        def wf(u, v, d):
            return d.get("cost", 0) + h
        return wf
    def make_ratio(a):
        def wf(u, v, d):
            c = d.get("cost", 0)
            t = max(d.get("throughput", 1.0), 0.001)
            return c + a * c / t
        return wf
    # Cost-per-bandwidth: penalize low bandwidth high cost edges
    def make_cpb(a):
        def wf(u, v, d):
            c = d.get("cost", 0)
            t = max(d.get("throughput", 1.0), 0.001)
            return c * (1 + a / t)
        return wf

    weight_fns = ["cost"]
    for a in [0.001, 0.002, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.07, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0]:
        weight_fns.append(make_bal(a))
    for p in [1.02, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0, 3.0, 5.0]:
        weight_fns.append(make_cross(p))
    for h in [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]:
        weight_fns.append(make_hop(h))
    for a in [0.01, 0.05, 0.1, 0.5, 1.0, 2.0]:
        weight_fns.append(make_ratio(a))
    for a in [0.01, 0.05, 0.1, 0.5, 1.0]:
        weight_fns.append(make_cpb(a))

    # Generate candidates
    candidates = []
    for wf in weight_fns:
        for builder in [build_spt, build_greedy_steiner]:
            result = builder(wf)
            if result:
                candidates.append(result)

    # Pick best at data_vol=300
    best_cost = float('inf')
    best_paths = None
    for cand in candidates:
        cost = compute_cost(cand, 300)
        if cost < best_cost:
            best_cost = cost
            best_paths = cand

    if best_paths is None:
        best_paths = build_spt("cost") or {}

    # --- Aggressive local search ---
    # Phase 1: k-shortest paths per destination
    for _ in range(10):
        improved = False
        for dst in dsts:
            cur_cost = compute_cost(best_paths, 300)
            alts = []
            try:
                for p in nx.shortest_simple_paths(G, src, dst, weight="cost"):
                    alts.append(p)
                    if len(alts) >= 20:
                        break
            except:
                pass
            for alt in alts:
                test = dict(best_paths)
                test[dst] = alt
                c = compute_cost(test, 300)
                if c < cur_cost - 0.001:
                    best_paths = test
                    cur_cost = c
                    improved = True
        if not improved:
            break

    # Phase 2: Try rerouting through existing nodes (path through tree)
    all_tree_nodes = set()
    for d in dsts:
        if d in best_paths:
            for n in best_paths[d]:
                all_tree_nodes.add(n)

    for _ in range(3):
        improved = False
        for dst in dsts:
            cur_cost = compute_cost(best_paths, 300)
            cur_path = best_paths[dst]
            # Try routing through each intermediate tree node
            for mid in all_tree_nodes:
                if mid == src or mid == dst:
                    continue
                try:
                    p1 = nx.dijkstra_path(G, src, mid, weight="cost")
                    p2 = nx.dijkstra_path(G, mid, dst, weight="cost")
                    combined = p1 + p2[1:]
                    # Remove any cycles
                    seen = set()
                    clean = []
                    for n in combined:
                        if n in seen and n != combined[-1]:
                            # Find the cycle and remove
                            idx = clean.index(n)
                            clean = clean[:idx]
                        clean.append(n)
                        seen.add(n)
                    test = dict(best_paths)
                    test[dst] = clean
                    c = compute_cost(test, 300)
                    if c < cur_cost - 0.001:
                        best_paths = test
                        cur_cost = c
                        improved = True
                except:
                    continue
        if not improved:
            break

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
