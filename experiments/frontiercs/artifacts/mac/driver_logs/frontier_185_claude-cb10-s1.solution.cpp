#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1001;
bitset<MAXN> adj[MAXN];
int N, M;
int best_size = 0;
vector<int> best_clique;
chrono::steady_clock::time_point start_time;
bool timeout_flag;
mt19937 rng(12345);

inline int elapsed_ms() {
    return (int)chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - start_time).count();
}

int greedy_color_bound(const vector<int>& verts, vector<int>& ordered, vector<int>& colors) {
    int cnt = verts.size();
    if (cnt == 0) return 0;
    
    int ncolors = 0;
    vector<vector<int>> color_sets;
    vector<bitset<MAXN>> color_bs;
    vector<int> col(N+1, 0);
    
    // Sort vertices by degree in subgraph (descending) for better coloring
    bitset<MAXN> P;
    for (int v : verts) P.set(v);
    
    vector<int> sv = verts;
    sort(sv.begin(), sv.end(), [&](int a, int b) {
        return (adj[a] & P).count() > (adj[b] & P).count();
    });
    
    for (int v : sv) {
        int c;
        for (c = 0; c < ncolors; c++) {
            if ((adj[v] & color_bs[c]).none()) break;
        }
        if (c == ncolors) { color_sets.push_back({}); color_bs.emplace_back(); ncolors++; }
        color_sets[c].push_back(v);
        color_bs[c].set(v);
        col[v] = c + 1;
    }
    
    // Recolor pass
    for (int pass = 0; pass < 3; pass++) {
        for (int v : sv) {
            int cur_c = col[v] - 1;
            for (int c = 0; c < cur_c; c++) {
                if ((adj[v] & color_bs[c]).none()) {
                    color_bs[cur_c].reset(v);
                    // Remove from color_sets[cur_c]
                    color_bs[c].set(v);
                    col[v] = c + 1;
                    break;
                }
            }
        }
    }
    
    // Rebuild color_sets after recoloring
    color_sets.clear();
    int max_col = 0;
    for (int v : sv) if (col[v] > max_col) max_col = col[v];
    color_sets.resize(max_col);
    for (int v : sv) color_sets[col[v]-1].push_back(v);
    
    ordered.clear();
    colors.clear();
    for (int c = 0; c < max_col; c++) {
        for (int v : color_sets[c]) {
            ordered.push_back(v);
            colors.push_back(c + 1);
        }
    }
    return max_col;
}

int simple_color(const vector<int>& verts, vector<int>& ordered, vector<int>& colors) {
    int cnt = verts.size();
    if (cnt == 0) return 0;
    
    int ncolors = 0;
    vector<vector<int>> color_sets;
    vector<bitset<MAXN>> color_bs;
    vector<int> col(N+1, 0);
    
    for (int v : verts) {
        int c;
        for (c = 0; c < ncolors; c++) {
            if ((adj[v] & color_bs[c]).none()) break;
        }
        if (c == ncolors) { color_sets.push_back({}); color_bs.emplace_back(); ncolors++; }
        color_sets[c].push_back(v);
        color_bs[c].set(v);
        col[v] = c + 1;
    }
    
    ordered.clear();
    colors.clear();
    for (int c = 0; c < ncolors; c++) {
        for (int v : color_sets[c]) {
            ordered.push_back(v);
            colors.push_back(c + 1);
        }
    }
    return ncolors;
}

void bnb(bitset<MAXN>& P, vector<int>& cur, int depth, int time_limit) {
    if (timeout_flag) return;
    if ((depth & 15) == 0 && elapsed_ms() > time_limit) { timeout_flag = true; return; }
    
    if (P.none()) {
        if ((int)cur.size() > best_size) {
            best_size = cur.size();
            best_clique = cur;
        }
        return;
    }
    
    int cnt = (int)P.count();
    if ((int)cur.size() + cnt <= best_size) return;
    
    vector<int> verts;
    verts.reserve(cnt);
    for (int v = (int)P._Find_first(); v <= N; v = (int)P._Find_next(v)) verts.push_back(v);
    
    vector<int> ordered, colors;
    int ncolors;
    if (cnt <= 150) {
        ncolors = greedy_color_bound(verts, ordered, colors);
    } else {
        ncolors = simple_color(verts, ordered, colors);
    }
    
    if ((int)cur.size() + ncolors <= best_size) return;
    
    for (int i = cnt - 1; i >= 0; i--) {
        if (timeout_flag) return;
        if ((int)cur.size() + colors[i] <= best_size) return;
        int v = ordered[i];
        P.reset(v);
        bitset<MAXN> newP = P & adj[v];
        cur.push_back(v);
        bnb(newP, cur, depth + 1, time_limit);
        cur.pop_back();
    }
}

void local_search(int time_limit_ms) {
    auto run_search = [&](vector<int> clique, int end_ms) {
        bitset<MAXN> inClique;
        for (int v : clique) inClique.set(v);
        vector<int> tight(N+1, 0);
        for (int v : clique)
            for (int u = (int)adj[v]._Find_first(); u <= N; u = (int)adj[v]._Find_next(u)) tight[u]++;
        int csize = (int)clique.size();
        vector<int> tabu(N+1, 0);
        int iter = 0, no_improve = 0;
        
        while (elapsed_ms() < end_ms) {
            iter++; no_improve++;
            
            // Try to add
            int best_add = -1, best_score = -1;
            for (int v = 1; v <= N; v++) {
                if (!inClique[v] && tight[v] == csize && tabu[v] <= iter) {
                    int d = (int)(adj[v] & ~inClique).count();
                    if (d > best_score) { best_add = v; best_score = d; }
                }
            }
            if (best_add == -1) {
                for (int v = 1; v <= N; v++)
                    if (!inClique[v] && tight[v] == csize) { best_add = v; break; }
            }
            
            if (best_add != -1) {
                inClique.set(best_add); clique.push_back(best_add); csize++;
                for (int u = (int)adj[best_add]._Find_first(); u <= N; u = (int)adj[best_add]._Find_next(u)) tight[u]++;
                tabu[best_add] = iter + csize + (rng() % 5);
                if (csize > best_size) { best_size = csize; best_clique = clique; no_improve = 0; }
                continue;
            }
            
            // (1,1) swap
            vector<int> cands;
            for (int v = 1; v <= N; v++)
                if (!inClique[v] && tight[v] == csize - 1 && tabu[v] <= iter) cands.push_back(v);
            if (!cands.empty()) {
                int bs = cands[rng() % cands.size()];
                int drop = -1;
                for (int u : clique) if (!adj[bs][u]) { drop = u; break; }
                if (drop != -1) {
                    inClique.reset(drop);
                    clique.erase(find(clique.begin(), clique.end(), drop)); csize--;
                    for (int u = (int)adj[drop]._Find_first(); u <= N; u = (int)adj[drop]._Find_next(u)) tight[u]--;
                    tabu[drop] = iter + csize + 3 + (rng() % 10);
                    inClique.set(bs); clique.push_back(bs); csize++;
                    for (int u = (int)adj[bs]._Find_first(); u <= N; u = (int)adj[bs]._Find_next(u)) tight[u]++;
                    tabu[bs] = iter + csize + (rng() % 5);
                }
                continue;
            }
            
            // Perturbation
            if (csize > 1) {
                int nd = (no_improve > 50) ? min(csize-1, 1+(int)(rng()%max(1,csize/3))) : 1;
                for (int d = 0; d < nd && csize > 1; d++) {
                    int idx = rng() % csize;
                    int drop = clique[idx];
                    inClique.reset(drop);
                    clique[idx] = clique.back(); clique.pop_back(); csize--;
                    for (int u = (int)adj[drop]._Find_first(); u <= N; u = (int)adj[drop]._Find_next(u)) tight[u]--;
                    tabu[drop] = iter + csize + 5 + (rng() % 15);
                }
                if (no_improve > 50) no_improve = 0;
            }
        }
    };
    
    while (elapsed_ms() < time_limit_ms) {
        vector<int> init;
        int r = rng() % 8;
        if (r < 4 && !best_clique.empty()) { init = best_clique; }
        else {
            int sv = rng() % N + 1; init = {sv};
            bitset<MAXN> common = adj[sv];
            while (common.any()) {
                vector<int> c;
                for (int v = (int)common._Find_first(); v <= N; v = (int)common._Find_next(v)) c.push_back(v);
                sort(c.begin(), c.end(), [&](int a, int b){ return (adj[a]&common).count() > (adj[b]&common).count(); });
                int top = max(1,(int)c.size()/3);
                init.push_back(c[rng()%top]);
                common &= adj[init.back()];
            }
        }
        int rem = time_limit_ms - elapsed_ms();
        if (rem < 5) break;
        run_search(init, min(time_limit_ms, elapsed_ms() + max(80, rem/3)));
    }
}

int main() {
    ios::sync_with_stdio(false); cin.tie(NULL);
    start_time = chrono::steady_clock::now();
    cin >> N >> M;
    for (int i = 0; i < M; i++) { int u, v; cin >> u >> v; adj[u].set(v); adj[v].set(u); }
    
    vector<int> deg(N+1); for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    vector<int> order;
    vector<bool> removed(N+1, false);
    for (int it = 0; it < N; it++) {
        int mv = -1, md = N+1;
        for (int i = 1; i <= N; i++) if (!removed[i] && deg[i] < md) { md = deg[i]; mv = i; }
        order.push_back(mv); removed[mv] = true;
        for (int j = 1; j <= N; j++) if (!removed[j] && adj[mv][j]) deg[j]--;
    }
    
    timeout_flag = false;
    for (int idx = N-1; idx >= 0 && !timeout_flag; idx--) {
        int v = order[idx];
        bitset<MAXN> P;
        for (int j = idx+1; j < N; j++) if (adj[v][order[j]]) P.set(order[j]);
        vector<int> cur = {v};
        if ((int)cur.size() + (int)P.count() <= best_size) continue;
        bnb(P, cur, 0, 1300);
    }
    
    local_search(1920);
    
    vector<int> inC(N+1, 0);
    for (int v : best_clique) inC[v] = 1;
    for (int i = 1; i <= N; i++) cout << inC[i] << "\n";
}
