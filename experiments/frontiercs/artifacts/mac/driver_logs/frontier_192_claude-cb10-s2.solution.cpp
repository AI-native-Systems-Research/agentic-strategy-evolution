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
        for(int i = 0; i < n; i++){ if(i) cout << ' '; cout << 0; }
        cout << '\n';
        return 0;
    }
    
    mt19937 rng(12345);
    vector<int> s(n), gain(n), bestS(n, 0);
    int bestCut = 0;
    
    auto computeCut = [&]() -> int {
        int c = 0;
        for(auto& [a,b] : edges) c += (s[a] != s[b]);
        return c;
    };
    
    auto computeGain = [&](){
        for(int u = 0; u < n; u++){
            int g = 0;
            for(int v : adj[u]) g += (s[u] == s[v]) ? 1 : -1;
            gain[u] = g;
        }
    };
    
    auto doFlip = [&](int u, int& cur){
        cur += gain[u];
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            if(s[u] == s[v]) gain[v] += 2;
            else gain[v] -= 2;
        }
    };
    
    auto localSearch = [&](int& cur){
        bool imp = true;
        while(imp){
            imp = false;
            for(int u = 0; u < n; u++){
                if(gain[u] > 0){ doFlip(u, cur); imp = true; }
            }
        }
    };
    
    auto t0 = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    };
    
    double timeLimit = 1.8;
    
    while(elapsed() < timeLimit){
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        computeGain();
        int cur = computeCut();
        localSearch(cur);
        if(cur > bestCut){ bestCut = cur; bestS = s; }
        
        double Tinit = max(2.0, 0.3 * sqrt((double)m));
        double Tfinal = 0.01;
        int totalIter = max(200000, n * 500);
        
        for(int iter = 0; iter < totalIter; iter++){
            if((iter & 4095) == 0 && elapsed() >= timeLimit) break;
            double frac = (double)iter / totalIter;
            double T = Tinit * pow(Tfinal / Tinit, frac);
            int u = rng() % n;
            int g = gain[u];
            if(g > 0 || (uniform_real_distribution<double>(0,1)(rng) < exp((double)g / T))){
                doFlip(u, cur);
                if(cur > bestCut){ bestCut = cur; bestS = s; }
            }
        }
        
        s = bestS; computeGain(); int cc = computeCut();
        localSearch(cc);
        if(cc > bestCut){ bestCut = cc; bestS = s; }
    }
    
    for(int i = 0; i < n; i++){ if(i) cout << ' '; cout << bestS[i]; }
    cout << '\n';
}
