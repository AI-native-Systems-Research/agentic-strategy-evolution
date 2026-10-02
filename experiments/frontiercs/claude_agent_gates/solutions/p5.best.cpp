// Approach v20: Combined approach optimized for all graph densities
// Key insight: problem guarantees Hamiltonian path exists
// For sparse graphs (m ~ n): greedy with smart branching
// For medium graphs: DFS with backtracking
// For dense graphs: Warnsdorff + insertion
// Use randomized restarts with time management

#include <bits/stdc++.h>
using namespace std;

int n, m;
vector<vector<int>> adj, radj;

auto start_time = chrono::steady_clock::now();
long long elapsed_ms() {
    return chrono::duration_cast<chrono::milliseconds>(
        chrono::steady_clock::now() - start_time).count();
}

bool has_edge(int u, int v) {
    return binary_search(adj[u].begin(), adj[u].end(), v);
}

mt19937 rng(42);

int best_len = 0;
vector<int> best_path;

void update_best(const vector<int>& path) {
    if((int)path.size() > best_len) {
        best_len = path.size();
        best_path = path;
    }
}

// DFS with backtracking + Warnsdorff ordering
// Limited by time
bool dfs_found = false;

void dfs(vector<int>& path, vector<bool>& used, int depth, long long tl) {
    if(dfs_found) return;
    if(depth == n) {
        update_best(path);
        dfs_found = true;
        return;
    }
    if(elapsed_ms() > tl) {
        if(depth > best_len) update_best(path);
        return;
    }
    
    int last = path.back();
    
    // Collect candidates with Warnsdorff scores
    vector<pair<int,int>> cands;
    for(int v : adj[last]) {
        if(!used[v]) {
            int cnt = 0;
            for(int w : adj[v]) if(!used[w]) cnt++;
            cands.push_back({cnt, v});
        }
    }
    sort(cands.begin(), cands.end());
    
    // If only one candidate, no branching needed (fast path)
    if(cands.size() == 1) {
        int v = cands[0].second;
        path.push_back(v);
        used[v] = true;
        dfs(path, used, depth + 1, tl);
        if(!dfs_found) {
            path.pop_back();
            used[v] = false;
        }
        return;
    }
    
    for(auto& [cnt, v] : cands) {
        if(dfs_found || elapsed_ms() > tl) return;
        path.push_back(v);
        used[v] = true;
        dfs(path, used, depth + 1, tl);
        if(!dfs_found) {
            path.pop_back();
            used[v] = false;
        }
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    cin >> n >> m;
    int a[10];
    for(int i = 0; i < 10; i++) cin >> a[i];
    
    adj.resize(n+1);
    radj.resize(n+1);
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        adj[u].push_back(v);
        radj[v].push_back(u);
    }
    for(int i = 1; i <= n; i++){
        sort(adj[i].begin(), adj[i].end());
        sort(radj[i].begin(), radj[i].end());
    }
    
    vector<int> out_deg(n+1), in_deg(n+1);
    for(int i = 1; i <= n; i++) {
        out_deg[i] = adj[i].size();
        in_deg[i] = radj[i].size();
    }
    
    // ====== DAG check ======
    {
        vector<int> ti(n+1, 0);
        for(int u = 1; u <= n; u++) for(int v : adj[u]) ti[v]++;
        priority_queue<pair<int,int>, vector<pair<int,int>>, greater<>> pq;
        for(int i = 1; i <= n; i++) if(ti[i]==0) pq.push({out_deg[i], i});
        vector<int> topo; topo.reserve(n);
        while(!pq.empty()) {
            auto [od, u] = pq.top(); pq.pop();
            topo.push_back(u);
            for(int v : adj[u]) { ti[v]--; if(ti[v]==0) pq.push({out_deg[v], v}); }
        }
        if((int)topo.size() == n) {
            // DAG - compute longest path
            vector<int> idx(n+1);
            for(int i = 0; i < n; i++) idx[topo[i]] = i;
            vector<int> dp(n, 1), par(n, -1);
            int bv = 0;
            for(int i = 0; i < n; i++) {
                for(int v : adj[topo[i]]) {
                    int j = idx[v];
                    if(dp[i]+1 > dp[j]) { dp[j] = dp[i]+1; par[j] = i; }
                }
                if(dp[i] > dp[bv]) bv = i;
            }
            vector<int> path;
            for(int c = bv; c != -1; c = par[c]) path.push_back(topo[c]);
            reverse(path.begin(), path.end());
            update_best(path);
            
            // Check if the topo order itself is a Hamiltonian path
            if(best_len < n) {
                bool ok = true;
                for(int i = 0; i+1 < n; i++) if(!has_edge(topo[i], topo[i+1])) { ok = false; break; }
                if(ok) { best_path = topo; best_len = n; }
            }
        }
    }
    
    if(best_len == n) { goto output; }
    
    // ====== DFS with backtracking ======
    if(n <= 5000) {
        // Find vertices with in-degree 0 (most likely path starts)
        vector<int> starts;
        for(int i = 1; i <= n; i++) {
            if(in_deg[i] == 0) starts.push_back(i);
        }
        // Also add low in-degree vertices
        {
            vector<int> verts(n);
            iota(verts.begin(), verts.end(), 1);
            sort(verts.begin(), verts.end(), [&](int a, int b){ return in_deg[a] < in_deg[b]; });
            for(int i = 0; i < min(n, 20); i++) starts.push_back(verts[i]);
        }
        
        for(int sv : starts) {
            if(dfs_found || elapsed_ms() > 3000) break;
            vector<int> path = {sv};
            vector<bool> used(n+1, false);
            used[sv] = true;
            long long tl = min(3000LL, elapsed_ms() + max(200LL, 2500LL / (long long)starts.size()));
            dfs(path, used, 1, tl);
        }
        
        // If not found yet, try random starts
        if(!dfs_found && n <= 3000) {
            vector<int> verts(n);
            iota(verts.begin(), verts.end(), 1);
            shuffle(verts.begin(), verts.end(), rng);
            for(int t = 0; t < min(n, 50) && !dfs_found && elapsed_ms() < 3500; t++) {
                vector<int> path = {verts[t]};
                vector<bool> used(n+1, false);
                used[verts[t]] = true;
                dfs(path, used, 1, min(3500LL, elapsed_ms() + 200));
            }
        }
    }
    
    if(best_len == n) goto output;
    
    {
    // ====== Greedy Warnsdorff with maintained counters ======
    vector<int> out_avail(n+1), in_avail(n+1);
    vector<bool> used(n+1, false);
    int remaining;
    
    auto init_build = [&]() {
        for(int i = 1; i <= n; i++) {
            out_avail[i] = out_deg[i];
            in_avail[i] = in_deg[i];
            used[i] = false;
        }
        remaining = n;
    };
    
    auto mark = [&](int v) {
        used[v] = true;
        remaining--;
        for(int u : radj[v]) out_avail[u]--;
        for(int w : adj[v]) in_avail[w]--;
    };
    
    auto build_path = [&](int start_v, bool randomize_ties) -> vector<int> {
        init_build();
        
        deque<int> path;
        path.push_back(start_v);
        mark(start_v);
        
        bool prog = true;
        while(prog) {
            prog = false;
            
            // Extend back
            {
                int last = path.back();
                int bv = -1, bs = INT_MAX, cnt = 0;
                bool bd = true; // best is dead-end?
                
                for(int v : adj[last]) {
                    if(used[v]) continue;
                    int s = out_avail[v];
                    bool dead = (s == 0 && remaining > 1);
                    
                    if(!dead && bd) { bs=s; bv=v; bd=false; cnt=1; }
                    else if(dead == bd) {
                        if(s < bs) { bs=s; bv=v; cnt=1; }
                        else if(s == bs) { cnt++; if(randomize_ties && rng()%cnt==0) bv=v; }
                    }
                }
                if(bv != -1) { path.push_back(bv); mark(bv); prog=true; }
            }
            
            // Extend front
            {
                int first = path.front();
                int bv = -1, bs = INT_MAX, cnt = 0;
                bool bd = true;
                
                for(int v : radj[first]) {
                    if(used[v]) continue;
                    int s = in_avail[v];
                    bool dead = (s == 0 && remaining > 1);
                    
                    if(!dead && bd) { bs=s; bv=v; bd=false; cnt=1; }
                    else if(dead == bd) {
                        if(s < bs) { bs=s; bv=v; cnt=1; }
                        else if(s == bs) { cnt++; if(randomize_ties && rng()%cnt==0) bv=v; }
                    }
                }
                if(bv != -1) { path.push_front(bv); mark(bv); prog=true; }
            }
        }
        
        return vector<int>(path.begin(), path.end());
    };
    
    // Smart insertion using linked list
    auto insert_missing = [&](vector<int>& path, long long tl) {
        if((int)path.size() == n) return;
        
        vector<int> nxt(n+1, -1), prv(n+1, -1);
        vector<bool> inp(n+1, false);
        int head = path[0], tail = path.back();
        inp[head] = true;
        for(int i = 1; i < (int)path.size(); i++) {
            nxt[path[i-1]] = path[i];
            prv[path[i]] = path[i-1];
            inp[path[i]] = true;
        }
        int plen = path.size();
        
        vector<int> missing;
        for(int i = 1; i <= n; i++) if(!inp[i]) missing.push_back(i);
        
        bool changed = true;
        while(changed && elapsed_ms() < tl && !missing.empty()) {
            changed = false;
            vector<int> sm;
            for(int v : missing) {
                bool ins = false;
                if(has_edge(tail, v)) {
                    nxt[tail]=v;prv[v]=tail;tail=v;inp[v]=true;plen++;ins=changed=true;
                } else if(has_edge(v, head)) {
                    prv[head]=v;nxt[v]=head;head=v;inp[v]=true;plen++;ins=changed=true;
                } else {
                    // Check adj[v] for w in path where prv[w]->v exists
                    for(int w : adj[v]) {
                        if(!inp[w] || w == head) continue;
                        int u = prv[w];
                        if(u >= 1 && has_edge(u, v)) {
                            nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;inp[v]=true;plen++;ins=changed=true;break;
                        }
                    }
                    if(!ins) {
                        for(int u : radj[v]) {
                            if(!inp[u] || u == tail) continue;
                            int w = nxt[u];
                            if(w >= 1 && has_edge(v, w)) {
                                nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;inp[v]=true;plen++;ins=changed=true;break;
                            }
                        }
                    }
                }
                if(!ins) sm.push_back(v);
            }
            missing = sm;
        }
        
        path.clear();
        path.reserve(plen);
        int cur = head;
        while(cur >= 1) { path.push_back(cur); cur = nxt[cur]; }
    };
    
    // Phase 1: Deterministic starts
    {
        vector<int> verts(n);
        iota(verts.begin(), verts.end(), 1);
        sort(verts.begin(), verts.end(), [&](int a, int b){
            return in_deg[a] < in_deg[b];
        });
        for(int t = 0; t < min(n, 10) && elapsed_ms() < 500 && best_len < n; t++) {
            auto p = build_path(verts[t], false);
            update_best(p);
        }
        sort(verts.begin(), verts.end(), [&](int a, int b){
            return out_deg[a] > out_deg[b];
        });
        for(int t = 0; t < min(n, 10) && elapsed_ms() < 800 && best_len < n; t++) {
            auto p = build_path(verts[t], false);
            update_best(p);
        }
    }
    
    // Phase 2: Random restarts
    while(elapsed_ms() < 2500 && best_len < n) {
        int sv = rng() % n + 1;
        auto p = build_path(sv, true);
        update_best(p);
    }
    
    // Phase 3: Insertion on best path
    if(best_len < n && elapsed_ms() < 3200) {
        insert_missing(best_path, 3200);
        best_len = best_path.size();
    }
    
    // Phase 4: Perturbation - remove segments and rebuild
    if(best_len < n && elapsed_ms() < 3700) {
        for(int iter = 0; elapsed_ms() < 3600 && best_len < n; iter++) {
            vector<int> cur = best_path;
            int sz = cur.size();
            if(sz < 3) break;
            
            int seg_len = max(1, (int)(rng() % max(1, sz / 5)) + 1);
            int sp = rng() % max(1, sz - seg_len);
            
            vector<int> np;
            for(int i = 0; i < sz; i++)
                if(i < sp || i >= sp + seg_len)
                    np.push_back(cur[i]);
            
            // Re-validate path
            vector<int> vp;
            if(!np.empty()) {
                vp.push_back(np[0]);
                for(int i = 1; i < (int)np.size(); i++)
                    if(has_edge(vp.back(), np[i]))
                        vp.push_back(np[i]);
            }
            
            insert_missing(vp, min(elapsed_ms() + 100, 3600LL));
            update_best(vp);
        }
    }
    }
    
output:
    cout << best_len << "\n";
    for(int i = 0; i < best_len; i++) { if(i) cout << " "; cout << best_path[i]; }
    cout << "\n";
    return 0;
}
