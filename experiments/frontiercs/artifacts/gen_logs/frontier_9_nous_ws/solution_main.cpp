#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1005;

int n, P[MAXN];
vector<pair<int,int>> adj[MAXN]; // {neighbor, edge_index}
int eu[MAXN], ev[MAXN];
int D[MAXN][MAXN]; // all-pairs distances

// Tree DP for max weight matching
int par_node[MAXN];
vector<int> ch[MAXN];
int edge_idx_of[MAXN]; // edge_idx_of[c] = edge index between c and par_node[c]
int EW[MAXN]; // edge weight for current round

int dp0[MAXN], dp1[MAXN], best_ch[MAXN];

void bfs(int src) {
    memset(D[src], -1, sizeof(D[src]));
    D[src][src] = 0;
    queue<int> q;
    q.push(src);
    while (!q.empty()) {
        int u = q.front(); q.pop();
        for (auto& [v, _] : adj[u])
            if (D[src][v] == -1) { D[src][v] = D[src][u] + 1; q.push(v); }
    }
}

void root_tree(int root) {
    par_node[root] = 0;
    queue<int> q;
    q.push(root);
    vector<bool> vis(n + 1, false);
    vis[root] = true;
    while (!q.empty()) {
        int u = q.front(); q.pop();
        ch[u].clear();
        for (auto& [v, idx] : adj[u]) {
            if (!vis[v]) {
                vis[v] = true;
                par_node[v] = u;
                ch[u].push_back(v);
                edge_idx_of[v] = idx;
                q.push(v);
            }
        }
    }
}

void compute_dp(int u) {
    dp0[u] = 0;
    dp1[u] = -1;
    best_ch[u] = -1;

    int sum = 0;
    for (int c : ch[u]) {
        compute_dp(c);
        sum += max(dp0[c], dp1[c]);
    }
    dp0[u] = sum;

    for (int c : ch[u]) {
        int w = EW[edge_idx_of[c]];
        if (w <= 0) continue;
        int val = sum - max(dp0[c], dp1[c]) + dp0[c] + w;
        if (val > dp1[u]) {
            dp1[u] = val;
            best_ch[u] = c;
        }
    }
}

void extract(int u, bool use1, vector<int>& matching) {
    if (use1 && best_ch[u] != -1) {
        int c = best_ch[u];
        matching.push_back(edge_idx_of[c]);
        extract(c, false, matching);
        for (int cc : ch[u]) {
            if (cc == c) continue;
            extract(cc, dp1[cc] > dp0[cc], matching);
        }
    } else {
        for (int cc : ch[u]) {
            extract(cc, dp1[cc] > dp0[cc], matching);
        }
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
    root_tree(1);

    vector<vector<int>> all_ops;

    for (int round = 0; round < 4 * n; round++) {
        bool sorted = true;
        for (int i = 1; i <= n; i++) if (P[i] != i) { sorted = false; break; }
        if (sorted) break;

        // Compute edge weights: how many elements want to cross
        for (int idx = 1; idx < n; idx++) {
            int u = eu[idx], v = ev[idx];
            int a = P[u], b = P[v];
            // a at u wants to go to v iff v is next step toward target a
            bool aw = (a != u) && (D[v][a] == D[u][a] - 1);
            // b at v wants to go to u iff u is next step toward target b
            bool bw = (b != v) && (D[u][b] == D[v][b] - 1);
            EW[idx] = (aw ? 1 : 0) + (bw ? 1 : 0);
        }

        compute_dp(1);

        vector<int> matching;
        extract(1, dp1[1] > dp0[1], matching);

        if (matching.empty()) {
            // Fallback: force one swap for any misplaced element
            for (int i = 1; i <= n; i++) {
                if (P[i] != i) {
                    int target = P[i];
                    for (auto& [v, idx] : adj[i]) {
                        if (D[v][target] == D[i][target] - 1) {
                            matching.push_back(idx);
                            break;
                        }
                    }
                    break;
                }
            }
        }

        if (matching.empty()) break;

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
