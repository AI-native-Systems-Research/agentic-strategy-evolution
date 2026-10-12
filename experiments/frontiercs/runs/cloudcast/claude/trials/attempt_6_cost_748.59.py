class Solution:
    def solve(self, spec_path=None):
        code = r'''
import networkx as nx
from collections import defaultdict
import json

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

    # --- Build multiple Steiner trees with different weight functions ---
    # Then pick the best one, or split partitions across them

    def build_greedy_steiner(weight_fn):
        """Build greedy Steiner tree with given weight function."""
        try:
            src_lengths, src_paths = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None, None

        s_nodes = {src}
        s_edges = set()
        s_dst_paths = {}
        remain = [d for d in dsts if d in src_lengths]

        # Cache
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
                    c = cache_cost[key]
                    if c < best_c:
                        best_c = c
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

        # Find paths from src to each dst in Steiner subgraph
        sub = nx.DiGraph()
        for u, v in s_edges:
            sub.add_edge(u, v, **G[u][v])

        for d in dsts:
            if d not in src_lengths:
                continue
            try:
                path = nx.dijkstra_path(sub, src, d, weight="cost")
                s_dst_paths[d] = path
            except nx.NetworkXNoPath:
                s_dst_paths[d] = src_paths.get(d)

        return s_dst_paths, s_edges

    # Weight function 1: pure cost
    wf_cost = "cost"

    # Weight function 2: cost + throughput penalty
    def wf_balanced(u, v, d):
        c = d.get("cost", 0)
        t = d.get("throughput", 1.0)
        return c + 0.01 / max(t, 0.001)

    # Weight function 3: cost * (1 + cross-cloud penalty)
    def wf_same_cloud(u, v, d):
        c = d.get("cost", 0)
        penalty = 1.5 if _provider(u) != _provider(v) else 1.0
        return c * penalty

    # Build candidates
    candidates = []
    for wf in [wf_cost, wf_balanced, wf_same_cloud]:
        result = build_greedy_steiner(wf)
        if result[0] is not None:
            candidates.append(result)

    # Evaluate each candidate
    def eval_candidate(dst_paths, edges):
        if not dst_paths:
            return float('inf')
        # Collect all nodes and edges
        all_nodes = set()
        all_edges = set()
        for d in dsts:
            path = dst_paths.get(d)
            if path is None:
                return float('inf')
            for i in range(len(path) - 1):
                all_edges.add((path[i], path[i+1]))
                all_nodes.add(path[i])
                all_nodes.add(path[i+1])

        # Egress cost: num_partitions * s_part * sum(c_e)
        # s_part cancels in comparison, so just use sum(c_e) * num_partitions
        egress = sum(G[u][v].get("cost", 0) for u, v in all_edges) * num_partitions

        # Instance cost: |V| * 2 * 0.54/3600 * t_transfer
        # t_transfer = max_e(num_partitions * s_part * 8 / throughput_e)
        # s_part = data_vol / num_partitions, so num_partitions * s_part = data_vol
        # t_transfer = max_e(data_vol * 8 / throughput_e)
        # We don't know data_vol, but for comparison we can use
        # t_transfer_proxy = max_e(1/throughput_e) since data_vol is constant
        max_inv_thr = 0
        for u, v in all_edges:
            t = G[u][v].get("throughput", 1.0)
            inv_t = 1.0 / max(t, 0.001)
            max_inv_thr = max(max_inv_thr, inv_t)

        # Actually for instance cost with bandwidth constraints:
        # All partitions on same path means the edge carrying most partitions = num_partitions
        # Node egress/ingress limits cause bandwidth splitting
        # Estimate congestion
        node_out_degree = defaultdict(int)
        node_in_degree = defaultdict(int)
        for u, v in all_edges:
            node_out_degree[u] += 1
            node_in_degree[v] += 1

        # Effective throughput considering bandwidth limits
        egress_limits = {"aws": 5, "gcp": 7, "azure": 16}
        ingress_limits = {"aws": 10, "gcp": 16, "azure": 16}
        n_vm = 2

        max_time_factor = 0
        for u, v in all_edges:
            edge_thr = G[u][v].get("throughput", 1.0)
            # Egress constraint at u
            prov_u = _provider(u)
            eg_limit = egress_limits.get(prov_u, 5) * n_vm
            out_deg = node_out_degree[u]
            eg_per_edge = eg_limit / max(out_deg, 1)
            # Ingress constraint at v
            prov_v = _provider(v)
            ig_limit = ingress_limits.get(prov_v, 10) * n_vm
            in_deg = node_in_degree[v]
            ig_per_edge = ig_limit / max(in_deg, 1)
            # Actual flow
            actual_flow = min(edge_thr, eg_per_edge, ig_per_edge)
            # Time factor: num_partitions * s_part * 8 / actual_flow
            # = data_vol * 8 / actual_flow (when all partitions on same edge)
            time_factor = 1.0 / max(actual_flow, 0.001)
            max_time_factor = max(max_time_factor, time_factor)

        instance_proxy = len(all_nodes) * 2 * (0.54 / 3600) * max_time_factor
        return egress + instance_proxy * 100  # scale instance proxy

    best_score = float('inf')
    best_paths = None
    for dst_paths, edges in candidates:
        score = eval_candidate(dst_paths, edges)
        if score < best_score:
            best_score = score
            best_paths = dst_paths

    # Fallback
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
