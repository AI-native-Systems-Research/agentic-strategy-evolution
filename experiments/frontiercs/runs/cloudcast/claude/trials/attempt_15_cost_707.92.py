class Solution:
    def solve(self, spec_path=None):
        code = r'''
import networkx as nx
from collections import defaultdict
import time

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

def _remove_cycles(path):
    seen = {}
    result = []
    for n in path:
        if n in seen:
            result = result[:seen[n]]
        seen[n] = len(result)
        result.append(n)
    return result

def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)
    t0 = time.time()
    TIME_LIMIT = 55

    egress_limits = {"aws": 5, "gcp": 7, "azure": 16}
    ingress_limits = {"aws": 10, "gcp": 16, "azure": 16}
    n_vm = 2
    r_instance = 0.54

    def compute_cost(dst_paths, data_vol=300):
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
    def make_cpb(a):
        def wf(u, v, d):
            c = d.get("cost", 0)
            t = max(d.get("throughput", 1.0), 0.001)
            return c * (1 + a / t)
        return wf
    # Min-cost max-throughput combo
    def make_mcmt(a, b):
        def wf(u, v, d):
            c = d.get("cost", 0)
            t = max(d.get("throughput", 1.0), 0.001)
            return a * c + b / t
        return wf

    weight_fns = ["cost"]
    for a in [0.001, 0.002, 0.005, 0.008, 0.01, 0.012, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.07, 0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0]:
        weight_fns.append(make_bal(a))
    for p in [1.01, 1.02, 1.05, 1.08, 1.1, 1.12, 1.15, 1.2, 1.3, 1.5, 2.0, 3.0, 5.0]:
        weight_fns.append(make_cross(p))
    for h in [0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.003, 0.005, 0.01, 0.02, 0.05]:
        weight_fns.append(make_hop(h))
    for a in [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]:
        weight_fns.append(make_cpb(a))
    for a, b in [(1, 0.01), (1, 0.05), (1, 0.1), (0.5, 0.1), (0.5, 0.5), (1, 0.5), (1, 1), (2, 1)]:
        weight_fns.append(make_mcmt(a, b))

    # Generate candidates
    candidates = []
    for wf in weight_fns:
        if time.time() - t0 > TIME_LIMIT * 0.25:
            break
        for builder in [build_spt, build_greedy_steiner]:
            result = builder(wf)
            if result:
                candidates.append(result)

    # Pick best
    best_cost = float('inf')
    best_paths = None
    for cand in candidates:
        cost = compute_cost(cand)
        if cost < best_cost:
            best_cost = cost
            best_paths = cand

    if best_paths is None:
        best_paths = build_spt("cost") or {}

    # --- Local search Phase 1: k-shortest paths ---
    for _ in range(20):
        if time.time() - t0 > TIME_LIMIT * 0.5:
            break
        improved = False
        for dst in dsts:
            if time.time() - t0 > TIME_LIMIT * 0.5:
                break
            cur_cost = compute_cost(best_paths)
            alts = []
            try:
                for p in nx.shortest_simple_paths(G, src, dst, weight="cost"):
                    alts.append(p)
                    if len(alts) >= 30:
                        break
            except:
                pass
            for alt in alts:
                test = dict(best_paths)
                test[dst] = alt
                c = compute_cost(test)
                if c < cur_cost - 0.001:
                    best_paths = test
                    cur_cost = c
                    improved = True
        if not improved:
            break

    # --- Local search Phase 2: reroute through tree nodes ---
    all_tree_nodes = set()
    for d in dsts:
        if d in best_paths:
            for n in best_paths[d]:
                all_tree_nodes.add(n)

    sp_from = {}
    for n in all_tree_nodes:
        if time.time() - t0 > TIME_LIMIT * 0.65:
            break
        try:
            sp_from[n] = nx.single_source_dijkstra_path(G, n, weight="cost")
        except:
            sp_from[n] = {}

    for _ in range(10):
        if time.time() - t0 > TIME_LIMIT * 0.8:
            break
        improved = False
        for dst in dsts:
            if time.time() - t0 > TIME_LIMIT * 0.8:
                break
            cur_cost = compute_cost(best_paths)
            for mid in all_tree_nodes:
                if mid == src or mid == dst:
                    continue
                p1 = sp_from.get(src, {}).get(mid)
                p2 = sp_from.get(mid, {}).get(dst)
                if not p1 or not p2:
                    continue
                combined = _remove_cycles(p1 + p2[1:])
                if len(combined) < 2 or combined[0] != src or combined[-1] != dst:
                    continue
                if not all(G.has_edge(combined[i], combined[i+1]) for i in range(len(combined)-1)):
                    continue
                test = dict(best_paths)
                test[dst] = combined
                c = compute_cost(test)
                if c < cur_cost - 0.001:
                    best_paths = test
                    cur_cost = c
                    improved = True
        if not improved:
            break

    # Update tree nodes after phase 2
    all_tree_nodes = set()
    for d in dsts:
        if d in best_paths:
            for n in best_paths[d]:
                all_tree_nodes.add(n)

    # --- Local search Phase 3: 2-hop relay ---
    if time.time() - t0 < TIME_LIMIT * 0.85:
        # Precompute sp_from for any new nodes
        for n in all_tree_nodes:
            if n not in sp_from:
                if time.time() - t0 > TIME_LIMIT * 0.85:
                    break
                try:
                    sp_from[n] = nx.single_source_dijkstra_path(G, n, weight="cost")
                except:
                    sp_from[n] = {}

    sorted_tree_nodes = sorted(all_tree_nodes)[:30]
    for dst in dsts:
        if time.time() - t0 > TIME_LIMIT * 0.92:
            break
        cur_cost = compute_cost(best_paths)
        for mid1 in sorted_tree_nodes:
            if time.time() - t0 > TIME_LIMIT * 0.92:
                break
            if mid1 in (src, dst):
                continue
            for mid2 in sorted_tree_nodes:
                if mid2 in (src, dst, mid1):
                    continue
                p1 = sp_from.get(src, {}).get(mid1)
                p2 = sp_from.get(mid1, {}).get(mid2)
                p3 = sp_from.get(mid2, {}).get(dst)
                if not all([p1, p2, p3]):
                    continue
                combined = _remove_cycles(p1 + p2[1:] + p3[1:])
                if len(combined) < 2 or combined[0] != src or combined[-1] != dst:
                    continue
                if not all(G.has_edge(combined[i], combined[i+1]) for i in range(len(combined)-1)):
                    continue
                test = dict(best_paths)
                test[dst] = combined
                c = compute_cost(test)
                if c < cur_cost - 0.001:
                    best_paths = test
                    cur_cost = c

    # --- Final phase: try removing hops to reduce |V| ---
    if time.time() - t0 < TIME_LIMIT * 0.95:
        for dst in dsts:
            if time.time() - t0 > TIME_LIMIT * 0.95:
                break
            path = best_paths.get(dst)
            if path is None or len(path) <= 2:
                continue
            cur_cost = compute_cost(best_paths)
            # Try shortcutting: skip intermediate nodes if direct edge exists
            for i in range(len(path) - 2):
                for j in range(i + 2, len(path)):
                    if G.has_edge(path[i], path[j]):
                        shortcut = path[:i+1] + path[j:]
                        test = dict(best_paths)
                        test[dst] = shortcut
                        c = compute_cost(test)
                        if c < cur_cost - 0.001:
                            best_paths = test
                            cur_cost = c
                            path = best_paths[dst]
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
