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
        int u, v; cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    mt19937 rng(42);
    auto start_time = chrono::steady_clock::now();
    auto elapsed_ms = [&]() -> double {
        return chrono::duration<double,milli>(chrono::steady_clock::now()-start_time).count();
    };
    
    vector<int> best_s(n+1,0);
    int best_cut = -1;
    
    auto compute_cut = [&](const vector<int>& s) -> int {
        int c=0; for(auto&[u,v]:edges) if(s[u]!=s[v]) c++; return c;
    };
    
    while(elapsed_ms() < 1500.0){
        vector<int> s(n+1);
        for(int i=1;i<=n;i++) s[i]=rng()&1;
        
        vector<int> gain(n+1,0);
        for(int v=1;v<=n;v++)
            for(int u:adj[v])
                gain[v] += (s[u]==s[v]) ? 1 : -1;
        
        bool imp=true;
        while(imp){
            imp=false;
            for(int v=1;v<=n;v++){
                if(gain[v]>0){
                    s[v]^=1; gain[v]=-gain[v];
                    for(int u:adj[v]){
                        if(s[u]==s[v]) gain[u]+=2; else gain[u]-=2;
                    }
                    imp=true;
                }
            }
        }
        
        int cur_cut = compute_cut(s);
        if(cur_cut>best_cut){best_cut=cur_cut;best_s=s;}
        
        double T=2.0;
        while(T>0.01 && elapsed_ms()<1500.0){
            for(int it=0;it<1000;it++){
                int v=(rng()%n)+1;
                if(gain[v]>0 || (rng()%1000000)<(int)(1000000*exp((double)gain[v]/T))){
                    s[v]^=1; cur_cut+=gain[v]; gain[v]=-gain[v];
                    for(int u:adj[v]){
                        if(s[u]==s[v]) gain[u]+=2; else gain[u]-=2;
                    }
                    if(cur_cut>best_cut){best_cut=cur_cut;best_s=s;}
                }
            }
            T*=0.9995;
        }
    }
    
    for(int i=1;i<=n;i++){
        if(i>1) cout<<' ';
        cout<<best_s[i];
    }
    cout<<'\n';
}
