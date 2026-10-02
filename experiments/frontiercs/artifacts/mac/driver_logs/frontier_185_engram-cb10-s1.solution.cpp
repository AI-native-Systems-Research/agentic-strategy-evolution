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

// Greedy coloring using bitsets for speed
void color_sort(const vector<int>& P, vector<int>& order, vector<int>& color_num) {
    int n = P.size();
    if (n == 0) return;
    
    // Use bitsets for color classes
    static bitset<MAXN> color_bs[MAXN + 1];
    int maxno = 0;
    
    order.resize(n);
    color_num.resize(n);
    
    // Build a bitset of P for fast lookup
    bitset<MAXN> Pset;
    for (int v : P) Pset.set(v);
    
    // Temporary storage for ordering
    vector<pair<int,int>> vc; // (color, vertex)
    vc.reserve(n);
    
    for (int i = 0; i < n; i++) {
        int v = P[i];
        int k = 1;
        while (k <= maxno) {
            // Check if v is adjacent to any vertex in color class k
            if ((adj[v] & color_bs[k]).none()) break;
            k++;
        }
        if (k > maxno) {
            maxno = k;
            color_bs[k].reset();
        }
        color_bs[k].set(v);
        vc.push_back({k, v});
    }
    
    // Sort by color number
    sort(vc.begin(), vc.end());
    
    for (int i = 0; i < n; i++) {
        order[i] = vc[i].second;
        color_num[i] = vc[i].first;
    }
    
    // Clean up
    for (int k = 1; k <= maxno; k++) color_bs[k].reset();
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
        
        // Build new candidate set: vertices in order[0..i-1] adjacent to v
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
        
        if ((elapsed_ms()) > 1850) {
            timeout_flag = true;
            return;
        }
    }
}

// Greedy clique construction from a given vertex ordering
vector<int> greedy_clique(const vector<int>& order) {
    bitset<MAXN> clique_bs;
    vector<int> clique;
    for (int v : order) {
        // Check if v is adjacent to all current clique members
        if ((adj[v] & clique_bs) == clique_bs) {
            // But we need clique_bs to be subset of adj[v]
            // Actually we need all bits set in clique_bs to also be set in adj[v]
            bitset<MAXN> test = clique_bs & ~adj[v];
            if (test.none()) {
                clique.push_back(v);
                clique_bs.set(v);
            }
        }
    }
    return clique;
}

// Tabu search for maximum clique
void tabu_search(int max_ms) {
    // Start from best_clique
    if (best_clique.empty()) return;
    
    mt19937 rng(42);
    
    bitset<MAXN> clique_bs;
    vector<int> clique = best_clique;
    for (int v : clique) clique_bs.set(v);
    
    // Compute tightness: for each vertex not in clique, how many clique members it's adjacent to
    vector<int> tightness(N + 1, 0);
    for (int v = 1; v <= N; v++) {
        if (!clique_bs[v]) {
            tightness[v] = (adj[v] & clique_bs).count();
        }
    }
    
    vector<int> tabu(N + 1, 0);
    int iter = 0;
    int clique_size = clique.size();
    
    while (elapsed_ms() < max_ms) {
        iter++;
        
        // Try to add a vertex (tightness == clique_size)
        int best_add = -1;
        int best_add_deg = -1;
        for (int v = 1; v <= N; v++) {
            if (!clique_bs[v] && tightness[v] == clique_size && tabu[v] <= iter) {
                int d = adj[v].count();
                if (d > best_add_deg) {
                    best_add_deg = d;
                    best_add = v;
                }
            }
        }
        
        if (best_add != -1) {
            // Add vertex
            clique.push_back(best_add);
            clique_bs.set(best_add);
            clique_size++;
            for (int v = 1; v <= N; v++) {
                if (!clique_bs[v] && adj[best_add][v]) tightness[v]++;
            }
            
            if (clique_size > best_size) {
                best_size = clique_size;
                best_clique = clique;
            }
        } else {
            // Swap: remove a vertex from clique, try to add one with tightness == clique_size - 2
            // Pick a random clique member to remove
            if (clique.empty()) break;
            int idx = rng() % clique.size();
            int rem = clique[idx];
            clique.erase(clique.begin() + idx);
            clique_bs.reset(rem);
            clique_size--;
            tabu[rem] = iter + clique_size + 5;
            for (int v = 1; v <= N; v++) {
                if (!clique_bs[v] && adj[rem][v]) tightness[v]--;
            }
            tightness[rem] = (adj[rem] & clique_bs).count();
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
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    
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
    
    // Initial greedy clique
    vector<int> gc = greedy_clique(degen_order);
    if ((int)gc.size() > best_size) {
        best_size = gc.size();
        best_clique = gc;
    }
    
    // Reverse order greedy
    vector<int> rev_order(degen_order.rbegin(), degen_order.rend());
    gc = greedy_clique(rev_order);
    if ((int)gc.size() > best_size) {
        best_size = gc.size();
        best_clique = gc;
    }
    
    // Exact B&B
    vector<int> P = degen_order;
    expand(P);
    
    // If we timed out, try tabu search with remaining time
    if (timeout_flag && elapsed_ms() < 1950) {
        tabu_search(1950);
    }
    
    set<int> in_clique(best_clique.begin(), best_clique.end());
    for (int i = 1; i <= N; i++) {
        cout << (in_clique.count(i) ? 1 : 0) << "\n";
    }
}
