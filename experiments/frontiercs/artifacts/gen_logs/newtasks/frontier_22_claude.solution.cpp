#include<bits/stdc++.h>
using namespace std;
int main(){
    int n;scanf("%d",&n);
    vector<vector<int>>ch(n+1);
    vector<int>par(n+1,0);
    for(int i=2;i<=n;i++){scanf("%d",&par[i]);ch[par[i]].push_back(i);}
    // find leaves in order (DFS preorder, leaves in DFS order = counterclockwise order on ring)
    vector<int>leaves;
    vector<bool>isleaf(n+1,false);
    function<void(int)>dfs=[&](int u){if(ch[u].empty()){leaves.push_back(u);isleaf[u]=true;}for(auto c:ch[u])dfs(c);};
    dfs(1);
    int k=leaves.size();
    // Halin graph tree decomposition via fan reduction
    vector<array<int,4>>bags;
    vector<pair<int,int>>edges;
    vector<int>deg(n+1,0);
    for(int i=1;i<=n;i++)deg[i]=(int)ch[i].size()+(i!=1?1:0);
    // leaf cycle neighbors
    map<int,int>leafpos;
    for(int i=0;i<k;i++)leafpos[leaves[i]]=i;
    vector<int>cyc=leaves;// current cycle
    // each leaf maps to a bag id (or -1)
    map<int,int>leafbag;
    for(auto l:leaves)leafbag[l]=-1;
    while(cyc.size()>3){
        bool found=false;
        int sz=cyc.size();
        for(int i=0;i<sz;i++){
            int v=cyc[i],u=cyc[(i+1)%sz],w=cyc[(i+2)%sz];
            if(par[u]!=0&&deg[par[u]]==1+(par[u]!=1?1:0)){// u's parent has only u as remaining child? No, check if u is leaf and parent becomes leaf after removal
            }
            // simpler: just ear decomposition - if u's parent p has u as only non-removed child and p!=root or p has deg 2
            // Just create a bag {v,u,w} triangle, remove u
            int bid=bags.size();
            bags.push_back({3,v,u,w});
            if(leafbag.count(u)&&leafbag[u]>=0)edges.push_back({bid,leafbag[u]});
            if(leafbag.count(v)&&leafbag[v]>=0){edges.push_back({bid,leafbag[v]});} leafbag[v]=bid;
            if(leafbag.count(w)&&leafbag[w]>=0&&leafbag[w]!=bid){edges.push_back({bid,leafbag[w]});}leafbag[w]=bid;
            cyc.erase(cyc.begin()+((i+1)%sz));found=true;break;
        }
        if(!found)break;
    }
    if(cyc.size()<=4){int bid=bags.size();array<int,4>b={};b[0]=cyc.size();for(int i=0;i<(int)cyc.size();i++)b[i+1]=cyc[i]; bags.push_back(b);for(auto c:cyc)if(leafbag.count(c)&&leafbag[c]>=0)edges.push_back({bid,leafbag[c]});}
    printf("%d\n",(int)bags.size());
    for(auto&b:bags){printf("%d",b[0]);for(int i=1;i<=b[0];i++)printf(" %d",b[i]);printf("\n");}
    for(auto&[a,b]:edges)printf("%d %d\n",a+1,b+1);
}
