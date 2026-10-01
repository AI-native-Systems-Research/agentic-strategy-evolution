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
        int u,v; cin>>u>>v; u--; v--;
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
    vector<int> s(n), gain(n), bestS(n);
    int bestCut=-1;
    auto computeGain=[&]()->int{
        fill(gain.begin(),gain.end(),0);
        int c=0;
        for(auto&[u,v]:edges){
            if(s[u]!=s[v]){c++;gain[u]--;gain[v]--;}
            else{gain[u]++;gain[v]++;}
        }
        return c;
    };
    auto doFlip=[&](int u,int&cur){
        cur+=gain[u];
        s[u]^=1;
        gain[u]=-gain[u];
        for(int v:adj[u]){
            if(s[u]==s[v]){gain[u]--;gain[v]-=2;}
            else{gain[u]++;gain[v]+=2;}
        }
    };
    auto localSearch=[&](int&cur){
        bool imp=true;
        while(imp){imp=false;for(int u=0;u<n;u++)if(gain[u]>0){doFlip(u,cur);imp=true;}}
    };
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    while(elapsed()<1.8){
        for(int i=0;i<n;i++) s[i]=rng()&1;
        int cur=computeGain();
        localSearch(cur);
        if(cur>bestCut){bestCut=cur;bestS=s;}
        // SA
        int sabest=cur; vector<int> saS=s;
        double st=elapsed(), budget=min(0.4, 1.75-st);
        if(budget<0.01) continue;
        double Tmax=max(2.0,0.005*m), Tmin=0.001;
        for(int it=0;;it++){
            if((it&1023)==0 && elapsed()-st>=budget) break;
            double f=(elapsed()-st)/budget;
            double T=Tmax*pow(Tmin/Tmax,f);
            int u=rng()%n;
            int g=gain[u];
            if(g>0 || (rng()%1000000)<(int)(1000000.0*exp(g/T))){
                doFlip(u,cur);
                if(cur>sabest){sabest=cur;saS=s;}
            }
        }
        s=saS; cur=computeGain(); localSearch(cur);
        if(cur>bestCut){bestCut=cur;bestS=s;}
    }
    for(int i=0;i<n;i++){if(i)cout<<' ';cout<<bestS[i];}
    cout<<'\n';
}
