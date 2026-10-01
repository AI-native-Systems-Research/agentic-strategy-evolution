#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n,m;
    cin>>n>>m;
    vector<vector<int>>adj(n+1);
    vector<pair<int,int>>edges(m);
    for(int i=0;i<m;i++){
        int u,v;cin>>u>>v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i]={u,v};
    }
    vector<int> bestSide(n+1,1);
    int bestCut=0;
    mt19937 rng(42);
    auto t0=chrono::steady_clock::now();
    auto ms=[&]()->double{return chrono::duration<double,milli>(chrono::steady_clock::now()-t0).count();};
    double TL=4500;
    
    while(ms()<TL){
        vector<int>side(n+1,0);
        for(int i=1;i<=n;i++) side[i]=rng()&1;
        
        vector<int>gain(n+1,0);
        for(int v=1;v<=n;v++){
            for(int u:adj[v]){
                if(side[u]==side[v]) gain[v]++;
                else gain[v]--;
            }
        }
        int curCut=0;
        for(auto&[u,v]:edges) if(side[u]!=side[v]) curCut++;
        
        // Local search
        bool imp=true;
        while(imp){
            imp=false;
            for(int v=1;v<=n;v++){
                if(gain[v]>0){
                    side[v]^=1;
                    curCut+=gain[v];
                    for(int u:adj[v]){
                        if(side[u]==side[v]) gain[u]-=2;
                        else gain[u]+=2;
                    }
                    gain[v]=-gain[v];
                    imp=true;
                }
            }
        }
        
        if(curCut>bestCut){bestCut=curCut;bestSide=side;}
        
        // SA
        double T=2.0;
        uniform_real_distribution<double>U(0,1);
        int noImprove=0;
        for(int it=0;it<500000&&ms()<TL;it++){
            int v=(rng()%n)+1;
            int g=gain[v];
            if(g>0||U(rng)<exp((double)g/T)){
                side[v]^=1;curCut+=g;
                for(int u:adj[v]){
                    if(side[u]==side[v])gain[u]-=2;
                    else gain[u]+=2;
                }
                gain[v]=-g;
                if(curCut>bestCut){bestCut=curCut;bestSide=side;noImprove=0;}
            }
            T*=0.999995;
            if(T<0.001)T=0.001;
        }
    }
    
    // Try both label conventions
    for(int i=1;i<=n;i++){
        cout<<(bestSide[i]+1);
        if(i<n)cout<<' ';
    }
    cout<<'\n';
}
