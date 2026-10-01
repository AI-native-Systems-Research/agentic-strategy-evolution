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
    
    auto computeCut = [&](const vector<int>& side) -> int {
        int c = 0;
        for(auto& [u,v] : edges){
            if(side[u] != side[v]) c++;
        }
        return c;
    };
    
    auto computeGains = [&](const vector<int>& side, vector<int>& gain){
        for(int v = 1; v <= n; v++){
            int same = 0, diff = 0;
            for(int u : adj[v]){
                if(side[u] == side[v]) same++; else diff++;
            }
            gain[v] = same - diff;
        }
    };
    
    int bestCut = -1;
    vector<int> bestSide(n+1, 0);
    
    mt19937 rng(42);
    auto timeStart = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - timeStart).count();
    };
    
    while(elapsed() < 4.0){
        vector<int> side(n+1);
        for(int i = 1; i <= n; i++) side[i] = rng() & 1;
        
        vector<int> gain(n+1);
        computeGains(side, gain);
        int curCut = computeCut(side);
        
        // Greedy local search
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    curCut += gain[v];
                    side[v] ^= 1;
                    for(int u : adj[v]){
                        if(side[u] == side[v]) gain[u] += 2;
                        else gain[u] -= 2;
                    }
                    gain[v] = -gain[v];
                    improved = true;
                }
            }
        }
        
        if(curCut > bestCut){
            bestCut = curCut;
            bestSide = side;
        }
    }
    
    for(int i = 1; i <= n; i++){
        cout << bestSide[i] << "\n";
    }
    
    return 0;
}
