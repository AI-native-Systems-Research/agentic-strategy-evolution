#include <bits/stdc++.h>
using namespace std;

struct UF {
    vector<int> p, r;
    UF(int n): p(n), r(n,0) { iota(p.begin(),p.end(),0); }
    int find(int x){ return p[x]==x?x:p[x]=find(p[x]); }
    bool unite(int a, int b){ a=find(a);b=find(b);if(a==b)return false;if(r[a]<r[b])swap(a,b);p[b]=a;if(r[a]==r[b])r[a]++;return true;}
};

int main(){
    int N,K;
    scanf("%d%d",&N,&K);
    int T=N+K;
    vector<int> vid(T);
    vector<double> vx(T),vy(T);
    vector<int> tp(T);
    vector<int> robots, relays;
    for(int i=0;i<T;i++){
        char t[4];
        scanf("%d%lf%lf%s",&vid[i],&vx[i],&vy[i],t);
        tp[i]=(t[0]=='R'?0:(t[0]=='S'?1:2));
        if(tp[i]!=2) robots.push_back(i);
        else relays.push_back(i);
    }
    int NR=robots.size();
    // Edge cost
    auto ecost=[&](int i,int j)->double{
        if(tp[i]==2&&tp[j]==2) return 1e30;
        double dx=vx[i]-vx[j],dy=vy[i]-vy[j],D=dx*dx+dy*dy;
        if(tp[i]==2||tp[j]==2) return D;
        if(tp[i]==1||tp[j]==1) return 0.8*D;
        return D;
    };
    // Prim on subset
    auto primMST=[&](vector<int>&nodes)->pair<double,vector<pair<int,int>>>{
        int n=nodes.size();
        if(n<=1) return {0,{}};
        vector<double> dist(n,1e30);
        vector<int> from(n,-1);
        vector<bool> done(n,false);
        dist[0]=0;
        vector<pair<int,int>> edges;
        double total=0;
        for(int it=0;it<n;it++){
            int u=-1;
            for(int i=0;i<n;i++) if(!done[i]&&(u<0||dist[i]<dist[u])) u=i;
            if(u<0||dist[u]>=1e29) break;
            done[u]=true;
            total+=dist[u];
            if(from[u]>=0) edges.push_back({nodes[u],nodes[from[u]]});
            for(int v=0;v<n;v++) if(!done[v]){
                double c=ecost(nodes[u],nodes[v]);
                if(c<dist[v]){dist[v]=c;from[v]=u;}
            }
        }
        return {total,edges};
    };
    // Base MST (robots only)
    auto [baseCost,baseEdges]=primMST(robots);
    // Full MST (all nodes)
    vector<int> all(T);
    iota(all.begin(),all.end(),0);
    auto [fullCost,fullEdges]=primMST(all);
    // Build adjacency for full MST
    vector<vector<int>> adj(T);
    for(auto&[a,b]:fullEdges){adj[a].push_back(b);adj[b].push_back(a);}
    // Iteratively remove relay leaves that don't help
    bool changed=true;
    while(changed){
        changed=false;
        for(int r:relays){
            if(adj[r].size()==1){
                int nb=adj[r][0];
                adj[nb].erase(find(adj[nb].begin(),adj[nb].end(),r));
                adj[r].clear();
                changed=true;
            } else if(adj[r].empty()) continue;
        }
    }
    // For degree-2 relays, check if removing them saves cost
    changed=true;
    while(changed){
        changed=false;
        for(int r:relays){
            if(adj[r].size()==2){
                int a=adj[r][0], b=adj[r][1];
                double via=ecost(a,r)+ecost(r,b);
                double direct=ecost(a,b);
                if(direct<=via){
                    // Remove relay, add direct edge
                    adj[r].clear();
                    adj[a].erase(find(adj[a].begin(),adj[a].end(),r));
                    adj[b].erase(find(adj[b].begin(),adj[b].end(),r));
                    adj[a].push_back(b);
                    adj[b].push_back(a);
                    changed=true;
                }
            } else if(adj[r].size()==1){
                int nb=adj[r][0];
                adj[nb].erase(find(adj[nb].begin(),adj[nb].end(),r));
                adj[r].clear();
                changed=true;
            }
        }
    }
    // Compute cost of current tree
    double curCost=0;
    vector<pair<int,int>> curEdges;
    set<int> usedRelays;
    for(int i=0;i<T;i++) for(int j:adj[i]) if(i<j){
        curEdges.push_back({i,j});
        curCost+=ecost(i,j);
        if(tp[i]==2) usedRelays.insert(i);
        if(tp[j]==2) usedRelays.insert(j);
    }
    // Pick best solution
    double bestCost=baseCost;
    vector<pair<int,int>> bestEdges=baseEdges;
    set<int> bestRelays;
    if(curCost<bestCost){
        bestCost=curCost;
        bestEdges=curEdges;
        bestRelays=usedRelays;
    }
    // Output
    if(bestRelays.empty()) printf("#\n");
    else{bool f=1;for(int r:bestRelays){if(!f)printf("#");printf("%d",vid[r]);f=0;}printf("\n");}
    bool f=1;
    for(auto&[a,b]:bestEdges){
        int va=vid[a],vb=vid[b];
        if(va>vb) swap(va,vb);
        if(!f)printf("#");
        printf("%d-%d",va,vb);
        f=0;
    }
    if(f) printf("#");
    printf("\n");
}
