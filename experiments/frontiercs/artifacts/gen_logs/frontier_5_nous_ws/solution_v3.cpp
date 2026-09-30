#include <bits/stdc++.h>
using namespace std;

int n, m;
vector<vector<int>> adj, radj;
vector<int> outdeg, indeg;
vector<vector<int>> sadj;

mt19937 rng(42);
chrono::high_resolution_clock::time_point t0;
double elapsed(){
    return chrono::duration<double>(chrono::high_resolution_clock::now()-t0).count();
}
bool hasEdge(int u, int v){
    return binary_search(sadj[u].begin(),sadj[u].end(),v);
}

int bestLen=0;
vector<int> bestPath;

// --- Approach 1: DFS with bounded backtracks (for small-medium graphs) ---
vector<char> vis;
vector<int> curPath;
long long bt_count;
long long bt_limit;
bool found_hp;

void dfs_bounded(int u, double tl){
    curPath.push_back(u);
    vis[u]=1;
    if((int)curPath.size()==n){ found_hp=true; return; }
    if((int)curPath.size()>bestLen){
        bestLen=curPath.size();
        bestPath=curPath;
    }
    if(elapsed()>tl){ vis[u]=0; curPath.pop_back(); return; }

    // Collect unvisited neighbors, sort by Warnsdorff (fewest unvisited out-neighbors)
    static vector<pair<int,int>> nbrs;
    nbrs.clear();
    for(int v:adj[u]) if(!vis[v]){
        int cnt=0;
        for(int w:adj[v]) if(!vis[w]) cnt++;
        nbrs.push_back({cnt,v});
    }
    sort(nbrs.begin(),nbrs.end());

    bool first=true;
    for(auto &[c,v]:nbrs){
        if(!first){
            bt_count++;
            if(bt_count>bt_limit) break;
            if(elapsed()>tl) break;
        }
        dfs_bounded(v,tl);
        if(found_hp) return;
        first=false;
    }
    vis[u]=0;
    curPath.pop_back();
}

// --- Approach 2: Enhanced greedy with Warnsdorff + bidirectional + insertion ---
vector<int> nxt_g, prv_g, dout_g;
vector<char> used_g;

void greedyRun(int start, double tl){
    for(int u=1;u<=n;u++){dout_g[u]=outdeg[u];used_g[u]=0;nxt_g[u]=0;prv_g[u]=0;}
    used_g[start]=1;
    for(int u:radj[start]) if(!used_g[u]) dout_g[u]--;

    int head=start, tail=start;
    auto mark=[&](int v){
        used_g[v]=1;
        for(int u:radj[v]) if(!used_g[u]) dout_g[u]--;
    };

    auto extF=[&]{
        while(true){
            int bd=INT_MAX,cnt=0; int picks[16];
            for(int v:adj[tail]) if(!used_g[v]){
                if(dout_g[v]<bd){bd=dout_g[v];cnt=0;picks[0]=v;cnt=1;}
                else if(dout_g[v]==bd&&cnt<16){picks[cnt++]=v;}
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            nxt_g[tail]=p;prv_g[p]=tail;nxt_g[p]=0;mark(p);tail=p;
        }
    };
    auto extB=[&]{
        while(true){
            int bd=INT_MAX,cnt=0; int picks[16];
            for(int u:radj[head]) if(!used_g[u]){
                if(dout_g[u]<bd){bd=dout_g[u];cnt=0;picks[0]=u;cnt=1;}
                else if(dout_g[u]==bd&&cnt<16){picks[cnt++]=u;}
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            prv_g[head]=p;nxt_g[p]=head;prv_g[p]=0;mark(p);head=p;
        }
    };
    auto ins=[&]()->bool{
        bool ch=false;
        int u=head;
        while(u){int w=nxt_g[u];if(!w)break;
            for(int v:adj[u]) if(!used_g[v]&&hasEdge(v,w)){
                nxt_g[u]=v;prv_g[v]=u;nxt_g[v]=w;prv_g[w]=v;mark(v);w=v;ch=true;
            }
            u=w;
        }
        // Reverse direction insertion
        u=head;
        while(u){int p2=prv_g[u];if(p2){
            for(int v:radj[u]) if(!used_g[v]&&hasEdge(p2,v)){
                nxt_g[p2]=v;prv_g[v]=p2;nxt_g[v]=u;prv_g[u]=v;mark(v);ch=true;break;
            }
        }u=nxt_g[u];}
        return ch;
    };

    extF(); extB();
    for(int p=0;p<20&&elapsed()<tl;p++){
        if(!ins()) break;
        extF(); extB();
    }

    // Post-processing: try inserting remaining unvisited vertices
    for(int iter2=0;iter2<3&&elapsed()<tl;iter2++){
        bool ch=false;
        for(int v=1;v<=n&&elapsed()<tl;v++){
            if(used_g[v]) continue;
            // Try prepend
            if(hasEdge(v,head)){
                prv_g[head]=v;nxt_g[v]=head;prv_g[v]=0;head=v;mark(v);ch=true;continue;
            }
            // Try append
            if(hasEdge(tail,v)){
                nxt_g[tail]=v;prv_g[v]=tail;nxt_g[v]=0;tail=v;mark(v);ch=true;continue;
            }
            // Try internal insert
            int u2=head;
            while(u2){
                int w=nxt_g[u2];
                if(!w) break;
                if(hasEdge(u2,v)&&hasEdge(v,w)){
                    nxt_g[u2]=v;prv_g[v]=u2;nxt_g[v]=w;prv_g[w]=v;mark(v);ch=true;break;
                }
                u2=nxt_g[u2];
            }
        }
        if(!ch) break;
    }

    int len=0;
    for(int u=head;u;u=nxt_g[u]) len++;
    if(len>bestLen){
        bestLen=len;
        bestPath.clear(); bestPath.reserve(n);
        for(int u=head;u;u=nxt_g[u]) bestPath.push_back(u);
    }
}

int main(){
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    adj.resize(n+1); radj.resize(n+1); sadj.resize(n+1);
    outdeg.assign(n+1,0); indeg.assign(n+1,0);
    for(int i=0;i<m;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj[u].push_back(v);
        radj[v].push_back(u);
        outdeg[u]++; indeg[v]++;
    }
    for(int u=1;u<=n;u++){
        sadj[u]=adj[u];
        sort(sadj[u].begin(),sadj[u].end());
    }

    t0=chrono::high_resolution_clock::now();

    nxt_g.resize(n+1); prv_g.resize(n+1);
    dout_g.resize(n+1); used_g.resize(n+1);
    vis.assign(n+1,0);

    // Start candidates
    vector<int> starts;
    for(int u=1;u<=n;u++) if(indeg[u]==0) starts.push_back(u);
    {
        vector<int> order(n); iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[&](int a2,int b2){return indeg[a2]<indeg[b2];});
        for(int i=0;i<min(n,20);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
        sort(order.begin(),order.end(),[&](int a2,int b2){return outdeg[a2]-indeg[a2]>outdeg[b2]-indeg[b2];});
        for(int i=0;i<min(n,10);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
    }

    // Strategy selection based on n
    if(n <= 2000){
        // Use DFS with bounded backtracks for small/medium graphs
        // Try smart starts with increasing backtrack budgets
        bt_limit = 500000; // backtracks budget
        for(int s:starts){
            if(bestLen==n||elapsed()>2.0) break;
            found_hp=false;
            bt_count=0;
            curPath.clear();
            dfs_bounded(s, 2.0);
            if(found_hp) break;
        }
        // Random restart DFS if not found
        while(bestLen<n && elapsed()<3.0){
            int s = (rng()%n)+1;
            found_hp=false;
            bt_count=0;
            bt_limit = 200000;
            curPath.clear();
            dfs_bounded(s, 3.0);
            if(found_hp) break;
        }
        // Fall back to greedy for remaining time
        if(bestLen<n){
            for(int s:starts){
                if(bestLen==n||elapsed()>3.5) break;
                greedyRun(s, 3.5);
            }
            while(bestLen<n && elapsed()<3.7){
                greedyRun((rng()%n)+1, 3.7);
            }
        }
    } else {
        // Use greedy for large graphs
        for(int s:starts){
            if(bestLen==n||elapsed()>1.0) break;
            greedyRun(s, 3.5);
        }
        while(bestLen<n && elapsed()<3.5){
            greedyRun((rng()%n)+1, 3.5);
        }
    }

    printf("%d\n",bestLen);
    for(int i=0;i<bestLen;i++){
        if(i) printf(" ");
        printf("%d",bestPath[i]);
    }
    printf("\n");
    return 0;
}
