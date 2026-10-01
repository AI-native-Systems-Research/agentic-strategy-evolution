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
    vector<int> bestSide(n+1,0);
    mt19937 rng(12345);
    auto timeStart=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-timeStart).count();};
    int bestCut=-1;
    while(elapsed()<4.0){
        vector<int> side(n+1);
        for(int i=1;i<=n;i++) side[i]=rng()&1;
        vector<int> gain(n+1,0);
        for(int v=1;v<=n;v++)
            for(int u:adj[v])
                gain[v]+=(side[u]==side[v])?1:-1;
        int curCut=0;
        for(auto&[u,v]:edges) if(side[u]!=side[v]) curCut++;
        bool improved=true;
        while(improved){
            improved=false;
            for(int v=1;v<=n;v++){
                if(gain[v]>0){
                    side[v]^=1; curCut+=gain[v];
                    for(int u:adj[v]){
                        if(side[u]==side[v]) gain[u]+=2; else gain[u]-=2;
                    }
                    gain[v]=-gain[v]; improved=true;
                }
            }
        }
        if(curCut>bestCut){bestCut=curCut;bestSide=side;}
        double T=2.0;
        uniform_real_distribution<double> d01(0,1);
        double phaseEnd=min(elapsed()+0.5,4.0);
        while(elapsed()<phaseEnd){
            for(int it=0;it<2000;it++){
                int v=(rng()%n)+1;
                int g=gain[v];
                if(g>0||d01(rng)<exp((double)g/T)){
                    side[v]^=1; curCut+=g;
                    for(int u:adj[v]){if(side[u]==side[v])gain[u]+=2;else gain[u]-=2;}
                    gain[v]=-g;
                    if(curCut>bestCut){bestCut=curCut;bestSide=side;}
                }
                T*=0.99999; if(T<0.01)T=0.01;
            }
        }
    }
    cout<<bestCut<<'\n';
    for(int i=1;i<=n;i++){cout<<(bestSide[i]+1);if(i<n)cout<<' ';}
    cout<<'\n';
}
