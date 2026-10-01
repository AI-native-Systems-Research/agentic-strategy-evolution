#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    auto t0 = chrono::steady_clock::now();
    auto elapsed_ms = [&](){
        return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();
    };
    
    int n, m;
    cin >> n >> m;
    
    vector<vector<int>> adj(n);
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v; u--; v--;
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    
    vector<int> bestS(n, 0);
    int bestCut = -1;
    mt19937 rng(12345);
    vector<int> s(n), gain(n);
    
    auto computeGains = [&](){
        for(int v = 0; v < n; v++){
            int g = 0;
            for(int u : adj[v]) g += (s[u]==s[v]) ? 1 : -1;
            gain[v] = g;
        }
    };
    auto getCut = [&](){
        int c=0;
        for(int v=0;v<n;v++) for(int u:adj[v]) if(s[u]!=s[v]) c++;
        return c/2;
    };
    auto flipNode = [&](int v){
        for(int u:adj[v]){
            if(s[u]==s[v]){ gain[u]-=2; } else { gain[u]+=2; }
        }
        s[v]^=1;
        gain[v]=-gain[v];
    };
    auto localSearch = [&](){
        bool imp=true;
        while(imp){
            imp=false;
            for(int v=0;v<n;v++) if(gain[v]>0){ flipNode(v); imp=true; }
        }
    };
    
    while(elapsed_ms()<1900){
        for(int v=0;v<n;v++) s[v]=rng()&1;
        computeGains();
        localSearch();
        int curCut=getCut();
        if(curCut>bestCut){bestCut=curCut;bestS=s;}
        
        for(int iter=0;iter<300&&elapsed_ms()<1900;iter++){
            auto saved=s;
            int nf=max(1,1+(int)(rng()%max(1,n/5)));
            for(int i=0;i<nf;i++) flipNode(rng()%n);
            localSearch();
            int nc=getCut();
            if(nc>=curCut){
                curCut=nc;
                if(nc>bestCut){bestCut=nc;bestS=s;}
            } else {
                s=saved;
                computeGains();
                // keep curCut
            }
        }
    }
    
    for(int i=0;i<n;i++){
        if(i) cout<<' ';
        cout<<bestS[i];
    }
    cout<<'\n';
}
