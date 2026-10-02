#include <iostream>
#include <vector>
#include <algorithm>
#include <random>
#include <chrono>

using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int T;
    cin >> T;
    
    while(T--){
        int n;
        cin >> n;
        
        vector<int> p0(n+1);
        for(int i = 1; i <= n; i++) cin >> p0[i];
        
        vector<pair<int,int>> edges(n-1);
        vector<vector<int>> adj(n+1);
        for(int i = 0; i < n-1; i++){
            cin >> edges[i].first >> edges[i].second;
            adj[edges[i].first].push_back(edges[i].second);
            adj[edges[i].second].push_back(edges[i].first);
        }
        
        // BFS from each node to compute distances
        vector<vector<int>> dist(n+1, vector<int>(n+1, -1));
        // Also compute parent for path queries
        vector<vector<int>> parent(n+1, vector<int>(n+1, -1));
        for(int s = 1; s <= n; s++){
            dist[s][s] = 0;
            vector<int> q = {s};
            for(int qi = 0; qi < (int)q.size(); qi++){
                int u = q[qi];
                for(int v : adj[u]){
                    if(dist[s][v] == -1){
                        dist[s][v] = dist[s][u] + 1;
                        parent[s][v] = u;
                        q.push_back(v);
                    }
                }
            }
        }
        
        // next_on_path(from, to): the next node on the path from 'from' to 'to'
        // This is the neighbor of 'from' that is closer to 'to'
        // We can get this: next_on_path(u, t) = parent[u][t] won't work directly
        // Actually parent[s][v] = predecessor of v in BFS from s
        // So path from s to v: v, parent[s][v], parent[s][parent[s][v]], ..., s
        // next_on_path(s, v) = parent[v][s] ... no.
        // Actually: next step from u toward t: we need the neighbor of u on the path to t
        // That's the node w adjacent to u with dist[w][t] = dist[u][t]-1
        // Or equivalently, parent[t][u] gives the node after u on path from t... no.
        // parent[t][u] = predecessor of u in BFS from t = neighbor of u closer to t
        // So next_on_path(u, t) = parent[t][u]. Yes!
        
        auto next_on_path = [&](int u, int t) -> int {
            if(u == t) return u;
            return parent[t][u]; // predecessor of u in BFS from t = neighbor of u on path to t
        };
        
        mt19937 rng(42);
        
        vector<vector<int>> bestOps;
        int bestRounds = 3*n;
        
        int restarts = max(1, min(200, (int)(800000 / max(1, n*n))));
        
        for(int restart = 0; restart < restarts; restart++){
            vector<int> p = p0;
            vector<vector<int>> ops;
            
            for(int iter = 0; iter < 2*n; iter++){
                bool sorted_flag = true;
                for(int i = 1; i <= n; i++) if(p[i] != i){ sorted_flag = false; break; }
                if(sorted_flag) break;
                
                // For each edge, compute weight
                struct Cand { double weight; int idx; };
                vector<Cand> candidates;
                for(int i = 0; i < n-1; i++){
                    int u = edges[i].first, v = edges[i].second;
                    int pu = p[u], pv = p[v];
                    if(pu == u && pv == v) continue;
                    
                    int before = dist[pu][u] + dist[pv][v];
                    int after = dist[pu][v] + dist[pv][u];
                    int benefit = before - after;
                    
                    // Check if elements need to cross this edge
                    bool u_crosses = (pu != u) && (next_on_path(u, pu) == v || dist[pu][v] < dist[pu][u]);
                    bool v_crosses = (pv != v) && (next_on_path(v, pv) == u || dist[pv][u] < dist[pv][v]);
                    
                    double w = benefit;
                    if(benefit <= 0 && u_crosses && v_crosses) w = 0.5;
                    else if(benefit <= 0 && (u_crosses || v_crosses)) w = 0.1;
                    
                    if(w > 0){
                        double noise = (rng() % 1000) * 0.0001;
                        candidates.push_back({w + noise, i});
                    }
                }
                
                sort(candidates.begin(), candidates.end(), [](auto& a, auto& b){ return a.weight > b.weight; });
                
                vector<bool> used(n+1, false);
                vector<int> matching;
                for(auto& c : candidates){
                    int u = edges[c.idx].first, v = edges[c.idx].second;
                    if(!used[u] && !used[v]){
                        used[u] = used[v] = true;
                        matching.push_back(c.idx);
                    }
                }
                
                if(matching.empty()) break;
                
                for(int idx : matching) swap(p[edges[idx].first], p[edges[idx].second]);
                ops.push_back(matching);
            }
            
            // Check sorted
            bool ok = true;
            for(int i = 1; i <= n; i++) if(p[i] != i){ ok = false; break; }
            
            if(ok && (int)ops.size() < bestRounds){
                bestRounds = ops.size();
                bestOps = ops;
            }
        }
        
        cout << bestOps.size() << "\n";
        for(auto& m : bestOps){
            cout << m.size();
            for(int idx : m) cout << " " << (idx+1);
            cout << "\n";
        }
    }
    
    return 0;
}