#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1005;
int n, P[MAXN];
vector<pair<int,int>> adj[MAXN];
int eu[MAXN], ev[MAXN];
int D[MAXN][MAXN];

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

void solve() {
    scanf("%d", &n);
    for (int i = 1; i <= n; i++) { scanf("%d", &P[i]); adj[i].clear(); }
    for (int i = 1; i < n; i++) {
        scanf("%d%d", &eu[i], &ev[i]);
        adj[eu[i]].push_back({ev[i], i});
        adj[ev[i]].push_back({eu[i], i});
    }
    for (int i = 1; i <= n; i++) bfs(i);

    vector<vector<int>> all_ops;

    // Naive greedy: each round, scan edges and greedily pick first beneficial swap
    // No tree DP matching, no anti-oscillation
    for (int round = 0; round < 6 * n; round++) {
        bool sorted = true;
        for (int i = 1; i <= n; i++) if (P[i] != i) { sorted = false; break; }
        if (sorted) break;

        vector<int> matching;
        vector<bool> used(n + 1, false);

        for (int idx = 1; idx < n; idx++) {
            int u = eu[idx], v = ev[idx];
            if (used[u] || used[v]) continue;
            int a = P[u], b = P[v];
            bool aw = (a != u) && (D[v][a] == D[u][a] - 1);
            bool bw = (b != v) && (D[u][b] == D[v][b] - 1);
            int type = (aw ? 1 : 0) + (bw ? 1 : 0);
            if (type >= 1) {
                matching.push_back(idx);
                used[u] = true;
                used[v] = true;
            }
        }

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
