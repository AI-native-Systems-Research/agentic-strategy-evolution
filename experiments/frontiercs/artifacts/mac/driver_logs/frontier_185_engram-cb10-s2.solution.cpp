#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 1001;
static const int WORDS = (MAXN + 63) / 64;
typedef unsigned long long u64;

struct Bitset {
    u64 w[WORDS];
    void reset() { memset(w, 0, sizeof(w)); }
    void set(int i) { w[i >> 6] |= 1ULL << (i & 63); }
    bool test(int i) const { return (w[i >> 6] >> (i & 63)) & 1; }
    int count() const { int c = 0; for (int i = 0; i < WORDS; i++) c += __builtin_popcountll(w[i]); return c; }
    void andWith(const Bitset& o) { for (int i = 0; i < WORDS; i++) w[i] &= o.w[i]; }
    Bitset operator&(const Bitset& o) const { Bitset r; for (int i = 0; i < WORDS; i++) r.w[i] = w[i] & o.w[i]; return r; }
};

Bitset adj[MAXN];
int N, M;
int bestSize, bestClique[MAXN], bestCliqueSize;
chrono::steady_clock::time_point startT;
bool timeout_;
inline long long ems() { return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - startT).count(); }

void expand(int* P, int np, int* clique, int cs) {
    if (timeout_) return;
    if (np == 0) { if (cs > bestSize) { bestSize = cs; memcpy(bestClique, clique, cs * sizeof(int)); bestCliqueSize = cs; } return; }
    // Greedy coloring to get upper bound
    int col[MAXN];
    bool usedColor[MAXN + 1];
    int maxCol = 0;
    for (int i = 0; i < np; i++) {
        memset(usedColor, 0, (maxCol + 2) * sizeof(bool));
        int v = P[i];
        for (int j = 0; j < i; j++) {
            if (adj[v].test(P[j])) usedColor[col[j]] = true;
        }
        int c = 1;
        while (usedColor[c]) c++;
        col[i] = c;
        if (c > maxCol) maxCol = c;
    }
    if (cs + maxCol <= bestSize) return;
    int localP[MAXN];
    for (int i = np - 1; i >= 0; i--) {
        if (timeout_) return;
        if ((i & 31) == 0 && ems() > 1900) { timeout_ = true; return; }
        if (cs + col[i] <= bestSize) return;
        int v = P[i], nnp = 0;
        for (int j = 0; j < i; j++) if (adj[v].test(P[j])) localP[nnp++] = P[j];
        clique[cs] = v;
        expand(localP, nnp, clique, cs + 1);
    }
}

int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    startT = chrono::steady_clock::now(); timeout_ = false;
    cin >> N >> M;
    for (int i = 0; i <= N; i++) adj[i].reset();
    for (int i = 0; i < M; i++) { int u, v; cin >> u >> v; adj[u].set(v); adj[v].set(u); }
    vector<int> deg(N + 1); for (int i = 1; i <= N; i++) deg[i] = adj[i].count();
    vector<bool> rem(N + 1, false); vector<int> order; order.reserve(N);
    for (int it = 0; it < N; it++) {
        int best = -1, bd = N + 1;
        for (int i = 1; i <= N; i++) if (!rem[i] && deg[i] < bd) { bd = deg[i]; best = i; }
        rem[best] = true; order.push_back(best);
        for (int j = 1; j <= N; j++) if (!rem[j] && adj[best].test(j)) deg[j]--;
    }
    bestSize = 0; bestCliqueSize = 0;
    for (int start = N - 1; start >= max(0, N - 200); start--) {
        Bitset ca; for (int i = 0; i < WORDS; i++) ca.w[i] = ~0ULL;
        int cl[MAXN], cs = 0;
        cl[cs++] = order[start]; ca.andWith(adj[order[start]]); ca.set(order[start]);
        for (int i = N - 1; i >= 0; i--) { int v = order[i]; if (v == order[start]) continue; if (ca.test(v)) { cl[cs++] = v; ca.andWith(adj[v]); ca.set(v); } }
        if (cs > bestSize) { bestSize = cs; memcpy(bestClique, cl, cs * sizeof(int)); bestCliqueSize = cs; }
    }
    int P[MAXN], clique[MAXN];
    for (int idx = N - 1; idx >= 0; idx--) {
        if (timeout_) break;
        int v = order[idx]; int np = 0;
        for (int j = idx + 1; j < N; j++) if (adj[v].test(order[j])) P[np++] = order[j];
        if (np + 1 <= bestSize) continue;
        clique[0] = v;
        expand(P, np, clique, 1);
    }
    vector<int> inc(N + 1, 0);
    for (int i = 0; i < bestCliqueSize; i++) inc[bestClique[i]] = 1;
    for (int i = 1; i <= N; i++) cout << inc[i] << "\n";
}
