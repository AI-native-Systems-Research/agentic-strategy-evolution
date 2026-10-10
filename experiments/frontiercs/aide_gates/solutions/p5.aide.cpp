#include <iostream>
#include <vector>
#include <algorithm>
#include <random>
#include <chrono>
#include <queue>
#include <deque>

using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    int a[10];
    for(int i = 0; i < 10; i++) cin >> a[i];
    
    vector<vector<int>> adj(n+1), radj(n+1);
    vector<int> indeg(n+1, 0);
    
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        adj[u].push_back(v);
        radj[v].push_back(u);
        indeg[v]++;
    }
    
    // Sort adjacency lists for binary search edge check
    vector<vector<int>> adj_sorted(n+1);
    for(int i = 1; i <= n; i++){
        adj_sorted[i] = adj[i];
        sort(adj_sorted[i].begin(), adj_sorted[i].end());
    }
    
    auto hasEdge = [&](int u, int v) -> bool {
        auto &vec = adj_sorted[u];
        auto it = lower_bound(vec.begin(), vec.end(), v);
        return it != vec.end() && *it == v;
    };
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    vector<int> bestPath;
    
    // Try topological sort approach first (works if DAG)
    {
        vector<int> topo;
        vector<int> deg = indeg;
        queue<int> q;
        for(int i = 1; i <= n; i++) if(deg[i] == 0) q.push(i);
        while(!q.empty()){
            int u = q.front(); q.pop();
            topo.push_back(u);
            for(int v : adj[u]){
                if(--deg[v] == 0) q.push(v);
            }
        }
        if((int)topo.size() == n){
            // DAG - find longest path
            vector<int> dp(n+1, 1), par(n+1, -1);
            for(int i = (int)topo.size()-1; i >= 0; i--){
                int u = topo[i];
                for(int v : adj[u]){
                    if(dp[v] + 1 > dp[u]){
                        dp[u] = dp[v] + 1;
                        par[u] = v;
                    }
                }
            }
            int best = 0, bestStart = topo[0];
            for(int i = 1; i <= n; i++){
                if(dp[i] > best){ best = dp[i]; bestStart = i; }
            }
            vector<int> path;
            int cur = bestStart;
            while(cur != -1){ path.push_back(cur); cur = par[cur]; }
            bestPath = path;
            if((int)bestPath.size() == n){
                cout << bestPath.size() << "\n";
                for(int i = 0; i < (int)bestPath.size(); i++){
                    if(i) cout << " ";
                    cout << bestPath[i];
                }
                cout << "\n";
                return 0;
            }
        }
    }
    
    mt19937 rng(42);
    
    // Linked list arrays for insertion phase
    vector<int> nxt(n+1, -1), prv(n+1, -1);
    vector<bool> inPath(n+1, false);
    
    // Vertex insertion using linked list
    // head, tail are the endpoints of the linked list path
    // used[] marks vertices in the path
    auto doVertexInsertion = [&](int &head, int &tail, vector<bool> &used, int &pathLen) {
        // Build linked list from current path info (already built outside)
        // Scan unvisited vertices and try to insert
        bool changed = true;
        while(changed){
            changed = false;
            for(int w = 1; w <= n; w++){
                if(used[w]) continue;
                bool inserted = false;
                // Check in-neighbors of w that are in path
                for(int u : radj[w]){
                    if(!used[u]) continue;
                    int nx = nxt[u];
                    if(nx == -1) continue; // u is tail, can't insert after
                    if(hasEdge(w, nx)){
                        // Insert w between u and nx
                        nxt[u] = w;
                        prv[w] = u;
                        nxt[w] = nx;
                        prv[nx] = w;
                        used[w] = true;
                        pathLen++;
                        inserted = true;
                        changed = true;
                        break;
                    }
                }
                if(!inserted){
                    // Check out-neighbors of w that are in path
                    for(int v : adj[w]){
                        if(!used[v]) continue;
                        int pv = prv[v];
                        if(pv == -1) continue; // v is head
                        if(hasEdge(pv, w)){
                            // Insert w between pv and v
                            nxt[pv] = w;
                            prv[w] = pv;
                            nxt[w] = v;
                            prv[v] = w;
                            used[w] = true;
                            pathLen++;
                            changed = true;
                            break;
                        }
                    }
                }
            }
        }
    };
    
    // Convert linked list to vector
    auto llToVec = [&](int head, int pathLen) -> vector<int> {
        vector<int> res;
        res.reserve(pathLen);
        int cur = head;
        while(cur != -1){
            res.push_back(cur);
            cur = nxt[cur];
        }
        return res;
    };
    
    // Build linked list from deque
    auto buildLL = [&](deque<int> &path, int &head, int &tail) {
        head = path.front();
        tail = path.back();
        for(int i = 0; i < (int)path.size(); i++){
            int v = path[i];
            nxt[v] = (i+1 < (int)path.size()) ? path[i+1] : -1;
            prv[v] = (i > 0) ? path[i-1] : -1;
        }
    };
    
    auto tryOnce = [&](int startVertex) -> vector<int> {
        deque<int> path;
        vector<bool> used(n+1, false);
        
        path.push_back(startVertex);
        used[startVertex] = true;
        
        // Extend forward greedily
        auto extendForward = [&]() {
            while(true){
                int t = path.back();
                auto &nbrs = adj[t];
                if(nbrs.empty()) break;
                bool found = false;
                int off = rng() % nbrs.size();
                for(int i = 0; i < (int)nbrs.size(); i++){
                    int v = nbrs[(off + i) % nbrs.size()];
                    if(!used[v]){
                        path.push_back(v);
                        used[v] = true;
                        found = true;
                        break;
                    }
                }
                if(!found) break;
            }
        };
        
        // Extend backward greedily
        auto extendBackward = [&]() {
            while(true){
                int h = path.front();
                auto &nbrs = radj[h];
                if(nbrs.empty()) break;
                bool found = false;
                int off = rng() % nbrs.size();
                for(int i = 0; i < (int)nbrs.size(); i++){
                    int v = nbrs[(off + i) % nbrs.size()];
                    if(!used[v]){
                        path.push_front(v);
                        used[v] = true;
                        found = true;
                        break;
                    }
                }
                if(!found) break;
            }
        };
        
        extendForward();
        extendBackward();
        extendForward();
        
        // Vertex insertion phase using linked list
        if((int)path.size() < n){
            int head, tail;
            buildLL(path, head, tail);
            int pathLen = (int)path.size();
            doVertexInsertion(head, tail, used, pathLen);
            
            // Convert back to deque
            vector<int> vec = llToVec(head, pathLen);
            path = deque<int>(vec.begin(), vec.end());
            
            // Re-extend after insertion
            extendForward();
            extendBackward();
            extendForward();
        }
        
        // Perturbation phase
        for(int iter = 0; iter < 100000 && (int)path.size() < n; iter++){
            if(iter % 200 == 0 && elapsed() > 3.3) break;
            
            int dropCount = rng() % min((int)path.size(), 8) + 1;
            if(rng() % 2 == 0){
                for(int i = 0; i < dropCount && path.size() > 1; i++){
                    int v = path.back();
                    used[v] = false;
                    path.pop_back();
                }
            } else {
                for(int i = 0; i < dropCount && path.size() > 1; i++){
                    int v = path.front();
                    used[v] = false;
                    path.pop_front();
                }
            }
            
            extendForward();
            extendBackward();
            extendForward();
            
            // Periodically run vertex insertion
            if(iter % 50 == 0 && (int)path.size() < n){
                int head, tail;
                buildLL(path, head, tail);
                int pathLen = (int)path.size();
                doVertexInsertion(head, tail, used, pathLen);
                vector<int> vec = llToVec(head, pathLen);
                path = deque<int>(vec.begin(), vec.end());
                extendForward();
                extendBackward();
                extendForward();
            }
        }
        
        return vector<int>(path.begin(), path.end());
    };
    
    int maxRestarts = (n <= 1000) ? 50000 : (n <= 10000) ? 500 : 50;
    
    for(int restart = 0; restart < maxRestarts; restart++){
        if(elapsed() > 3.3) break;
        
        int start = rng() % n + 1;
        vector<int> path = tryOnce(start);
        
        if((int)path.size() > (int)bestPath.size()){
            bestPath = path;
            if((int)bestPath.size() == n) break;
        }
    }
    
    cout << bestPath.size() << "\n";
    for(int i = 0; i < (int)bestPath.size(); i++){
        if(i) cout << " ";
        cout << bestPath[i];
    }
    cout << "\n";
    
    return 0;
}