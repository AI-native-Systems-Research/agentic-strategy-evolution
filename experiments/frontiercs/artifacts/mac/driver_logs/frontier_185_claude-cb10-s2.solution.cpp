#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1005;
bitset<MAXN> adj[MAXN];
int N, M;
int bestSize = 0;
vector<int> bestClique;
chrono::steady_clock::time_point startTime;
bool timeUp = false;

inline bool checkTime(int ms = 1900) {
    auto now = chrono::steady_clock::now();
    if (chrono::duration_cast<chrono::milliseconds>(now - startTime).count() > ms) {
        timeUp = true;
        return true;
    }
    return false;
}

int clique[MAXN];
int cliqueLevel;
int callCount = 0;

// Color vertices in order[], return max color used
// Uses a tighter approach: for each vertex, find minimum color not used by already-colored neighbors
int vertColor[MAXN];

int colorBound(int order[], int cnt, bitset<MAXN>& P) {
    // color vertices in given order
    int maxc = 0;
    // For each vertex, track which colors its neighbors use
    static int colorOf[MAXN]; // color assigned (1-indexed)
    static bool used[MAXN];
    
    for (int i = 0; i < cnt; i++) {
        int v = order[i];
        // find colors used by already-colored neighbors in P
        memset(used, 0, (maxc + 2) * sizeof(bool));
        for (int j = 0; j < i; j++) {
            int u = order[j];
            if (adj[v].test(u)) {
                used[colorOf[u]] = true;
            }
        }
        int c = 1;
        while (used[c]) c++;
        colorOf[v] = c;
        vertColor[v] = c;
        if (c > maxc) maxc = c;
    }
    return maxc;
}

void expand(bitset<MAXN>& P, int pcnt) {
    if (timeUp) return;
    if ((++callCount & 2047) == 0) checkTime();
    
    if (pcnt == 0) {
        if (cliqueLevel > bestSize) {
            bestSize = cliqueLevel;
            bestClique.assign(clique, clique + cliqueLevel);
        }
        return;
    }
    
    // Build candidate list sorted by degree in subgraph (ascending for coloring)
    int order[MAXN], oc = 0;
    for (int v = (int)P._Find_first(); v <= N; v = (int)P._Find_next(v))
        order[oc++] = v;
    
    // Sort by subgraph degree ascending (good for greedy coloring bound)
    sort(order, order + oc, [&](int a, int b) {
        return (adj[a] & P).count() < (adj[b] & P).count();
    });
    
    int maxc = colorBound(order, oc, P);
    if (cliqueLevel + maxc <= bestSize) return;
    
    // Branch from highest color first
    sort(order, order + oc, [](int a, int b) { return vertColor[a] < vertColor[b]; });
    
    for (int i = oc - 1; i >= 0 && !timeUp; i--) {
        if (cliqueLevel + vertColor[order[i]] <= bestSize) return;
        int v = order[i];
        clique[cliqueLevel++] = v;
        bitset<MAXN> newP = P & adj[v];
        int nc = (int)newP.count();
        P.reset(v);
        expand(newP, nc);
        cliqueLevel--;
    }
}

vector<int> greedyClique(int start) {
    vector<int> cl = {start};
    bitset<MAXN> cand = adj[start];
    while (cand.any()) {
        int best = -1, bestDeg = -1;
        for (int v = (int)cand._Find_first(); v <= N; v = (int)cand._Find_next(v)) {
            int d = (int)(adj[v] & cand).count();
            if (d > bestDeg) { bestDeg = d; best = v; }
        }
        cl.push_back(best);
        cand &= adj[best];
    }
    return cl;
}

int main(){
    ios::sync_with_stdio(false); cin.tie(nullptr);
    startTime = chrono::steady_clock::now();
    cin >> N >> M;
    for (int i = 0; i < M; i++) { int u, v; cin >> u >> v; adj[u].set(v); adj[v].set(u); }
    
    for (int v = 1; v <= N && !timeUp; v++) {
        auto cl = greedyClique(v);
        if ((int)cl.size() > bestSize) { bestSize = cl.size(); bestClique = cl; }
    }
    
    // Degeneracy ordering (bucket sort)
    vector<int> deg(N+1), degen;
    vector<bool> rem(N+1, false);
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    int maxDeg = *max_element(deg.begin()+1, deg.begin()+N+1);
    vector<set<int>> buckets(maxDeg+1);
    for (int i = 1; i <= N; i++) buckets[deg[i]].insert(i);
    
    for (int i = 0; i < N; i++) {
        int mv = -1;
        for (int d = 0; d <= maxDeg; d++) {
            if (!buckets[d].empty()) { mv = *buckets[d].begin(); buckets[d].erase(buckets[d].begin()); break; }
        }
        degen.push_back(mv); rem[mv] = true;
        for (int v = (int)adj[mv]._Find_first(); v <= N; v = (int)adj[mv]._Find_next(v)) {
            if (!rem[v]) {
                buckets[deg[v]].erase(v);
                deg[v]--;
                buckets[deg[v]].insert(v);
            }
        }
    }
    
    for (int idx = N - 1; idx >= 0 && !timeUp; idx--) {
        int v = degen[idx];
        bitset<MAXN> P;
        int pc = 0;
        for (int j = idx + 1; j < N; j++)
            if (adj[v].test(degen[j])) { P.set(degen[j]); pc++; }
        if (pc + 1 <= bestSize) continue;
        cliqueLevel = 1; clique[0] = v;
        expand(P, pc);
        if ((callCount & 255) == 0) checkTime();
    }
    
    vector<bool> inC(N + 1, false);
    for (int v : bestClique) inC[v] = true;
    for (int i = 1; i <= N; i++) cout << (inC[i] ? 1 : 0) << "\n";
}
