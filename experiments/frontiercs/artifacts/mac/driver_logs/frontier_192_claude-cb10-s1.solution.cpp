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
    
    vector<int> best(n, 0);
    
    if(m == 0){
        for(int i = 0; i < n; i++){ if(i) cout << ' '; cout << 0; }
        cout << '\n';
        return 0;
    }
    
    int bestCut = 0;
    mt19937 rng(42);
    vector<int> s(n), gain(n);
    
    auto calcGain = [&](){
        for(int u = 0; u < n; u++){
            int g = 0;
            for(int v : adj[u]) g += (s[u] == s[v]) ? 1 : -1;
            gain[u] = g;
        }
    };
    
    auto flipNode = [&](int u){
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            if(s[u] == s[v]) gain[v] -= 2; else gain[v] += 2;
        }
    };
    
    auto localSearch = [&](){
        bool imp = true;
        while(imp){ imp = false; for(int u = 0; u < n; u++) if(gain[u] > 0){ flipNode(u); imp = true; } }
    };
    
    auto calcCut = [&](){ int c = 0; for(auto&[a,b] : edges) c += (s[a] != s[b]); return c; };
    
    auto t0 = chrono::steady_clock::now();
    auto elapsed = [&](){ return chrono::duration<double>(chrono::steady_clock::now() - t0).count(); };
    
    double timeLimit = 1.8;
    
    while(elapsed() < timeLimit){
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        calcGain();
        localSearch();
        int c = calcCut();
        if(c > bestCut){ bestCut = c; best = s; }
        
        // SA phase
        double T0 = max(2.0, 0.3 * sqrt((double)m));
        int curCut = c;
        
        for(int it = 0; ; it++){
            if((it & 255) == 0 && elapsed() >= timeLimit) break;
            int u = rng() % n;
            int d = gain[u];
            if(d >= 0){
                flipNode(u); curCut += d;
                if(curCut > bestCut){ bestCut = curCut; best = s; }
            } else {
                double frac = min(1.0, elapsed() / timeLimit);
                double T = T0 * (1.0 - frac) + 0.01;
                double r = (rng() % 100000) / 100000.0;
                if(exp((double)d / T) > r){
                    flipNode(u); curCut += d;
                }
            }
        }
        
        s = best; calcGain(); localSearch();
        c = calcCut();
        if(c > bestCut){ bestCut = c; best = s; }
    }
    
    for(int i = 0; i < n; i++){ if(i) cout << ' '; cout << best[i]; }
    cout << '\n';
    return 0;
}
