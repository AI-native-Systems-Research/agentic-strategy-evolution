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
    
    mt19937 rng(42);
    vector<int> best(n, 0), s(n), gain(n);
    int bestCut = -1;
    
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
            if(s[u] == s[v]){ gain[v] -= 2; }
            else { gain[v] += 2; }
        }
    };
    
    auto localSearch = [&](){
        bool imp = true;
        while(imp){
            imp = false;
            for(int u = 0; u < n; u++){
                if(gain[u] > 0){ flipNode(u); imp = true; }
            }
        }
    };
    
    auto calcCut = [&]() -> int {
        int c = 0;
        for(auto &[u,v] : edges) if(s[u] != s[v]) c++;
        return c;
    };
    
    auto t0 = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    };
    
    double timeLimit = 1.8;
    
    // Multiple restarts with SA
    while(elapsed() < timeLimit){
        double startTime = elapsed();
        double remaining = timeLimit - startTime;
        if(remaining < 0.01) break;
        double runTime = min(remaining, 0.5);
        
        // Random initial
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        calcGain();
        localSearch();
        
        int curCut = calcCut();
        if(curCut > bestCut){ bestCut = curCut; best = s; }
        
        // SA
        vector<int> bestLocal = s;
        int bestLocalCut = curCut;
        
        double T0 = max(1.0, 0.05 * m / (double)n * 2);
        double Tend = 0.001;
        
        long long iter = 0;
        while(true){
            if((iter & 1023) == 0){
                double now = elapsed();
                if(now >= startTime + runTime) break;
                double frac = (now - startTime) / runTime;
                double T = T0 * pow(Tend / T0, frac);
                // batch
                for(int rep = 0; rep < 1024 && rep + iter < 100000000LL; rep++){
                    int u = rng() % n;
                    int d = gain[u];
                    if(d > 0 || (d == 0 && (rng() & 1)) || 
                       (d < 0 && (rng() & 0xFFFF) < (unsigned)(exp(d / T) * 65536))){
                        flipNode(u);
                    }
                }
                iter += 1024;
                
                // periodic local search
                if((iter & 16383) == 0){
                    localSearch();
                    curCut = calcCut();
                    if(curCut > bestLocalCut){ bestLocalCut = curCut; bestLocal = s; }
                }
            } else {
                iter++;
            }
        }
        
        s = bestLocal;
        calcGain();
        localSearch();
        curCut = calcCut();
        if(curCut > bestCut){ bestCut = curCut; best = s; }
    }
    
    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << best[i];
    }
    cout << '\n';
}
