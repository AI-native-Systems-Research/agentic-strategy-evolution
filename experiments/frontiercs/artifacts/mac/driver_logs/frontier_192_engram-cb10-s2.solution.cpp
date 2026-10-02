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
    
    auto start_time = chrono::steady_clock::now();
    auto elapsed_ms = [&]() -> double {
        return chrono::duration<double, milli>(chrono::steady_clock::now() - start_time).count();
    };
    
    vector<int> best_s(n+1, 0);
    int best_cut = 0;
    mt19937 rng(12345);
    
    auto compute_cut = [&](vector<int>& s) -> int {
        int c = 0;
        for(auto& [u,v] : edges) if(s[u] != s[v]) c++;
        return c;
    };
    
    while(elapsed_ms() < 900.0){
        vector<int> s(n+1);
        for(int i = 1; i <= n; i++) s[i] = rng() & 1;
        
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++)
            for(int u : adj[v])
                gain[v] += (s[u] == s[v]) ? 1 : -1;
        
        for(int iter = 0; iter < 300 && elapsed_ms() < 900.0; iter++){
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
            int cur = compute_cut(s);
            if(cur > best_cut){ best_cut = cur; best_s = s; }
            int ps = max(1, (int)(rng() % max(1, n/5)));
            for(int i = 0; i < ps; i++){
                int v = 1 + rng() % n;
                s[v] ^= 1; gain[v] = -gain[v];
                for(int u : adj[v]){
                    if(s[u] == s[v]) gain[u] += 2;
                    else gain[u] -= 2;
                }
            }
        }
    }
    
    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << best_s[i];
    }
    cout << '\n';
}
