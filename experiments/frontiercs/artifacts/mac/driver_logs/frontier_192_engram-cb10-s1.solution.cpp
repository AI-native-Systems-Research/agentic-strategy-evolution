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
    
    if(m == 0){
        for(int i = 1; i <= n; i++){
            cout << 0;
            if(i < n) cout << ' ';
        }
        cout << '\n';
        return 0;
    }
    
    // For each vertex, compute gain of flipping: change in cut edges
    // If vertex v is in side[v], gain[v] = (neighbors in same side) - (neighbors in different side)
    // Flipping v changes cut by gain[v]
    
    auto computeCut = [&](vector<int>& side) -> int {
        int c = 0;
        for(auto& [u,v] : edges){
            if(side[u] != side[v]) c++;
        }
        return c;
    };
    
    int bestCut = 0;
    vector<int> bestSide(n+1, 0);
    
    mt19937 rng(42);
    
    auto timeStart = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - timeStart).count();
    };
    
    double timeLimit = 4.5; // conservative under typical 5s limit
    
    int restarts = 0;
    
    while(elapsed() < timeLimit){
        restarts++;
        vector<int> side(n+1);
        for(int i = 1; i <= n; i++){
            side[i] = rng() & 1;
        }
        
        // Compute gain for each vertex: how much cut increases if we flip it
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++){
            int same = 0, diff = 0;
            for(int u : adj[v]){
                if(side[u] == side[v]) same++;
                else diff++;
            }
            gain[v] = same - diff; // flipping v increases cut by this amount
        }
        
        int curCut = computeCut(side);
        
        // Greedy local search: flip best gain vertex repeatedly
        bool improved = true;
        while(improved && elapsed() < timeLimit){
            improved = false;
            // Try all vertices, flip the one with best positive gain
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    // Flip v
                    side[v] ^= 1;
                    curCut += gain[v];
                    // Update gains of neighbors
                    for(int u : adj[v]){
                        if(side[u] == side[v]){
                            // u and v now same side; before flip they were different
                            gain[u] -= 2; // lost one diff, gained one same
                        } else {
                            gain[u] += 2;
                        }
                    }
                    gain[v] = -gain[v];
                    improved = true;
                }
            }
        }
        
        // Simulated annealing phase
        double T = 2.0;
        double coolRate = 0.9999;
        double minT = 0.01;
        uniform_real_distribution<double> dist01(0.0, 1.0);
        
        double phaseEnd = min(elapsed() + 0.3, timeLimit);
        while(elapsed() < phaseEnd){
            for(int iter = 0; iter < 1000 && T > minT; iter++){
                int v = (rng() % n) + 1;
                int g = gain[v];
                if(g > 0 || dist01(rng) < exp((double)g / T)){
                    side[v] ^= 1;
                    curCut += g;
                    for(int u : adj[v]){
                        if(side[u] == side[v]) gain[u] -= 2;
                        else gain[u] += 2;
                    }
                    gain[v] = -g;
                }
                T *= coolRate;
            }
            if(T <= minT) break;
        }
        
        // Final greedy pass
        improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    side[v] ^= 1;
                    curCut += gain[v];
                    for(int u : adj[v]){
                        if(side[u] == side[v]) gain[u] -= 2;
                        else gain[u] += 2;
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
        cout << bestSide[i];
        if(i < n) cout << ' ';
    }
    cout << '\n';
    
    return 0;
}
