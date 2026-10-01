#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 1001;
bitset<MAXN> adj[MAXN];
int N, M;
int best_size;
vector<int> best_clique;
vector<int> cur_clique;
chrono::steady_clock::time_point start_time;
bool timeout_flag = false;

inline long long elapsed_ms() {
    return chrono::duration_cast<chrono::milliseconds>(
        chrono::steady_clock::now() - start_time).count();
}

// Greedy coloring: returns color assignments and the number of colors used
void color_sort(const vector<int>& P, vector<int>& order, vector<int>& color_num) {
    int n = P.size();
    if (n == 0) return;
    
    // Use bitset-based coloring
    vector<bitset<MAXN>> color_sets; // vertices in each color class
    vector<int> vertex_color(n);
    int maxcolor = 0;
    
    for (int i = 0; i < n; i++) {
        int v = P[i];
        int k = 0;
        while (k < maxcolor) {
            if ((adj[v] & color_sets[k]).none()) break;
            k++;
        }
        if (k == maxcolor) {
            color_sets.push_back(bitset<MAXN>());
            maxcolor++;
        }
        color_sets[k].set(v);
        vertex_color[i] = k + 1; // 1-indexed color
    }
    
    // Sort by color: vertices with same color grouped, lower colors first
    vector<pair<int,int>> cv(n);
    for (int i = 0; i < n; i++) cv[i] = {vertex_color[i], P[i]};
    sort(cv.begin(), cv.end());
    
    order.resize(n);
    color_num.resize(n);
    for (int i = 0; i < n; i++) {
        order[i] = cv[i].second;
        color_num[i] = cv[i].first;
    }
}

void expand(const vector<int>& P) {
    if (timeout_flag) return;
    
    vector<int> order, color_num;
    color_sort(P, order, color_num);
    
    for (int i = (int)order.size() - 1; i >= 0; i--) {
        if (timeout_flag) return;
        if ((int)cur_clique.size() + color_num[i] <= best_size) return;
        
        int v = order[i];
        cur_clique.push_back(v);
        
        vector<int> newP;
        newP.reserve(i);
        for (int j = 0; j < i; j++) {
            if (adj[v][order[j]]) newP.push_back(order[j]);
        }
        
        if (newP.empty()) {
            if ((int)cur_clique.size() > best_size) {
                best_size = cur_clique.size();
                best_clique = cur_clique;
            }
        } else {
            expand(newP);
        }
        cur_clique.pop_back();
        
        if (elapsed_ms() > 1850) {
            timeout_flag = true;
            return;
        }
    }
}

// Greedy clique construction starting from vertex v
vector<int> greedy_clique(int start, const vector<int>& vertex_order) {
    vector<int> clique;
    bitset<MAXN> clique_adj;
    clique_adj.set(); // all 1s
    
    clique.push_back(start);
    clique_adj &= adj[start];
    clique_adj.set(start, 0);
    
    for (int v : vertex_order) {
        if (v == start) continue;
        if (clique_adj[v]) {
            clique.push_back(v);
            clique_adj &= adj[v];
        }
    }
    return clique;
}

// Local search: try to swap vertices to grow clique
void local_search_improve(vector<int>& clique) {
    bool improved = true;
    while (improved && elapsed_ms() < 500) {
        improved = false;
        
        bitset<MAXN> in_clique;
        bitset<MAXN> clique_common;
        clique_common.set();
        for (int v : clique) {
            in_clique.set(v);
            clique_common &= adj[v];
        }
        
        // Try to add a vertex directly
        for (int v = 1; v <= N; v++) {
            if (!in_clique[v] && clique_common[v]) {
                clique.push_back(v);
                in_clique.set(v);
                clique_common &= adj[v];
                improved = true;
            }
        }
        if (improved) continue;
        
        // Try swap: remove one vertex, add two
        for (int idx = 0; idx < (int)clique.size() && !improved; idx++) {
            int removed = clique[idx];
            // Compute common neighbors of clique \ {removed}
            bitset<MAXN> new_common;
            new_common.set();
            for (int j = 0; j < (int)clique.size(); j++) {
                if (j != idx) new_common &= adj[clique[j]];
            }
            new_common &= ~in_clique;
            
            // Find two vertices in new_common that are adjacent
            vector<int> candidates;
            for (int v = new_common._Find_first(); v < MAXN; v = new_common._Find_next(v)) {
                if (v <= N) candidates.push_back(v);
            }
            
            for (int a = 0; a < (int)candidates.size() && !improved; a++) {
                for (int b = a + 1; b < (int)candidates.size() && !improved; b++) {
                    if (adj[candidates[a]][candidates[b]]) {
                        // Do the swap
                        clique.erase(clique.begin() + idx);
                        clique.push_back(candidates[a]);
                        clique.push_back(candidates[b]);
                        improved = true;
                    }
                }
            }
        }
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    start_time = chrono::steady_clock::now();
    
    cin >> N >> M;
    for (int i = 0; i < M; i++) {
        int u, v; cin >> u >> v;
        adj[u].set(v); adj[v].set(u);
    }
    
    // Degeneracy ordering
    vector<int> deg(N+1);
    vector<bool> removed(N+1, false);
    for (int i = 1; i <= N; i++) deg[i] = (int)(adj[i] & bitset<MAXN>().set()).count(); // count neighbors among 1..N
    // Simpler: just count
    for (int i = 1; i <= N; i++) deg[i] = 0;
    for (int i = 1; i <= N; i++) {
        for (int j = i+1; j <= N; j++) {
            if (adj[i][j]) { deg[i]++; deg[j]++; }
        }
    }
    
    vector<int> degen_order;
    for (int iter = 0; iter < N; iter++) {
        int best = -1;
        for (int i = 1; i <= N; i++) {
            if (!removed[i] && (best == -1 || deg[i] < deg[best])) best = i;
        }
        removed[best] = true;
        degen_order.push_back(best);
        for (int j = 1; j <= N; j++) {
            if (!removed[j] && adj[best][j]) deg[j]--;
        }
    }
    
    // Build initial solution via greedy + local search
    // Sort by degree descending for greedy
    vector<int> by_deg(N);
    iota(by_deg.begin(), by_deg.end(), 1);
    sort(by_deg.begin(), by_deg.end(), [](int a, int b){ return (int)adj[a].count() > (int)adj[b].count(); });
    
    best_size = 0;
    for (int i = 0; i < min(N, 20); i++) {
        auto cl = greedy_clique(by_deg[i], by_deg);
        if ((int)cl.size() > best_size) {
            best_size = cl.size();
            best_clique = cl;
        }
    }
    
    // Local search on best greedy clique
    local_search_improve(best_clique);
    best_size = best_clique.size();
    
    // Run exact B&B with degeneracy ordering
    cur_clique.clear();
    vector<int> P = degen_order;
    expand(P);
    
    // If timed out, try tabu search to improve
    if (timeout_flag && elapsed_ms() < 1950) {
        // Additional local search attempts
        for (int trial = 0; trial < 100 && elapsed_ms() < 1950; trial++) {
            vector<int> cl = best_clique;
            // Random perturbation: remove a random vertex and rebuild
            if (!cl.empty()) {
                int ridx = rand() % cl.size();
                cl.erase(cl.begin() + ridx);
                local_search_improve(cl);
                if ((int)cl.size() > best_size) {
                    best_size = cl.size();
                    best_clique = cl;
                }
            }
        }
    }
    
    set<int> in_clique(best_clique.begin(), best_clique.end());
    for (int i = 1; i <= N; i++) {
        cout << (in_clique.count(i) ? 1 : 0) << "\n";
    }
}
