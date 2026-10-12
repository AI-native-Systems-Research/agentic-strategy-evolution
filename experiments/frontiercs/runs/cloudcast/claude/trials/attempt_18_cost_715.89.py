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
    TL = 55

    egress_limits = {"aws": 5, "gcp": 7, "azure": 16}
    ingress_limits = {"aws": 10, "gcp": 16, "azure": 16}
    n_vm = 2
    r_instance = 0.54
    DV = 300
    SP = DV / num_partitions

    def compute_cost(dst_paths):
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

        egress = sum(num_partitions * SP * G[u][v].get("cost", 0) for u, v in all_edges)

        node_out = defaultdict(int)
        node_in = defaultdict(int)
        for u, v in all_edges:
            node_out[u] += 1
            node_in[v] += 1

        max_time = 0
        bottleneck = None
        for u, v in all_edges:
            et = G[u][v].get("throughput", 1.0)
            el = egress_limits.get(_provider(u), 5) * n_vm
            il = ingress_limits.get(_provider(v), 10) * n_vm
            af = min(et, el / max(node_out[u], 1), il / max(node_in[v], 1))
            te = num_partitions * SP * 8 / max(af, 0.001)
            if te > max_time:
                max_time = te
                bottleneck = (u, v)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance, bottleneck

    def compute_cost_val(dst_paths):
        r = compute_cost(dst_paths)
        return r[0] if isinstance(r, tuple) else r

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
            bd, bp, bc = None, None, float('inf')
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
                    if l < bc:
                        bc, bp, bd = l, p, d
            if bd is None or bp is None:
                break
            remain.remove(bd)
            for i in range(len(bp) - 1):
                s_edges.add((bp[i], bp[i+1]))
                s_nodes.add(bp[i])
                s_nodes.add(bp[i+1])
            for nn in set(bp):
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

    wfs = ["cost"]
    for a in [0.001, 0.002, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.07, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0]:
        wfs.append(make_bal(a))
    for p in [1.02, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0, 3.0, 5.0]:
        wfs.append(make_cross(p))
    for h in [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]:
        wfs.append(make_hop(h))
    for a in [0.01, 0.05, 0.1, 0.5, 1.0]:
        wfs.append(make_cpb(a))

    candidates = []
    for wf in wfs:
        if time.time() - t0 > TL * 0.25:
            break
        for builder in [build_spt, build_greedy_steiner]:
            result = builder(wf)
            if result:
                candidates.append(result)

    best_cost = float('inf')
    best_paths = None
    for cand in candidates:
        cost = compute_cost_val(cand)
        if cost < best_cost:
            best_cost = cost
            best_paths = cand
    if best_paths is None:
        best_paths = build_spt("cost") or {}

    # --- Iterative bottleneck avoidance ---
    # Find bottleneck edge and penalize it, re-solve
    for bn_round in range(5):
        if time.time() - t0 > TL * 0.35:
            break
        cost_val, bottleneck = compute_cost(best_paths)
        if bottleneck is None:
            break
        bu, bv = bottleneck
        # Create weight that heavily penalizes the bottleneck edge
        for penalty in [10, 50, 100]:
            def make_avoid(bu, bv, pen):
                def wf(u, v, d):
                    c = d.get("cost", 0)
                    if u == bu and v == bv:
                        return c * pen
                    return c
                return wf
            avoid_wf = make_avoid(bu, bv, penalty)
            for builder in [build_spt, build_greedy_steiner]:
                result = builder(avoid_wf)
                if result:
                    c = compute_cost_val(result)
                    if c < best_cost:
                        best_cost = c
                        best_paths = result

    # --- Local search Phase 1: k-shortest ---
    for rnd in range(15):
        if time.time() - t0 > TL * 0.55:
            break
        improved = False
        for dst in dsts:
            if time.time() - t0 > TL * 0.55:
                break
            cur_cost = compute_cost_val(best_paths)
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
                c = compute_cost_val(test)
                if c < cur_cost - 0.001:
                    best_paths = test
                    cur_cost = c
                    improved = True
        if not improved:
            break

    # --- Phase 2: reroute through tree nodes ---
    all_tree_nodes = set()
    for d in dsts:
        if d in best_paths:
            for n in best_paths[d]:
                all_tree_nodes.add(n)

    sp_from = {}
    for n in all_tree_nodes:
        if time.time() - t0 > TL * 0.7:
            break
        try:
            sp_from[n] = nx.single_source_dijkstra_path(G, n, weight="cost")
        except:
            sp_from[n] = {}

    for rnd in range(10):
        if time.time() - t0 > TL * 0.82:
            break
        improved = False
        for dst in dsts:
            if time.time() - t0 > TL * 0.82:
                break
            cur_cost = compute_cost_val(best_paths)
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
                c = compute_cost_val(test)
                if c < cur_cost - 0.001:
                    best_paths = test
                    cur_cost = c
                    improved = True
        if not improved:
            break

    # --- Phase 3: shortcutting ---
    for dst in dsts:
        if time.time() - t0 > TL * 0.9:
            break
        path = best_paths.get(dst)
        if path is None or len(path) <= 2:
            continue
        cur_cost = compute_cost_val(best_paths)
        changed = True
        while changed:
            changed = False
            path = best_paths[dst]
            for i in range(len(path) - 2):
                for j in range(i + 2, min(i + 6, len(path))):
                    if G.has_edge(path[i], path[j]):
                        shortcut = path[:i+1] + path[j:]
                        test = dict(best_paths)
                        test[dst] = shortcut
                        c = compute_cost_val(test)
                        if c < cur_cost - 0.001:
                            best_paths = test
                            cur_cost = c
                            changed = True
                            break
                if changed:
                    break

    # --- Phase 4: bottleneck-aware path swap ---
    # After local search, check bottleneck again and try to reroute dsts that use it
    if time.time() - t0 < TL * 0.95:
        cost_val, bottleneck = compute_cost(best_paths)
        if bottleneck:
            bu, bv = bottleneck
            # Find which dsts use this bottleneck edge
            for dst in dsts:
                if time.time() - t0 > TL * 0.95:
                    break
                path = best_paths[dst]
                uses_bottleneck = False
                for i in range(len(path) - 1):
                    if path[i] == bu and path[i+1] == bv:
                        uses_bottleneck = True
                        break
                if not uses_bottleneck:
                    continue
                # Try to find alt path that avoids bottleneck
                cur_cost = compute_cost_val(best_paths)
                try:
                    def avoid_bn(u, v, d):
                        c = d.get("cost", 0)
                        if u == bu and v == bv:
                            return c * 100
                        return c
                    alt = nx.dijkstra_path(G, src, dst, weight=avoid_bn)
                    test = dict(best_paths)
                    test[dst] = alt
                    c = compute_cost_val(test)
                    if c < cur_cost - 0.001:
                        best_paths = test
                except:
                    pass

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
