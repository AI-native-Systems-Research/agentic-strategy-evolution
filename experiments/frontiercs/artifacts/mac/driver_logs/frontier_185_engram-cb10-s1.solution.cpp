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

// Bitset-parallel greedy coloring for upper bound + ordering
void color_sort_bitset(const vector<int>& P, vector<int>& order, vector<int>& color_num) {
    int n = P.size();
    order.clear();
    color_num.clear();
    order.reserve(n);
    color_num.reserve(n);
    
    // Build a bitset of vertices in P
    bitset<MAXN> inP;
    for (int v : P) inP.set(v);
    
    // color_class[k] is the bitset of vertices in color class k
    vector<bitset<MAXN>> color_class;
    vector<vector<int>> color_verts; // vertices in each color class for output
    
    for (int v : P) {
        // Find the first color class where v has no neighbors
        int k = -1;
        for (int c = 0; c < (int)color_class.size(); c++) {
            if ((adj[v] & color_class[c]).none()) {
                k = c;
                break;
            }
        }
        if (k == -1) {
            k = color_class.size();
            color_class.push_back(bitset<MAXN>());
            color_verts.push_back(vector<int>());
        }
        color_class[k].set(v);
        color_verts[k].push_back(v);
    }
    
    for (int k = 0; k < (int)color_verts.size(); k++) {
        for (int v : color_verts[k]) {
            order.push_back(v);
            color_num.push_back(k + 1);
        }
    }
}

void expand(const vector<int>& P, const bitset<MAXN>& Pbits) {
    if (timeout_flag) return;
    
    vector<int> order, color_num;
    color_sort_bitset(P, order, color_num);
    
    for (int i = (int)order.size() - 1; i >= 0; i--) {
        if (timeout_flag) return;
        if ((int)cur_clique.size() + color_num[i] <= best_size) return;
        
        int v = order[i];
        cur_clique.push_back(v);
        
        // New candidates: vertices in order[0..i-1] that are adjacent to v
        bitset<MAXN> newPbits;
        vector<int> newP;
        if (i > 0) {
            // Build bitset of order[0..i-1]
            bitset<MAXN> cand;
            for (int j = 0; j < i; j++) cand.set(order[j]);
            newPbits = adj[v] & cand;
            // Extract vertices in original order
            for (int j = 0; j < i; j++) {
                if (newPbits.test(order[j])) {
                    newP.push_back(order[j]);
                }
            }
        }
        
        if (newP.empty()) {
            if ((int)cur_clique.size() > best_size) {
                best_size = cur_clique.size();
                best_clique = cur_clique;
            }
        } else {
            expand(newP, newPbits);
        }
        cur_clique.pop_back();
        
        // Check time every few iterations
        if ((i & 63) == 0) {
            auto now = chrono::steady_clock::now();
            if (chrono::duration_cast<chrono::milliseconds>(now - start_time).count() > 1850) {
                timeout_flag = true;
                return;
            }
        }
    }
}

// Greedy clique construction from a given vertex ordering
vector<int> greedy_clique(const vector<int>& order) {
    vector<int> clique;
    bitset<MAXN> clique_bits;
    for (int v : order) {
        if ((adj[v] & clique_bits) == clique_bits) {
            // v is adjacent to all current clique members
            clique.push_back(v);
            clique_bits.set(v);
        }
    }
    return clique;
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
    for (int i = 1; i <= N; i++) deg[i] = (int)(adj[i].count());
    
    vector<int> degen_order;
    degen_order.reserve(N);
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
    
    // Try greedy clique from degeneracy order (reversed - high core first)
    vector<int> rev_order(degen_order.rbegin(), degen_order.rend());
    best_clique = greedy_clique(rev_order);
    best_size = best_clique.size();
    
    // Also try greedy from several random orderings
    {
        mt19937 rng(42);
        for (int t = 0; t < 20; t++) {
            vector<int> rorder(rev_order);
            shuffle(rorder.begin(), rorder.end(), rng);
            auto c = greedy_clique(rorder);
            if ((int)c.size() > best_size) {
                best_size = c.size();
                best_clique = c;
            }
        }
    }
    
    // Exact B&B using degeneracy order
    vector<int> P = degen_order; // process in degeneracy order
    bitset<MAXN> Pbits;
    for (int v : P) Pbits.set(v);
    
    cur_clique.clear();
    expand(P, Pbits);
    
    // If we timed out, try local search to improve
    if (timeout_flag) {
        bitset<MAXN> clique_bits;
        for (int v : best_clique) clique_bits.set(v);
        // Try adding vertices
        for (int v = 1; v <= N; v++) {
            if (!clique_bits.test(v)) {
                if ((adj[v] & clique_bits) == clique_bits) {
                    best_clique.push_back(v);
                    clique_bits.set(v);
                    best_size++;
                }
            }
        }
        // Try swap: remove one, add two
        // (simple perturbation)
    }
    
    set<int> in_clique(best_clique.begin(), best_clique.end());
    for (int i = 1; i <= N; i++) {
        cout << (in_clique.count(i) ? 1 : 0) << "\n";
    }
}
