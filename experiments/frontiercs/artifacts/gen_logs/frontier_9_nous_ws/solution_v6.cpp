#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1005;
int n, P[MAXN];
vector<pair<int,int>> adj[MAXN];
int eu[MAXN], ev[MAXN];
int D[MAXN][MAXN];

int par_node[MAXN], depth_node[MAXN];
vector<int> ch[MAXN];
int edge_of[MAXN];
int edge_color[MAXN];
int sub_sz[MAXN];

int EW[MAXN];
int dp0[MAXN], dp1[MAXN], best_ch[MAXN];

void bfs(int src) {
    memset(D[src], -1, sizeof(D[src]));
    D[src][src] = 0;
    queue<int> q; q.push(src);
    while (!q.empty()) {
        int u = q.front(); q.pop();
        for (auto& [v, _] : adj[u])
            if (D[src][v] == -1) { D[src][v] = D[src][u] + 1; q.push(v); }
    }
}

// Find centroid of the tree
int find_centroid() {
    // BFS from vertex 1 to compute subtree sizes
    vector<int> order;
    vector<int> par(n+1, 0);
    vector<bool> vis(n+1, false);
    queue<int> q; q.push(1); vis[1] = true;
    while (!q.empty()) {
        int u = q.front(); q.pop(); order.push_back(u);
        for (auto& [v, _] : adj[u]) if (!vis[v]) { vis[v]=true; par[v]=u; q.push(v); }
    }
    vector<int> sz(n+1, 1);
    for (int i = (int)order.size()-1; i >= 0; i--) {
        int u = order[i];
        if (par[u]) sz[par[u]] += sz[u];
    }
    int best = 1, best_val = n;
    for (int v = 1; v <= n; v++) {
        int maxsub = n - sz[v]; // "parent subtree"
        for (auto& [c, _] : adj[v]) {
            if (c != par[v]) maxsub = max(maxsub, sz[c]);
        }
        if (maxsub < best_val) { best_val = maxsub; best = v; }
    }
    return best;
}

void root_tree(int root) {
    par_node[root] = 0; depth_node[root] = 0;
    queue<int> q; q.push(root);
    vector<bool> vis(n + 1, false); vis[root] = true;
    while (!q.empty()) {
        int u = q.front(); q.pop();
        ch[u].clear();
        for (auto& [v, idx] : adj[u]) {
            if (!vis[v]) {
                vis[v] = true; par_node[v] = u;
                depth_node[v] = depth_node[u] + 1;
                ch[u].push_back(v); edge_of[v] = idx;
                edge_color[idx] = depth_node[v] % 2;
                q.push(v);
            }
        }
    }
}

void compute_dp(int u) {
    dp0[u] = 0; dp1[u] = -1; best_ch[u] = -1;
    int sum = 0;
    for (int c : ch[u]) { compute_dp(c); sum += max(dp0[c], dp1[c]); }
    dp0[u] = sum;
    for (int c : ch[u]) {
        int w = EW[edge_of[c]];
        if (w <= 0) continue;
        int val = sum - max(dp0[c], dp1[c]) + dp0[c] + w;
        if (val > dp1[u]) { dp1[u] = val; best_ch[u] = c; }
    }
}

void extract(int u, bool use1, vector<int>& matching) {
    if (use1 && best_ch[u] != -1) {
        int c = best_ch[u];
        matching.push_back(edge_of[c]);
        extract(c, false, matching);
        for (int cc : ch[u]) {
            if (cc == c) continue;
            extract(cc, dp1[cc] > dp0[cc], matching);
        }
    } else {
        for (int cc : ch[u])
            extract(cc, dp1[cc] > dp0[cc], matching);
    }
}

void solve() {
    scanf("%d", &n);
    for (int i = 1; i <= n; i++) { scanf("%d", &P[i]); adj[i].clear(); }
    for (int i = 1; i < n; i++) {
        scanf("%d%d", &eu[i], &ev[i]);
        adj[eu[i]].push_back({ev[i], i});
        adj[ev[i]].push_back({eu[i], i});
    }
    for (int i = 1; i <= n; i++) bfs(i);

    int centroid = find_centroid();
    root_tree(centroid);

    vector<vector<int>> all_ops;

    for (int round = 0; round < 6 * n; round++) {
        bool sorted = true;
        for (int i = 1; i <= n; i++) if (P[i] != i) { sorted = false; break; }
        if (sorted) break;

        int color = round % 2;
        for (int idx = 1; idx < n; idx++) {
            int u = eu[idx], v = ev[idx];
            int a = P[u], b = P[v];
            bool aw = (a != u) && (D[v][a] == D[u][a] - 1);
            bool bw = (b != v) && (D[u][b] == D[v][b] - 1);
            int type = (aw ? 1 : 0) + (bw ? 1 : 0);
            if (type == 2)
                EW[idx] = 2;
            else if (type == 1 && edge_color[idx] == color)
                EW[idx] = 1;
            else
                EW[idx] = 0;
        }

        compute_dp(centroid);
        vector<int> matching;
        extract(centroid, dp1[centroid] > dp0[centroid], matching);

        if (matching.empty()) continue;
        for (int idx : matching) swap(P[eu[idx]], P[ev[idx]]);
        all_ops.push_back(matching);
    }

    printf("%d\n", (int)all_ops.size());
    for (auto& op : all_ops) {
        printf("%d", (int)op.size());
        for (int idx : op) printf(" %d", idx);
        printf("\n");
    }
}

int main() {
    int T; scanf("%d", &T);
    while (T--) solve();
    return 0;
}
