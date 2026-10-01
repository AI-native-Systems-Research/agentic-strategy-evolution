#pragma GCC optimize("O3,unroll-loops")
#pragma GCC target("avx2")
#include <cstdio>
#include <cstring>
#include <algorithm>
using namespace std;

const int MAXN = 1005;
const int MAXE = 2 * MAXN;

int n;
int P[MAXN];

// Adjacency list using arrays
int head_arr[MAXN], nxt_arr[MAXE], to_arr[MAXE], eidx_arr[MAXE], ecnt;
int eu[MAXN], ev[MAXN];

// Tree structure
int par_node[MAXN], depth_node[MAXN];
int ch_arr[MAXN][MAXN];
int nch[MAXN];
int edge_of[MAXN];
int edge_color[MAXN];

// DFS timestamps
int tin[MAXN], tout[MAXN], dfs_timer;
int child_endpoint[MAXN];

// Edge weights
int EW[MAXN];

// BFS order
int bfs_order[MAXN];
int bfs_sz;

inline void add_edge(int u, int v, int idx) {
    ++ecnt;
    to_arr[ecnt] = v;
    eidx_arr[ecnt] = idx;
    nxt_arr[ecnt] = head_arr[u];
    head_arr[u] = ecnt;
}

void root_tree(int root) {
    par_node[root] = 0;
    depth_node[root] = 0;
    nch[root] = 0;
    bool vis[MAXN];
    memset(vis + 1, 0, sizeof(bool) * n);
    vis[root] = true;
    int qh = 0;
    bfs_sz = 0;
    bfs_order[bfs_sz++] = root;
    while (qh < bfs_sz) {
        int u = bfs_order[qh++];
        nch[u] = 0;
        for (int e = head_arr[u]; e; e = nxt_arr[e]) {
            int v = to_arr[e];
            if (!vis[v]) {
                vis[v] = true;
                par_node[v] = u;
                depth_node[v] = depth_node[u] + 1;
                ch_arr[u][nch[u]++] = v;
                edge_of[v] = eidx_arr[e];
                edge_color[eidx_arr[e]] = depth_node[v] & 1;
                child_endpoint[eidx_arr[e]] = v;
                bfs_order[bfs_sz++] = v;
            }
        }
    }
}

void compute_dfs_timestamps(int root) {
    dfs_timer = 0;
    struct Frame { int u; int ci; };
    Frame stk[MAXN];
    int sp = 0;
    stk[sp++] = {root, 0};
    tin[root] = dfs_timer++;
    while (sp > 0) {
        Frame& f = stk[sp - 1];
        if (f.ci < nch[f.u]) {
            int c = ch_arr[f.u][f.ci++];
            tin[c] = dfs_timer++;
            stk[sp++] = {c, 0};
        } else {
            tout[f.u] = dfs_timer++;
            sp--;
        }
    }
}

inline bool is_in_subtree(int v, int target) {
    return tin[v] <= tin[target] && tin[target] <= tout[v];
}

// LEAF-TO-ROOT GREEDY MATCHING
// Process nodes from leaves to root (reverse BFS order).
// At each node, if unmatched, try to match with its parent edge if weight > 0 and parent unmatched.
int match_buf[MAXN];
int match_sz;
bool matched_node[MAXN];

void leaf_to_root_greedy() {
    match_sz = 0;
    memset(matched_node + 1, 0, sizeof(bool) * n);

    // Process from leaves to root (reverse BFS order)
    for (int oi = bfs_sz - 1; oi >= 1; oi--) {
        int v = bfs_order[oi]; // v is a non-root node (child)
        int u = par_node[v];   // u is v's parent
        int idx = edge_of[v];  // edge (u, v)

        if (EW[idx] > 0 && !matched_node[u] && !matched_node[v]) {
            match_buf[match_sz++] = idx;
            matched_node[u] = matched_node[v] = true;
        }
    }
}

// Output buffer
char obuf[1 << 22];
int opos;

void write_int(int x) {
    if (x < 0) { obuf[opos++] = '-'; x = -x; }
    if (x >= 10) write_int(x / 10);
    obuf[opos++] = '0' + x % 10;
}

void flush_output() {
    fwrite(obuf, 1, opos, stdout);
    opos = 0;
}

void solve() {
    scanf("%d", &n);
    ecnt = 0;
    memset(head_arr + 1, 0, sizeof(int) * n);
    for (int i = 1; i <= n; i++) scanf("%d", &P[i]);
    for (int i = 1; i < n; i++) {
        scanf("%d%d", &eu[i], &ev[i]);
        add_edge(eu[i], ev[i], i);
        add_edge(ev[i], eu[i], i);
    }
    root_tree(1);
    compute_dfs_timestamps(1);

    static int all_ops[6 * MAXN][MAXN / 2];
    static int all_ops_sz[6 * MAXN];
    int num_ops = 0;

    int max_rounds = 6 * n;
    for (int round = 0; round < max_rounds; round++) {
        bool sorted = true;
        for (int i = 1; i <= n; i++) {
            if (P[i] != i) { sorted = false; break; }
        }
        if (sorted) break;

        int color = round & 1;
        for (int idx = 1; idx < n; idx++) {
            int v = child_endpoint[idx];
            int u = (eu[idx] == v) ? ev[idx] : eu[idx];
            int a = P[u], b = P[v];

            bool aw = (a != u) && is_in_subtree(v, a);
            bool bw = (b != v) && !is_in_subtree(v, b);

            int type = (aw ? 1 : 0) + (bw ? 1 : 0);
            if (type == 2)
                EW[idx] = 2;
            else if (type == 1 && edge_color[idx] == color)
                EW[idx] = 1;
            else
                EW[idx] = 0;
        }

        leaf_to_root_greedy();

        if (match_sz == 0) continue;
        all_ops_sz[num_ops] = match_sz;
        for (int i = 0; i < match_sz; i++)
            all_ops[num_ops][i] = match_buf[i];
        num_ops++;
        for (int i = 0; i < match_sz; i++) {
            int idx = match_buf[i];
            swap(P[eu[idx]], P[ev[idx]]);
        }
    }

    write_int(num_ops);
    obuf[opos++] = '\n';
    for (int i = 0; i < num_ops; i++) {
        write_int(all_ops_sz[i]);
        for (int j = 0; j < all_ops_sz[i]; j++) {
            obuf[opos++] = ' ';
            write_int(all_ops[i][j]);
        }
        obuf[opos++] = '\n';
    }
}

int main() {
    opos = 0;
    int T;
    scanf("%d", &T);
    while (T--) solve();
    flush_output();
    return 0;
}
