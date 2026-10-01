#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n,m;
    cin>>n>>m;
    vector<pair<int,int>> edges(m);
    vector<vector<int>> adj(n);
    for(int i=0;i<m;i++){
        int u,v;cin>>u>>v;u--;v--;
        edges[i]={u,v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    if(m==0){
        for(int i=0;i<n;i++){if(i)cout<<' ';cout<<0;}
        cout<<'\n';
        return 0;
    }
    vector<int> best(n,0);
    int bestCut=0;
    mt19937 rng(42);
    auto start=chrono::steady_clock::now();
    auto ms=[&]()->long long{return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-start).count();};
    while(ms()<1900){
        vector<int> s(n);
        for(int i=0;i<n;i++) s[i]=rng()&1;
        // compute gain for each vertex: how much cut increases if we flip it
        vector<int> gain(n,0);
        for(int u=0;u<n;u++)
            for(int v:adj[u])
                gain[u]+=(s[u]==s[v])?1:-1;
        auto doFlip=[&](int u){
            for(int v:adj[u]){
                if(s[u]==s[v]){gain[v]-=2;}
                else{gain[v]+=2;}
            }
            s[u]^=1;
            gain[u]=-gain[u];
        };
        // local search
        bool imp=true;
        while(imp){imp=false;for(int u=0;u<n;u++)if(gain[u]>0){doFlip(u);imp=true;}}
        int cut=0;
        for(auto&[u,v]:edges) cut+=(s[u]!=s[v]);
        if(cut>bestCut){bestCut=cut;best=s;}
        // SA
        double T=2.0;
        uniform_real_distribution<double> rd(0.0,1.0);
        for(int it=0;it<4000000&&ms()<1900;it++){
            int u=rng()%n;
            int g=gain[u];
            if(g>0||(g==0&&(rng()&1))||(T>1e-12&&rd(rng)<exp((double)g/T))){
                doFlip(u);
                cut+=g;
                if(cut>bestCut){bestCut=cut;best=s;}
            }
            if((it&0xFFF)==0) T*=0.997;
        }
        // final local search
        imp=true;
        while(imp){imp=false;for(int u=0;u<n;u++)if(gain[u]>0){doFlip(u);imp=true;}}
        cut=0;
        for(auto&[u,v]:edges) cut+=(s[u]!=s[v]);
        if(cut>bestCut){bestCut=cut;best=s;}
    }
    for(int i=0;i<n;i++){if(i)cout<<' ';cout<<best[i];}
    cout<<'\n';
}
