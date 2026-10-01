#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1001;
bitset<MAXN> adj[MAXN];
int N, M;
int best_size = 0;
vector<int> best_clique;
chrono::steady_clock::time_point start_time;
bool timeout_flag = false;

inline int elapsed_ms() {
    return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - start_time).count();
}

vector<int> cur_clique;

int color_bound_sorted(const vector<int>& Pvec, vector<pair<int,int>>& colored) {
    int np = Pvec.size();
    colored.resize(np);
    // Use greedy coloring with DSATUR-like approach
    // But for speed, just greedy coloring on given order
    static bitset<MAXN> color_class[MAXN+1];
    int num_colors = 0;
    
    for (int i = 0; i < np; i++) {
        int v = Pvec[i];
        int c;
        for (c = 0; c < num_colors; c++) {
            if ((adj[v] & color_class[c]).none()) break;
        }
        if (c == num_colors) {
            color_class[c].reset();
            num_colors++;
        }
        color_class[c].set(v);
        colored[i] = {c + 1, v};
    }
    for (int c = 0; c < num_colors; c++) color_class[c].reset();
    return num_colors;
}

void expand(vector<int>& Pvec) {
    if (timeout_flag) return;
    if (Pvec.empty()) {
        if ((int)cur_clique.size() > best_size) {
            best_size = cur_clique.size();
            best_clique = cur_clique;
        }
        return;
    }
    if (elapsed_ms() > 1850) { timeout_flag = true; return; }
    
    // Sort Pvec by degree in subgraph (ascending) for better coloring
    bitset<MAXN> Pset;
    for (int v : Pvec) Pset.set(v);
    sort(Pvec.begin(), Pvec.end(), [&](int a, int b){
        return (adj[a] & Pset).count() < (adj[b] & Pset).count();
    });
    
    vector<pair<int,int>> colored;
    int ub = color_bound_sorted(Pvec, colored);
    if ((int)cur_clique.size() + ub <= best_size) return;
    
    sort(colored.begin(), colored.end());
    
    for (int i = (int)colored.size() - 1; i >= 0; i--) {
        if (timeout_flag) return;
        int v = colored[i].second;
        int c = colored[i].first;
        if ((int)cur_clique.size() + c <= best_size) return;
        
        vector<int> newPvec;
        for (int j = 0; j < i; j++) {
            int u = colored[j].second;
            if (adj[v][u]) newPvec.push_back(u);
        }
        
        cur_clique.push_back(v);
        expand(newPvec);
        cur_clique.pop_back();
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(NULL);
    start_time = chrono::steady_clock::now();
    cin >> N >> M;
    for(int i = 0; i < M; i++){
        int u, v; cin >> u >> v;
        adj[u].set(v);
        adj[v].set(u);
    }
    
    vector<int> order;
    vector<bool> removed(N+1, false);
    vector<int> d(N+1);
    for (int i = 1; i <= N; i++) d[i] = (int)adj[i].count();
    for (int iter = 0; iter < N; iter++) {
        int best = -1;
        for (int i = 1; i <= N; i++)
            if (!removed[i] && (best == -1 || d[i] < d[best])) best = i;
        order.push_back(best);
        removed[best] = true;
        for (int i = 1; i <= N; i++)
            if (!removed[i] && adj[best][i]) d[i]--;
    }
    
    for (int idx = 0; idx < N && !timeout_flag; idx++) {
        int v = order[idx];
        cur_clique.clear();
        cur_clique.push_back(v);
        vector<int> Pvec;
        for (int j = idx + 1; j < N; j++) {
            int u = order[j];
            if (adj[v][u]) Pvec.push_back(u);
        }
        expand(Pvec);
    }
    
    vector<int> inC(N+1, 0);
    for (int v : best_clique) inC[v] = 1;
    for (int i = 1; i <= N; i++) cout << inC[i] << "\n";
}
