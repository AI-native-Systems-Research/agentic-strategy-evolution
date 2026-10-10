#include <bits/stdc++.h>
using namespace std;

int main(){
    int T;
    scanf("%d",&T);
    while(T--){
        int n;
        scanf("%d",&n);
        vector<int> p(n+1);
        for(int i=1;i<=n;i++) scanf("%d",&p[i]);
        vector<pair<int,int>> edges(n-1);
        vector<vector<pair<int,int>>> adj(n+1);
        for(int i=0;i<n-1;i++){
            int u,v;
            scanf("%d%d",&u,&v);
            edges[i]={u,v};
            adj[u].push_back({v,i});
            adj[v].push_back({u,i});
        }
        // BFS-based distance: dist[u][v]
        vector<vector<int>> dist(n+1, vector<int>(n+1,0));
        for(int s=1;s<=n;s++){
            queue<int> q;
            q.push(s);
            dist[s][s]=0;
            vector<bool> vis(n+1,false);
            vis[s]=true;
            while(!q.empty()){
                int u=q.front();q.pop();
                for(auto [v,idx]:adj[u]) if(!vis[v]){
                    vis[v]=true;
                    dist[s][v]=dist[s][u]+1;
                    q.push(v);
                }
            }
        }
        vector<vector<int>> ops;
        while(true){
            bool sorted=true;
            for(int i=1;i<=n;i++) if(p[i]!=i){sorted=false;break;}
            if(sorted) break;
            // Greedy matching: prioritize edges by benefit
            vector<pair<int,int>> cands;
            for(int i=0;i<n-1;i++){
                auto [u,v]=edges[i];
                int before=dist[u][p[u]]+dist[v][p[v]];
                int after=dist[u][p[v]]+dist[v][p[u]];
                if(after<before) cands.push_back({before-after,i});
            }
            sort(cands.rbegin(),cands.rend());
            vector<bool> used(n+1,false);
            vector<int> sel;
            for(auto [ben,i]:cands){
                auto [u,v]=edges[i];
                // recheck benefit with current p
                int before=dist[u][p[u]]+dist[v][p[v]];
                int after=dist[u][p[v]]+dist[v][p[u]];
                if(after<before && !used[u] && !used[v]){
                    used[u]=used[v]=true;
                    sel.push_back(i);
                    swap(p[u],p[v]);
                }
            }
            if(sel.empty()){
                // force a swap on any edge where p[u]!=u or p[v]!=v
                for(int i=0;i<n-1;i++){
                    auto [u,v]=edges[i];
                    if(p[u]!=u||p[v]!=v){sel.push_back(i);swap(p[u],p[v]);break;}
                }
            }
            ops.push_back(sel);
        }
        printf("%d\n",(int)ops.size());
        for(auto &op:ops){
            printf("%d",(int)op.size());
            for(int x:op) printf(" %d",x+1);
            printf("\n");
        }
    }
}
