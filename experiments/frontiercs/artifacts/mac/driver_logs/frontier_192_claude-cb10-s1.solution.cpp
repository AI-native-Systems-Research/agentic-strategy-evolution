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
    mt19937 rng(12345);
    vector<int> best(n,0), s(n), gain(n);
    int bestCut=0;
    auto calcGain=[&](){
        for(int u=0;u<n;u++){
            int g=0;
            for(int v:adj[u]) g+=(s[u]==s[v])?1:-1;
            gain[u]=g;
        }
    };
    auto flipNode=[&](int u){
        s[u]^=1; gain[u]=-gain[u];
        for(int v:adj[u]){
            if(s[u]==s[v]) gain[v]-=2;
            else gain[v]+=2;
        }
    };
    auto localSearch=[&](){
        bool imp=true;
        while(imp){
            imp=false;
            for(int u=0;u<n;u++){
                if(gain[u]>0){flipNode(u);imp=true;}
            }
        }
    };
    auto getCut=[&]()->int{int c=0;for(auto&[u,v]:edges)if(s[u]!=s[v])c++;return c;};
    auto t0=chrono::steady_clock::now();
    auto ms=[&]()->double{return chrono::duration<double,milli>(chrono::steady_clock::now()-t0).count();};
    while(ms()<900.0){
        for(int i=0;i<n;i++) s[i]=rng()&1;
        calcGain();
        localSearch();
        double T=2.0;
        uniform_real_distribution<double> uni(0.0,1.0);
        int check=0;
        for(int step=0;step<500000;step++){
            T*=0.999995;
            if(T<0.005)T=0.005;
            int u=rng()%n;
            int d=gain[u];
            if(d>0||(d==0&&(rng()&1))||uni(rng)<exp((double)d/T)){
                flipNode(u);
            }
            if(++check>=5000){check=0;if(ms()>=900.0)break;}
        }
        calcGain();
        localSearch();
        int c=getCut();
        if(c>bestCut){bestCut=c;best=s;}
    }
    for(int i=0;i<n;i++){
        if(i)cout<<' ';
        cout<<best[i];
    }
    cout<<'\n';
    return 0;
}
