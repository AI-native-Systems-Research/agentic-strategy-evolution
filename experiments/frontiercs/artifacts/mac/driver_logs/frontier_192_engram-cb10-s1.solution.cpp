#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n,m;
    cin>>n>>m;
    vector<vector<int>> adj(n+1);
    vector<pair<int,int>> edges(m);
    for(int i=0;i<m;i++){
        int u,v; cin>>u>>v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i]={u,v};
    }
    int bestCut=-1;
    vector<int> bestSide(n+1,0);
    mt19937 rng(12345);
    auto t0=chrono::steady_clock::now();
    auto ms=[&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    while(ms()<4500){
        vector<int> s(n+1);
        for(int i=1;i<=n;i++) s[i]=rng()&1;
        vector<int> g(n+1,0);
        for(int v=1;v<=n;v++)
            for(int u:adj[v])
                g[v]+=(s[u]==s[v])?1:-1;
        int cc=0;
        for(auto&[u,v]:edges) cc+=(s[u]!=s[v]);
        auto doFlip=[&](int v){
            cc+=g[v]; s[v]^=1;
            for(int u:adj[v]){
                if(s[u]==s[v]) g[u]+=2;
                else g[u]-=2;
            }
            g[v]=-g[v];
        };
        bool imp=true;
        while(imp){
            imp=false;
            for(int v=1;v<=n;v++)
                if(g[v]>0){doFlip(v);imp=true;}
        }
        if(cc>bestCut){bestCut=cc;bestSide=s;}
    }
    cout<<bestCut<<"\n";
    for(int i=1;i<=n;i++){
        if(i>1) cout<<' ';
        cout<<(bestSide[i]+1);
    }
    cout<<"\n";
}
