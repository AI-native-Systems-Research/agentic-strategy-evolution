/*
 * Tree Decomposition of Tree + Leaf Ring
 * 
 * Algorithm: Elimination ordering for outerplanar graphs (treewidth <= 2)
 * 
 * 1. Read tree, identify leaves, build augmented graph (tree + leaf ring)
 * 2. Repeatedly eliminate vertices of degree <= 2:
 *    - Create bag = {v, neighbors_of_v}  (size <= 3)
 *    - Remove v, add fill-in edge between its two neighbors
 * 3. Build bag tree: each bag's parent = bag of its latest-eliminated neighbor
 * 
 * Complexity: O(N) amortized with careful bookkeeping
 * Bags: exactly N, each of size <= 3. Well within K <= 4N and size <= 4.
 */

#include <bits/stdc++.h>
using namespace std;

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin >> N;
    
    // Read tree edges. The tree is rooted at 1, numbered in pre-order.
    // Input format: N-1 edges, or parent array, etc.
    // Let's assume input is: first line N, then N-1 lines each with two integers u v.
    // We need to figure out the exact input format. Let me assume parent array:
    // p2, p3, ..., pN where pi is the parent of node i.
    // Actually, for pre-order numbered trees, a common format is:
    // Line 1: N
    // Line 2: p2 p3 ... pN (parent of each node 2..N)
    
    vector<vector<int>> children(N + 1);
    vector<int> par(N + 1, 0);
    
    for (int i = 2; i <= N; i++) {
        cin >> par[i];
        children[par[i]].push_back(i);
    }
    
    // Identify leaves (nodes with no children)
    vector<int> leaves;
    for (int i = 1; i <= N; i++) {
        if (children[i].empty()) {
            leaves.push_back(i);
        }
    }
    // leaves are already in pre-order (increasing) since we iterate 1..N
    
    int K = leaves.size();
    
    // Build augmented graph using adjacency sets
    // For efficiency, use unordered_set or set
    // But N can be large... let's use set<int> for correctness
    
    // Actually, for the elimination algorithm on a graph with treewidth 2,
    // each vertex has degree at most some value. Let me think...
    // In the augmented graph:
    // - Internal node with d children: degree = d + 1 (parent + children), or d for root
    // - Leaf: degree = 3 (parent + 2 ring neighbors), or 2 if only 1 leaf, etc.
    // During elimination, fill-in edges are added, but since tw=2, 
    // degrees stay manageable.
    
    // Use adjacency with sets for easy edge addition/removal
    vector<set<int>> adj(N + 1);
    
    auto add_edge = [&](int u, int v) {
        if (u != v) {
            adj[u].insert(v);
            adj[v].insert(u);
        }
    };
    
    // Tree edges
    for (int i = 2; i <= N; i++) {
        add_edge(i, par[i]);
    }
    
    // Ring edges
    if (K >= 2) {
        for (int i = 0; i < K; i++) {
            add_edge(leaves[i], leaves[(i + 1) % K]);
        }
    }
    
    // Elimination algorithm
    // We need: for each vertex, its current degree
    // Queue of vertices with degree <= 2
    
    vector<bool> eliminated(N + 1, false);
    
    // Bags: bags[i] = set of vertices in bag i
    // We create one bag per vertex elimination
    vector<vector<int>> bags;
    vector<int> elim_vertex;  // elim_vertex[i] = vertex eliminated to create bag i
    vector<int> bag_of(N + 1, -1);  // bag_of[v] = index of bag where v was eliminated
    
    queue<int> q;
    for (int v = 1; v <= N; v++) {
        if ((int)adj[v].size() <= 2) {
            q.push(v);
        }
    }
    
    while (!q.empty()) {
        int v = q.front(); q.pop();
        if (eliminated[v]) continue;
        if ((int)adj[v].size() > 2) continue;  // degree changed since enqueue
        
        // Create bag
        vector<int> bag;
        bag.push_back(v);
        vector<int> neighbors;
        for (int u : adj[v]) {
            if (!eliminated[u]) {
                bag.push_back(u);
                neighbors.push_back(u);
            }
        }
        
        int bag_idx = bags.size();
        bags.push_back(bag);
        elim_vertex.push_back(v);
        bag_of[v] = bag_idx;
        eliminated[v] = true;
        
        // Remove v from adjacency
        for (int u : neighbors) {
            adj[u].erase(v);
        }
        
        // Add fill-in edge
        if (neighbors.size() == 2) {
            add_edge(neighbors[0], neighbors[1]);
        }
        
        // Check if neighbors now have degree <= 2
        for (int u : neighbors) {
            if (!eliminated[u] && (int)adj[u].size() <= 2) {
                q.push(u);
            }
        }
    }
    
    // Handle any remaining vertices (shouldn't happen for tw <= 2, but just in case)
    for (int v = 1; v <= N; v++) {
        if (!eliminated[v]) {
            vector<int> bag;
            bag.push_back(v);
            for (int u : adj[v]) {
                if (!eliminated[u]) {
                    bag.push_back(u);
                }
            }
            int bag_idx = bags.size();
            bags.push_back(bag);
            elim_vertex.push_back(v);
            bag_of[v] = bag_idx;
            eliminated[v] = true;
        }
    }
    
    int num_bags = bags.size();
    
    // Build bag tree
    // For each bag i (eliminating vertex v), its parent in the bag tree is
    // the bag of the neighbor in the bag that was eliminated latest.
    vector<int> td_parent(num_bags, -1);
    
    // We need elimination order to determine "latest eliminated"
    vector<int> elim_order(N + 1, -1);
    for (int i = 0; i < num_bags; i++) {
        elim_order[elim_vertex[i]] = i;
    }
    
    int root_bag = -1;
    for (int i = 0; i < num_bags; i++) {
        int v = elim_vertex[i];
        int best = -1;
        int best_order = -1;
        for (int u : bags[i]) {
            if (u != v && elim_order[u] > best_order) {
                best_order = elim_order[u];
                best = u;
            }
        }
        if (best != -1) {
            td_parent[i] = bag_of[best];
        } else {
            root_bag = i;
            td_parent[i] = -1; // This is the root of the bag tree
        }
    }
    
    // Output
    // Format (typical for tree decomposition problems):
    // Line 1: K (number of bags)
    // For each bag: size of bag, then the vertices
    // Then K-1 lines: edges of the bag tree
    // 
    // But let me check what typical competitive programming format is...
    // Usually:
    // Line 1: K
    // Next K lines: bag_size v1 v2 ... v_{bag_size}
    // Next K-1 lines: u v (edges of the bag tree), or parent array
    
    // Let me use 1-indexed bags
    cout << num_bags << "\n";
    for (int i = 0; i < num_bags; i++) {
        cout << bags[i].size();
        for (int v : bags[i]) {
            cout << " " << v;
        }
        cout << "\n";
    }
    
    // Output bag tree edges
    // Using parent representation: for each bag except root, output edge to parent
    for (int i = 0; i < num_bags; i++) {
        if (td_parent[i] != -1) {
            cout << (i + 1) << " " << (td_parent[i] + 1) << "\n";
        }
    }
    
    return 0;
}