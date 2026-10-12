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

    def build_greedy_steiner(weight_fn):
        try:
            src_lengths, src_paths = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None

        s_nodes = {src}
        s_edges = set()
        remain = [d for d in dsts if d in src_lengths]

        cache_cost = {}
        cache_path = {}
        for d in remain:
            cache_cost[(src, d)] = src_lengths[d]
            cache_path[(src, d)] = src_paths[d]

        while remain:
            best_d = None
            best_p = None
            best_c = float('inf')

            for d in remain:
                for sn in list(s_nodes):
                    key = (sn, d)
                    if key not in cache_cost:
                        try:
                            l, p = nx.single_source_dijkstra(G, sn, target=d, weight=weight_fn)
                            cache_cost[key] = l
                            cache_path[key] = p
                        except:
                            cache_cost[key] = float('inf')
                            cache_path[key] = None
                    if cache_cost[key] < best_c:
                        best_c = cache_cost[key]
                        best_p = cache_path[key]
                        best_d = d

            if best_d is None or best_p is None:
                break

            remain.remove(best_d)
            new_nodes = set()
            for i in range(len(best_p) - 1):
                s_edges.add((best_p[i], best_p[i+1]))
                new_nodes.add(best_p[i])
                new_nodes.add(best_p[i+1])
            s_nodes.update(new_nodes)

            for nn in new_nodes:
                for d in remain:
                    key = (nn, d)
                    if key not in cache_cost:
                        try:
                            l, p = nx.single_source_dijkstra(G, nn, target=d, weight=weight_fn)
                            cache_cost[key] = l
                            cache_path[key] = p
                        except:
                            cache_cost[key] = float('inf')
                            cache_path[key] = None

        # Build Steiner subgraph and find paths from src to each dst
        sub = nx.DiGraph()
        for u, v in s_edges:
            sub.add_edge(u, v, **G[u][v])

        dst_paths = {}
        for d in dsts:
            try:
                path = nx.dijkstra_path(sub, src, d, weight="cost")
                dst_paths[d] = path
            except:
                if d in src_paths:
                    dst_paths[d] = src_paths[d]
        return dst_paths

    def build_direct_paths(weight_fn):
        dst_paths = {}
        for d in dsts:
            try:
                dst_paths[d] = nx.dijkstra_path(G, src, d, weight=weight_fn)
            except:
                pass
        return dst_paths

    def compute_cost(dst_paths, data_vol=300):
        if not dst_paths or any(d not in dst_paths for d in dsts):
            return float('inf')

        s_part = data_vol / num_partitions
        all_edges = set()
        all_nodes = set()

        for d in dsts:
            path = dst_paths[d]
            for i in range(len(path) - 1):
                e = (path[i], path[i+1])
                all_edges.add(e)
                all_nodes.add(path[i])
                all_nodes.add(path[i+1])

        # All partitions use same path, so each edge carries num_partitions
        # Egress cost
        egress = 0
        for u, v in all_edges:
            c = G[u][v].get("cost", 0)
            egress += num_partitions * s_part * c

        # Transfer time with bandwidth constraints
        node_out = defaultdict(int)
        node_in = defaultdict(int)
        for u, v in all_edges:
            node_out[u] += 1
            node_in[v] += 1

        max_time = 0
        for u, v in all_edges:
            edge_thr = G[u][v].get("throughput", 1.0)
            prov_u = _provider(u)
            prov_v = _provider(v)
            eg_lim = egress_limits.get(prov_u, 5) * n_vm
            ig_lim = ingress_limits.get(prov_v, 10) * n_vm
            eg_per = eg_lim / max(node_out[u], 1)
            ig_per = ig_lim / max(node_in[v], 1)
            actual_flow = min(edge_thr, eg_per, ig_per)
            time_e = num_partitions * s_part * 8 / max(actual_flow, 0.001)
            max_time = max(max_time, time_e)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance

    # --- Generate candidates ---
    candidates = []

    def make_bal(a):
        def wf(u, v, d):
            return d.get("cost", 0) + a / max(d.get("throughput", 1.0), 0.001)
        return wf

    def make_cross(p):
        def wf(u, v, d):
            c = d.get("cost", 0)
            mult = p if _provider(u) != _provider(v) else 1.0
            return c * mult
        return wf

    def wf_thr(u, v, d):
        return 1.0 / max(d.get("throughput", 1.0), 0.001)

    weight_fns = [
        "cost",
        wf_thr,
    ]
    for a in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5]:
        weight_fns.append(make_bal(a))
    for p in [1.1, 1.2, 1.5, 2.0, 3.0]:
        weight_fns.append(make_cross(p))

    for wf in weight_fns:
        steiner = build_greedy_steiner(wf)
        if steiner and len(steiner) >= len(dsts):
            candidates.append(steiner)

        direct = build_direct_paths(wf)
        if direct and len(direct) >= len(dsts):
            candidates.append(direct)

    # Evaluate all with single data_vol=300 (default)
    best_cost = float('inf')
    best_paths = None

    for cand in candidates:
        cost = compute_cost(cand, data_vol=300)
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
