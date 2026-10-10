#include<bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n,m;
    cin>>n>>m;
    int a[10];
    for(int i=0;i<10;i++) cin>>a[i];
    vector<vector<int>> adj(n+1), radj(n+1);
    for(int i=0;i<m;i++){int u,v;cin>>u>>v;adj[u].push_back(v);radj[v].push_back(u);}
    
    auto now=chrono::steady_clock::now;
    auto start=now();
    mt19937 rng(123);
    
    vector<int> best_path;
    
    auto try_find=[&](){
        vector<int> path;
        vector<bool> used(n+1,false);
        // random start
        int s=rng()%n+1;
        path.push_back(s); used[s]=true;
        
        auto get_score=[&](int u)->int{
            int c=0;
            for(int v:adj[u]) if(!used[v]) c++;
            return c;
        };
        
        auto extend_back=[&]()->bool{
            int u=path.back();
            int bv=-1, bs=1e9;
            for(int v:adj[u]) if(!used[v]){
                int sc=get_score(v);
                if(sc<bs||(sc==bs&&(rng()&1))){bs=sc;bv=v;}
            }
            if(bv<0) return false;
            path.push_back(bv); used[bv]=true;
            return true;
        };
        
        auto extend_front=[&]()->bool{
            int u=path.front();
            int bv=-1, bs=1e9;
            for(int v:radj[u]) if(!used[v]){
                int sc=get_score(v);// out-degree of v among unused
                if(sc<bs||(sc==bs&&(rng()&1))){bs=sc;bv=v;}
            }
            if(bv<0) return false;
            path.insert(path.begin(),bv); used[bv]=true;
            return true;
        };
        
        // directed rotation: if tail t->path[i] edge exists, and path[i-1] has unused out-neighbor
        // then new path = path[0..i-1] ++ unvisited extensions from path[i-1]
        // Actually just set tail to path[i-1] and continue extending
        auto rotate=[&]()->bool{
            int t=path.back();
            vector<int> cands;
            for(int v:adj[t]) if(used[v]) cands.push_back(v);
            shuffle(cands.begin(),cands.end(),rng);
            // not easy for directed; just restart differently
            return false;
        };
        (void)rotate;
        
        int stale=0;
        while((int)path.size()<n&&stale<500){
            if(extend_back()){stale=0;continue;}
            if(extend_front()){stale=0;continue;}
            stale++; break;
        }
        if((int)path.size()>(int)best_path.size()) best_path=path;
    };
    
    while(chrono::duration_cast<chrono::milliseconds>(now()-start).count()<3700){
        try_find();
        if((int)best_path.size()==n) break;
    }
    
    cout<<best_path.size()<<"\n";
    for(int i=0;i<(int)best_path.size();i++){if(i)cout<<' ';cout<<best_path[i];}
    cout<<"\n";
}
