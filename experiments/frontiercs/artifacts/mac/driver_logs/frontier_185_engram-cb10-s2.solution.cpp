#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 1001;
bitset<MAXN> adj[MAXN];
int N, M;
int bestSize;
vector<int> bestClique;
int curClique[MAXN], curSize;
chrono::steady_clock::time_point startT;
bool timed_out;

inline long long ems(){ return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-startT).count(); }

// Color the subgraph induced by vertices in cand using bitsets
// Returns upper bound. Fills 'order' and 'color' arrays.
int colorSort(int* cand, int ncand, int* order, int* color){
    static bitset<MAXN> colorClass[MAXN];
    int ncolors = 0;
    int pos = 0;
    for(int i = 0; i < ncand; i++){
        int v = cand[i];
        int c = -1;
        for(int k = 0; k < ncolors; k++){
            if((adj[v] & colorClass[k]).none()){
                c = k; break;
            }
        }
        if(c == -1){ c = ncolors; colorClass[ncolors].reset(); ncolors++; }
        colorClass[c].set(v);
    }
    // Sort by color ascending
    // Rebuild: group by color
    pos = 0;
    for(int k = 0; k < ncolors; k++){
        for(int i = 0; i < ncand; i++){
            if(colorClass[k].test(cand[i])){
                order[pos] = cand[i];
                color[pos] = k+1;
                pos++;
            }
        }
        colorClass[k].reset();
    }
    return ncolors;
}

void expand(int* cand, int ncand){
    if(timed_out) return;
    static int ord[MAXN], col[MAXN];
    int ub = colorSort(cand, ncand, ord, col);
    if(curSize + ub <= bestSize) return;
    
    for(int i = ncand-1; i >= 0; i--){
        if(timed_out) return;
        if(curSize + col[i] <= bestSize) return;
        int v = ord[i];
        curClique[curSize++] = v;
        // Build new candidate set: intersection of ord[0..i-1] with adj[v]
        static int newcand[MAXN];
        int nn = 0;
        for(int j = 0; j < i; j++){
            if(adj[v].test(ord[j])) newcand[nn++] = ord[j];
        }
        if(nn == 0){
            if(curSize > bestSize){ bestSize = curSize; bestClique.assign(curClique, curClique+curSize); }
        } else {
            if((++callCnt & 4095) == 0 && ems() > 1900) timed_out = true;
            expand(newcand, nn);
        }
        curSize--;
    }
}
int callCnt;

int main(){
    ios::sync_with_stdio(false); cin.tie(nullptr);
    startT = chrono::steady_clock::now(); timed_out = false; callCnt = 0;
    cin >> N >> M;
    for(int i = 0; i < M; i++){int u,v; cin >> u >> v; adj[u].set(v); adj[v].set(u);}
    // Degeneracy ordering
    vector<int> deg(N+1), order;
    vector<bool> rem(N+1,false);
    for(int i=1;i<=N;i++) deg[i]=adj[i].count();
    for(int it=0;it<N;it++){
        int b=-1,bd=N+1;
        for(int i=1;i<=N;i++) if(!rem[i]&&deg[i]<bd){bd=deg[i];b=i;}
        rem[b]=true; order.push_back(b);
        for(int j=1;j<=N;j++) if(!rem[j]&&adj[b].test(j)) deg[j]--;
    }
    bestSize=0; curSize=0;
    for(int idx=N-1;idx>=0;idx--){
        if(timed_out) break;
        int v=order[idx];
        int cand[MAXN], nc=0;
        for(int j=idx+1;j<N;j++) if(adj[v].test(order[j])) cand[nc++]=order[j];
        if(nc+1<=bestSize) continue;
        curSize=0; curClique[curSize++]=v;
        expand(cand, nc);
    }
    vector<int> inc(N+1,0);
    for(int v:bestClique) inc[v]=1;
    for(int i=1;i<=N;i++) cout<<inc[i]<<"\n";
}
