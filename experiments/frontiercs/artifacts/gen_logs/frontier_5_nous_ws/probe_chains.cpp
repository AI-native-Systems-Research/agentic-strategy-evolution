#include <bits/stdc++.h>
using namespace std;
int main(){
    int N,M;
    scanf("%d%d",&N,&M);
    int a[10]; for(int i=0;i<10;i++) scanf("%d",&a[i]);
    vector<vector<int>> adj(N+1), radj(N+1);
    vector<int> odeg(N+1,0), ideg(N+1,0);
    for(int i=0;i<M;i++){
        int u,v; scanf("%d%d",&u,&v);
        adj[u].push_back(v);
        radj[v].push_back(u);
        odeg[u]++; ideg[v]++;
    }
    
    // Find forced chains: sequences where vertices have deg-1
    // A forced forward chain: odeg[u]=1, follow the single edge
    // A forced backward chain: ideg[u]=1, follow the single reverse edge
    
    vector<bool> visited(N+1, false);
    int total_chain_verts = 0;
    int num_chains = 0;
    int max_chain = 0;
    vector<int> chain_lens;
    
    for(int u=1; u<=N; u++){
        if(visited[u]) continue;
        if(odeg[u] != 1 && ideg[u] != 1) continue;
        
        // Try to build a chain from u
        // Walk backward to find chain start
        int start = u;
        while(ideg[start]==1 && !visited[start]){
            int prev = radj[start][0];
            if(odeg[prev]==1 && !visited[prev]) start = prev;
            else break;
        }
        
        // Walk forward from start
        int v = start;
        int len = 0;
        while(!visited[v]){
            visited[v] = true;
            len++;
            if(odeg[v]==1){
                v = adj[v][0];
            } else break;
        }
        if(len > 1){
            chain_lens.push_back(len);
            total_chain_verts += len;
            num_chains++;
            max_chain = max(max_chain, len);
        }
    }
    
    sort(chain_lens.rbegin(), chain_lens.rend());
    printf("Forced chains: %d\n", num_chains);
    printf("Total chain vertices: %d (%.1f%%)\n", total_chain_verts, 100.0*total_chain_verts/N);
    printf("Max chain length: %d\n", max_chain);
    if(!chain_lens.empty()){
        printf("Top chain lengths: ");
        for(int i=0; i<min((int)chain_lens.size(),20); i++) printf("%d ", chain_lens[i]);
        printf("\n");
    }
    
    // Also analyze: for vertices NOT in forced chains, what's their connectivity?
    int free_verts = 0;
    int free_edges = 0;
    for(int u=1; u<=N; u++){
        if(!visited[u]){
            free_verts++;
            free_edges += odeg[u];
        }
    }
    printf("Free vertices (not in forced chains): %d (%.1f%%)\n", free_verts, 100.0*free_verts/N);
    if(free_verts > 0)
        printf("Free graph avg_deg: %.2f\n", (double)free_edges/free_verts);
    
    return 0;
}
