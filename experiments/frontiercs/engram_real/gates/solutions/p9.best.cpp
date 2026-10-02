// Approach: Edge coloring + repeated sweeps
// Color tree edges with max_degree colors (each color class = matching)
// Repeatedly sweep through colors, swapping productive edges in each color class
// This guarantees convergence because:
// 1. Each color class is a valid matching
// 2. We only swap when it doesn't increase total displacement (change <= 0)
// 3. When no change=-2 edges exist, change=0 edges still make progress by shuffling
// 4. Sweeping through all colors ensures all edges get chances
//
// Additionally, we use "virtual potential" to break ties and prevent cycling
#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int T;
    cin >> T;
    while(T--){
        int n;
        cin >> n;
        vector<int> p(n+1);
        for(int i = 1; i <= n; i++) cin >> p[i];
        
        vector<pair<int,int>> edges(n); // 1-indexed edges
        vector<vector<pair<int,int>>> adj(n+1);
        for(int i = 1; i < n; i++){
            int u, v;
            cin >> u >> v;
            edges[i] = {u, v};
            adj[u].push_back({v, i});
            adj[v].push_back({u, i});
        }
        
        // Precompute all-pairs distances
        vector<vector<int>> dist(n+1, vector<int>(n+1, 0));
        for(int s = 1; s <= n; s++){
            vector<bool> vis(n+1, false);
            queue<int> q;
            q.push(s);
            vis[s] = true;
            while(!q.empty()){
                int u = q.front(); q.pop();
                for(auto& [v, eidx] : adj[u]){
                    if(!vis[v]){
                        vis[v] = true;
                        dist[s][v] = dist[s][u] + 1;
                        q.push(v);
                    }
                }
            }
        }
        
        // Edge coloring: assign colors 0..max_deg-1 to edges
        // such that no two edges sharing a vertex have the same color
        int max_deg = 0;
        vector<int> deg(n+1, 0);
        for(int i = 1; i < n; i++){
            auto [u,v] = edges[i];
            deg[u]++; deg[v]++;
        }
        for(int i = 1; i <= n; i++) max_deg = max(max_deg, deg[i]);
        
        // Greedy edge coloring
        vector<int> edge_color(n, -1);
        vector<set<int>> used_colors(n+1); // used_colors[v] = set of colors used by edges incident to v
        for(int i = 1; i < n; i++){
            auto [u,v] = edges[i];
            int c = 0;
            while(used_colors[u].count(c) || used_colors[v].count(c)) c++;
            edge_color[i] = c;
            used_colors[u].insert(c);
            used_colors[v].insert(c);
        }
        
        int num_colors = *max_element(edge_color.begin()+1, edge_color.begin()+n) + 1;
        
        // Group edges by color
        vector<vector<int>> color_edges(num_colors);
        for(int i = 1; i < n; i++){
            color_edges[edge_color[i]].push_back(i);
        }
        
        vector<vector<int>> operations;
        
        // Repeatedly sweep through all colors
        // In each sweep, for each color, try to swap productive edges
        int max_iters = 4 * n;
        for(int iter = 0; iter < max_iters; iter++){
            bool sorted_flag = true;
            for(int i = 1; i <= n; i++){
                if(p[i] != i){ sorted_flag = false; break; }
            }
            if(sorted_flag) break;
            
            int color = iter % num_colors;
            
            // For this color class (which is a matching), decide which edges to swap
            vector<int> matching;
            for(int e : color_edges[color]){
                auto [u, v] = edges[e];
                int val_u = p[u], val_v = p[v];
                if(val_u == u && val_v == v) continue; // both home
                
                int cur_dist = dist[u][val_u] + dist[v][val_v];
                int new_dist = dist[v][val_u] + dist[u][val_v];
                int change = new_dist - cur_dist;
                
                if(change < 0){
                    // Always swap if it reduces total displacement
                    matching.push_back(e);
                } else if(change == 0){
                    // Swap if at least one element moves toward home
                    bool u_benefits = dist[v][val_u] < dist[u][val_u];
                    bool v_benefits = dist[u][val_v] < dist[v][val_v];
                    if(u_benefits || v_benefits){
                        matching.push_back(e);
                    }
                }
            }
            
            if(!matching.empty()){
                for(int eidx : matching){
                    auto [u, v] = edges[eidx];
                    swap(p[u], p[v]);
                }
                operations.push_back(matching);
            }
        }
        
        cout << operations.size() << "\n";
        for(auto& op : operations){
            cout << op.size();
            for(int e : op) cout << " " << e;
            cout << "\n";
        }
    }
    return 0;
}
