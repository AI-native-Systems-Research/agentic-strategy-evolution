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

int color_bound(const bitset<MAXN>& cand, vector<pair<int,int>>& colored) {
    colored.clear();
    static bitset<MAXN> color_sets[MAXN];
    int max_color = 0;
    
    for (int v = cand._Find_first(); v < MAXN; v = cand._Find_next(v)) {
        int c = 1;
        while (c <= max_color && (color_sets[c] & adj[v]).any()) c++;
        if (c > max_color) { max_color = c; color_sets[c].reset(); }
        color_sets[c].set(v);
        colored.push_back({c, v});
    }
    for (int c = 1; c <= max_color; c++) color_sets[c].reset();
    sort(colored.begin(), colored.end());
    return max_color;
}

void expand(bitset<MAXN>& cand) {
    if (timeout_flag) return;
    
    vector<pair<int,int>> colored;
    int ub = color_bound(cand, colored);
    if ((int)cur_clique.size() + ub <= best_size) return;
    
    for (int i = (int)colored.size() - 1; i >= 0; i--) {
        if (timeout_flag) return;
        if ((int)cur_clique.size() + colored[i].first <= best_size) return;
        
        int v = colored[i].second;
        cur_clique.push_back(v);
        bitset<MAXN> newCand = cand & adj[v];
        
        if (newCand.none()) {
            if ((int)cur_clique.size() > best_size) {
                best_size = cur_clique.size();
                best_clique = cur_clique;
            }
        } else {
            expand(newCand);
        }
        cur_clique.pop_back();
        cand.reset(v);
        if (elapsed_ms() > 1900) { timeout_flag = true; return; }
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
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    vector<set<int>> buckets(N+1);
    for (int i = 1; i <= N; i++) buckets[deg[i]].insert(i);
    vector<bool> removed(N+1, false);
    vector<int> order;
    for (int iter = 0; iter < N; iter++) {
        int d = 0;
        while (d <= N && buckets[d].empty()) d++;
        int v = *buckets[d].begin();
        buckets[d].erase(buckets[d].begin());
        removed[v] = true; order.push_back(v);
        for (int u = adj[v]._Find_first(); u < MAXN; u = adj[v]._Find_next(u))
            if (!removed[u]) { buckets[deg[u]].erase(u); deg[u]--; buckets[deg[u]].insert(u); }
    }
    
    vector<int> rev(order.rbegin(), order.rend());
    bitset<MAXN> ca; ca.set();
    for (int v : rev) if (ca[v]) { best_clique.push_back(v); ca &= adj[v]; }
    best_size = (int)best_clique.size();
    
    // BnB using degeneracy ordering: for each vertex in order, search among later neighbors
    bitset<MAXN> later;
    for (int i = (int)order.size()-1; i >= 0 && !timeout_flag; i--) {
        int v = order[i];
        bitset<MAXN> cand = adj[v] & later;
        cur_clique.clear();
        cur_clique.push_back(v);
        if ((int)cand.count() + 1 > best_size) expand(cand);
        later.set(v);
    }
    
    set<int> in_clique(best_clique.begin(), best_clique.end());
    for (int i = 1; i <= N; i++) cout << (in_clique.count(i) ? 1 : 0) << "\n";
}
