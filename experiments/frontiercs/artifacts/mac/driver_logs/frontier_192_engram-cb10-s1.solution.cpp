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
        vector<int> side(n+1, 0);
        for(int v = 1; v <= n; v++) side[v] = rng() & 1;
        
        // gain[v] = increase in cut if we flip v
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++){
            for(int u : adj[v]){
                if(side[u] == side[v]) gain[v]++; else gain[v]--;
            }
        }
        
        int curCut = 0;
        for(auto& [u,v] : edges) if(side[u] != side[v]) curCut++;
        
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    side[v] ^= 1;
                    curCut += gain[v];
                    for(int u : adj[v]){
                        if(side[u] == side[v]) gain[u] -= 2; else gain[u] += 2;
                    }
                    gain[v] = -gain[v];
                    improved = true;
                }
            }
        }
        
        if(curCut > bestCut){ bestCut = curCut; bestSide = side; }
    }
    
    cout << bestCut << "\n";
    for(int i = 1; i <= n; i++){
        if(i > 1) cout << " ";
        cout << bestSide[i];
    }
    cout << "\n";
    
    return 0;
}
