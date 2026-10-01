#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<vector<int>> adj(n+1);
    vector<pair<int,int>> edges(m);
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    if(m == 0){
        for(int i = 1; i <= n; i++){
            if(i > 1) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }
    
    auto start_time = chrono::steady_clock::now();
    auto elapsed_ms = [&]() -> double {
        return chrono::duration<double, milli>(chrono::steady_clock::now() - start_time).count();
    };
    
    vector<int> best_s(n+1, 0);
    int best_cut = -1;
    
    mt19937 rng(42);
    
    auto compute_cut = [&](vector<int>& s) -> int {
        int c = 0;
        for(auto& [u,v] : edges) if(s[u] != s[v]) c++;
        return c;
    };
    
    int restart = 0;
    while(elapsed_ms() < 1800.0){
        restart++;
        vector<int> s(n+1, 0);
        
        // Greedy initialization with random order
        vector<int> order(n);
        iota(order.begin(), order.end(), 1);
        shuffle(order.begin(), order.end(), rng);
        
        for(int v : order){
            int c0 = 0, c1 = 0;
            for(int u : adj[v]){
                if(s[u] == 0) c0++;
                else c1++;
            }
            s[v] = (c0 >= c1) ? 1 : 0;
        }
        
        // Compute gain for each vertex
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++){
            for(int u : adj[v]){
                if(s[u] == s[v]) gain[v]++;
                else gain[v]--;
            }
        }
        
        // Local search with multiple passes + perturbation
        for(int iter = 0; iter < 200; iter++){
            // 1-flip local search to local optimum
            bool imp = true;
            while(imp){
                imp = false;
                for(int v = 1; v <= n; v++){
                    if(gain[v] > 0){
                        s[v] ^= 1;
                        gain[v] = -gain[v];
                        for(int u : adj[v]){
                            if(s[u] == s[v]) gain[u] += 2;
                            else gain[u] -= 2;
                        }
                        imp = true;
                    }
                }
            }
            
            int cur_cut = compute_cut(s);
            if(cur_cut > best_cut){
                best_cut = cur_cut;
                best_s = s;
            }
            
            if(elapsed_ms() > 1800.0) break;
            
            // Perturbation: flip some random vertices
            int perturb_size = max(1, n / 20 + (int)(rng() % (max(1, n/10))));
            for(int i = 0; i < perturb_size; i++){
                int v = 1 + rng() % n;
                s[v] ^= 1;
                gain[v] = -gain[v];
                for(int u : adj[v]){
                    if(s[u] == s[v]) gain[u] += 2;
                    else gain[u] -= 2;
                }
            }
        }
        
        if(elapsed_ms() > 1800.0) break;
    }
    
    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << best_s[i];
    }
    cout << '\n';
    return 0;
}
