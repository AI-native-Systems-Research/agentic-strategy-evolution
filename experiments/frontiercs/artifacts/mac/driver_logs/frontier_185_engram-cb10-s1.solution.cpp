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

void color_sort(vector<int>& verts, vector<int>& colors) {
    int nv = verts.size();
    vector<vector<int>> color_class;
    
    for (int i = 0; i < nv; i++) {
        int v = verts[i];
        int k = 0;
        while (k < (int)color_class.size()) {
            bool fits = true;
            for (int u : color_class[k]) {
                if (adj[v].test(u)) { fits = false; break; }
            }
            if (fits) break;
            k++;
        }
        if (k == (int)color_class.size()) color_class.push_back({});
        color_class[k].push_back(v);
    }
    
    verts.clear();
    colors.clear();
    for (int k = 0; k < (int)color_class.size(); k++) {
        for (int v : color_class[k]) {
            verts.push_back(v);
            colors.push_back(k + 1);
        }
    }
}

void expand(vector<int>& P) {
    if (timeout_flag) return;
    
    vector<int> colors;
    color_sort(P, colors);
    
    int nv = P.size();
    for (int i = nv - 1; i >= 0; i--) {
        if (timeout_flag) return;
        if ((int)cur_clique.size() + colors[i] <= best_size) return;
        
        int v = P[i];
        cur_clique.push_back(v);
        
        vector<int> newP;
        for (int j = 0; j < i; j++) {
            if (adj[v].test(P[j])) newP.push_back(P[j]);
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
        
        if ((i & 31) == 0) {
            auto now = chrono::steady_clock::now();
            if (chrono::duration_cast<chrono::milliseconds>(now - start_time).count() > 1900)
                { timeout_flag = true; return; }
        }
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    start_time = chrono::steady_clock::now();
    cin >> N >> M;
    for (int i = 0; i < M; i++) { int u,v; cin >> u >> v; adj[u].set(v); adj[v].set(u); }
    
    // Degeneracy ordering
    vector<int> order;
    vector<bool> removed(N+1, false);
    vector<int> deg(N+1);
    for (int i = 1; i <= N; i++) deg[i] = adj[i].count();
    for (int iter = 0; iter < N; iter++) {
        int best = -1, bd = N+1;
        for (int i = 1; i <= N; i++) if (!removed[i] && deg[i] < bd) { bd = deg[i]; best = i; }
        order.push_back(best);
        removed[best] = true;
        for (int j = adj[best]._Find_first(); j < MAXN; j = adj[best]._Find_next(j))
            if (!removed[j]) deg[j]--;
    }
    
    best_size = 0;
    
    for (int idx = N-1; idx >= 0; idx--) {
        if (timeout_flag) break;
        int v = order[idx];
        cur_clique.clear();
        cur_clique.push_back(v);
        vector<int> P;
        for (int j = idx+1; j < N; j++)
            if (adj[v].test(order[j])) P.push_back(order[j]);
        if ((int)P.size() + 1 > best_size) {
            if (P.empty()) { if (1 > best_size) { best_size = 1; best_clique = {v}; } }
            else expand(P);
        }
        cur_clique.clear();
    }
    
    vector<bool> in_clique(N+1, false);
    for (int v : best_clique) in_clique[v] = true;
    for (int i = 1; i <= N; i++) cout << in_clique[i] << "\n";
}
