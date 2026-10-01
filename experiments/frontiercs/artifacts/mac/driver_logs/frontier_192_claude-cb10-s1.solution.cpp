#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<pair<int,int>> edges(m);
    vector<vector<int>> adj(n+1);
    
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        edges[i] = {u, v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    
    if(m == 0){
        for(int i = 1; i <= n; i++){
            if(i > 1) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }
    
    vector<int> s(n+1, 0), gain(n+1, 0), bestS(n+1, 0);
    int bestCut = -1;
    mt19937 rng(42);
    
    auto computeGain = [&](){
        for(int u = 1; u <= n; u++){
            int same = 0, diff = 0;
            for(int v : adj[u]){
                if(s[u] == s[v]) same++; else diff++;
            }
            gain[u] = same - diff;
        }
    };
    
    auto flipNode = [&](int u){
        for(int v : adj[u]){
            if(s[v] == s[u]) gain[v] -= 2;
            else gain[v] += 2;
        }
        s[u] ^= 1;
        gain[u] = -gain[u];
    };
    
    auto localSearch = [&](){
        bool improved = true;
        while(improved){
            improved = false;
            for(int u = 1; u <= n; u++){
                if(gain[u] > 0){
                    flipNode(u);
                    improved = true;
                }
            }
        }
    };
    
    auto computeCut = [&](){
        int c = 0;
        for(auto&[u,v] : edges) c += (s[u] != s[v]);
        return c;
    };
    
    auto start = chrono::steady_clock::now();
    
    for(int restart = 0; ; restart++){
        auto now = chrono::steady_clock::now();
        if(chrono::duration<double>(now - start).count() > 1.7) break;
        
        for(int i = 1; i <= n; i++) s[i] = rng() & 1;
        computeGain();
        localSearch();
        
        int c = computeCut();
        if(c > bestCut){ bestCut = c; for(int i=1;i<=n;i++) bestS[i]=s[i]; }
        
        // SA perturbation phase
        double T = 2.0;
        for(int iter = 0; iter < 50000 && T > 0.01; iter++){
            if(iter % 5000 == 0 && chrono::duration<double>(chrono::steady_clock::now()-start).count() > 1.7) break;
            int u = (int)(rng() % n) + 1;
            int g = gain[u];
            if(g > 0 || uniform_real_distribution<double>(0,1)(rng) < exp(g / T)){
                flipNode(u);
                c += g;
                if(c > bestCut){ bestCut = c; for(int i=1;i<=n;i++) bestS[i]=s[i]; }
            }
            T *= 0.99995;
        }
    }
    
    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << bestS[i];
    }
    cout << '\n';
}
