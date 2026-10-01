#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1002;
bitset<MAXN> adj[MAXN];
int N, M;
vector<int> bestClique;
int bestSize = 0;
mt19937 rng(12345);
chrono::steady_clock::time_point startTime;

inline int elapsed_ms() {
    return (int)chrono::duration_cast<chrono::milliseconds>(
        chrono::steady_clock::now() - startTime).count();
}

int timeLimitMs = 1900;
bool timeUp = false;

void expand(vector<int>& clique, bitset<MAXN>& P, int pSize) {
    if (timeUp) return;
    if (elapsed_ms() > timeLimitMs) { timeUp = true; return; }
    
    if (pSize == 0) {
        if ((int)clique.size() > bestSize) {
            bestSize = (int)clique.size();
            bestClique = clique;
        }
        return;
    }
    
    // Bound check
    if ((int)clique.size() + pSize <= bestSize) return;
    
    // Extract candidates
    vector<int> cands;
    cands.reserve(pSize);
    for (int v = (int)P._Find_first(); v <= N; v = (int)P._Find_next(v))
        cands.push_back(v);
    
    // Greedy coloring for upper bound
    int nc = (int)cands.size();
    vector<int> color(nc, 0);
    int maxColor = 0;
    
    // Sort candidates by degree in subgraph descending for better coloring
    vector<int> subdeg(nc);
    for (int i = 0; i < nc; i++) {
        subdeg[i] = (int)(adj[cands[i]] & P).count();
    }
    vector<int> order(nc);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int a, int b){ return subdeg[a] > subdeg[b]; });
    
    vector<int> orderedCands(nc);
    for (int i = 0; i < nc; i++) orderedCands[i] = cands[order[i]];
    
    // Color in this order
    for (int i = 0; i < nc; i++) {
        bitset<MAXN> nbrs = adj[orderedCands[i]];
        vector<bool> used(maxColor + 2, false);
        for (int j = 0; j < i; j++) {
            if (nbrs.test(orderedCands[j])) used[color[j]] = true;
        }
        int c = 1;
        while (c <= maxColor + 1 && used[c]) c++;
        color[i] = c;
        if (c > maxColor) maxColor = c;
    }
    
    if ((int)clique.size() + maxColor <= bestSize) return;
    
    // Sort by color ascending for branching
    vector<int> idx2(nc);
    iota(idx2.begin(), idx2.end(), 0);
    sort(idx2.begin(), idx2.end(), [&](int a, int b){ return color[a] < color[b]; });
    
    vector<int> sortedCands(nc), sortedColor(nc);
    for (int i = 0; i < nc; i++) {
        sortedCands[i] = orderedCands[idx2[i]];
        sortedColor[i] = color[idx2[i]];
    }
    
    for (int i = nc - 1; i >= 0; i--) {
        if (timeUp) return;
        if ((int)clique.size() + sortedColor[i] <= bestSize) return;
        
        int v = sortedCands[i];
        clique.push_back(v);
        P.reset(v);
        
        bitset<MAXN> newP = P & adj[v];
        int newPSize = (int)newP.count();
        
        expand(clique, newP, newPSize);
        clique.pop_back();
    }
    for (int i = 0; i < nc; i++) P.set(sortedCands[i]);
}

void greedyClique(vector<int>& perm) {
    vector<int> clique;
    bitset<MAXN> cn;
    cn.set();
    for (int v : perm) {
        if (cn.test(v)) {
            clique.push_back(v);
            cn &= adj[v];
        }
    }
    if ((int)clique.size() > bestSize) {
        bestSize = (int)clique.size();
        bestClique = clique;
    }
}

void localSearch(int endMs) {
    vector<int> deg(N+1);
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    
    for (int rep = 0; elapsed_ms() < endMs; rep++) {
        vector<int> perm(N);
        iota(perm.begin(), perm.end(), 1);
        
        int strategy = rep % 10;
        if (strategy == 0) shuffle(perm.begin(), perm.end(), rng);
        else if (strategy == 1) sort(perm.begin(), perm.end(), [&](int a, int b){ return deg[a] > deg[b]; });
        else if (strategy == 2) sort(perm.begin(), perm.end(), [&](int a, int b){ return deg[a] < deg[b]; });
        else if (strategy == 3) {
            sort(perm.begin(), perm.end(), [&](int a, int b){
                return deg[a] + (int)(rng()%15) > deg[b] + (int)(rng()%15);
            });
        } else {
            shuffle(perm.begin(), perm.end(), rng);
        }
        
        greedyClique(perm);
        
        // Build initial clique
        vector<int> clique;
        bitset<MAXN> cBS;
        bitset<MAXN> cn; cn.set();
        for (int v : perm) {
            if (cn.test(v)) { clique.push_back(v); cBS.set(v); cn &= adj[v]; }
        }
        int cs = (int)clique.size();
        
        // tight[v] = |adj[v] ∩ clique|
        vector<int> tight(N+1, 0);
        for (int v = 1; v <= N; v++) tight[v] = (int)(adj[v] & cBS).count();
        
        set<int> cSet(clique.begin(), clique.end());
        vector<int> tabu(N+1, 0);
        
        int localBest = cs;
        
        for (int iter = 0; iter < 1000000 && elapsed_ms() < endMs; iter++) {
            // Try to add a vertex connected to all clique members
            int bestV = -1, bestDeg = -1;
            for (int v = 1; v <= N; v++) {
                if (!cSet.count(v) && tight[v] == cs) {
                    if (tabu[v] > iter && cs + 1 <= bestSize) continue;
                    int d = deg[v];
                    if (d > bestDeg) { bestDeg = d; bestV = v; }
                }
            }
            if (bestV != -1) {
                clique.push_back(bestV); cSet.insert(bestV); cBS.set(bestV);
                for (int w = (int)adj[bestV]._Find_first(); w <= N; w = (int)adj[bestV]._Find_next(w)) tight[w]++;
                cs++;
                if (cs > bestSize) { bestSize = cs; bestClique = clique; }
                localBest = max(localBest, cs);
                continue;
            }
            // Swap: remove u, add v
            vector<int> cp(clique);
            shuffle(cp.begin(), cp.end(), rng);
            bool did = false;
            for (int u : cp) {
                vector<int> addC;
                for (int v = 1; v <= N; v++) {
                    if (!cSet.count(v) && tight[v] == cs - 1 && !adj[v].test(u)) {
                        if (tabu[v] <= iter || cs > bestSize) addC.push_back(v);
                    }
                }
                if (addC.empty()) continue;
                int v = addC[rng() % addC.size()];
                cSet.erase(u); cBS.reset(u);
                for (int w = (int)adj[u]._Find_first(); w <= N; w = (int)adj[u]._Find_next(w)) tight[w]--;
                clique.erase(find(clique.begin(), clique.end(), u));
                clique.push_back(v); cSet.insert(v); cBS.set(v);
                for (int w = (int)adj[v]._Find_first(); w <= N; w = (int)adj[v]._Find_next(w)) tight[w]++;
                tabu[u] = iter + cs + (int)(rng() % 10) + 2;
                cs = (int)clique.size(); did = true; break;
            }
            if (!did && !clique.empty()) {
                int i2 = rng() % clique.size(); int u = clique[i2];
                cSet.erase(u); cBS.reset(u);
                for (int w = (int)adj[u]._Find_first(); w <= N; w = (int)adj[u]._Find_next(w)) tight[w]--;
                clique.erase(clique.begin() + i2);
                tabu[u] = iter + cs + (int)(rng() % 5) + 3; cs = (int)clique.size();
            }
        }
    }
}

int main(){
    ios::sync_with_stdio(false); cin.tie(nullptr);
    startTime = chrono::steady_clock::now();
    cin >> N >> M;
    for (int i = 0; i < M; i++) { int u,v; cin >> u >> v; adj[u].set(v); adj[v].set(u); }
    
    // Initial greedy + local search
    localSearch(min(500, timeLimitMs));
    
    // BnB with degeneracy ordering
    timeUp = false;
    vector<int> deg(N+1);
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    vector<bool> rem(N+1, false);
    vector<int> degen;
    vector<int> d(N+1);
    for (int i = 1; i <= N; i++) d[i] = deg[i];
    for (int i = 0; i < N; i++) {
        int mv = 0, md = N+1;
        for (int v = 1; v <= N; v++) if (!rem[v] && d[v] < md) { md = d[v]; mv = v; }
        degen.push_back(mv); rem[mv] = true;
        for (int v = (int)adj[mv]._Find_first(); v <= N; v = (int)adj[mv]._Find_next(v))
            if (!rem[v]) d[v]--;
    }
    
    for (int idx = N-1; idx >= 0 && !timeUp && elapsed_ms() < timeLimitMs - 200; idx--) {
        int v = degen[idx];
        bitset<MAXN> P;
        int pSize = 0;
        for (int j = idx+1; j < N; j++) {
            if (adj[v].test(degen[j])) { P.set(degen[j]); pSize++; }
        }
        if (pSize + 1 <= bestSize) continue;
        vector<int> cl = {v};
        expand(cl, P, pSize);
    }
    
    // Fill remaining time with local search
    timeUp = false;
    if (elapsed_ms() < timeLimitMs - 50) localSearch(timeLimitMs - 30);
    
    vector<bool> inC(N+1, false);
    for (int v : bestClique) inC[v] = true;
    for (int i = 1; i <= N; i++) cout << (inC[i] ? 1 : 0) << "\n";
}
