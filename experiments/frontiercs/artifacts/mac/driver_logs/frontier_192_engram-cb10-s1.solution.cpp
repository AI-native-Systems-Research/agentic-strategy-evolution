#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<vector<int>> adj(n);
    vector<pair<int,int>> edges(m);
    
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        u--; v--;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    mt19937 rng(42);
    
    auto computeCut = [&](vector<int>& side) -> int {
        int c = 0;
        for(auto&[u,v]:edges) if(side[u]!=side[v]) c++;
        return c;
    };
    
    auto localSearch = [&](vector<int>& side) {
        vector<int> gain(n, 0);
        for(int v = 0; v < n; v++)
            for(int u : adj[v])
                gain[v] += (side[u]==side[v]) ? 1 : -1;
        
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 0; v < n; v++){
                if(gain[v] > 0){
                    side[v] ^= 1;
                    for(int u : adj[v]){
                        if(side[u]==side[v]) gain[u] += 2; else gain[u] -= 2;
                    }
                    gain[v] = -gain[v];
                    improved = true;
                }
            }
        }
    };
    
    int bestCut = -1;
    vector<int> bestSide(n, 0);
    auto ts = chrono::steady_clock::now();
    
    int iters = 0;
    while(chrono::duration<double>(chrono::steady_clock::now()-ts).count() < 4.0){
        vector<int> side(n);
        for(int i = 0; i < n; i++) side[i] = rng() & 1;
        localSearch(side);
        int c = computeCut(side);
        if(c > bestCut){ bestCut = c; bestSide = side; }
        iters++;
        if(iters > 1000) break;
    }
    
    // Output: just partition, space-separated, 1-indexed groups
    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << (bestSide[i] + 1);
    }
    cout << "\n";
    
    return 0;
}
