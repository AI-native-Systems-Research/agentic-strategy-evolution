#include <bits/stdc++.h>
using namespace std;

struct Node {
    int id;
    double x, y;
    char type;
};

int par[6001], rnk_[6001];
int find_(int x){return par[x]==x?x:par[x]=find_(par[x]);}
bool unite_(int a,int b){a=find_(a);b=find_(b);if(a==b)return false;if(rnk_[a]<rnk_[b])swap(a,b);par[b]=a;if(rnk_[a]==rnk_[b])rnk_[a]++;return true;}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N,K;
    cin>>N>>K;
    
    vector<Node> nd(N+K);
    for(int i=0;i<N+K;i++){
        cin>>nd[i].id>>nd[i].x>>nd[i].y>>nd[i].type;
    }
    
    // Separate robots and relays
    vector<int> robots, relays;
    for(int i=0;i<N+K;i++){
        if(nd[i].type=='C') relays.push_back(i);
        else robots.push_back(i);
    }
    
    int NR=robots.size();
    
    auto dist2=[&](int i,int j)->double{
        double dx=nd[i].x-nd[j].x, dy=nd[i].y-nd[j].y;
        return dx*dx+dy*dy;
    };
    
    auto edgeCost=[&](int i,int j)->double{
        if(nd[i].type=='C'&&nd[j].type=='C') return 1e18;
        double D=dist2(i,j);
        if(nd[i].type!='C'&&nd[j].type!='C'){
            if(nd[i].type=='S'||nd[j].type=='S') return 0.8*D;
            return D;
        }
        return D; // relay to robot
    };
    
    // Prim's MST over robots only
    vector<double> key(NR,1e18);
    vector<int> parent(NR,-1);
    vector<bool> inMST(NR,false);
    key[0]=0;
    
    // Use O(N^2) Prim
    for(int iter=0;iter<NR;iter++){
        int u=-1;
        for(int i=0;i<NR;i++)
            if(!inMST[i]&&(u==-1||key[i]<key[u])) u=i;
        inMST[u]=true;
        for(int v=0;v<NR;v++){
            if(!inMST[v]){
                double c=edgeCost(robots[u],robots[v]);
                if(c<key[v]){key[v]=c;parent[v]=u;}
            }
        }
    }
    
    // MST edges (in robot-index space)
    struct TEdge{int u,v;double w;};
    vector<TEdge> treeEdges;
    double totalCost=0;
    for(int i=1;i<NR;i++){
        double c=edgeCost(robots[i],robots[parent[i]]);
        treeEdges.push_back({robots[i],robots[parent[i]],c});
        totalCost+=c;
    }
    
    // Now try inserting relays: for each relay c, for each pair of robots (or nodes) 
    // connected by a tree edge, check if routing through c is cheaper
    // Simple approach: for each tree edge (u,v) with cost w, and each relay c,
    // check if edgeCost(u,c)+edgeCost(v,c) < w. If so, replace.
    
    set<int> usedRelays;
    bool improved=true;
    while(improved){
        improved=false;
        for(auto& re:relays){
            if(usedRelays.count(re)) continue;
            int bestE=-1; double bestSave=-1e-9;
            for(int e=0;e<(int)treeEdges.size();e++){
                double nc=edgeCost(treeEdges[e].u,re)+edgeCost(treeEdges[e].v,re);
                double save=treeEdges[e].w-nc;
                if(save>bestSave){bestSave=save;bestE=e;}
            }
            if(bestE>=0&&bestSave>1e-9){
                int u=treeEdges[bestE].u, v=treeEdges[bestE].v;
                treeEdges[bestE]={u,re,edgeCost(u,re)};
                treeEdges.push_back({re,v,edgeCost(re,v)});
                usedRelays.insert(re);
                totalCost-=bestSave;
                improved=true;
            }
        }
    }
    
    // Also try: for relay already in tree with degree 2, try connecting to a third robot
    // to save another edge (Steiner node with degree 3)
    // Build adjacency for tree
    {
        bool imp2=true;
        while(imp2){
            imp2=false;
            // For each used relay, find its neighbors in tree
            map<int,vector<int>> adj; // node -> list of edge indices
            for(int e=0;e<(int)treeEdges.size();e++){
                adj[treeEdges[e].u].push_back(e);
                adj[treeEdges[e].v].push_back(e);
            }
            // For each tree edge not involving a relay, check if an existing relay could help
            // by becoming degree 3
            // Skip for now - the simple approach should work
            break;
        }
    }
    
    // Output
    if(usedRelays.empty()) cout<<"#"<<"\n";
    else{
        bool first=true;
        for(int c:usedRelays){
            if(!first)cout<<"#";
            cout<<nd[c].id;
            first=false;
        }
        cout<<"\n";
    }
    
    {
        bool first=true;
        for(auto&e:treeEdges){
            if(!first)cout<<"#";
            cout<<nd[e.u].id<<"-"<<nd[e.v].id;
            first=false;
        }
        cout<<"\n";
    }
    
    return 0;
}
