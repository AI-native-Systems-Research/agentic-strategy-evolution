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
    data_vol = 300  # estimate
    s_part = data_vol / num_partitions

    def compute_cost_precise(dst_paths, partition_assign=None):
        """Compute total cost with precise bandwidth model.
        partition_assign: dict (dst, part_id) -> path_nodes, or None for uniform."""
        if not dst_paths:
            return float('inf')

        # Count partitions per edge, collect nodes
        edge_parts = defaultdict(set)  # edge -> set of (dst, part_id) tuples
        all_nodes = set()

        for d in dsts:
            for p in range(num_partitions):
                if partition_assign and (d, p) in partition_assign:
                    path = partition_assign[(d, p)]
                else:
                    path = dst_paths.get(d)
                if path is None:
                    return float('inf')
                for i in range(len(path) - 1):
                    e = (path[i], path[i+1])
                    edge_parts[e].add((d, p))
                    all_nodes.add(path[i])
                    all_nodes.add(path[i+1])

        # Egress cost: sum_e(|P_e| * s_part * c_e)
        egress = 0
        for e, parts in edge_parts.items():
            u, v = e
            c = G[u][v].get("cost", 0)
            egress += len(parts) * s_part * c

        # Bandwidth model: equal distribution among edges at each node
        # Count outgoing/incoming edges per node
        node_out_edges = defaultdict(set)
        node_in_edges = defaultdict(set)
        for e in edge_parts:
            node_out_edges[e[0]].add(e)
            node_in_edges[e[1]].add(e)

        # Transfer time: max over all dst,partition,edge of (|P_e| * s_part * 8 / f_e)
        # f_e = min(throughput_e, egress_limit_u / out_degree_u, ingress_limit_v / in_degree_v)
        max_time = 0
        for e, parts in edge_parts.items():
            u, v = e
            edge_thr = G[u][v].get("throughput", 1.0)
            eg_lim = egress_limits.get(_provider(u), 5) * n_vm
            ig_lim = ingress_limits.get(_provider(v), 10) * n_vm
            out_deg = len(node_out_edges[u])
            in_deg = len(node_in_edges[v])
            eg_per = eg_lim / max(out_deg, 1)
            ig_per = ig_lim / max(in_deg, 1)
            actual_flow = min(edge_thr, eg_per, ig_per)
            pe = len(parts)
            time_e = pe * s_part * 8 / max(actual_flow, 0.001)
            max_time = max(max_time, time_e)

        instance = len(all_nodes) * n_vm * (r_instance / 3600) * max_time
        return egress + instance

    # --- Candidate generation ---
    def build_spt(weight_fn):
        try:
            _, paths = nx.single_source_dijkstra(G, src, weight=weight_fn)
        except:
            return None
        dp = {d: paths[d] for d in dsts if d in paths}
        return dp if len(dp) == len(dsts) else None

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

    # Weight functions
    def make_bal(a):
        def wf(u, v, d):
            return d.get("cost", 0) + a / max(d.get("throughput", 1.0), 0.001)
        return wf

    def make_cross(p):
        def wf(u, v, d):
            c = d.get("cost", 0)
            return c * (p if _provider(u) != _provider(v) else 1.0)
        return wf

    def make_hop_penalty(h):
        def wf(u, v, d):
            return d.get("cost", 0) + h
        return wf

    weight_fns = ["cost"]
    for a in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]:
        weight_fns.append(make_bal(a))
    for p in [1.1, 1.2, 1.5, 2.0, 3.0]:
        weight_fns.append(make_cross(p))
    for h in [0.001, 0.005, 0.01, 0.05]:
        weight_fns.append(make_hop_penalty(h))

    candidates = []
    for wf in weight_fns:
        for builder in [build_spt, build_greedy_steiner]:
            result = builder(wf)
            if result:
                candidates.append(result)

    # --- Evaluate and pick best ---
    best_cost = float('inf')
    best_paths = None

    for cand in candidates:
        cost = compute_cost_precise(cand)
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

    # --- Local search: per-destination path replacement ---
    for iteration in range(3):
        improved = False
        for dst in dsts:
            current_cost = compute_cost_precise(best_paths)
            for wf in weight_fns:
                try:
                    if wf == "cost":
                        alt = nx.dijkstra_path(G, src, dst, weight="cost")
                    else:
                        alt = nx.dijkstra_path(G, src, dst, weight=wf)
                except:
                    continue
                test = dict(best_paths)
                test[dst] = alt
                c = compute_cost_precise(test)
                if c < current_cost - 0.01:
                    best_paths = test
                    current_cost = c
                    improved = True
        if not improved:
            break

    # --- Try partition splitting: spread partitions across 2 trees ---
    # Find a second good tree that's different from best
    second_best = None
    second_cost = float('inf')
    for cand in candidates:
        if cand is best_paths:
            continue
        c = compute_cost_precise(cand)
        if c < second_cost:
            second_cost = c
            second_best = cand

    if second_best is not None and num_partitions >= 2:
        # Try even split
        for k in range(1, num_partitions):
            assign = {}
            for d in dsts:
                for p in range(k):
                    assign[(d, p)] = best_paths.get(d)
                for p in range(k, num_partitions):
                    assign[(d, p)] = second_best.get(d)
            c = compute_cost_precise(best_paths, assign)
            if c < best_cost:
                best_cost = c
                # Record winning split
                winning_assign = dict(assign)

    try:
        winning_assign
        use_split = True
    except NameError:
        use_split = False
        winning_assign = None

    # --- Build topology ---
    for dst in dsts:
        for p in range(num_partitions):
            if use_split and winning_assign:
                path = winning_assign.get((dst, p), best_paths.get(dst))
            else:
                path = best_paths.get(dst)
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
