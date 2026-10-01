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
    
    int bestCut = -1;
    vector<int> bestSide(n+1, 0);
    
    mt19937 rng(42);
    auto timeStart = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - timeStart).count();
    };
    
    double timeLimit = 4.5;
    
    while(elapsed() < timeLimit){
        vector<int> side(n+1);
        for(int i = 1; i <= n; i++) side[i] = rng() & 1;
        
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++){
            for(int u : adj[v]){
                if(side[u] == side[v]) gain[v]++;
                else gain[v]--;
            }
        }
        
        int curCut = 0;
        for(auto& [a,b] : edges) if(side[a] != side[b]) curCut++;
        
        auto doFlip = [&](int v){
            side[v] ^= 1;
            curCut += gain[v];
            gain[v] = -gain[v];
            for(int u : adj[v]){
                if(side[u] == side[v]) gain[u] += 2;
                else gain[u] -= 2;
            }
        };
        
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){ doFlip(v); improved = true; }
            }
        }
        
        double T = 2.0;
        uniform_real_distribution<double> dist01(0.0, 1.0);
        while(elapsed() < timeLimit && T > 0.005){
            for(int it = 0; it < 1000; it++){
                int v = (rng() % n) + 1;
                int g = gain[v];
                if(g > 0 || dist01(rng) < exp((double)g / T)) doFlip(v);
            }
            T *= 0.9995;
            // Local search after cooling
            if(T < 0.01){
                for(int v = 1; v <= n; v++) if(gain[v] > 0) doFlip(v);
            }
        }
        
        for(int v = 1; v <= n; v++) if(gain[v] > 0) doFlip(v);
        
        if(curCut > bestCut){ bestCut = curCut; bestSide = side; }
    }
    
    cout << bestCut << '\n';
    for(int i = 1; i <= n; i++){
        cout << bestSide[i];
        if(i < n) cout << ' ';
    }
    cout << '\n';
    return 0;
}
