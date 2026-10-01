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
    
    mt19937 rng(12345);
    vector<int> bestS(n, 0), s(n), gain(n);
    int bestCut = -1;
    
    auto computeGain = [&]() -> int {
        fill(gain.begin(), gain.end(), 0);
        int cur = 0;
        for(auto& [u,v] : edges){
            if(s[u]==s[v]){ gain[u]++; gain[v]++; }
            else { gain[u]--; gain[v]--; cur++; }
        }
        return cur;
    };
    
    auto flip = [&](int u, int& cur){
        cur += gain[u];
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            if(s[u]==s[v]){ gain[u]--; gain[v]--; }
            else { gain[u]++; gain[v]++; }
        }
    };
    
    // Oops, the flip function above is wrong. Let me redo properly.
    auto flip2 = [&](int u, int& cur){
        cur += gain[u];
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            // After flipping u: if now same side, this edge is not cut (was cut before) -> neighbor gains +2
            // If now different side, this edge is cut (wasn't before) -> neighbor gains -2
            if(s[u]==s[v]){ gain[v] += 2; } else { gain[v] -= 2; }
        }
    };
    
    auto localSearch = [&](int& cur){
        bool imp = true;
        while(imp){
            imp = false;
            for(int u = 0; u < n; u++){
                if(gain[u] > 0){ flip2(u, cur); imp = true; }
            }
        }
    };
    
    auto t0 = chrono::steady_clock::now();
    auto elapsed = [&]() -> int {
        return (int)chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - t0).count();
    };
    
    while(elapsed() < 1800){
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        int cur = computeGain();
        localSearch(cur);
        if(cur > bestCut){ bestCut = cur; bestS = s; }
        
        // SA phase
        double T = 0.05 * m + 1.0;
        for(int it = 0; it < 500000 && T > 0.01; it++){
            if(it % 20000 == 0 && elapsed() > 1800) break;
            T *= 0.99997;
            int u = rng() % n;
            int g = gain[u];
            if(g > 0 || (rng() % 1000000) < (int)(1000000.0 * exp((double)g / T))){
                flip2(u, cur);
            }
        }
        localSearch(cur);
        if(cur > bestCut){ bestCut = cur; bestS = s; }
    }
    
    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << bestS[i];
    }
    cout << '\n';
}
