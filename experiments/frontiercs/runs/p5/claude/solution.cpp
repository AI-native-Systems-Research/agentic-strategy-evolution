#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 500002;

int n, m;
vector<int> adj[MAXN], radj[MAXN];
int out_deg[MAXN], in_deg[MAXN];

int cur_stamp;
int pstamp[MAXN];
int dstamp[MAXN], dval[MAXN];
int rstamp[MAXN], rval[MAXN];
int nstamp[MAXN], nval[MAXN];
int pvstamp[MAXN], pvval[MAXN];

inline bool on_path(int v) { return pstamp[v] == cur_stamp; }
inline void mark_on(int v) { pstamp[v] = cur_stamp; }
inline int get_cnt(int v) { return (dstamp[v]==cur_stamp) ? out_deg[v]-dval[v] : out_deg[v]; }
inline void dec_cnt(int v) { if(dstamp[v]!=cur_stamp){dstamp[v]=cur_stamp;dval[v]=0;} dval[v]++; }
inline int get_rcnt(int v) { return (rstamp[v]==cur_stamp) ? in_deg[v]-rval[v] : in_deg[v]; }
inline void dec_rcnt(int v) { if(rstamp[v]!=cur_stamp){rstamp[v]=cur_stamp;rval[v]=0;} rval[v]++; }
inline int get_nxt(int v) { return (nstamp[v]==cur_stamp) ? nval[v] : -1; }
inline void set_nxt(int v,int w) { nstamp[v]=cur_stamp; nval[v]=w; }
inline int get_prv(int v) { return (pvstamp[v]==cur_stamp) ? pvval[v] : -1; }
inline void set_prv(int v,int w) { pvstamp[v]=cur_stamp; pvval[v]=w; }

mt19937 rng(54321);
int head_g, tail_g, pl;

void visit_v(int u) {
    mark_on(u); pl++;
    for (int w : radj[u]) dec_cnt(w);
    for (int w : adj[u]) dec_rcnt(w);
}

bool has_edge(int u, int v) {
    return binary_search(adj[u].begin(), adj[u].end(), v);
}

vector<int> best_path;

void save_best() {
    if (pl > (int)best_path.size()) {
        best_path.resize(pl);
        int c = head_g;
        for (int i = 0; i < pl; i++) { best_path[i] = c; c = get_nxt(c); }
    }
}

void append_tail(int v) {
    set_nxt(tail_g, v); set_prv(v, tail_g);
    tail_g = v; visit_v(v);
}
void prepend_head(int v) {
    set_nxt(v, head_g); set_prv(head_g, v);
    head_g = v; visit_v(v);
}

int tail_score(int v) {
    int c = get_cnt(v);
    return (c == 0 && pl < n-1) ? n+1 : c;
}
int head_score(int v) {
    int c = get_rcnt(v);
    return (c == 0 && pl < n-1) ? n+1 : c;
}

void extend_greedily() {
    while (pl < n) {
        int tb = -1, ts = INT_MAX;
        for (int v : adj[tail_g])
            if (!on_path(v)) {
                int s = tail_score(v);
                if (s < ts || (s == ts && (rng()&1))) { ts = s; tb = v; }
            }

        int hb = -1, hs = INT_MAX;
        for (int u : radj[head_g])
            if (!on_path(u)) {
                int s = head_score(u);
                if (s < hs || (s == hs && (rng()&1))) { hs = s; hb = u; }
            }

        if (tb == -1 && hb == -1) break;
        if (tb != -1 && (hb == -1 || ts <= hs))
            append_tail(tb);
        else
            prepend_head(hb);
    }
}

void insert_remaining() {
    for (int pass = 0; pass < 5 && pl < n; pass++) {
        bool any = false;
        for (int u = 1; u <= n && pl < n; u++) {
            if (on_path(u)) continue;
            if (has_edge(tail_g, u)) {
                append_tail(u); any = true;
                extend_greedily();
                continue;
            }
            if (has_edge(u, head_g)) {
                prepend_head(u); any = true;
                extend_greedily();
                continue;
            }
            for (int w : radj[u]) {
                if (on_path(w)) {
                    int nx = get_nxt(w);
                    if (nx != -1 && has_edge(u, nx)) {
                        set_nxt(w,u); set_prv(u,w);
                        set_nxt(u,nx); set_prv(nx,u);
                        visit_v(u); any = true;
                        break;
                    }
                }
            }
        }
        if (!any) break;
    }
}

void try_solve(int start, bool ins) {
    cur_stamp++;
    head_g = tail_g = start; pl = 0;
    visit_v(start);
    extend_greedily();
    if (ins && pl < n) insert_remaining();
    save_best();
}

int main() {
    scanf("%d %d", &n, &m);
    int a[10];
    for (int i = 0; i < 10; i++) scanf("%d", &a[i]);
    for (int i = 0; i < m; i++) {
        int u, v; scanf("%d %d", &u, &v);
        adj[u].push_back(v); radj[v].push_back(u);
        out_deg[u]++; in_deg[v]++;
    }
    for (int i = 1; i <= n; i++) {
        sort(adj[i].begin(), adj[i].end());
        sort(radj[i].begin(), radj[i].end());
    }

    memset(pstamp,0,sizeof(pstamp));
    memset(dstamp,0,sizeof(dstamp));
    memset(rstamp,0,sizeof(rstamp));
    memset(nstamp,0,sizeof(nstamp));
    memset(pvstamp,0,sizeof(pvstamp));
    cur_stamp = 0;

    auto t0 = chrono::steady_clock::now();
    auto ms = [&]() { return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count(); };

    vector<int> zero_in;
    for (int i=1;i<=n;i++) if(in_deg[i]==0) zero_in.push_back(i);
    for (int s : zero_in) {
        try_solve(s, true);
        if ((int)best_path.size()==n) goto done;
        if (ms()>2000) break;
    }

    {
        vector<int> perm(n); iota(perm.begin(),perm.end(),1);
        shuffle(perm.begin(),perm.end(),rng);
        for (int i=0; i<min(n,300) && ms()<2500; i++) {
            try_solve(perm[i], true);
            if ((int)best_path.size()==n) goto done;
        }
    }

    while (ms()<3500) {
        try_solve(1+rng()%n, false);
        if ((int)best_path.size()==n) goto done;
    }

done:
    printf("%d\n",(int)best_path.size());
    for (int i=0;i<(int)best_path.size();i++) {
        if(i) putchar(' ');
        printf("%d",best_path[i]);
    }
    putchar('\n');
    return 0;
}
