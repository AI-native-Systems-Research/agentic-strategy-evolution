#include <cstdio>
#include <cstring>
#include <vector>
#include <algorithm>
using namespace std;

const int MAXN = 1005;
int n, P[MAXN];
vector<pair<int,int>> adj[MAXN];
int eu[MAXN], ev[MAXN];
short D[MAXN][MAXN];  // Keep short for cache

int par_node[MAXN], depth_node[MAXN];
vector<int> ch[MAXN];
int edge_of[MAXN], edge_color[MAXN];
int EW[MAXN], dp0[MAXN], dp1[MAXN], best_ch[MAXN];
int bfs_order[MAXN], bfs_sz;

void bfs(int src) {
    memset(D[src] + 1, -1, sizeof(short) * n);
    D[src][src] = 0;
    int q[MAXN], qh = 0, qt = 0;
    q[qt++] = src;
    while (qh < qt) {
        int u = q[qh++];
        for (auto& [v, _] : adj[u])
            if (D[src][v] == -1) { D[src][v] = D[src][u] + 1; q[qt++] = v; }
    }
}

void root_tree(int root) {
    par_node[root] = 0; depth_node[root] = 0;
    bool vis[MAXN]; memset(vis+1, 0, sizeof(bool)*n);
    vis[root] = true;
    int qh = 0; bfs_sz = 0;
    bfs_order[bfs_sz++] = root;
    while (qh < bfs_sz) {
        int u = bfs_order[qh++];
        ch[u].clear();
        for (auto& [v, idx] : adj[u]) {
            if (!vis[v]) {
                vis[v] = true; par_node[v] = u;
                depth_node[v] = depth_node[u] + 1;
                ch[u].push_back(v);
                edge_of[v] = idx;
                edge_color[idx] = depth_node[v] & 1;
                bfs_order[bfs_sz++] = v;
            }
        }
    }
}

// ITERATIVE DP (key optimization) but with vector children
void compute_dp_iterative() {
    for (int oi = bfs_sz - 1; oi >= 0; oi--) {
        int u = bfs_order[oi];
        int sum = 0;
        for (int c : ch[u]) sum += (dp1[c] > dp0[c]) ? dp1[c] : dp0[c];
        dp0[u] = sum; dp1[u] = -1; best_ch[u] = -1;
        for (int c : ch[u]) {
            int w = EW[edge_of[c]];
            if (w <= 0) continue;
            int val = sum - ((dp1[c] > dp0[c]) ? dp1[c] : dp0[c]) + dp0[c] + w;
            if (val > dp1[u]) { dp1[u] = val; best_ch[u] = c; }
        }
    }
}

int match_buf[MAXN], match_sz;
void extract_iterative(int root) {
    match_sz = 0;
    struct Frame { int u; bool use1; };
    Frame stk[MAXN]; int sp = 0;
    stk[sp++] = {root, dp1[root] > dp0[root]};
    while (sp > 0) {
        auto [u, use1] = stk[--sp];
        if (use1 && best_ch[u] != -1) {
            int c = best_ch[u];
            match_buf[match_sz++] = edge_of[c];
            stk[sp++] = {c, false};
            for (int cc : ch[u]) if (cc != c) stk[sp++] = {cc, dp1[cc] > dp0[cc]};
        } else {
            for (int cc : ch[u]) stk[sp++] = {cc, dp1[cc] > dp0[cc]};
        }
    }
}

char obuf[1 << 22]; int opos;
void write_int(int x) { if (x < 0) { obuf[opos++] = '-'; x = -x; } if (x >= 10) write_int(x / 10); obuf[opos++] = '0' + x % 10; }
void flush_output() { fwrite(obuf, 1, opos, stdout); opos = 0; }

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

    static int all_ops[6 * MAXN][MAXN / 2];
    static int all_ops_sz[6 * MAXN];
    int num_ops = 0;
    for (int round = 0; round < 6 * n; round++) {
        bool sorted = true;
        for (int i = 1; i <= n; i++) if (P[i] != i) { sorted = false; break; }
        if (sorted) break;
        int color = round & 1;
        for (int idx = 1; idx < n; idx++) {
            int u = eu[idx], v = ev[idx], a = P[u], b = P[v];
            int aw = (a != u && D[v][a] == D[u][a] - 1) ? 1 : 0;
            int bw = (b != v && D[u][b] == D[v][b] - 1) ? 1 : 0;
            int type = aw + bw;
            if (type == 2) EW[idx] = 2;
            else if (type == 1 && edge_color[idx] == color) EW[idx] = 1;
            else EW[idx] = 0;
        }
        compute_dp_iterative();
        extract_iterative(1);
        if (match_sz == 0) continue;
        all_ops_sz[num_ops] = match_sz;
        for (int i = 0; i < match_sz; i++) all_ops[num_ops][i] = match_buf[i];
        num_ops++;
        for (int i = 0; i < match_sz; i++) { int idx = match_buf[i]; swap(P[eu[idx]], P[ev[idx]]); }
    }
    write_int(num_ops); obuf[opos++] = '\n';
    for (int i = 0; i < num_ops; i++) {
        write_int(all_ops_sz[i]);
        for (int j = 0; j < all_ops_sz[i]; j++) { obuf[opos++] = ' '; write_int(all_ops[i][j]); }
        obuf[opos++] = '\n';
    }
}

int main() { opos = 0; int T; scanf("%d", &T); while (T--) solve(); flush_output(); return 0; }
