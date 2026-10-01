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

static bitset<MAXN> color_bs[MAXN + 1];

void color_sort(const vector<int>& P, vector<int>& order, vector<int>& color_num) {
    int n = P.size();
    if (n == 0) return;
    order.resize(n);
    color_num.resize(n);
    
    int maxno = 0;
    vector<pair<int,int>> vc;
    vc.reserve(n);
    
    for (int i = 0; i < n; i++) {
        int v = P[i];
        int k = 1;
        while (k <= maxno && (adj[v] & color_bs[k]).any()) k++;
        if (k > maxno) { maxno = k; color_bs[k].reset(); }
        color_bs[k].set(v);
        vc.push_back({k, v});
    }
    
    sort(vc.begin(), vc.end());
    for (int i = 0; i < n; i++) {
        order[i] = vc[i].second;
        color_num[i] = vc[i].first;
    }
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
        
        if ((i & 31) == 0 && elapsed_ms() > 1800) {
            timeout_flag = true;
            return;
        }
    }
}

vector<int> greedy_clique(const vector<int>& order) {
    bitset<MAXN> clique_bs;
    vector<int> clique;
    for (int v : order) {
        if ((clique_bs & ~adj[v]).none()) {
            clique.push_back(v);
            clique_bs.set(v);
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
    
    vector<int> deg(N+1);
    vector<bool> removed(N+1, false);
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    
    vector<int> degen_order;
    for (int iter = 0; iter < N; iter++) {
        int best = -1;
        for (int i = 1; i <= N; i++)
            if (!removed[i] && (best == -1 || deg[i] < deg[best])) best = i;
        removed[best] = true;
        degen_order.push_back(best);
        for (int j = 1; j <= N; j++)
            if (!removed[j] && adj[best][j]) deg[j]--;
    }
    
    auto try_greedy = [&](const vector<int>& order) {
        auto gc = greedy_clique(order);
        if ((int)gc.size() > best_size) { best_size = gc.size(); best_clique = gc; }
    };
    
    try_greedy(degen_order);
    vector<int> rev(degen_order.rbegin(), degen_order.rend());
    try_greedy(rev);
    
    mt19937 rng(42);
    for (int r = 0; r < 200 && elapsed_ms() < 300; r++) {
        vector<int> ro(degen_order);
        shuffle(ro.begin(), ro.end(), rng);
        try_greedy(ro);
    }
    
    expand(degen_order);
    
    set<int> in_clique(best_clique.begin(), best_clique.end());
    for (int i = 1; i <= N; i++) cout << (in_clique.count(i) ? 1 : 0) << "\n";
}
