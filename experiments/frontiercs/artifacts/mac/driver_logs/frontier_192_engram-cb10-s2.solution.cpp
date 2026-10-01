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
        int u, v; cin >> u >> v; u--; v--;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    auto start_time = chrono::steady_clock::now();
    auto elapsed_ms = [&]() -> double {
        return chrono::duration<double,milli>(chrono::steady_clock::now()-start_time).count();
    };
    
    vector<int> best_s(n, 0);
    int best_cut = -1;
    mt19937 rng(12345);
    
    while(elapsed_ms() < 1800.0){
        vector<int> s(n);
        for(int i = 0; i < n; i++) s[i] = rng()&1;
        
        vector<int> gain(n, 0);
        for(int v = 0; v < n; v++){
            for(int u : adj[v]){
                if(s[u]==s[v]) gain[v]++; else gain[v]--;
            }
        }
        
        bool imp = true;
        while(imp){
            imp = false;
            for(int v = 0; v < n; v++){
                if(gain[v] > 0){
                    s[v]^=1; gain[v]=-gain[v];
                    for(int u : adj[v]){
                        if(s[u]==s[v]) gain[u]+=2; else gain[u]-=2;
                    }
                    imp = true;
                }
            }
        }
        
        int cut = 0;
        for(auto&[u,v]:edges) if(s[u]!=s[v]) cut++;
        if(cut > best_cut){ best_cut = cut; best_s = s; }
        
        double T = 3.0;
        while(T > 0.01 && elapsed_ms() < 1800.0){
            for(int it = 0; it < n; it++){
                int v = rng()%n;
                int g = gain[v];
                if(g > 0 || (rng()%1000000) < (int)(1000000.0*exp((double)g/T))){
                    s[v]^=1; gain[v]=-gain[v];
                    for(int u : adj[v]){
                        if(s[u]==s[v]) gain[u]+=2; else gain[u]-=2;
                    }
                }
            }
            T *= 0.999;
            cut = 0;
            for(auto&[u,v]:edges) if(s[u]!=s[v]) cut++;
            if(cut > best_cut){ best_cut = cut; best_s = s; }
        }
    }
    
    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << best_s[i];
    }
    cout << '\n';
}
