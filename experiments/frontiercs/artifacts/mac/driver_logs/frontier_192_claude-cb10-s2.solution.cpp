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
    
    vector<int> bestS(n+1, 0);
    
    if(m == 0){
        for(int i = 1; i <= n; i++){ if(i>1) cout << ' '; cout << 0; }
        cout << '\n';
        return 0;
    }
    
    vector<int> s(n+1), gain(n+1);
    int bestCut = -1;
    mt19937 rng(12345);
    
    auto startTime = chrono::steady_clock::now();
    auto ms_elapsed = [&]() -> double {
        return chrono::duration_cast<chrono::microseconds>(chrono::steady_clock::now()-startTime).count()/1000.0;
    };
    
    double timeLimit = 900.0; // 900ms to be safe
    
    while(ms_elapsed() < timeLimit){
        if(bestCut < 0 || (rng()%3) != 0){
            for(int i=1;i<=n;i++) s[i] = rng()&1;
        } else {
            s = bestS;
            for(int k=0; k < max(1,n/10); k++) s[(rng()%n)+1] ^= 1;
        }
        
        for(int u=1;u<=n;u++){
            gain[u]=0;
            for(int v:adj[u]) gain[u] += (s[u]==s[v]) ? 1 : -1;
        }
        int curCut=0;
        for(auto&[u,v]:edges) curCut += (s[u]!=s[v]);
        
        bool imp=true;
        while(imp){
            imp=false;
            for(int u=1;u<=n;u++){
                if(gain[u]>0){
                    for(int v:adj[u]){
                        if(s[u]==s[v]) gain[v]-=2; else gain[v]+=2;
                    }
                    curCut+=gain[u]; s[u]^=1; gain[u]=-gain[u]; imp=true;
                }
            }
        }
        if(curCut>bestCut){bestCut=curCut; bestS=s;}
        
        double t0=ms_elapsed();
        double budget=min(200.0, (timeLimit-t0)*0.5);
        if(budget < 5) continue;
        for(int iter=0;;iter++){
            if((iter&1023)==0 && ms_elapsed()-t0>=budget) break;
            double frac=(ms_elapsed()-t0)/budget;
            if(frac>1.0) break;
            double T=3.0*(1.0-frac)+0.01;
            int u=(rng()%n)+1;
            int g=gain[u];
            if(g>0 || (double)(rng()%65536)/65536.0 < exp((double)g/T)){
                for(int v:adj[u]){
                    if(s[u]==s[v]) gain[v]-=2; else gain[v]+=2;
                }
                s[u]^=1; gain[u]=-gain[u]; curCut+=g;
                if(curCut>bestCut){bestCut=curCut; bestS=s;}
            }
        }
    }
    
    for(int i=1;i<=n;i++){if(i>1)cout<<' ';cout<<bestS[i];}
    cout<<'\n';
}
