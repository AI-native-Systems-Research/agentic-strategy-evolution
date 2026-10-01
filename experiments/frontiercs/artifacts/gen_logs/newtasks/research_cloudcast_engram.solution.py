class Solution:
    def solve(self, spec_path: str = None) -> dict:
        code = r'''
import networkx as nx
from collections import defaultdict
import random
import math

class BroadCastTopology:
    def __init__(self, src: str, dsts: list, num_partitions: int):
        self.src = src
        self.dsts = dsts
        self.num_partitions = int(num_partitions)
        self.paths = {dst: {str(i): None for i in range(self.num_partitions)} for dst in dsts}

    def append_dst_partition_path(self, dst: str, partition: int, path: list):
        partition = str(partition)
        if self.paths[dst][partition] is None:
            self.paths[dst][partition] = []
        self.paths[dst][partition].append(path)

    def set_dst_partition_paths(self, dst: str, partition: int, paths: list):
        partition = str(partition)
        self.paths[dst][partition] = paths

    def set_num_partitions(self, num_partitions: int):
        self.num_partitions = num_partitions


def search_algorithm(src, dsts, G, num_partitions):
    bc_topology = BroadCastTopology(src, dsts, num_partitions)
    
    # Extract network parameters from the graph
    # Try to get config info from graph attributes
    num_vms = 2
    
    # Provider-based bandwidth limits (Gbps per VM)
    ingress_limit_map = {"aws": 10, "gcp": 16, "azure": 16}
    egress_limit_map = {"aws": 5, "gcp": 7, "azure": 16}
    
    # Instance cost rates ($/hour per VM) - approximate
    instance_rate_map = {"aws": 3.0, "gcp": 3.0, "azure": 3.0}
    
    def get_provider(node):
        parts = node.split(":")
        return parts[0] if parts else "aws"
    
    def get_region(node):
        parts = node.split(":")
        return parts[1] if len(parts) > 1 else ""
    
    def get_node_egress_gbps(node):
        provider = get_provider(node)
        return egress_limit_map.get(provider, 5) * num_vms
    
    def get_node_ingress_gbps(node):
        provider = get_provider(node)
        return ingress_limit_map.get(provider, 10) * num_vms
    
    def get_node_instance_rate(node):
        provider = get_provider(node)
        return instance_rate_map.get(provider, 3.0) * num_vms
    
    # Try to figure out data volume from graph or use a reasonable default
    # The problem states data is split into num_partitions
    # We'll estimate data_vol. Common test: 1-100 GB
    # Actually let's try to read it from graph attrs
    data_vol_gb = 20.0  # default guess
    if hasattr(G, 'graph'):
        if 'data_vol' in G.graph:
            data_vol_gb = float(G.graph['data_vol'])
        if 'num_vms' in G.graph:
            num_vms = int(G.graph['num_vms'])
    
    partition_size_gb = data_vol_gb / num_partitions
    
    def path_edges_list(path):
        """Convert node path to list of [u, v, edge_data] for the topology."""
        edges = []
        for i in range(len(path) - 1):
            edges.append([path[i], path[i+1], dict(G[path[i]][path[i+1]])])
        return edges
    
    def path_cost_per_gb(path):
        """Total egress cost per GB for a path."""
        total = 0.0
        for i in range(len(path) - 1):
            total += G[path[i]][path[i+1]].get("cost", 0.0)
        return total
    
    # Find K shortest paths for each destination
    K_PATHS = 20
    dst_candidate_paths = {}
    for dst in dsts:
        try:
            candidates = []
            gen = nx.shortest_simple_paths(G, src, dst, weight="cost")
            for i, path in enumerate(gen):
                if i >= K_PATHS:
                    break
                candidates.append(path)
            dst_candidate_paths[dst] = candidates
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            dst_candidate_paths[dst] = []
    
    # Also find paths optimized for throughput (shortest hop count = likely highest throughput)
    for dst in dsts:
        try:
            sp = nx.shortest_path(G, src, dst)  # unweighted = fewest hops
            if sp not in dst_candidate_paths[dst]:
                dst_candidate_paths[dst].append(sp)
        except:
            pass
        # Also try by throughput (negative for max)
        try:
            # Create a throughput-weighted graph (invert throughput for shortest path)
            tp_path_gen = nx.shortest_simple_paths(G, src, dst, weight="cost")
            # Already covered above
        except:
            pass
    
    def compute_total_cost(assignment):
        """
        Compute estimated total cost given an assignment of (dst, partition) -> path_index.
        
        Total cost = egress_cost + instance_cost
        egress_cost = sum over unique edges of (partitions_on_edge * partition_size_gb * edge_cost_per_gb)
        instance_cost = sum over nodes of (instance_rate/3600 * transfer_time)
        transfer_time = max over all edges of (partitions_on_edge * partition_size_gb * 8 / edge_bandwidth_gbps)
        
        edge_bandwidth_gbps = min(edge_throughput, 
                                   src_node_egress / num_outgoing_edges_at_src,
                                   dst_node_ingress / num_incoming_edges_at_dst)
        """
        edge_partition_count = defaultdict(int)
        nodes_used = set()
        node_out_edges = defaultdict(set)
        node_in_edges = defaultdict(set)
        
        for (dst, p), path_idx in assignment.items():
            candidates = dst_candidate_paths.get(dst, [])
            if not candidates or path_idx >= len(candidates):
                continue
            path = candidates[path_idx]
            for i in range(len(path) - 1):
                u, v = path[i], path[i+1]
                ek = (u, v)
                edge_partition_count[ek] += 1
                node_out_edges[u].add(ek)
                node_in_edges[v].add(ek)
                nodes_used.add(u)
                nodes_used.add(v)
        
        if not edge_partition_count:
            return float('inf')
        
        # Egress cost
        egress_cost = 0.0
        for ek, count in edge_partition_count.items():
            u, v = ek
            cost_per_gb = G[u][v].get("cost", 0.0)
            egress_cost += count * partition_size_gb * cost_per_gb
        
        # Transfer time: max over all edges
        max_transfer_time = 0.0
        for ek, count in edge_partition_count.items():
            u, v = ek
            edge_tp = G[u][v].get("throughput", 1.0)  # Gbps
            
            # Egress limit at u split among outgoing edges
            n_out = len(node_out_edges[u])
            eg_bw = get_node_egress_gbps(u) / max(n_out, 1)
            
            # Ingress limit at v split among incoming edges
            n_in = len(node_in_edges[v])
            ig_bw = get_node_ingress_gbps(v) / max(n_in, 1)
            
            actual_bw = min(edge_tp, eg_bw, ig_bw)
            if actual_bw <= 0:
                actual_bw = 0.001
            
            # Data on this edge = count * partition_size_gb (in Gb = *8)
            data_gb_on_edge = count * partition_size_gb
            transfer_time = data_gb_on_edge * 8.0 / actual_bw  # seconds
            max_transfer_time = max(max_transfer_time, transfer_time)
        
        # Instance cost
        instance_cost = 0.0
        for node in nodes_used:
            rate = get_node_instance_rate(node)
            instance_cost += (rate / 3600.0) * max_transfer_time
        
        return egress_cost + instance_cost
    
    def compute_total_cost_detailed(assignment):
        """Return (egress_cost, instance_cost, transfer_time, total)"""
        edge_partition_count = defaultdict(int)
        nodes_used = set()
        node_out_edges = defaultdict(set)
        node_in_edges = defaultdict(set)
        
        for (dst, p), path_idx in assignment.items():
            candidates = dst_candidate_paths.get(dst, [])
            if not candidates or path_idx >= len(candidates):
                continue
            path = candidates[path_idx]
            for i in range(len(path) - 1):
                u, v = path[i], path[i+1]
                ek = (u, v)
                edge_partition_count[ek] += 1
                node_out_edges[u].add(ek)
                node_in_edges[v].add(ek)
                nodes_used.add(u)
                nodes_used.add(v)
        
        egress_cost = 0.0
        for ek, count in edge_partition_count.items():
            u, v = ek
            cost_per_gb = G[u][v].get("cost", 0.0)
            egress_cost += count * partition_size_gb * cost_per_gb
        
        max_transfer_time = 0.0
        for ek, count in edge_partition_count.items():
            u, v = ek
            edge_tp = G[u][v].get("throughput", 1.0)
            n_out = len(node_out_edges[u])
            eg_bw = get_node_egress_gbps(u) / max(n_out, 1)
            n_in = len(node_in_edges[v])
            ig_bw = get_node_ingress_gbps(v) / max(n_in, 1)
            actual_bw = min(edge_tp, eg_bw, ig_bw)
            if actual_bw <= 0:
                actual_bw = 0.001
            data_gb_on_edge = count * partition_size_gb
            transfer_time = data_gb_on_edge * 8.0 / actual_bw
            max_transfer_time = max(max_transfer_time, transfer_time)
        
        instance_cost = 0.0
        for node in nodes_used:
            rate = get_node_instance_rate(node)
            instance_cost += (rate / 3600.0) * max_transfer_time
        
        return egress_cost, instance_cost, max_transfer_time, egress_cost + instance_cost
    
    # ================================================================
    # Strategy 1: All partitions on shortest cost path
    # ================================================================
    def strategy_cheapest():
        assignment = {}
        for dst in dsts:
            candidates = dst_candidate_paths[dst]
            if not candidates:
                continue
            for p in range(num_partitions):
                assignment[(dst, p)] = 0
        return assignment
    
    # ================================================================
    # Strategy 2: Spread evenly across top paths
    # ================================================================
    def strategy_spread_even():
        assignment = {}
        for dst in dsts:
            candidates = dst_candidate_paths[dst]
            if not candidates:
                continue
            # Use min of available paths and num_partitions
            n_use = min(len(candidates), num_partitions)
            for p in range(num_partitions):
                assignment[(dst, p)] = p % n_use
        return assignment
    
    # ================================================================
    # Strategy 3: Greedy partition assignment with accurate cost model
    # ================================================================
    def strategy_greedy_accurate():
        assignment = {}
        edge_partition_count = defaultdict(int)
        nodes_used = set()
        node_out_edges = defaultdict(set)
        node_in_edges = defaultdict(set)
        
        # Process all (dst, partition) pairs
        # Order: process destinations with fewer path options first (more constrained)
        dst_order = sorted(dsts, key=lambda d: len(dst_candidate_paths.get(d, [])))
        
        for dst in dst_order:
            candidates = dst_candidate_paths[dst]
            if not candidates:
                continue
            
            for p in range(num_partitions):
                best_idx = 0
                best_cost_increase = float('inf')
                
                for idx, cand_path in enumerate(candidates):
                    # Compute incremental cost of adding this partition to this path
                    
                    # Temporary state
                    temp_epc = defaultdict(int, edge_partition_count)
                    temp_nodes = set(nodes_used)
                    temp_noe = defaultdict(set)
                    for k, v in node_out_edges.items():
                        temp_noe[k] = set(v)
                    temp_nie = defaultdict(set)
                    for k, v in node_in_edges.items():
                        temp_nie[k] = set(v)
                    
                    for i in range(len(cand_path) - 1):
                        u, v = cand_path[i], cand_path[i+1]
                        ek = (u, v)
                        temp_epc[ek] += 1
                        temp_noe[u].add(ek)
                        temp_nie[v].add(ek)
                        temp_nodes.add(u)
                        temp_nodes.add(v)
                    
                    # Compute egress cost increment
                    egress_inc = path_cost_per_gb(cand_path) * partition_size_gb
                    
                    # Compute new max transfer time
                    max_tt = 0.0
                    for ek, count in temp_epc.items():
                        u, v = ek
                        edge_tp = G[u][v].get("throughput", 1.0)
                        n_out = len(temp_noe[u])
                        eg_bw = get_node_egress_gbps(u) / max(n_out, 1)
                        n_in = len(temp_nie[v])
                        ig_bw = get_node_ingress_gbps(v) / max(n_in, 1)
                        actual_bw = min(edge_tp, eg_bw, ig_bw)
                        if actual_bw <= 0:
                            actual_bw = 0.001
                        tt = count * partition_size_gb * 8.0 / actual_bw
                        max_tt = max(max_tt, tt)
                    
                    # Instance cost
                    inst_cost = 0.0
                    for node in temp_nodes:
                        rate = get_node_instance_rate(node)
                        inst_cost += (rate / 3600.0) * max_tt
                    
                    total_cost = egress_inc + inst_cost  # Note: egress_inc is incremental, inst_cost is total
                    # Actually we should compute total cost properly
                    # Let's compute total egress cost too
                    total_egress = 0.0
                    for ek, count in temp_epc.items():
                        u, v = ek
                        total_egress += count * partition_size_gb * G[u][v].get("cost", 0.0)
                    
                    total_cost = total_egress + inst_cost
                    
                    if total_cost < best_cost_increase:
                        best_cost_increase = total_cost
                        best_idx = idx
                
                assignment[(dst, p)] = best_idx
                
                # Commit
                chosen = candidates[best_idx]
                for i in range(len(chosen) - 1):
                    u, v = chosen[i], chosen[i+1]
                    ek = (u, v)
                    edge_partition_count[ek] += 1
                    node_out_edges[u].add(ek)
                    node_in_edges[v].add(ek)
                    nodes_used.add(u)
                    nodes_used.add(v)
        
        return assignment
    
    # ================================================================
    # Strategy 4: Steiner-tree inspired - find a good shared tree
    # ================================================================
    def strategy_steiner_tree():
        """Use a minimum cost Steiner tree approach - all partitions use the tree."""
        # Build shortest path tree from src to all dsts using cost
        assignment = {}
        
        # For each dst, use cheapest path but try to reuse edges
        # Approximate Steiner tree: iteratively add closest destination to current tree
        tree_nodes = {src}
        tree_edges = set()
        dst_paths = {}
        
        remaining = list(dsts)
        
        while remaining:
            best_dst = None
            best_path = None
            best_cost = float('inf')
            
            for dst in remaining:
                # Find cheapest path from any tree node to dst
                for tree_node in tree_nodes:
                    try:
                        path = nx.shortest_path(G, tree_node, dst, weight="cost")
                        cost = sum(G[path[i]][path[i+1]]["cost"] for i in range(len(path)-1))
                        if cost < best_cost:
                            best_cost = cost
                            best_path = path
                            best_dst = dst
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        pass
            
            if best_dst is None:
                # Can't reach remaining destinations
                break
            
            remaining.remove(best_dst)
            
            # Add path to tree
            for node in best_path:
                tree_nodes.add(node)
            for i in range(len(best_path)-1):
                tree_edges.add((best_path[i], best_path[i+1]))
            
            # Store path from src to dst through tree
            # We need the full path from src, not from the intermediate tree node
            try:
                # Build a subgraph of the tree and find path in it
                tree_graph = nx.DiGraph()
                for u, v in tree_edges:
                    tree_graph.add_edge(u, v, **G[u][v])
                full_path = nx.shortest_path(tree_graph, src, best_dst, weight="cost")
                dst_paths[best_dst] = full_path
            except:
                # Fallback to direct path
                candidates = dst_candidate_paths.get(best_dst, [])
                if candidates:
                    dst_paths[best_dst] = candidates[0]
        
        # Assign all partitions to the Steiner tree paths
        for dst in dsts:
            if dst in dst_paths:
                path = dst_paths[dst]
                # Find this path's index in candidates, or add it
                candidates = dst_candidate_paths[dst]
                path_idx = None
                for idx, cp in enumerate(candidates):
                    if cp == path:
                        path_idx = idx
                        break
                if path_idx is None:
                    # Add it
                    candidates.append(path)
                    path_idx = len(candidates) - 1
                
                for p in range(num_partitions):
                    assignment[(dst, p)] = path_idx
            else:
                candidates = dst_candidate_paths.get(dst, [])
                if candidates:
                    for p in range(num_partitions):
                        assignment[(dst, p)] = 0
        
        return assignment
    
    # ================================================================
    # Strategy 5: Optimize num_partitions
    # ================================================================
    # The number of partitions affects the tradeoff. More partitions = more flexibility
    # but the evaluator seems to set num_partitions from outside.
    # We'll keep the given num_partitions.
    
    # ================================================================
    # Try all strategies, evaluate, pick best
    # ================================================================
    strategies = [
        ("cheapest", strategy_cheapest),
        ("spread", strategy_spread_even),
        ("greedy", strategy_greedy_accurate),
        ("steiner", strategy_steiner_tree),
    ]
    
    best_assignment = None
    best_total_cost = float('inf')
    best_name = ""
    
    for name, strat_fn in strategies:
        try:
            assignment = strat_fn()
            cost = compute_total_cost(assignment)
            if cost < best_total_cost:
                best_total_cost = cost
                best_assignment = assignment
                best_name = name
        except Exception as e:
            pass
    
    if best_assignment is None:
        best_assignment = strategy_cheapest()
        best_total_cost = compute_total_cost(best_assignment)
    
    # ================================================================
    # Local search improvement (simulated annealing)
    # ================================================================
    current_assignment = dict(best_assignment)
    current_cost = best_total_cost
    
    random.seed(42)
    
    temperature = current_cost * 0.1 if current_cost > 0 and current_cost < float('inf') else 1.0
    cooling_rate = 0.995
    
    n_items = num_partitions * len(dsts)
    max_iters = min(2000, n_items * 10)
    
    all_keys = [(dst, p) for dst in dsts for p in range(num_partitions)]
    
    for iteration in range(max_iters):
        if not all_keys:
            break
        
        key = random.choice(all_keys)
        dst, p = key
        
        candidates = dst_candidate_paths.get(dst, [])
        if not candidates or len(candidates) <= 1:
            continue
        
        current_idx = current_assignment.get(key, 0)
        new_idx = random.randint(0, len(candidates) - 1)
        if new_idx == current_idx:
            continue
        
        # Try the swap
        test_assignment = dict(current_assignment)
        test_assignment[key] = new_idx
        test_cost = compute_total_cost(test_assignment)
        
        delta = test_cost - current_cost
        
        if delta < 0 or (temperature > 0 and random.random() < math.exp(-delta / max(temperature, 1e-10))):
            current_assignment = test_assignment
            current_cost = test_cost
        
        temperature *= cooling_rate
    
    if current_cost < best_total_cost:
        best_assignment = current_assignment
        best_total_cost = current_cost
    
    # ================================================================
    # Try different partition counts if allowed
    # ================================================================
    # Test if fewer partitions with single path might be cheaper
    # (reduces overhead if instance cost dominates)
    for test_np in [1, 2, 4, 8, num_partitions]:
        if test_np > num_partitions:
            continue
        if test_np == num_partitions:
            continue  # already tested
        
        test_ps = data_vol_gb / test_np
        
        # Simple assignment: all partitions on cheapest path
        test_assignment = {}
        for dst in dsts:
            candidates = dst_candidate_paths[dst]
            if not candidates:
                continue
            for p in range(test_np):
                test_assignment[(dst, p)] = 0
        
        # Can't easily change num_partitions in evaluation since partition_size changes
        # Skip this for now - the evaluator controls num_partitions
    
    # ================================================================
    # Build final topology
    # ================================================================
    for dst in dsts:
        candidates = dst_candidate_paths.get(dst, [])
        if not candidates:
            continue
        for p in range(num_partitions):
            key = (dst, p)
            path_idx = best_assignment.get(key, 0)
            if path_idx >= len(candidates):
                path_idx = 0
            path = candidates[path_idx]
            edges = path_edges_list(path)
            bc_topology.set_dst_partition_paths(dst, p, edges)
    
    return bc_topology
'''
        return {"code": code}
