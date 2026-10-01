#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<pair<int,int>> edges(m);
    vector<vector<int>> adj(n);
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v; u--; v--;
        edges[i] = {u, v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    
    if(m == 0){
        for(int i = 0; i < n; i++){
            if(i) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }
    
    mt19937 rng(12345);
    vector<int> bestS(n, 0), s(n), gain(n);
    int bestCut = 0;
    
    auto calcCut = [&](){
        int c = 0;
        for(auto&[a,b] : edges) c += (s[a] != s[b]);
        return c;
    };
    
    auto computeGain = [&](){
        for(int u = 0; u < n; u++){
            int g = 0;
            for(int v : adj[u]) g += (s[u] == s[v]) ? 1 : -1;
            gain[u] = g;
        }
    };
    
    auto doFlip = [&](int u, int &cur){
        cur += gain[u];
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            if(s[u] == s[v]) gain[v] += 2;
            else gain[v] -= 2;
        }
    };
    
    auto localSearch = [&](int &cur){
        bool imp = true;
        while(imp){
            imp = false;
            for(int u = 0; u < n; u++){
                if(gain[u] > 0){
                    doFlip(u, cur);
                    imp = true;
                }
            }
        }
    };
    
    auto t0 = chrono::steady_clock::now();
    auto ms = [&]() -> long long {
        return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - t0).count();
    };
    
    long long timeLimit = 1800;
    
    while(ms() < timeLimit){
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        int cur = calcCut();
        computeGain();
        localSearch(cur);
        if(cur > bestCut){ bestCut = cur; bestS = s; }
        
        // Simulated annealing from this local optimum
        double T = 3.0;
        while(T > 0.01 && ms() < timeLimit){
            for(int it = 0; it < n * 2; it++){
                int u = rng() % n;
                int g = gain[u];
                if(g >= 0){
                    doFlip(u, cur);
                } else {
                    double p = exp((double)g / T);
                    if((double)(rng() & 0xFFFFFF) / 0xFFFFFF < p){
                        doFlip(u, cur);
                    }
                }
                if(cur > bestCut){ bestCut = cur; bestS = s; }
            }
            T *= 0.999;
        }
    }
    
    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << bestS[i];
    }
    cout << '\n';
    return 0;
}
