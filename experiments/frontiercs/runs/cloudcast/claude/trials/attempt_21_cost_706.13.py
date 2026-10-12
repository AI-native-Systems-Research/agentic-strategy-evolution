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

        dv = 300
        sp = dv / num_partitions
        egress = sum(num_partitions * sp * G[u][v].get("cost", 0) for u, v in all_edges)

        node_out = defaultdict(int)
        node_in = defaultdict(int)
        for u, v in all_edges:
            node_out[u] += 1
            node_in[v] += 1

        max_time = 0
        for u, v in all_edges:
            et = G[u][v].get("throughput", 1.0)
            el = egress_limits.get(_provider(u), 5) * n_vm
            il = ingress_limits.get(_provider(v), 10) * n_vm
            af = min(et, el / max(node_out[u], 1), il / max(node_in[v], 1))
            te = num_partitions * sp * 8 / max(af, 0.001)
            max_time = max(max_time, te)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance

    def build_greedy_steiner_with_paths(weight_fn):
        """Build Steiner tree and record actual dst paths (src->dst through tree)."""
        try:
            src_l, src_p = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None

        s_nodes = {src}
        s_edges = set()
        # Track how each dst was connected: connector_node -> dst path
        dst_connector = {}
        remain = [d for d in dsts if d in src_l]
        cache = {(src, d): (src_l[d], src_p[d]) for d in remain}

        while remain:
            bd, bp, bc, bsn = None, None, float('inf'), None
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
                        bc, bp, bd, bsn = l, p, d, sn
            if bd is None or bp is None:
                break
            remain.remove(bd)
            dst_connector[bd] = (bsn, bp)
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

        # Build dst paths by tracing from src to connector to dst
        # First build Steiner subgraph for src-to-connector routing
        sub = nx.DiGraph()
        for u, v in s_edges:
            sub.add_edge(u, v, **G[u][v])

        dp = {}
        for d in dsts:
            if d not in dst_connector:
                if d in src_p:
                    dp[d] = src_p[d]
                continue
            sn, seg = dst_connector[d]
            if sn == src:
                dp[d] = seg
            else:
                # Route src -> sn in subgraph, then sn -> d from seg
                try:
                    prefix = nx.dijkstra_path(sub, src, sn, weight="cost")
                    full = _remove_cycles(prefix + seg[1:])
                    if full[0] == src and full[-1] == d:
                        # Verify edges
                        if all(G.has_edge(full[i], full[i+1]) for i in range(len(full)-1)):
                            dp[d] = full
                        else:
                            dp[d] = src_p.get(d, seg)
                    else:
                        dp[d] = src_p.get(d)
                except:
                    dp[d] = src_p.get(d)
        return dp if dp and len(dp) >= len(dsts) else None

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

    weight_fns = ["cost"]
    for a in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]:
        weight_fns.append(make_bal(a))
    for p in [1.05, 1.1, 1.2, 1.5, 2.0, 3.0]:
        weight_fns.append(make_cross(p))
    for h in [0.0005, 0.001, 0.005, 0.01, 0.05]:
        weight_fns.append(make_hop(h))
    for a in [0.01, 0.1, 0.5, 1.0]:
        weight_fns.append(make_cpb(a))

    candidates = []
    for wf in weight_fns:
        if time.time() - t0 > TL * 0.2:
            break
        for builder in [build_spt, build_greedy_steiner_with_paths]:
            result = builder(wf)
            if result:
                candidates.append(result)

    best_cost = float('inf')
    best_paths = None
    for cand in candidates:
        cost = compute_cost(cand)
        if cost < best_cost:
            best_cost = cost
            best_paths = cand
    if best_paths is None:
        best_paths = build_spt("cost") or {}

    # --- Bottleneck avoidance: find bottleneck, re-solve avoiding it ---
    def find_bottleneck(dst_paths):
        if not dst_paths:
            return None
        all_edges = set()
        all_nodes = set()
        for d in dsts:
            path = dst_paths.get(d)
            if not path:
                continue
            for i in range(len(path) - 1):
                all_edges.add((path[i], path[i+1]))
                all_nodes.add(path[i])
                all_nodes.add(path[i+1])
        dv, sp = 300, 300 / num_partitions
        node_out = defaultdict(int)
        node_in = defaultdict(int)
        for u, v in all_edges:
            node_out[u] += 1
            node_in[v] += 1
        bn, mt = None, 0
        for u, v in all_edges:
            et = G[u][v].get("throughput", 1.0)
            el = egress_limits.get(_provider(u), 5) * n_vm
            il = ingress_limits.get(_provider(v), 10) * n_vm
            af = min(et, el / max(node_out[u], 1), il / max(node_in[v], 1))
            te = num_partitions * sp * 8 / max(af, 0.001)
            if te > mt:
                mt, bn = te, (u, v)
        return bn

    for _ in range(5):
        if time.time() - t0 > TL * 0.4:
            break
        bn = find_bottleneck(best_paths)
        if bn is None:
            break
        bu, bv = bn
        for pen in [10, 50, 100]:
            def make_avoid(bu, bv, pen):
                def wf(u, v, d):
                    c = d.get("cost", 0)
                    return c * pen if (u == bu and v == bv) else c
                return wf
            avoid_wf = make_avoid(bu, bv, pen)
            for builder in [build_spt, build_greedy_steiner_with_paths]:
                result = builder(avoid_wf)
                if result:
                    c = compute_cost(result)
                    if c < best_cost:
                        best_cost = c
                        best_paths = result

    # --- Local search Phase 1: k-shortest paths + throughput alternatives ---
    for rnd in range(15):
        if time.time() - t0 > TL * 0.55:
            break
        improved = False
        for dst in dsts:
            if time.time() - t0 > TL * 0.55:
                break
            cur_cost = compute_cost(best_paths)
            alts = []
            try:
                for p in nx.shortest_simple_paths(G, src, dst, weight="cost"):
                    alts.append(p)
                    if len(alts) >= 20:
                        break
            except:
                pass
            # Also try throughput-optimized paths
            for wf in [
                lambda u, v, d: 1.0 / max(d.get("throughput", 1.0), 0.001),
                lambda u, v, d: d.get("cost", 0) + 0.05 / max(d.get("throughput", 1.0), 0.001),
                lambda u, v, d: d.get("cost", 0) + 0.2 / max(d.get("throughput", 1.0), 0.001),
            ]:
                try:
                    p = nx.dijkstra_path(G, src, dst, weight=wf)
                    if p not in alts:
                        alts.append(p)
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
        if time.time() - t0 > TL * 0.7:
            break
        try:
            sp_from[n] = nx.single_source_dijkstra_path(G, n, weight="cost")
        except:
            sp_from[n] = {}

    for rnd in range(10):
        if time.time() - t0 > TL * 0.85:
            break
        improved = False
        for dst in dsts:
            if time.time() - t0 > TL * 0.85:
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

    # --- Phase 3: shortcutting (skip hops) ---
    for dst in dsts:
        if time.time() - t0 > TL * 0.92:
            break
        path = best_paths.get(dst)
        if path is None or len(path) <= 2:
            continue
        cur_cost = compute_cost(best_paths)
        changed = True
        while changed:
            changed = False
            path = best_paths[dst]
            for i in range(len(path) - 2):
                for j in range(i + 2, min(i + 5, len(path))):
                    if G.has_edge(path[i], path[j]):
                        shortcut = path[:i+1] + path[j:]
                        test = dict(best_paths)
                        test[dst] = shortcut
                        c = compute_cost(test)
                        if c < cur_cost - 0.001:
                            best_paths = test
                            cur_cost = c
                            changed = True
                            break
                if changed:
                    break

    # --- Phase 4: 2-hop relay ---
    tn = sorted(all_tree_nodes)[:25]
    for dst in dsts:
        if time.time() - t0 > TL * 0.95:
            break
        cur_cost = compute_cost(best_paths)
        for mid1 in tn:
            if time.time() - t0 > TL * 0.95:
                break
            if mid1 in (src, dst):
                continue
            for mid2 in tn:
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

    # --- Phase 5: Targeted partition splitting ---
    # Only split partitions on destinations whose path goes through the bottleneck
    def compute_cost_split(dst_paths, split_assign):
        """Cost with per-partition path assignment.
        split_assign: dict of (dst, part_id) -> path, overrides dst_paths."""
        all_edges = set()
        all_nodes = set()
        edge_parts = defaultdict(int)
        dv, sp = 300, 300 / num_partitions
        for d in dsts:
            for p in range(num_partitions):
                path = split_assign.get((d, p), dst_paths.get(d))
                if path is None:
                    return float('inf')
                for i in range(len(path) - 1):
                    e = (path[i], path[i+1])
                    all_edges.add(e)
                    all_nodes.add(path[i])
                    all_nodes.add(path[i+1])
                    edge_parts[e] += 1

        egress = sum(edge_parts[e] * sp * G[e[0]][e[1]].get("cost", 0) for e in all_edges)

        node_out = defaultdict(int)
        node_in = defaultdict(int)
        for u, v in all_edges:
            node_out[u] += 1
            node_in[v] += 1

        max_time = 0
        for u, v in all_edges:
            et = G[u][v].get("throughput", 1.0)
            el = egress_limits.get(_provider(u), 5) * n_vm
            il = ingress_limits.get(_provider(v), 10) * n_vm
            af = min(et, el / max(node_out[u], 1), il / max(node_in[v], 1))
            te = edge_parts[(u, v)] * sp * 8 / max(af, 0.001)
            max_time = max(max_time, te)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance

    split_assign = {}
    if time.time() - t0 < TL * 0.95 and num_partitions >= 2:
        # Find bottleneck edge
        bn = find_bottleneck(best_paths)
        if bn:
            bu, bv = bn
            # Find destinations using bottleneck
            bn_dsts = []
            for d in dsts:
                path = best_paths.get(d)
                if path:
                    for i in range(len(path) - 1):
                        if path[i] == bu and path[i+1] == bv:
                            bn_dsts.append(d)
                            break

            if bn_dsts:
                # Find alt path for bottleneck destinations that avoids bottleneck
                def avoid_bn(u, v, d):
                    c = d.get("cost", 0)
                    return c * 100 if (u == bu and v == bv) else c

                alt_paths = {}
                for d in bn_dsts:
                    try:
                        alt_paths[d] = nx.dijkstra_path(G, src, d, weight=avoid_bn)
                    except:
                        pass

                if alt_paths:
                    # Try splitting: half partitions on original, half on alt
                    base_cost = compute_cost(best_paths)
                    half = num_partitions // 2
                    test_assign = {}
                    for d in dsts:
                        for p in range(num_partitions):
                            if d in alt_paths and p >= half:
                                test_assign[(d, p)] = alt_paths[d]
                            else:
                                test_assign[(d, p)] = best_paths.get(d)
                    split_cost = compute_cost_split(best_paths, test_assign)
                    if split_cost < base_cost:
                        split_assign = test_assign

    # --- Build topology ---
    for dst in dsts:
        for p in range(num_partitions):
            path = split_assign.get((dst, p), best_paths.get(dst))
            if path is None:
                continue
            edges = []
            for i in range(len(path) - 1):
                if G.has_edge(path[i], path[i+1]):
                    edges.append([path[i], path[i+1], G[path[i]][path[i+1]]])
            bc_topology.set_dst_partition_paths(dst, p, list(edges))

    return bc_topology
'''
        return {"code": code}
