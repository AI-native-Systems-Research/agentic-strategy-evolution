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

// Greedy coloring on candidates, returns upper bound
int greedyColor(vector<int>& cands, bitset<MAXN>& P, vector<int>& colorClass, vector<int>& colorOf) {
    int nc = (int)cands.size();
    int maxColor = 0;
    colorOf.resize(nc);
    colorClass.clear();
    
    // Color assignment
    vector<vector<int>> classes;
    for (int i = 0; i < nc; i++) {
        int v = cands[i];
        int c = -1;
        for (int j = 0; j < (int)classes.size(); j++) {
            bool fits = true;
            for (int u : classes[j]) {
                if (adj[v].test(u)) { fits = false; break; }
            }
            if (fits) { c = j; break; }
        }
        if (c == -1) {
            c = (int)classes.size();
            classes.push_back({});
        }
        classes[c].push_back(v);
        colorOf[i] = c + 1;
    }
    maxColor = (int)classes.size();
    
    // Reorder candidates by color (ascending) for better pruning
    vector<pair<int,int>> cv(nc);
    for (int i = 0; i < nc; i++) cv[i] = {colorOf[i], cands[i]};
    sort(cv.begin(), cv.end());
    for (int i = 0; i < nc; i++) {
        cands[i] = cv[i].second;
        colorOf[i] = cv[i].first;
    }
    
    return maxColor;
}

void expand(vector<int>& clique, bitset<MAXN>& P, int pSize) {
    if (timeUp) return;
    if (elapsed_ms() > timeLimitMs - 50) { timeUp = true; return; }
    
    if (pSize == 0) {
        if ((int)clique.size() > bestSize) {
            bestSize = (int)clique.size();
            bestClique = clique;
        }
        return;
    }
    
    if ((int)clique.size() + pSize <= bestSize) return;
    
    // Extract candidates sorted by degree in subgraph (ascending = process low degree first, high degree last)
    vector<int> cands;
    cands.reserve(pSize);
    for (int v = (int)P._Find_first(); v <= N; v = (int)P._Find_next(v))
        cands.push_back(v);
    
    int nc = (int)cands.size();
    
    // Sort by subgraph degree ascending
    sort(cands.begin(), cands.end(), [&](int a, int b){
        return (int)(adj[a] & P).count() < (int)(adj[b] & P).count();
    });
    
    // Greedy coloring for upper bound
    vector<int> colorClass, colorOf;
    int ub = greedyColor(cands, P, colorClass, colorOf);
    
    if ((int)clique.size() + ub <= bestSize) return;
    
    nc = (int)cands.size(); // cands reordered by color
    
    for (int i = nc - 1; i >= 0; i--) {
        if (timeUp) return;
        if ((int)clique.size() + colorOf[i] <= bestSize) return;
        
        int v = cands[i];
        clique.push_back(v);
        P.reset(v);
        
        bitset<MAXN> newP = P & adj[v];
        int newPSize = (int)newP.count();
        
        expand(clique, newP, newPSize);
        clique.pop_back();
    }
    // Restore P
    for (int i = 0; i < nc; i++) P.set(cands[i]);
}

void greedyClique(vector<int>& perm, vector<int>& result) {
    result.clear();
    bitset<MAXN> cn;
    cn.set();
    for (int v : perm) {
        if (cn.test(v)) {
            result.push_back(v);
            cn &= adj[v];
        }
    }
}

void localSearch(int endMs) {
    vector<int> deg(N+1);
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    
    for (int rep = 0; elapsed_ms() < endMs; rep++) {
        vector<int> perm(N);
        iota(perm.begin(), perm.end(), 1);
        
        int strategy = rep % 12;
        if (strategy == 0) {
            shuffle(perm.begin(), perm.end(), rng);
        } else if (strategy == 1) {
            sort(perm.begin(), perm.end(), [&](int a, int b){ return deg[a] > deg[b]; });
        } else if (strategy == 2) {
            sort(perm.begin(), perm.end(), [&](int a, int b){ return deg[a] < deg[b]; });
        } else {
            int noise = 5 + (strategy * 3);
            sort(perm.begin(), perm.end(), [&](int a, int b){
                return deg[a] + (int)(rng() % noise) > deg[b] + (int)(rng() % noise);
            });
        }
        
        vector<int> clique;
        greedyClique(perm, clique);
        int cs = (int)clique.size();
        if (cs > bestSize) { bestSize = cs; bestClique = clique; }
        
        // Tabu local search from this clique
        bitset<MAXN> cBS;
        set<int> cSet(clique.begin(), clique.end());
        for (int v : clique) cBS.set(v);
        
        vector<int> tight(N+1, 0);
        for (int v = 1; v <= N; v++) tight[v] = (int)(adj[v] & cBS).count();
        
        vector<int> tabu(N+1, 0);
        
        for (int iter = 0; iter < 300000 && elapsed_ms() < endMs; iter++) {
            // Try to add a vertex connected to all clique members
            int bestV = -1, bestDeg2 = -1;
            for (int v = 1; v <= N; v++) {
                if (!cSet.count(v) && tight[v] == cs) {
                    if (tabu[v] > iter && cs + 1 <= bestSize) continue;
                    if (deg[v] > bestDeg2) { bestDeg2 = deg[v]; bestV = v; }
                }
            }
            if (bestV != -1) {
                clique.push_back(bestV); cSet.insert(bestV); cBS.set(bestV);
                for (int w = (int)adj[bestV]._Find_first(); w <= N; w = (int)adj[bestV]._Find_next(w)) tight[w]++;
                cs++;
                if (cs > bestSize) { bestSize = cs; bestClique = clique; }
                continue;
            }
            // Swap: remove one, add one
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
    
    // Initial local search
    localSearch(min(400, timeLimitMs / 3));
    
    // Degeneracy ordering for B&B
    timeUp = false;
    vector<int> d(N+1);
    for (int i = 1; i <= N; i++) d[i] = (int)adj[i].count();
    vector<bool> rem(N+1, false);
    vector<int> degen;
    vector<int> dd(d.begin(), d.end());
    for (int i = 0; i < N; i++) {
        int mv = 0, md = N+1;
        for (int v = 1; v <= N; v++) if (!rem[v] && dd[v] < md) { md = dd[v]; mv = v; }
        degen.push_back(mv); rem[mv] = true;
        for (int v = (int)adj[mv]._Find_first(); v <= N; v = (int)adj[mv]._Find_next(v))
            if (!rem[v]) dd[v]--;
    }
    
    for (int idx = N-1; idx >= 0 && !timeUp && elapsed_ms() < timeLimitMs - 300; idx--) {
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
    
    // Use remaining time for more local search
    timeUp = false;
    if (elapsed_ms() < timeLimitMs - 50) localSearch(timeLimitMs - 30);
    
    vector<bool> inC(N+1, false);
    for (int v : bestClique) inC[v] = true;
    for (int i = 1; i <= N; i++) cout << (inC[i] ? 1 : 0) << "\n";
}
