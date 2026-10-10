// Approach: SCC decomposition + greedy path building with efficient data structures
// Key: Use deque for O(1) front/back operations, avoid Warnsdorff (too expensive per step)
// Use random neighbor selection with restarts, CSR format
// Agent 2, attempt 2

#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    int a[10];
    for(int i = 0; i < 10; i++) cin >> a[i];
    
    // Read edges
    vector<pair<int,int>> edges(m);
    vector<int> outdeg(n+1, 0), indeg_cnt(n+1, 0);
    for(int i = 0; i < m; i++){
        cin >> edges[i].first >> edges[i].second;
        outdeg[edges[i].first]++;
        indeg_cnt[edges[i].second]++;
    }
    
    // Build CSR for forward and reverse adjacency
    vector<int> adjStart(n+2, 0), radjStart(n+2, 0);
    for(int i = 0; i < m; i++){
        adjStart[edges[i].first + 1]++;
        radjStart[edges[i].second + 1]++;
    }
    for(int i = 1; i <= n+1; i++){
        adjStart[i] += adjStart[i-1];
        radjStart[i] += radjStart[i-1];
    }
    vector<int> adjList(m), radjList(m);
    {
        vector<int> adjPos(n+2), radjPos(n+2);
        for(int i = 1; i <= n; i++){
            adjPos[i] = adjStart[i];
            radjPos[i] = radjStart[i];
        }
        for(int i = 0; i < m; i++){
            int u = edges[i].first, v = edges[i].second;
            adjList[adjPos[u]++] = v;
            radjList[radjPos[v]++] = u;
        }
    }
    edges.clear();
    edges.shrink_to_fit();
    
    // Sort each adjacency list for binary search
    for(int i = 1; i <= n; i++){
        sort(adjList.begin() + adjStart[i], adjList.begin() + adjStart[i+1]);
        sort(radjList.begin() + radjStart[i], radjList.begin() + radjStart[i+1]);
    }
    
    auto hasEdge = [&](int u, int v) -> bool {
        return binary_search(adjList.begin() + adjStart[u], adjList.begin() + adjStart[u+1], v);
    };
    
    mt19937 rng(12345);
    auto start_time = chrono::steady_clock::now();
    
    auto getElapsed = [&]() -> long long {
        return chrono::duration_cast<chrono::milliseconds>(
            chrono::steady_clock::now() - start_time).count();
    };
    
    // Kosaraju's SCC (iterative)
    vector<int> order;
    order.reserve(n);
    vector<bool> visited(n+1, false);
    
    for(int i = 1; i <= n; i++){
        if(visited[i]) continue;
        stack<pair<int,int>> stk;
        stk.push({i, adjStart[i]});
        visited[i] = true;
        while(!stk.empty()){
            auto& [u, idx] = stk.top();
            if(idx < adjStart[u+1]){
                int v = adjList[idx];
                idx++;
                if(!visited[v]){
                    visited[v] = true;
                    stk.push({v, adjStart[v]});
                }
            } else {
                order.push_back(u);
                stk.pop();
            }
        }
    }
    
    vector<int> comp(n+1, -1);
    int numComp = 0;
    
    for(int i = (int)order.size()-1; i >= 0; i--){
        int s = order[i];
        if(comp[s] != -1) continue;
        int c = numComp++;
        stack<int> stk;
        stk.push(s);
        comp[s] = c;
        while(!stk.empty()){
            int u = stk.top(); stk.pop();
            for(int j = radjStart[u]; j < radjStart[u+1]; j++){
                int v = radjList[j];
                if(comp[v] == -1){
                    comp[v] = c;
                    stk.push(v);
                }
            }
        }
    }
    
    vector<vector<int>> components(numComp);
    for(int i = 1; i <= n; i++){
        components[comp[i]].push_back(i);
    }
    
    // Build DAG
    vector<vector<int>> dagAdj(numComp);
    {
        vector<set<int>> dagAdjSet(numComp);
        for(int u = 1; u <= n; u++){
            for(int j = adjStart[u]; j < adjStart[u+1]; j++){
                int v = adjList[j];
                if(comp[u] != comp[v]){
                    dagAdjSet[comp[u]].insert(comp[v]);
                }
            }
        }
        for(int c = 0; c < numComp; c++){
            dagAdj[c] = vector<int>(dagAdjSet[c].begin(), dagAdjSet[c].end());
        }
    }
    
    // Topological sort with greedy chaining
    vector<int> dagIndeg(numComp, 0);
    for(int c = 0; c < numComp; c++){
        for(int d : dagAdj[c]) dagIndeg[d]++;
    }
    
    vector<int> dagOrder;
    {
        vector<int> ind = dagIndeg;
        vector<bool> used(numComp, false);
        set<int> sources;
        for(int c = 0; c < numComp; c++){
            if(ind[c] == 0) sources.insert(c);
        }
        
        for(int step = 0; step < numComp; step++){
            if(sources.empty()) break;
            
            int pick = -1;
            if(!dagOrder.empty()){
                int prev = dagOrder.back();
                for(int d : dagAdj[prev]){
                    if(!used[d] && sources.count(d)){
                        pick = d;
                        break;
                    }
                }
            }
            if(pick == -1){
                int bestSize = -1;
                for(int c : sources){
                    if((int)components[c].size() > bestSize){
                        bestSize = components[c].size();
                        pick = c;
                    }
                }
            }
            
            dagOrder.push_back(pick);
            used[pick] = true;
            sources.erase(pick);
            for(int d : dagAdj[pick]){
                if(!used[d]){
                    ind[d]--;
                    if(ind[d] == 0) sources.insert(d);
                }
            }
        }
    }
    
    // Find Hamiltonian path within an SCC
    auto findSCCPath = [&](vector<int>& verts, int desiredStart, long long timeBudget) -> vector<int> {
        int sz = verts.size();
        if(sz == 1) return verts;
        if(sz == 0) return {};
        
        vector<int> bestPath;
        vector<bool> inPath(n+1, false);
        
        int maxAttempts = max(1, min(500, 100000 / max(sz, 1)));
        long long deadline = getElapsed() + timeBudget;
        
        for(int attempt = 0; attempt < maxAttempts; attempt++){
            if(getElapsed() > deadline || getElapsed() > 3700) break;
            
            deque<int> path;
            
            int s;
            if(attempt == 0 && desiredStart != -1){
                s = desiredStart;
            } else {
                s = verts[rng() % sz];
            }
            path.push_back(s);
            inPath[s] = true;
            
            int stuckCount = 0;
            int maxIter = sz * 8;
            
            for(int iter = 0; iter < maxIter && (int)path.size() < sz; iter++){
                if(iter % 2000 == 0 && getElapsed() > deadline) break;
                
                bool progress = false;
                
                // Extend from back - random unvisited neighbor in same SCC
                {
                    int tail = path.back();
                    int sj = adjStart[tail], ej = adjStart[tail+1];
                    int deg = ej - sj;
                    if(deg > 0){
                        int off = rng() % deg;
                        for(int d = 0; d < deg; d++){
                            int v = adjList[sj + (off + d) % deg];
                            if(!inPath[v] && comp[v] == comp[tail]){
                                path.push_back(v);
                                inPath[v] = true;
                                progress = true;
                                stuckCount = 0;
                                break;
                            }
                        }
                    }
                }
                
                if(!progress){
                    // Extend from front
                    int head = path.front();
                    int sj = radjStart[head], ej = radjStart[head+1];
                    int deg = ej - sj;
                    if(deg > 0){
                        int off = rng() % deg;
                        for(int d = 0; d < deg; d++){
                            int v = radjList[sj + (off + d) % deg];
                            if(!inPath[v] && comp[v] == comp[head]){
                                path.push_front(v);
                                inPath[v] = true;
                                progress = true;
                                stuckCount = 0;
                                break;
                            }
                        }
                    }
                }
                
                if(!progress){
                    stuckCount++;
                    
                    // Try middle insertion with sampling
                    bool inserted = false;
                    int numSamples = min(10, sz - (int)path.size());
                    
                    for(int t = 0; t < numSamples * 3 && !inserted; t++){
                        int w = verts[rng() % sz];
                        if(inPath[w]) continue;
                        
                        // Check front/back first
                        if(hasEdge(w, path.front())){
                            path.push_front(w);
                            inPath[w] = true;
                            inserted = true;
                            break;
                        }
                        if(hasEdge(path.back(), w)){
                            path.push_back(w);
                            inPath[w] = true;
                            inserted = true;
                            break;
                        }
                        
                        // Check some middle positions
                        int psize = path.size();
                        int checkLimit = min(psize - 1, 30);
                        for(int ci = 0; ci < checkLimit && !inserted; ci++){
                            int i = (psize <= 30) ? ci : (int)(rng() % (psize - 1));
                            if(hasEdge(path[i], w) && hasEdge(w, path[i+1])){
                                // Rebuild path with insertion
                                deque<int> newPath;
                                for(int k = 0; k <= i; k++) newPath.push_back(path[k]);
                                newPath.push_back(w);
                                for(int k = i+1; k < psize; k++) newPath.push_back(path[k]);
                                path = newPath;
                                inPath[w] = true;
                                inserted = true;
                            }
                        }
                    }
                    
                    if(inserted){
                        stuckCount = 0;
                    } else {
                        // Backtrack
                        int bt = min((int)path.size()-1, 2 + (int)(rng() % (min(stuckCount*2, 20)+1)));
                        for(int b = 0; b < bt; b++){
                            if(path.size() > 1){
                                if(rng() % 3 != 0){
                                    inPath[path.back()] = false;
                                    path.pop_back();
                                } else {
                                    inPath[path.front()] = false;
                                    path.pop_front();
                                }
                            }
                        }
                    }
                }
            }
            
            if((int)path.size() > (int)bestPath.size()){
                bestPath = vector<int>(path.begin(), path.end());
                if((int)bestPath.size() == sz) {
                    for(int v : path) inPath[v] = false;
                    break;
                }
            }
            
            for(int v : path) inPath[v] = false;
        }
        
        return bestPath;
    };
    
    // Chain SCCs
    vector<int> finalPath;
    
    for(int ci = 0; ci < (int)dagOrder.size(); ci++){
        int c = dagOrder[ci];
        auto& verts = components[c];
        
        int desiredStart = -1;
        if(!finalPath.empty()){
            int prevV = finalPath.back();
            for(int j = adjStart[prevV]; j < adjStart[prevV+1]; j++){
                int v = adjList[j];
                if(comp[v] == c){
                    desiredStart = v;
                    break;
                }
            }
        }
        
        long long timeBudget = max(200LL, (long long)verts.size() * 3200LL / max(n, 1));
        
        auto path = findSCCPath(verts, desiredStart, timeBudget);
        
        if(!finalPath.empty() && !path.empty()){
            if(!hasEdge(finalPath.back(), path[0])){
                bool found = false;
                for(int i = 0; i < (int)path.size(); i++){
                    if(hasEdge(finalPath.back(), path[i])){
                        path = vector<int>(path.begin()+i, path.end());
                        found = true;
                        break;
                    }
                }
                if(!found) continue;
            }
        }
        
        for(int v : path) finalPath.push_back(v);
    }
    
    // Verify
    {
        vector<int> verified;
        vector<bool> used(n+1, false);
        for(int i = 0; i < (int)finalPath.size(); i++){
            if(used[finalPath[i]]) break;
            if(i > 0 && !hasEdge(finalPath[i-1], finalPath[i])) break;
            used[finalPath[i]] = true;
            verified.push_back(finalPath[i]);
        }
        finalPath = verified;
    }
    
    vector<int> bestPath = finalPath;
    
    // Random greedy restarts
    for(int attempt = 0; attempt < 1000; attempt++){
        if(getElapsed() > 3700) break;
        if((int)bestPath.size() == n) break;
        
        deque<int> path;
        vector<bool> inPath(n+1, false);
        
        int s = rng() % n + 1;
        path.push_back(s);
        inPath[s] = true;
        
        for(int iter = 0; iter < n * 3 && (int)path.size() < n; iter++){
            bool progress = false;
            
            // Extend back
            {
                int tail = path.back();
                int sj = adjStart[tail], ej = adjStart[tail+1];
                int deg = ej - sj;
                if(deg > 0){
                    int off = rng() % deg;
                    for(int d = 0; d < deg; d++){
                        int v = adjList[sj + (off + d) % deg];
                        if(!inPath[v]){
                            path.push_back(v);
                            inPath[v] = true;
                            progress = true;
                            break;
                        }
                    }
                }
            }
            if(progress) continue;
            
            // Extend front
            {
                int head = path.front();
                int sj = radjStart[head], ej = radjStart[head+1];
                int deg = ej - sj;
                if(deg > 0){
                    int off = rng() % deg;
                    for(int d = 0; d < deg; d++){
                        int v = radjList[sj + (off + d) % deg];
                        if(!inPath[v]){
                            path.push_front(v);
                            inPath[v] = true;
                            progress = true;
                            break;
                        }
                    }
                }
            }
            if(progress) continue;
            
            // Backtrack
            int bt = min((int)path.size()-1, 2+(int)(rng()%8));
            for(int b = 0; b < bt; b++){
                if(path.size() > 1){
                    if(rng() % 3 != 0){
                        inPath[path.back()] = false;
                        path.pop_back();
                    } else {
                        inPath[path.front()] = false;
                        path.pop_front();
                    }
                }
            }
        }
        
        if((int)path.size() > (int)bestPath.size()){
            bestPath = vector<int>(path.begin(), path.end());
        }
    }
    
    cout << bestPath.size() << "\n";
    for(int i = 0; i < (int)bestPath.size(); i++){
        cout << bestPath[i];
        if(i+1 < (int)bestPath.size()) cout << " ";
    }
    cout << "\n";
    
    return 0;
}