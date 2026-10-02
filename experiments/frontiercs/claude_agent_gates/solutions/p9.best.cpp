// Approach: Potential-decrease matching with cycle detection
// Uses tabu + permutation hashing to detect stuck states.
// When stuck, injects edge-coloring rounds to break the cycle.
#include <bits/stdc++.h>
using namespace std;
int main(){
    int T;
    scanf("%d", &T);
    while(T--){
        int n;
        scanf("%d", &n);
        vector<int> p(n+1);
        for(int i = 1; i <= n; i++) scanf("%d", &p[i]);
        vector<vector<pair<int,int>>> adj(n+1);
        vector<pair<int,int>> edges(n);
        for(int i = 1; i < n; i++){
            int u, v;
            scanf("%d %d", &u, &v);
            edges[i] = {u, v};
            adj[u].push_back({v, i});
            adj[v].push_back({u, i});
        }
        vector<int> par(n+1, 0), dep(n+1, 0);
        vector<bool> vis(n+1, false);
        queue<int> bfs;
        bfs.push(1); vis[1] = true;
        while(!bfs.empty()){
            int u = bfs.front(); bfs.pop();
            for(auto [v, eidx] : adj[u]){
                if(!vis[v]){
                    vis[v] = true;
                    par[v] = u;
                    dep[v] = dep[u] + 1;
                    bfs.push(v);
                }
            }
        }
        int LOG = 1;
        while((1 << LOG) <= n) LOG++;
        vector<vector<int>> up(LOG, vector<int>(n+1, 0));
        for(int v = 1; v <= n; v++) up[0][v] = par[v];
        for(int k = 1; k < LOG; k++)
            for(int v = 1; v <= n; v++)
                up[k][v] = up[k-1][up[k-1][v]];
        auto lca_func = [&](int u, int v) -> int {
            if(dep[u] < dep[v]) swap(u, v);
            int diff = dep[u] - dep[v];
            for(int k = 0; k < LOG; k++)
                if((diff >> k) & 1) u = up[k][u];
            if(u == v) return u;
            for(int k = LOG-1; k >= 0; k--)
                if(up[k][u] != up[k][v]){ u = up[k][u]; v = up[k][v]; }
            return up[0][u];
        };
        auto tree_dist = [&](int u, int v) -> int {
            int l = lca_func(u, v);
            return dep[u] + dep[v] - 2*dep[l];
        };
        
        // Euler tour for subtree queries
        vector<int> tin(n+1), tout(n+1);
        int timer = 0;
        {
            stack<pair<int,int>> stk;
            stk.push({1, 0});
            vector<int> ci(n+1, 0);
            while(!stk.empty()){
                auto& [u, st] = stk.top();
                if(st == 0){ tin[u] = timer++; st = 1; }
                bool found = false;
                while(ci[u] < (int)adj[u].size()){
                    auto [v, eidx] = adj[u][ci[u]]; ci[u]++;
                    if(v != par[u]){ stk.push({v, 0}); found = true; break; }
                }
                if(!found){ tout[u] = timer++; stk.pop(); }
            }
        }
        auto in_subtree = [&](int x, int u) -> bool {
            return tin[u] <= tin[x] && tout[x] <= tout[u];
        };
        
        vector<int> echild(n), epar_node(n);
        for(int i = 1; i < n; i++){
            auto [u, v] = edges[i];
            if(dep[u] > dep[v]){ echild[i] = u; epar_node[i] = v; }
            else { echild[i] = v; epar_node[i] = u; }
        }
        
        // Edge coloring
        int max_deg = 0;
        for(int v = 1; v <= n; v++) max_deg = max(max_deg, (int)adj[v].size());
        vector<int> edge_color(n, -1);
        {
            vector<set<int>> uc(n+1);
            for(int v = 1; v <= n; v++){
                for(auto [u, eidx] : adj[v]){
                    if(edge_color[eidx] == -1){
                        int c = 0;
                        while(uc[v].count(c) || uc[u].count(c)) c++;
                        edge_color[eidx] = c;
                        uc[v].insert(c);
                        uc[u].insert(c);
                    }
                }
            }
        }
        vector<vector<int>> color_edges(max_deg);
        for(int e = 1; e < n; e++) color_edges[edge_color[e]].push_back(e);
        
        vector<vector<int>> ops;
        
        // Track potential for cycle detection
        int prev_pot = -1;
        int stuck_count = 0;
        int ec_iter = 0;
        
        auto compute_pot = [&]() -> int {
            int pot = 0;
            for(int i = 1; i <= n; i++) if(p[i] != i) pot += tree_dist(i, p[i]);
            return pot;
        };
        
        for(int round = 0; round < 10*n; round++){
            bool done = true;
            for(int i = 1; i <= n; i++) if(p[i] != i){ done = false; break; }
            if(done) break;
            
            int cur_pot = compute_pot();
            if(cur_pot == prev_pot){
                stuck_count++;
            } else {
                stuck_count = 0;
            }
            prev_pot = cur_pot;
            
            if(stuck_count < 3){
                // Normal mode: potential-decrease + zero-delta with tabu
                vector<tuple<int,int,int>> edge_info;
                for(int e = 1; e < n; e++){
                    auto [u, v] = edges[e];
                    if(p[u] == u && p[v] == v) continue;
                    int old_c = tree_dist(u, p[u]) + tree_dist(v, p[v]);
                    int new_c = tree_dist(u, p[v]) + tree_dist(v, p[u]);
                    int delta = new_c - old_c;
                    if(delta <= 0){
                        // Secondary: for zero-delta, randomize order
                        int sec = (delta == 0) ? (rand() % 100) : -100;
                        edge_info.push_back({delta, sec, e});
                    }
                }
                sort(edge_info.begin(), edge_info.end());
                
                vector<bool> vused(n+1, false);
                vector<int> matching;
                for(auto [delta, sec, eidx] : edge_info){
                    auto [u, v] = edges[eidx];
                    if(!vused[u] && !vused[v]){
                        vused[u] = vused[v] = true;
                        matching.push_back(eidx);
                    }
                }
                
                if(!matching.empty()){
                    for(int eidx : matching){
                        auto [u, v] = edges[eidx];
                        swap(p[u], p[v]);
                    }
                    ops.push_back(matching);
                }
            } else {
                // Stuck mode: use edge coloring
                stuck_count = 0;
                // Do max_deg rounds of edge coloring
                for(int c = 0; c < max_deg; c++){
                    done = true;
                    for(int i = 1; i <= n; i++) if(p[i] != i){ done = false; break; }
                    if(done) break;
                    
                    vector<int> matching;
                    for(int e : color_edges[c]){
                        int ch = echild[e], pr = epar_node[e];
                        bool pr_wants_down = in_subtree(p[pr], ch);
                        bool c_wants_up = !in_subtree(p[ch], ch);
                        if(pr_wants_down || c_wants_up){
                            matching.push_back(e);
                        }
                    }
                    if(!matching.empty()){
                        for(int eidx : matching){
                            auto [u, v] = edges[eidx];
                            swap(p[u], p[v]);
                        }
                        ops.push_back(matching);
                    }
                }
            }
        }
        
        printf("%d\n", (int)ops.size());
        for(auto& op : ops){
            printf("%d", (int)op.size());
            for(int e : op) printf(" %d", e);
            printf("\n");
        }
    }
    return 0;
}
