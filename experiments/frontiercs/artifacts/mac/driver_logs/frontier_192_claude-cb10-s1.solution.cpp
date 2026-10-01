#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<pair<int,int>> edges(m);
    vector<vector<int>> adj(n);
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v; u--; v--;
        edges[i] = {u, v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    
    if(m == 0){
        for(int i = 0; i < n; i++){ if(i) cout << ' '; cout << 0; }
        cout << '\n';
        return 0;
    }
    
    vector<int> best(n,0), s(n), gain(n);
    int bestCut = -1;
    mt19937 rng(12345);
    
    auto calcGain = [&](){
        fill(gain.begin(), gain.end(), 0);
        for(auto&[a,b]: edges){
            if(s[a]==s[b]){ gain[a]++; gain[b]++; }
            else { gain[a]--; gain[b]--; }
        }
    };
    
    auto flipNode = [&](int u){
        s[u]^=1;
        gain[u]=-gain[u];
        for(int v: adj[u]){
            if(s[u]==s[v]){ gain[v]-=2; }
            else { gain[v]+=2; }
        }
    };
    
    auto countCut=[&](){ int c=0; for(auto&[a,b]:edges) c+=(s[a]!=s[b]); return c; };
    
    auto localSearch=[&](){
        bool imp=true;
        while(imp){ imp=false; for(int u=0;u<n;u++) if(gain[u]>0){ flipNode(u); imp=true; } }
    };
    
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){ return chrono::duration<double>(chrono::steady_clock::now()-t0).count(); };
    
    double timeLimit=1.85;
    
    while(elapsed()<timeLimit){
        for(int i=0;i<n;i++) s[i]=rng()&1;
        calcGain();
        localSearch();
        int c=countCut();
        if(c>bestCut){ bestCut=c; best=s; }
        
        double st=elapsed();
        double rt=min(timeLimit-st, 0.5);
        if(rt<0.02) break;
        
        double T0=max(2.0, 0.3*sqrt((double)m));
        int curCut=c;
        
        for(int it=0;;it++){
            if((it&1023)==0 && elapsed()-st>rt) break;
            double frac=(elapsed()-st)/rt;
            if(frac>1.0) break;
            double T=T0*(1.0-frac)+0.001;
            int u=rng()%n;
            int d=gain[u];
            if(d>0 || (double)(rng()%1000000)/1000000.0 < exp((double)d/T)){
                flipNode(u); curCut+=d;
                if(curCut>bestCut){ bestCut=curCut; best=s; }
            }
        }
        s=best; calcGain(); localSearch();
        int c2=countCut();
        if(c2>bestCut){ bestCut=c2; best=s; }
    }
    
    for(int i=0;i<n;i++){ if(i) cout<<' '; cout<<best[i]; }
    cout<<'\n';
}
