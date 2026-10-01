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
        int u, v; cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    vector<int> bestS(n+1, 0);
    int bestCut = -1;
    
    mt19937 rng(42);
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    while(elapsed() < 1.85){
        vector<int> s(n+1);
        for(int i = 1; i <= n; i++) s[i] = rng() & 1;
        
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++){
            for(int u : adj[v]){
                if(s[u] == s[v]) gain[v]++; else gain[v]--;
            }
        }
        
        // Local search to local optimum
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
        
        int cut = 0;
        for(auto& [u,v] : edges) if(s[u] != s[v]) cut++;
        
        vector<int> bestLocal = s;
        int bestLocalCut = cut;
        
        double T0 = max(1.0, 0.02 * m / (double)n);
        double Tmin = 0.01;
        
        for(int iter = 0; elapsed() < 1.83; iter++){
            double frac = min(1.0, iter / 500000.0);
            double T = T0 * pow(Tmin / T0, frac);
            
            int v = (rng() % n) + 1;
            int g = gain[v];
            if(g > 0 || (rng() % 1000000) < (int)(1000000.0 * exp((double)g / T))){
                s[v] ^= 1;
                cut += g;
                gain[v] = -g;
                for(int u : adj[v]){
                    if(s[u] == s[v]) gain[u] += 2;
                    else gain[u] -= 2;
                }
                if(cut > bestLocalCut){ bestLocalCut = cut; bestLocal = s; }
            }
            if(frac >= 1.0) break;
        }
        
        if(bestLocalCut > bestCut){ bestCut = bestLocalCut; bestS = bestLocal; }
    }
    
    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << bestS[i];
    }
    cout << '\n';
    return 0;
}
