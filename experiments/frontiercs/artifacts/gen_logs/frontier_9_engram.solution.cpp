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
        
        // Precompute BFS tree for distances/paths
        // For each node, compute parent and depth for LCA / path finding
        vector<int> depth(n+1,0), par(n+1,0);
        vector<int> order;
        vector<bool> visited(n+1,false);
        queue<int> q;
        q.push(1); visited[1]=true;
        while(!q.empty()){
            int u=q.front();q.pop();
            order.push_back(u);
            for(auto [v,ei]:adj[u]) if(!visited[v]){
                visited[v]=true;
                par[v]=u;
                depth[v]=depth[u]+1;
                q.push(v);
            }
        }
        
        vector<vector<int>> results;
        
        for(int iter=0;iter<2*n;iter++){
            bool done=true;
            for(int i=1;i<=n;i++) if(p[i]!=i){done=false;break;}
            if(done) break;
            
            // Compute benefit of each edge swap and greedily pick matching
            vector<pair<int,int>> benefit_edges; // (benefit, edge_index)
            for(int i=0;i<n-1;i++){
                auto [u,v]=edges[i];
                int bu=0,bv=0,au=0,av=0;
                // current: p[u] at u, p[v] at v. After swap: p[v] at u, p[u] at v
                bu += (p[u]==u?1:0)+(p[v]==v?1:0);
                au += (p[v]==u?1:0)+(p[u]==v?1:0);
                int ben = au - bu;
                if(ben > 0) benefit_edges.push_back({ben, i});
            }
            sort(benefit_edges.rbegin(), benefit_edges.rend());
            
            vector<bool> used(n+1,false);
            vector<int> matching;
            for(auto [ben,ei]:benefit_edges){
                auto [u,v]=edges[ei];
                if(!used[u]&&!used[v]){
                    used[u]=used[v]=true;
                    matching.push_back(ei);
                    swap(p[u],p[v]);
                }
            }
            if(matching.empty()){
                // Force a random beneficial or any swap
                for(int i=0;i<n-1;i++){
                    auto [u,v]=edges[i];
                    if(p[u]!=u||p[v]!=v){
                        matching.push_back(i);
                        swap(p[u],p[v]);
                        break;
                    }
                }
            }
            results.push_back(matching);
        }
        printf("%d\n",(int)results.size());
        for(auto &m:results){
            printf("%d",(int)m.size());
            for(int ei:m) printf(" %d",ei+1);
            printf("\n");
        }
    }
}
