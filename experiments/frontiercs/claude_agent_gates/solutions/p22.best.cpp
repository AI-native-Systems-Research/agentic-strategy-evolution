// Approach: Euler tour chain tree decomposition
// For the tree + leaf ring graph, build a tree decomposition where:
// - Each bag corresponds to a step in the Euler tour of the tree
// - Bags are chained in Euler tour order
// - Each bag contains: {u, v, prev_leaf, first_leaf} (deduplicated)
// - Bag size <= 4, total bags = 2(N-1) <= 4N
#include <bits/stdc++.h>
using namespace std;

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    int N;
    cin >> N;
    
    vector<vector<int>> children(N+1);
    vector<int> parent(N+1, 0);
    
    for(int i = 2; i <= N; i++){
        int p;
        cin >> p;
        parent[i] = p;
        children[p].push_back(i);
    }
    
    // Find leaves (nodes with no children)
    // Actually, node 1 has at least 2 roads (degree >= 2), so it's not a leaf.
    // Leaves are nodes with degree 1 in the tree.
    // But we're given parent array. Leaves = nodes with no children.
    // Wait: node 1 has at least 2 children (from problem statement: incident to at least 2 roads).
    // Other internal nodes might have 1 child (degree 2: one parent edge, one child edge).
    // Leaves = nodes with no children AND degree 1 in tree.
    // A node with no children has degree 1 (just the parent edge), except root which has degree = number of children.
    // So leaves = {v : v != 1 and children[v] is empty}
    
    // Find first leaf (smallest numbered leaf = first in DFS)
    int first_leaf = -1;
    for(int v = 2; v <= N; v++){
        if(children[v].empty()){
            first_leaf = v;
            break;
        }
    }
    
    // Euler tour: DFS, recording each edge traversal
    // For each edge traversal, create a bag
    struct Bag {
        set<int> nodes;
    };
    
    vector<Bag> bags;
    vector<pair<int,int>> decomp_edges; // edges in decomposition tree
    
    // DFS iteratively
    // Stack contains (node, child_index, bag_id_for_edge_to_this_node)
    // When we go down to a child, we create a new bag
    // When we go up, we create a new bag
    
    int prev_leaf = -1; // no prev leaf yet
    
    // We'll do DFS and for each edge traversal create a bag
    // bag_stack tracks the bag ID at the top (for the edge from parent to current node)
    
    // Actually, let me reconsider: I need to chain bags in Euler tour order.
    // But I also said the chain preserves connectivity for each node.
    // Let me verify: in a chain B1-B2-...-Bm, node v appears in consecutive bags
    // from when we first traverse an edge to/from v until we last traverse an edge to/from v.
    // In the Euler tour, edges incident to v appear in a contiguous block (from first entering v to last leaving v).
    // So v's bags are consecutive in the chain. Good.
    
    // prev_leaf also appears in consecutive bags (from when that leaf is left until next leaf is reached).
    // first_leaf appears in ALL bags.
    
    // Let me implement:
    
    // DFS with explicit stack
    struct Frame {
        int node;
        int ci; // child index (which child to process next)
    };
    
    stack<Frame> stk;
    stk.push({1, 0});
    
    // bag_id_stack: the bag ID associated with the edge leading to the current node
    // For root (node 1), there's no edge, so we use -1
    stack<int> bag_id_stack;
    bag_id_stack.push(-1);
    
    int last_bag_id = -1; // ID of the last created bag, for chaining
    
    while(!stk.empty()){
        Frame& f = stk.top();
        int u = f.node;
        
        if(f.ci < (int)children[u].size()){
            int child = children[u][f.ci];
            f.ci++;
            
            // Going down edge (u, child)
            // Create bag
            set<int> bag_nodes;
            bag_nodes.insert(u);
            bag_nodes.insert(child);
            if(prev_leaf != -1) bag_nodes.insert(prev_leaf);
            bag_nodes.insert(first_leaf);
            
            int bid = bags.size();
            bags.push_back({bag_nodes});
            
            // Connect to previous bag in chain
            if(last_bag_id != -1){
                decomp_edges.push_back({last_bag_id + 1, bid + 1}); // 1-indexed
            }
            last_bag_id = bid;
            
            // Push child
            stk.push({child, 0});
            bag_id_stack.push(bid);
            
            // Check if child is a leaf
            if(children[child].empty()){
                prev_leaf = child;
            }
        } else {
            // Done with all children of u, go up
            stk.pop();
            int my_bag = bag_id_stack.top();
            bag_id_stack.pop();
            
            if(!stk.empty()){
                // Going up from u to parent
                int par = stk.top().node;
                
                // Create bag for up-edge
                set<int> bag_nodes;
                bag_nodes.insert(par);
                bag_nodes.insert(u);
                if(prev_leaf != -1) bag_nodes.insert(prev_leaf);
                bag_nodes.insert(first_leaf);
                
                int bid = bags.size();
                bags.push_back({bag_nodes});
                
                if(last_bag_id != -1){
                    decomp_edges.push_back({last_bag_id + 1, bid + 1});
                }
                last_bag_id = bid;
            }
        }
    }
    
    // Output
    int K = bags.size();
    cout << K << "\n";
    for(int i = 0; i < K; i++){
        vector<int> v(bags[i].nodes.begin(), bags[i].nodes.end());
        cout << v.size();
        for(int x : v) cout << " " << x;
        cout << "\n";
    }
    for(auto& [a,b] : decomp_edges){
        cout << a << " " << b << "\n";
    }
    
    return 0;
}
