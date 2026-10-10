#include <bits/stdc++.h>
using namespace std;

int main(){
    int n, m;
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    vector<vector<int>> adj(n+1);
    for(int i=0;i<m;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj[u].push_back(v);
    }

    mt19937 rng(42);
    auto t0=chrono::high_resolution_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::high_resolution_clock::now()-t0).count();
    };

    int bestLen=0;
    vector<int> bestPath;
    vector<char> used(n+1);

    // Random greedy: no Warnsdorff, forward-only, no insertion
    while(elapsed()<3.5){
        int start=(rng()%n)+1;
        for(int u=1;u<=n;u++) used[u]=0;
        used[start]=1;

        vector<int> path;
        path.reserve(n);
        path.push_back(start);
        int cur=start;

        while(true){
            // Collect unvisited neighbors
            int cnt=0;
            int picks[32];
            for(int v:adj[cur]){
                if(!used[v] && cnt<32){
                    picks[cnt++]=v;
                }
            }
            if(!cnt) break;
            // Pick randomly (no Warnsdorff)
            int p=picks[rng()%cnt];
            used[p]=1;
            path.push_back(p);
            cur=p;
        }

        if((int)path.size()>bestLen){
            bestLen=(int)path.size();
            bestPath=path;
        }
        if(bestLen==n) break;
    }

    printf("%d\n",bestLen);
    for(int i=0;i<bestLen;i++){
        if(i) printf(" ");
        printf("%d",bestPath[i]);
    }
    printf("\n");
    return 0;
}
