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
    
    if(m == 0){
        for(int i = 1; i <= n; i++){ if(i>1) cout << ' '; cout << 0; }
        cout << '\n';
        return 0;
    }
    
    vector<int> gain(n+1);
    vector<int> s(n+1), bestS(n+1, 0);
    int bestCut = -1;
    
    mt19937 rng(42);
    auto start = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - start).count();
    };
    
    double timeLimit = 0.85;
    
    while(elapsed() < timeLimit){
        for(int i = 1; i <= n; i++) s[i] = rng() & 1;
        
        for(int u = 1; u <= n; u++){
            gain[u] = 0;
            for(int v : adj[u])
                gain[u] += (s[u] == s[v]) ? 1 : -1;
        }
        
        int curCut = 0;
        for(auto& [u,v] : edges) curCut += (s[u] != s[v]);
        
        // Greedy local search
        bool improved = true;
        while(improved){
            improved = false;
            for(int u = 1; u <= n; u++){
                if(gain[u] > 0){
                    for(int v : adj[u]){
                        if(s[u] == s[v]) gain[v] -= 2; else gain[v] += 2;
                    }
                    curCut += gain[u];
                    s[u] ^= 1;
                    gain[u] = -gain[u];
                    improved = true;
                }
            }
        }
        
        if(curCut > bestCut){ bestCut = curCut; for(int i=1;i<=n;i++) bestS[i]=s[i]; }
        
        // SA phase
        double t0 = elapsed();
        double remaining = timeLimit - t0;
        if(remaining < 0.01) break;
        double saEnd = t0 + remaining * 0.85;
        uniform_real_distribution<double> udist(0.0, 1.0);
        
        for(int iter = 0; ; iter++){
            if((iter & 511) == 0 && elapsed() >= saEnd) break;
            double frac = (elapsed() - t0) / (saEnd - t0);
            double T = 3.0 * (1.0 - frac) + 0.01;
            int u = rng() % n + 1;
            int g = gain[u];
            if(g > 0 || udist(rng) < exp((double)g / T)){
                for(int v : adj[u]){
                    if(s[u] == s[v]) gain[v] -= 2; else gain[v] += 2;
                }
                s[u] ^= 1;
                gain[u] = -gain[u];
                curCut += g;
                if(curCut > bestCut){ bestCut = curCut; for(int i=1;i<=n;i++) bestS[i]=s[i]; }
            }
        }
    }
    
    for(int i = 1; i <= n; i++){ if(i>1) cout << ' '; cout << bestS[i]; }
    cout << '\n';
    return 0;
}
