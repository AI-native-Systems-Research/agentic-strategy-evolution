#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    auto start_time = chrono::steady_clock::now();
    
    int n, m;
    cin >> n >> m;
    
    vector<vector<int>> adj(n);
    vector<pair<int,int>> edges(m);
    
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        u--; v--;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    auto elapsed_ms = [&]() -> double {
        return chrono::duration<double,milli>(chrono::steady_clock::now()-start_time).count();
    };
    
    vector<int> best_s(n, 0);
    int best_cut = -1;
    mt19937 rng(12345);
    
    vector<int> s(n), gain(n);
    vector<bool> inq(n, false);
    
    while(elapsed_ms() < 1800.0){
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        
        // Greedy assign
        vector<int> ord(n); iota(ord.begin(),ord.end(),0);
        shuffle(ord.begin(),ord.end(),rng);
        for(int v : ord){
            int c0=0,c1=0;
            for(int u:adj[v]) if(s[u]==0)c0++;else c1++;
            s[v]=(c0>=c1)?1:0;
        }
        
        // Compute gains
        for(int v=0;v<n;v++){
            gain[v]=0;
            for(int u:adj[v]) gain[v]+=(s[u]==s[v])?1:-1;
        }
        
        // Queue-based local search
        queue<int> q;
        fill(inq.begin(),inq.end(),false);
        for(int v=0;v<n;v++) if(gain[v]>0){q.push(v);inq[v]=true;}
        while(!q.empty()){
            int v=q.front();q.pop();inq[v]=false;
            if(gain[v]<=0) continue;
            s[v]^=1;
            gain[v]=-gain[v];
            for(int u:adj[v]){
                if(s[u]==s[v]){gain[u]+=2;}
                else{gain[u]-=2;}
                if(gain[u]>0&&!inq[u]){q.push(u);inq[u]=true;}
            }
        }
        
        // SA phase
        double temp=2.0;
        uniform_real_distribution<double> ud(0.0,1.0);
        for(int it=0;it<200000&&elapsed_ms()<1800.0;it++){
            int v=rng()%n;
            int g=gain[v];
            if(g>0||ud(rng)<exp((double)g/temp)){
                s[v]^=1;gain[v]=-gain[v];
                for(int u:adj[v]){
                    if(s[u]==s[v])gain[u]+=2;else gain[u]-=2;
                }
            }
            temp*=0.99995;
            if(temp<0.01)temp=0.01;
        }
        
        // Final local search
        for(int v=0;v<n;v++) if(gain[v]>0&&!inq[v]){q.push(v);inq[v]=true;}
        while(!q.empty()){
            int v=q.front();q.pop();inq[v]=false;
            if(gain[v]<=0) continue;
            s[v]^=1;gain[v]=-gain[v];
            for(int u:adj[v]){
                if(s[u]==s[v])gain[u]+=2;else gain[u]-=2;
                if(gain[u]>0&&!inq[u]){q.push(u);inq[u]=true;}
            }
        }
        
        int cut=0;
        for(auto&[u,v]:edges) if(s[u]!=s[v]) cut++;
        if(cut>best_cut){best_cut=cut;best_s=s;}
    }
    
    for(int i=0;i<n;i++){
        if(i)cout<<' ';
        cout<<best_s[i];
    }
    cout<<'\n';
}
