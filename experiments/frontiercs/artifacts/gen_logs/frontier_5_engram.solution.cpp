#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    int a[10];
    for(int i = 0; i < 10; i++) cin >> a[i];
    
    vector<vector<int>> adj(n+1), radj(n+1);
    // For fast adjacency check
    vector<unordered_set<int>> adj_set(n+1), radj_set(n+1);
    
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v;
        adj[u].push_back(v);
        radj[v].push_back(u);
        adj_set[u].insert(v);
        radj_set[v].insert(u);
    }
    
    auto now = chrono::steady_clock::now;
    auto start_time = now();
    auto elapsed_ms = [&](){return chrono::duration_cast<chrono::milliseconds>(now()-start_time).count();};
    
    // Check DAG - topological sort for longest path
    {
        vector<int> indeg(n+1, 0);
        for(int u = 1; u <= n; u++) for(int v : adj[u]) indeg[v]++;
        queue<int> q;
        for(int u = 1; u <= n; u++) if(indeg[u] == 0) q.push(u);
        vector<int> topo;
        topo.reserve(n);
        while(!q.empty()){
            int u = q.front(); q.pop(); topo.push_back(u);
            for(int v : adj[u]) if(--indeg[v] == 0) q.push(v);
        }
        if((int)topo.size() == n){
            // DAG: find longest path
            vector<int> dp(n+1, 1), nxt(n+1, -1);
            // Process in reverse topological order
            for(int i = n-1; i >= 0; i--){
                int u = topo[i]; dp[u] = 1; nxt[u] = -1;
                for(int v : adj[u]){
                    if(dp[v] + 1 > dp[u]){
                        dp[u] = dp[v] + 1;
                        nxt[u] = v;
                    }
                }
            }
            int bs = topo[0];
            for(int u : topo) if(dp[u] > dp[bs]) bs = u;
            vector<int> path;
            for(int u = bs; u != -1; u = nxt[u]) path.push_back(u);
            cout << path.size() << "\n";
            for(int i = 0; i < (int)path.size(); i++){
                if(i) cout << ' ';
                cout << path[i];
            }
            cout << "\n";
            return 0;
        }
    }
    
    mt19937 rng(12345);
    vector<int> best_path;
    
    // Helper: has_edge
    auto has_edge = [&](int u, int v) -> bool {
        return adj_set[u].count(v) > 0;
    };
    
    // Main loop: greedy + Pósa rotations with restarts
    while(elapsed_ms() < 3800 && (int)best_path.size() < n){
        // Pick a random starting vertex
        int sv = rng() % n + 1;
        
        // Build path using deque for O(1) front/back operations
        deque<int> dq;
        vector<int> pos(n+1, -1);
        dq.push_back(sv);
        pos[sv] = 0;
        
        // Greedy extend back with Warnsdorff
        auto extend_back = [&]() -> bool {
            int c = dq.back();
            int best = -1, best_score = INT_MAX;
            for(int v : adj[c]){
                if(pos[v] != -1) continue;
                int s = 0;
                for(int w : adj[v]) if(pos[w] == -1) s++;
                if(s < best_score || (s == best_score && (rng() & 1))){
                    best_score = s;
                    best = v;
                }
            }
            if(best == -1) return false;
            pos[best] = (int)dq.size();
            dq.push_back(best);
            return true;
        };
        
        // Greedy extend front with Warnsdorff
        auto extend_front = [&]() -> bool {
            int c = dq.front();
            int best = -1, best_score = INT_MAX;
            for(int v : radj[c]){
                if(pos[v] != -1) continue;
                int s = 0;
                for(int w : radj[v]) if(pos[w] == -1) s++;
                if(s < best_score || (s == best_score && (rng() & 1))){
                    best_score = s;
                    best = v;
                }
            }
            if(best == -1) return false;
            dq.push_front(best);
            // Rebuild positions
            for(int i = 0; i < (int)dq.size(); i++) pos[dq[i]] = i;
            return true;
        };
        
        // Initial greedy extension
        while(extend_back());
        while(extend_front());
        while(extend_back());
        while(extend_front());
        
        // Convert deque to vector for rotation operations
        vector<int> path(dq.begin(), dq.end());
        for(int i = 0; i < (int)path.size(); i++) pos[path[i]] = i;
        
        // Pósa rotation-extension
        // Try to extend path by rotating when stuck
        auto try_posa = [&]() -> bool {
            // Try rotating at the back
            int tail = path.back();
            // Find all path[i] such that tail -> path[i] is an edge, and i+1 < path.size()
            // Then we can reverse path[i+1..end] to make path[i+1] the new tail (but direction matters!)
            // For directed: if tail -> path[i], we truncate to path[0..i], giving new tail = path[i]
            // Wait, that shortens the path. That's not useful.
            
            // Directed Pósa: if tail -> path[i] exists, and path[i-1] -> path[i] is the edge used,
            // we can reroute: path[0..i-1] then jump to tail via reversed subpath.
            // But reversal in directed graph doesn't preserve edge directions.
            
            // Alternative: if tail -> path[i] exists, we keep path[0..i] and replace the rest.
            // That's shorter unless we can extend from the new front or from path[i-1].
            
            // Better approach: look for back-edge from tail to path[j], where path[j+1] has
            // an unvisited out-neighbor. Then: new path = path[0..j], tail (via tail->path[j]... no)
            
            // Actually for directed Pósa:
            // Current path: v0 -> v1 -> ... -> vk (tail = vk)
            // If vk -> vi is an edge, AND vi+1 has an out-edge to some unvisited vertex w:
            // New path: v0 -> ... -> vi -> vk -> vk-1 -> ... -> vi+1 -> w
            // BUT this requires edges vk->vk-1, vk-1->vk-2, ..., vi+2->vi+1, vi+1->w
            // These reverse edges may not exist!
            
            // So in directed case, simple reversal doesn't work.
            // Instead, we do: if tail -> path[j] exists, truncate path to path[0..j].
            // This gives a shorter path but a new endpoint. Then try to extend again.
            // If the extension makes up for the truncation, we gain.
            
            // Let's try: find back-edges from tail, pick one that leads to best re-extension
            vector<int> candidates;
            for(int v : adj[tail]){
                if(pos[v] != -1 && pos[v] < (int)path.size() - 1){
                    candidates.push_back(pos[v]);
                }
            }
            if(candidates.empty()) return false;
            
            // Shuffle and try a few
            shuffle(candidates.begin(), candidates.end(), rng);
            
            int orig_len = (int)path.size();
            
            for(int ci = 0; ci < min((int)candidates.size(), 5); ci++){
                int j = candidates[ci];
                // Truncate: keep path[0..j], then add tail
                // But wait, we need edge path[j-1]->path[j] which exists, and then tail->path[j]? No.
                // We need: path ends at tail, tail->path[j] exists
                // New path: path[0], ..., path[j], then from path[j] where do we go?
                // We had path[j]->path[j+1] before. Now tail->path[j].
                // Hmm, this doesn't help directly.
                
                // Different idea: drop everything after position j+1 from the path, freeing those vertices
                // New path = path[0..j] + tail (using edge path[j]... no, we need path[j]->tail)
                // We don't necessarily have path[j]->tail.
                // We have tail->path[j].
                
                // OK let me think about this differently.
                // We want to reroute. If tail->path[j] exists:
                // Option: path = path[0..j-1], then from path[j-1] we still go to path[j], 
                // but we want to skip some vertices and include tail.
                // 
                // Actually the standard directed Pósa trick:
                // If the last vertex vk has an edge to some vi on the path (vk -> vi),
                // then we can form: v0 -> v1 -> ... -> v_{i-1} -> vk -> v_{k-1} -> ... -> v_i
                // BUT only if all the reverse edges exist (v_k -> v_{k-1}, etc.)
                // In directed graphs this almost never works.
                
                // Practical approach: just truncate and re-extend
                // Save current path, truncate to path[0..j], free vertices j+1..k-1 (not tail, not 0..j)
                // Then try extending from the new end (path[j]) and also from tail somehow
                
                // Actually simpler: we can't really use tail->path[j] easily.
                // Let's try a different rotation: check if any vertex in path has an out-neighbor 
                // that's unvisited. If path[j] -> w (unvisited), we truncate path to [0..j, w] 
                // and re-extend. We lose vertices j+1..end but might gain more.
                
                // This is expensive. Let me just do: find the first unvisited neighbor of path[j+1]
                // and restructure.
                
                // I think the practical approach for directed graphs is:
                // When stuck, try removing the last few vertices and re-extending differently.
                break; // abandon this approach for now
            }
            
            // Alternative: random perturbation
            // Remove a random suffix of length L, try re-extending
            if(path.size() <= 2) return false;
            int remove_len = rng() % min((int)path.size() / 2, 20) + 1;
            int new_len = (int)path.size() - remove_len;
            // Free removed vertices
            for(int i = new_len; i < (int)path.size(); i++){
                pos[path[i]] = -1;
            }
            path.resize(new_len);
            
            // Re-extend with some randomness
            auto extend_back_rand = [&]() -> bool {
                int c = path.back();
                vector<int> cands;
                for(int v : adj[c]){
                    if(pos[v] == -1) cands.push_back(v);
                }
                if(cands.empty()) return false;
                // Warnsdorff with randomness
                int best = -1, best_score = INT_MAX;
                for(int v : cands){
                    int s = 0;
                    for(int w : adj[v]) if(pos[w] == -1) s++;
                    if(s < best_score || (s == best_score && (rng() & 3) == 0)){
                        best_score = s;
                        best = v;
                    }
                }
                pos[best] = (int)path.size();
                path.push_back(best);
                return true;
            };
            
            while(extend_back_rand());
            
            if((int)path.size() > orig_len) return true;
            return false; // didn't improve
        };
        
        // Try Pósa-style perturbations
        for(int iter = 0; iter < 200 && elapsed_ms() < 3800; iter++){
            if((int)path.size() >= n) break;
            try_posa();
            if((int)path.size() > (int)best_path.size()) best_path = path;
        }
        
        if((int)path.size() > (int)best_path.size()) best_path = path;
        
        // For very small n, try harder
        if(n <= 50 && (int)best_path.size() < n && elapsed_ms() < 2000){
            // Try vertex insertion: for each unvisited vertex, try to insert it into the path
            vector<bool> in_path(n+1, false);
            for(int v : path) in_path[v] = true;
            for(int v = 1; v <= n; v++){
                if(in_path[v]) continue;
                // Try to insert v between path[i] and path[i+1]
                for(int i = 0; i + 1 < (int)path.size(); i++){
                    if(has_edge(path[i], v) && has_edge(v, path[i+1])){
                        path.insert(path.begin() + i + 1, v);
                        in_path[v] = true;
                        // Update pos
                        for(int j = 0; j < (int)path.size(); j++) pos[path[j]] = j;
                        break;
                    }
                }
                // Try prepend
                if(!in_path[v] && has_edge(v, path[0])){
                    path.insert(path.begin(), v);
                    in_path[v] = true;
                    for(int j = 0; j < (int)path.size(); j++) pos[path[j]] = j;
                }
                // Try append
                if(!in_path[v] && has_edge(path.back(), v)){
                    path.push_back(v);
                    in_path[v] = true;
                    pos[v] = (int)path.size() - 1;
                }
            }
            if((int)path.size() > (int)best_path.size()) best_path = path;
        }
    }
    
    // DFS for small graphs as a final attempt
    if(n <= 30 && (int)best_path.size() < n && elapsed_ms() < 3500){
        vector<bool> vis(n+1, false);
        vector<int> cur_path;
        bool found = false;
        function<void(int)> dfs = [&](int u){
            if(found || elapsed_ms() > 3800) return;
            cur_path.push_back(u); vis[u] = true;
            if((int)cur_path.size() > (int)best_path.size()) best_path = cur_path;
            if((int)cur_path.size() == n){ found = true; vis[u] = false; cur_path.pop_back(); return; }
            vector<pair<int,int>> nb;
            for(int v : adj[u]) if(!vis[v]){
                int c = 0; for(int w : adj[v]) if(!vis[w]) c++;
                nb.push_back({c, v});
            }
            sort(nb.begin(), nb.end());
            for(auto&[c,v] : nb){
                if(found || elapsed_ms() > 3800) break;
                dfs(v);
            }
            vis[u] = false; cur_path.pop_back();
        };
        vector<int> order(n);
        iota(order.begin(), order.end(), 1);
        shuffle(order.begin(), order.end(), rng);
        for(int s : order){
            if(found || elapsed_ms() > 3800) break;
            dfs(s);
        }
    }
    
    cout << best_path.size() << "\n";
    for(int i = 0; i < (int)best_path.size(); i++){
        if(i) cout << ' ';
        cout << best_path[i];
    }
    cout << "\n";
    return 0;
}
