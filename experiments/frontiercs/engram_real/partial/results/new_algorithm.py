# MILP-based broadcast routing - Iterative Steiner Tree approach
# Strategy: Solve one Steiner tree at a time for groups of partitions
# After each solve, update remaining capacity and re-solve for next group
# This handles multicast properly while staying tractable
import networkx as nx
import json
import os
import time
import math
from typing import Dict, List
from itertools import islice

def search_algorithm(src, dsts, G, num_partitions):
    import pulp
    from pulp import LpProblem, LpMinimize, LpVariable, lpSum, LpBinary, LpContinuous, LpInteger, PULP_CBC_CMD, value
    
    start_time = time.time()
    print(f"=== Iterative Steiner Tree MILP ===")
    print(f"Source: {src}, Destinations: {dsts}, Partitions: {num_partitions}")
    
    TRANSFER_SIZE = 300  # GB
    VM_COST_PER_SEC = 0.00015  # $/second  
    VM_LIMIT = 2  # VMs per region
    partition_size = TRANSFER_SIZE / num_partitions  # GB per partition
    
    provider_egress = {'aws': 5, 'gcp': 7, 'azure': 16}
    provider_ingress = {'aws': 10, 'gcp': 16, 'azure': 16}
    
    def get_provider(node):
        return node.split(':')[0]
    
    h = G.copy()
    h.remove_edges_from(list(h.in_edges(src)) + list(nx.selfloop_edges(h)))
    
    # Build candidate nodes - only include nodes on promising paths
    candidate_nodes = set([src] + dsts)
    
    for dst in dsts:
        try:
            paths = list(islice(nx.shortest_simple_paths(h, src, dst, weight='cost'), 8))
            for path in paths:
                candidate_nodes.update(path)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass
    
    # Add neighbors of src and dsts
    for node in [src] + dsts:
        for neighbor in h.successors(node):
            candidate_nodes.add(neighbor)
    
    # Add relay candidates between destinations
    for i, d1 in enumerate(dsts):
        for d2 in dsts[i+1:]:
            try:
                path = nx.dijkstra_path(h, d1, d2, weight='cost')
                candidate_nodes.update(path)
            except:
                pass
    
    print(f"Candidate nodes: {len(candidate_nodes)}")
    
    subG = h.subgraph(candidate_nodes).copy()
    subG.remove_edges_from(list(subG.in_edges(src)))
    
    nodes_list = list(subG.nodes())
    edges_list = list(subG.edges())
    
    out_edges = {node: [] for node in nodes_list}
    in_edges_map = {node: [] for node in nodes_list}
    for (u, v) in edges_list:
        out_edges[u].append((u, v))
        in_edges_map[v].append((u, v))
    
    print(f"Subgraph: {len(nodes_list)} nodes, {len(edges_list)} edges")
    
    bc_topology = BroadCastTopology(src, dsts, num_partitions)
    
    # Track remaining capacity (in terms of how much data can still flow)
    # We'll track edge usage in partition-copies
    edge_usage = {(u, v): 0 for (u, v) in edges_list}
    node_out_usage = {node: 0 for node in nodes_list}
    node_in_usage = {node: 0 for node in nodes_list}
    
    remaining_partitions = num_partitions
    partition_offset = 0
    iteration = 0
    
    while remaining_partitions > 0:
        iteration += 1
        print(f"\n--- Iteration {iteration}: {remaining_partitions} partitions remaining ---")
        
        if time.time() - start_time > 150:
            print("Time limit approaching, using fallback for remaining")
            break
        
        # Solve for how many partitions to route through one Steiner tree
        prob = LpProblem(f"Steiner_{iteration}", LpMinimize)
        
        # Binary: edge in tree
        y = {}
        for (u, v) in edges_list:
            y[(u, v)] = LpVariable(f"y_{u}_{v}", 0, 1, cat=LpBinary)
        
        # How many partitions use this tree
        w = LpVariable("w", 1, remaining_partitions, cat=LpInteger)
        
        # Flow variables for connectivity
        fl = {}
        for dst in dsts:
            fl[dst] = {}
            for (u, v) in edges_list:
                fl[dst][(u, v)] = LpVariable(f"fl_{dst}_{u}_{v}", 0, 1, cat=LpContinuous)
        
        # Transfer time for the TOTAL solution (all partitions including previously assigned)
        T = LpVariable("T", 0, cat=LpContinuous)
        
        # Auxiliary: z[(u,v)] = w * y[(u,v)] (linearized)
        z = {}
        for (u, v) in edges_list:
            z[(u, v)] = LpVariable(f"z_{u}_{v}", 0, remaining_partitions, cat=LpInteger)
            prob += z[(u, v)] <= w, f"z_ub1_{u}_{v}"
            prob += z[(u, v)] <= remaining_partitions * y[(u, v)], f"z_ub2_{u}_{v}"
            prob += z[(u, v)] >= w - remaining_partitions * (1 - y[(u, v)]), f"z_lb_{u}_{v}"
        
        # Total edge usage = previous + new
        # n[(u,v)] = edge_usage[(u,v)] + z[(u,v)]
        
        # Egress cost for new partitions only
        egress_cost_new = lpSum([z[(u, v)] * partition_size * subG[u][v]['cost'] for (u, v) in edges_list])
        
        # Instance cost uses total time T
        num_active_est = 1 + len(dsts) + 3
        instance_cost = T * VM_COST_PER_SEC * num_active_est * VM_LIMIT
        
        prob += egress_cost_new + instance_cost, "Cost"
        
        # Connectivity: flow from src to each dst through tree
        for dst in dsts:
            for node in nodes_list:
                out_fl = lpSum([fl[dst][e] for e in out_edges.get(node, [])])
                in_fl = lpSum([fl[dst][e] for e in in_edges_map.get(node, [])])
                
                if node == src:
                    prob += out_fl - in_fl == 1, f"fc_{dst}_{node}"
                elif node == dst:
                    prob += in_fl - out_fl == 1, f"fc_{dst}_{node}"
                else:
                    prob += out_fl - in_fl == 0, f"fc_{dst}_{node}"
            
            for (u, v) in edges_list:
                prob += fl[dst][(u, v)] <= y[(u, v)], f"fe_{dst}_{u}_{v}"
        
        # Time constraints: (edge_usage + z) * partition_size * 8 / throughput <= T
        for (u, v) in edges_list:
            throughput = subG[u][v]['throughput']
            total_load = edge_usage[(u, v)] + z[(u, v)]
            prob += total_load * partition_size * 8 <= T * throughput, f"tc_{u}_{v}"
        
        # Node egress/ingress: (existing + new) must fit in T
        for node in nodes_list:
            provider = get_provider(node)
            eg_lim = provider_egress[provider] * VM_LIMIT
            ig_lim = provider_ingress[provider] * VM_LIMIT
            
            new_out = lpSum([z[e] * partition_size * 8 for e in out_edges.get(node, [])])
            existing_out = sum([edge_usage[e] * partition_size * 8 for e in out_edges.get(node, [])])
            prob += new_out + existing_out <= T * eg_lim, f"eg_{node}"
            
            new_in = lpSum([z[e] * partition_size * 8 for e in in_edges_map.get(node, [])])
            existing_in = sum([edge_usage[e] * partition_size * 8 for e in in_edges_map.get(node, [])])
            prob += new_in + existing_in <= T * ig_lim, f"ig_{node}"
        
        solver = PULP_CBC_CMD(msg=0, timeLimit=60, threads=4)
        prob.solve(solver)
        
        if prob.status != 1:
            print(f"Solver failed with status {prob.status}, breaking")
            break
        
        w_val = int(round(value(w)))
        T_val = value(T)
        print(f"Group size: {w_val}, T: {T_val:.2f}s, Obj: {value(prob.objective):.2f}")
        
        # Extract tree and paths
        tree_graph = nx.DiGraph()
        for (u, v) in edges_list:
            if value(y[(u, v)]) > 0.5:
                tree_graph.add_edge(u, v)
                print(f"  Tree edge: {u} -> {v} (cost={subG[u][v]['cost']})")
        
        # Update edge usage
        for (u, v) in edges_list:
            z_val = int(round(value(z[(u, v)])))
            if z_val > 0:
                edge_usage[(u, v)] += z_val
        
        # Assign paths to partitions
        for dst in dsts:
            try:
                path = nx.shortest_path(tree_graph, src, dst)
                for p_idx in range(partition_offset, partition_offset + w_val):
                    for i in range(len(path) - 1):
                        u, v = path[i], path[i+1]
                        bc_topology.append_dst_partition_path(dst, p_idx, [u, v, G[u][v]])
            except nx.NetworkXNoPath:
                print(f"WARNING: No tree path to {dst}, using fallback")
                fallback = nx.dijkstra_path(h, src, dst, weight='cost')
                for p_idx in range(partition_offset, partition_offset + w_val):
                    for i in range(len(fallback) - 1):
                        u, v = fallback[i], fallback[i+1]
                        bc_topology.append_dst_partition_path(dst, p_idx, [u, v, G[u][v]])
        
        partition_offset += w_val
        remaining_partitions -= w_val
    
    # Handle any remaining partitions with fallback
    if remaining_partitions > 0:
        print(f"Fallback for {remaining_partitions} remaining partitions")
        for dst in dsts:
            path = nx.dijkstra_path(h, src, dst, weight='cost')
            for p_idx in range(partition_offset, partition_offset + remaining_partitions):
                for i in range(len(path) - 1):
                    s, t = path[i], path[i+1]
                    bc_topology.append_dst_partition_path(dst, p_idx, [s, t, G[s][t]])
    
    print(f"\nTotal time: {time.time() - start_time:.2f}s")
    return bc_topology
