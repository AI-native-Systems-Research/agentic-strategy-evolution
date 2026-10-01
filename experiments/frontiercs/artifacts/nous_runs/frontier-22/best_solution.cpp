#include <bits/stdc++.h>
using namespace std;

/*
 * Tree Decomposition of Tree + Leaf Ring
 *
 * Given a rooted tree with a cycle on its leaves (outer ring road),
 * construct a tree decomposition with bag size <= 4 and <= 4N bags.
 *
 * Key idea: For each node u, track L[u] (leftmost leaf in subtree)
 * and R[u] (rightmost leaf in subtree). Build bags per internal node:
 *   H_i = {u, c_i, L[c_i], R[c_i]}   -- covers tree edge (u, c_i)
 *   S_i = {u, R[u], L[c_i], R[c_i]}   -- spine maintaining u, R[u]
 *   Lnk_i = {u, R[u], R[c_i], L[c_{i+1}]} -- covers ring edge
 *
 * The wraparound ring edge (last_leaf, first_leaf) = (R[root], L[root])
 * is covered by S[0] at the root, since L[c_1] = L[root].
 */

static const int MAXN = 100005;
int N;
vector<int> ch[MAXN]; // children in rooted tree
int L[MAXN], R[MAXN]; // leftmost/rightmost leaf in subtree

struct Bag {
    int elems[4];
    int sz;
};

vector<Bag> bags;
vector<pair<int,int>> tedges; // tree decomposition edges
int root_bag[MAXN]; // root bag index (1-indexed) for each original node

int add_bag(int a, int b, int c, int d) {
    // Create bag with up to 4 elements, dedup
    int arr[4] = {a, b, c, d};
    sort(arr, arr+4);
    Bag bg;
    bg.sz = 0;
    for (int i = 0; i < 4; i++) {
        if (arr[i] <= 0) continue;
        if (bg.sz > 0 && bg.elems[bg.sz-1] == arr[i]) continue;
        bg.elems[bg.sz++] = arr[i];
    }
    bags.push_back(bg);
    return (int)bags.size(); // 1-indexed
}

void add_edge(int u, int v) {
    tedges.push_back({u, v});
}

void dfs_lr(int u) {
    if (ch[u].empty()) {
        L[u] = R[u] = u;
        return;
    }
    for (int c : ch[u]) dfs_lr(c);
    L[u] = L[ch[u][0]];
    R[u] = R[ch[u].back()];
}

void dfs_build(int u) {
    if (ch[u].empty()) {
        // Leaf: single bag
        root_bag[u] = add_bag(u, 0, 0, 0);
        return;
    }

    int m = (int)ch[u].size();
    vector<int> H(m), S(m), Lnk;

    for (int i = 0; i < m; i++) {
        int c = ch[u][i];
        H[i] = add_bag(u, c, L[c], R[c]);
        S[i] = add_bag(u, R[u], L[c], R[c]);
    }

    if (m > 1) {
        Lnk.resize(m - 1);
        for (int i = 0; i < m - 1; i++) {
            Lnk[i] = add_bag(u, R[u], R[ch[u][i]], L[ch[u][i+1]]);
        }
    }

    // Connect spine: S_i -- H_i, S_i -- Lnk_i -- S_{i+1}
    for (int i = 0; i < m; i++) {
        add_edge(S[i], H[i]);
        if (i < m - 1) {
            add_edge(S[i], Lnk[i]);
            add_edge(Lnk[i], S[i+1]);
        }
    }

    // Recurse children and connect H_i to child's root bag
    for (int i = 0; i < m; i++) {
        dfs_build(ch[u][i]);
        add_edge(H[i], root_bag[ch[u][i]]);
    }

    root_bag[u] = S[0];
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);

    cin >> N;
    for (int i = 2; i <= N; i++) {
        int p;
        cin >> p;
        ch[p].push_back(i);
    }

    dfs_lr(1);
    dfs_build(1);

    int K = (int)bags.size();
    cout << K << "\n";
    for (int i = 0; i < K; i++) {
        cout << bags[i].sz;
        for (int j = 0; j < bags[i].sz; j++) {
            cout << " " << bags[i].elems[j];
        }
        cout << "\n";
    }
    for (auto &e : tedges) {
        cout << e.first << " " << e.second << "\n";
    }

    return 0;
}
