import networkx as nx

class Solution:
    def solve(self, spec_path: str = None) -> dict:
        return {"code": r"""
import networkx as nx
import heapq
from collections import deque

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
        self.paths[dst][str(partition)] = paths

    def set_num_partitions(self, num_partitions):
        self.num_partitions = num_partitions


def search_algorithm(src, dsts, G, num_partitions):
    bc = BroadCastTopology(src, dsts, num_partitions)

    nodes = list(G.nodes())
    n = len(nodes)
    node_idx = {v: i for i, v in enumerate(nodes)}
    k = len(dsts)
    INF = float('inf')
    full_mask = (1 << k) - 1

    # Throughput-aware edge weight: cost + tiny penalty for low throughput
    # epsilon is small enough to not change the cost-optimal tree,
    # but breaks ties in favor of high-throughput edges
    EPS = 1e-9

    def edge_weight(u, v):
        d = G[u][v]
        # Lower throughput = higher weight (small penalty)
        return d['cost'] + EPS / max(d['throughput'], 0.001)

    # Precompute single-source shortest paths using modified weight
    sp_cost = {}
    sp_pred = {}
    for v in nodes:
        # Custom Dijkstra with modified weight
        dist_v = {v: 0.0}
        pred_v = {}
        h = [(0.0, v)]
        while h:
            d, u = heapq.heappop(h)
            if d > dist_v.get(u, INF):
                continue
            for w in G.successors(u):
                nd = d + edge_weight(u, w)
                if nd < dist_v.get(w, INF):
                    dist_v[w] = nd
                    pred_v[w] = u
                    heapq.heappush(h, (nd, w))
        sp_cost[v] = dist_v
        sp_pred[v] = pred_v

    # DP tables
    dp = [[INF] * n for _ in range(full_mask + 1)]
    parent = [[None] * n for _ in range(full_mask + 1)]

    # Base case
    for i, t in enumerate(dsts):
        mask = 1 << i
        for vi, v in enumerate(nodes):
            if t in sp_cost[v]:
                dp[mask][vi] = sp_cost[v][t]
                parent[mask][vi] = ('leaf', i)

    for S in range(1, full_mask + 1):
        if S & (S - 1) != 0:
            sub = (S - 1) & S
            while sub > 0:
                comp = S ^ sub
                if comp > 0 and sub > comp:
                    for vi in range(n):
                        val = dp[sub][vi] + dp[comp][vi]
                        if val < dp[S][vi]:
                            dp[S][vi] = val
                            parent[S][vi] = ('merge', sub, comp)
                sub = (sub - 1) & S

        h = []
        for vi in range(n):
            if dp[S][vi] < INF:
                heapq.heappush(h, (dp[S][vi], vi))

        while h:
            cost_v, vi = heapq.heappop(h)
            if cost_v > dp[S][vi]:
                continue
            v = nodes[vi]
            for u in G.predecessors(v):
                ui = node_idx[u]
                new_cost = edge_weight(u, v) + cost_v
                if new_cost < dp[S][ui]:
                    dp[S][ui] = new_cost
                    parent[S][ui] = ('extend', vi)
                    heapq.heappush(h, (new_cost, ui))

    src_idx = node_idx[src]
    tree_edges = set()

    def reconstruct(mask, vi):
        info = parent[mask][vi]
        if info is None:
            return
        tag = info[0]
        if tag == 'leaf':
            t_idx = info[1]
            t = dsts[t_idx]
            v = nodes[vi]
            cur = t
            while cur != v:
                prev = sp_pred[v][cur]
                tree_edges.add((prev, cur))
                cur = prev
        elif tag == 'merge':
            sub1, sub2 = info[1], info[2]
            reconstruct(sub1, vi)
            reconstruct(sub2, vi)
        elif tag == 'extend':
            from_vi = info[1]
            v = nodes[vi]
            w = nodes[from_vi]
            tree_edges.add((v, w))
            reconstruct(mask, from_vi)

    reconstruct(full_mask, src_idx)

    adj = {}
    for u, v in tree_edges:
        if u not in adj:
            adj[u] = []
        adj[u].append(v)

    parent_map = {src: None}
    queue = deque([src])
    while queue:
        u = queue.popleft()
        if u in adj:
            for v in adj[u]:
                if v not in parent_map:
                    parent_map[v] = u
                    queue.append(v)

    for dst in dsts:
        path_nodes = []
        cur = dst
        while cur is not None:
            path_nodes.append(cur)
            cur = parent_map.get(cur)
        path_nodes.reverse()

        for p in range(num_partitions):
            for i in range(len(path_nodes) - 1):
                u, v = path_nodes[i], path_nodes[i + 1]
                bc.append_dst_partition_path(dst, p, [u, v, G[u][v]])

    return bc
"""}
