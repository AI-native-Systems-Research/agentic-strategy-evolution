#include <bits/stdc++.h>
using namespace std;
int main(int argc, char** argv){
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
    
    printf("n=%d m=%d avg_deg=%.2f\n",N,M,(double)M/N);
    printf("a_i: ");
    for(int i=0;i<10;i++) printf("%d ",a[i]);
    printf("\n");
    
    // Degree distribution
    map<int,int> od_hist, id_hist;
    int min_od=N,max_od=0,min_id=N,max_id=0;
    int zero_od=0, zero_id=0;
    for(int u=1;u<=N;u++){
        od_hist[odeg[u]]++;
        id_hist[ideg[u]]++;
        min_od=min(min_od,odeg[u]); max_od=max(max_od,odeg[u]);
        min_id=min(min_id,ideg[u]); max_id=max(max_id,ideg[u]);
        if(odeg[u]==0) zero_od++;
        if(ideg[u]==0) zero_id++;
    }
    printf("out-degree: min=%d max=%d zero=%d\n",min_od,max_od,zero_od);
    printf("in-degree: min=%d max=%d zero=%d\n",min_id,max_id,zero_id);
    
    // Show degree histogram (top entries)
    printf("out-degree histogram (top 15):\n");
    int cnt=0;
    for(auto&[d,c]:od_hist){
        printf("  deg %d: %d vertices (%.1f%%)\n",d,c,100.0*c/N);
        if(++cnt>=15) break;
    }
    printf("in-degree histogram (top 15):\n");
    cnt=0;
    for(auto&[d,c]:id_hist){
        printf("  deg %d: %d vertices (%.1f%%)\n",d,c,100.0*c/N);
        if(++cnt>=15) break;
    }
    
    // Vertices with both low in and out degree
    int low_both=0;
    for(int u=1;u<=N;u++){
        if(odeg[u]<=2 && ideg[u]<=2) low_both++;
    }
    printf("vertices with odeg<=2 AND ideg<=2: %d (%.1f%%)\n",low_both,100.0*low_both/N);
    
    // Count vertices that are "forced" (odeg=1 or ideg=1)
    int forced=0;
    for(int u=1;u<=N;u++){
        if(odeg[u]==1 || ideg[u]==1) forced++;
    }
    printf("forced vertices (odeg=1 or ideg=1): %d (%.1f%%)\n",forced,100.0*forced/N);
    
    return 0;
}
