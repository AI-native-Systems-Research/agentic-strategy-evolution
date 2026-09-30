#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    int a[10];
    for(int i=0;i<10;i++) cin >> a[i];
    
    vector<vector<int>> adj(n+1), radj(n+1);
    
    for(int i=0;i<m;i++){
        int u,v; cin>>u>>v;
        adj[u].push_back(v);
        radj[v].push_back(u);
    }
    
    // For fast edge lookup
    vector<unordered_set<int>> adjSet(n+1);
    for(int u=1;u<=n;u++) adjSet[u].insert(adj[u].begin(), adj[u].end());
    
    mt19937 rng(42);
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    vector<int> bestPath;
    
    auto tryImprove = [&](vector<int>& path) {
        // Try to insert unused vertices into the path
        vector<bool> used(n+1, false);
        for(int v : path) used[v] = true;
        
        bool improved = true;
        while(improved && (int)path.size() < n) {
            improved = false;
            for(int i = 0; i < (int)path.size() - 1 && !improved; i++) {
                int u = path[i], v = path[i+1];
                // Find w not in path with edge u->w and w->v
                for(int w : adj[u]) {
                    if(!used[w] && adjSet[w].count(v)) {
                        path.insert(path.begin()+i+1, w);
                        used[w] = true;
                        improved = true;
                        break;
                    }
                }
            }
        }
    };
    
    while(elapsed() < 3.5) {
        for(int i=1;i<=n;i++){
            shuffle(adj[i].begin(), adj[i].end(), rng);
            shuffle(radj[i].begin(), radj[i].end(), rng);
        }
        
        vector<int> path;
        vector<bool> used(n+1, false);
        int start = rng()%n+1;
        path.push_back(start); used[start]=true;
        
        // Extend back with Warnsdorff
        auto extBack = [&](){
            while(true){
                int last=path.back(), best=-1, bestDeg=INT_MAX;
                for(int x:adj[last]) if(!used[x]){
                    int deg=0; for(int y:adj[x]) if(!used[y]) deg++;
                    if(deg<bestDeg){bestDeg=deg;best=x;}
                }
                if(best==-1) break;
                path.push_back(best); used[best]=true;
            }
        };
        auto extFront = [&](){
            while(true){
                int first=path.front(), best=-1, bestDeg=INT_MAX;
                for(int x:radj[first]) if(!used[x]){
                    int deg=0; for(int y:radj[x]) if(!used[y]) deg++;
                    if(deg<bestDeg){bestDeg=deg;best=x;}
                }
                if(best==-1) break;
                path.insert(path.begin(), best); used[best]=true;
            }
        };
        extBack(); extFront();
        
        tryImprove(path);
        
        if((int)path.size()>(int)bestPath.size()) bestPath=path;
        if((int)bestPath.size()==n) break;
    }
    
    cout << bestPath.size() << "\n";
    for(int i=0;i<(int)bestPath.size();i++){
        if(i) cout<<' ';
        cout<<bestPath[i];
    }
    cout<<"\n";
}
