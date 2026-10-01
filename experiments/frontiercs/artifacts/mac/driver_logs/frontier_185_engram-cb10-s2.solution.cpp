#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 1001;
static const int WORDS = (MAXN + 63) / 64;
typedef unsigned long long u64;

struct Bitset {
    u64 w[WORDS];
    void clear() { memset(w, 0, sizeof(w)); }
    void set(int i) { w[i >> 6] |= 1ULL << (i & 63); }
    bool test(int i) const { return (w[i >> 6] >> (i & 63)) & 1; }
    int count() const { int c=0; for(int i=0;i<WORDS;i++) c+=__builtin_popcountll(w[i]); return c; }
    bool and_any(const Bitset& o) const { for(int i=0;i<WORDS;i++) if(w[i]&o.w[i]) return true; return false; }
};

Bitset adj[MAXN];
int N, M;
int bestLen;
int bestClique[MAXN];
int curClique[MAXN], curLen;
chrono::steady_clock::time_point startT;
bool timeout_;

inline long long ems() {
    return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - startT).count();
}

int colorBound(int* cand, int nc, int* outOrder, int* outColor) {
    static Bitset colorSet[MAXN];
    static int col[MAXN];
    int numColors = 0;
    for(int i = 0; i < nc; i++) {
        int v = cand[i];
        int c;
        for(c = 0; c < numColors; c++) {
            if(!adj[v].and_any(colorSet[c])) break;
        }
        if(c == numColors) { colorSet[c].clear(); numColors++; }
        colorSet[c].set(v);
        col[i] = c;
    }
    for(int i = 0; i < nc; i++) colorSet[col[i]].clear();
    static pair<int,int> cv[MAXN];
    for(int i = 0; i < nc; i++) cv[i] = {col[i], cand[i]};
    sort(cv, cv + nc);
    for(int i = 0; i < nc; i++) { outOrder[i] = cv[i].second; outColor[i] = cv[i].first + 1; }
    return numColors;
}

static int expOrder[MAXN], expColor[MAXN];
static int newP_stack[MAXN][MAXN];

void expand(int* P, int np, int depth) {
    if(timeout_) return;
    if(np == 0) { if(curLen > bestLen) { bestLen = curLen; memcpy(bestClique, curClique, curLen*sizeof(int)); } return; }
    int nc = colorBound(P, np, expOrder, expColor);
    if(curLen + nc <= bestLen) return;
    int* newP = newP_stack[depth];
    for(int i = np-1; i >= 0; i--) {
        if(timeout_) return;
        if(ems() > 1950) { timeout_ = true; return; }
        if(curLen + expColor[i] <= bestLen) return;
        int v = expOrder[i];
        int nnp = 0;
        for(int j = 0; j < i; j++) if(adj[v].test(expOrder[j])) newP[nnp++] = expOrder[j];
        curClique[curLen++] = v;
        expand(newP, nnp, depth+1);
        curLen--;
    }
}

int main(){
    ios::sync_with_stdio(false); cin.tie(nullptr);
    startT = chrono::steady_clock::now(); timeout_ = false;
    cin >> N >> M;
    for(int i=0;i<=N;i++) adj[i].clear();
    for(int i=0;i<M;i++){int u,v; cin>>u>>v; adj[u].set(v); adj[v].set(u);}
    vector<int> deg(N+1), order;
    vector<bool> rem(N+1, false);
    for(int i=1;i<=N;i++) deg[i]=adj[i].count();
    for(int it=0;it<N;it++){
        int best=-1,bd=N+1;
        for(int i=1;i<=N;i++) if(!rem[i]&&deg[i]<bd){bd=deg[i];best=i;}
        rem[best]=true; order.push_back(best);
        for(int j=1;j<=N;j++) if(!rem[j]&&adj[best].test(j)) deg[j]--;
    }
    bestLen = 0; curLen = 0;
    for(int start=N-1;start>=0;start--){
        Bitset ca; ca.clear();
        for(int k=0;k<WORDS;k++) ca.w[k]=adj[order[start]].w[k];
        int cl[MAXN],clen=0; cl[clen++]=order[start];
        for(int i=N-1;i>=0;i--){
            int v=order[i]; if(v==order[start]) continue;
            if(ca.test(v)){
                cl[clen++]=v;
                for(int k=0;k<WORDS;k++) ca.w[k]&=adj[v].w[k];
            }
        }
        if(clen>bestLen){bestLen=clen; memcpy(bestClique,cl,clen*sizeof(int));}
    }
    static int P[MAXN];
    for(int idx=N-1;idx>=0;idx--){
        if(timeout_) break;
        int v=order[idx];
        int np=0;
        for(int j=idx+1;j<N;j++) if(adj[v].test(order[j])) P[np++]=order[j];
        if(np+1<=bestLen) continue;
        curLen=0; curClique[curLen++]=v;
        expand(P, np, 0);
    }
    vector<int> inc(N+1,0);
    for(int i=0;i<bestLen;i++) inc[bestClique[i]]=1;
    for(int i=1;i<=N;i++) cout<<inc[i]<<"\n";
}
