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
        int u, v;
        cin >> u >> v;
        u--; v--;
        edges[i] = {u, v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    
    if(m == 0){
        for(int i = 0; i < n; i++){
            cout << 0;
            if(i < n-1) cout << ' ';
        }
        cout << '\n';
        return 0;
    }
    
    auto evaluate = [&](vector<int>& s) -> int {
        int cut = 0;
        for(auto& [u,v] : edges)
            if(s[u] != s[v]) cut++;
        return cut;
    };
    
    // Compute gain array
    auto computeGain = [&](vector<int>& s, vector<int>& gain){
        fill(gain.begin(), gain.end(), 0);
        for(int u = 0; u < n; u++){
            for(int v : adj[u]){
                if(s[u] == s[v]) gain[u]++;
                else gain[u]--;
            }
        }
    };
    
    auto flipVertex = [&](vector<int>& s, vector<int>& gain, int u){
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            if(s[u] == s[v]){
                gain[v] -= 2;
            } else {
                gain[v] += 2;
            }
        }
    };
    
    auto localSearch = [&](vector<int>& s, vector<int>& gain) -> int {
        bool improved = true;
        while(improved){
            improved = false;
            for(int u = 0; u < n; u++){
                if(gain[u] > 0){
                    flipVertex(s, gain, u);
                    improved = true;
                }
            }
        }
        return evaluate(s);
    };
    
    vector<int> bestS(n, 0);
    int bestCut = 0;
    
    mt19937 rng(12345);
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    vector<int> gain(n);
    
    for(int restart = 0; elapsed() < 4.5; restart++){
        vector<int> s(n);
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        
        computeGain(s, gain);
        localSearch(s, gain);
        
        // Simulated annealing
        int curCut = evaluate(s);
        double T = 2.0;
        double cool = 0.9995;
        int iters = max(100000, n * 200);
        
        for(int it = 0; it < iters && T > 0.001; it++){
            int u = rng() % n;
            int delta = gain[u]; // improvement if we flip
            if(delta > 0 || (T > 0 && exp(delta / T) > (rng() % 10000) / 10000.0)){
                flipVertex(s, gain, u);
                curCut += delta;
            }
            T *= cool;
        }
        
        // Final local search
        curCut = localSearch(s, gain);
        
        if(curCut > bestCut){
            bestCut = curCut;
            bestS = s;
        }
    }
    
    for(int i = 0; i < n; i++){
        cout << bestS[i];
        if(i < n-1) cout << ' ';
    }
    cout << '\n';
    
    return 0;
}
