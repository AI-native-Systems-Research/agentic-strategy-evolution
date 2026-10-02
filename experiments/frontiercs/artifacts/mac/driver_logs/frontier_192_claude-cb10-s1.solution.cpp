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
        int u,v; cin>>u>>v; u--;v--;
        edges[i]={u,v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    if(m==0){
        for(int i=0;i<n;i++){if(i)cout<<' ';cout<<0;}
        cout<<'\n'; return 0;
    }
    vector<int> best(n,0);
    int bestCut=0;
    mt19937 rng(42);
    vector<int> s(n), gain(n);
    auto computeGain=[&]{
        for(int u=0;u<n;u++){
            int g=0;
            for(int v:adj[u]) g+=(s[u]==s[v])?1:-1;
            gain[u]=g;
        }
    };
    auto doFlip=[&](int u){
        for(int v:adj[u]){
            if(s[v]==s[u]) gain[v]-=2;
            else gain[v]+=2;
        }
        s[u]^=1;
        gain[u]=-gain[u];
    };
    auto localSearch=[&]{
        bool imp=true;
        while(imp){
            imp=false;
            for(int u=0;u<n;u++){
                if(gain[u]>0){doFlip(u);imp=true;}
            }
        }
    };
    auto computeCut=[&]()->int{int c=0;for(auto&[a,b]:edges)c+=(s[a]!=s[b]);return c;};
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    double TL=0.9;
    int iter=0;
    while(elapsed()<TL){
        for(int i=0;i<n;i++) s[i]=rng()&1;
        computeGain();
        localSearch();
        int c=computeCut();
        if(c>bestCut){bestCut=c;best=s;}
        double t0=elapsed();
        double timeForSA=min(0.15,TL-t0-0.02);
        if(timeForSA<0.005) continue;
        double T0=3.0;
        int steps=0;
        while(true){
            steps++;
            if((steps&1023)==0){
                double now=elapsed();
                double frac=(now-t0)/timeForSA;
                if(frac>=1.0) break;
                double T=T0*(1.0-frac)+0.001;
                // continue with this T for next batch
                for(int rep=0;rep<1024&&frac<1.0;rep++){
                    int u=rng()%n;
                    int g=gain[u];
                    if(g>=0){doFlip(u);}
                    else if(T>0.001){
                        double p=exp((double)g/T);
                        if((rng()&0xFFFFFF)<(uint32_t)(p*16777216.0)) doFlip(u);
                    }
                }
            }
        }
        computeGain();
        localSearch();
        c=computeCut();
        if(c>bestCut){bestCut=c;best=s;}
        iter++;
    }
    for(int i=0;i<n;i++){if(i)cout<<' ';cout<<best[i];}
    cout<<'\n';
}
