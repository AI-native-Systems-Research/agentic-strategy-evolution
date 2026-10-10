#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1001;
bitset<MAXN> adj[MAXN];
int N, M;
int bestSize;
vector<int> bestClique;
chrono::steady_clock::time_point startTime;

inline int elapsed_ms() {
    return (int)chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - startTime).count();
}

mt19937 rng(12345);

bool isClique(const vector<int>& clique) {
    for (int i = 0; i < (int)clique.size(); i++)
        for (int j = i+1; j < (int)clique.size(); j++)
            if (!adj[clique[i]].test(clique[j])) return false;
    return true;
}

void updateBest(const vector<int>& clique) {
    if ((int)clique.size() > bestSize && isClique(clique)) {
        bestSize = clique.size();
        bestClique = clique;
    }
}

vector<int> curClique;
bool timeUp;

// Enhanced coloring bound with reordering
int colorBound(bitset<MAXN>& P, vector<pair<int,int>>& colored) {
    colored.clear();
    if (P.none()) return 0;
    
    // Collect vertices, sort by degree in subgraph (descending) for better coloring
    vector<int> verts;
    for (int v = P._Find_first(); v < MAXN; v = P._Find_next(v))
        verts.push_back(v);
    
    // Sort by number of neighbors in P (ascending = greedy sequential coloring works better)
    sort(verts.begin(), verts.end(), [&](int a, int b){
        return (adj[a] & P).count() < (adj[b] & P).count();
    });
    
    static bitset<MAXN> colorClass[MAXN+1];
    int maxColor = 0;
    
    for (int v : verts) {
        int c = 1;
        while (c <= maxColor && (adj[v] & colorClass[c]).any()) c++;
        if (c > maxColor) { maxColor = c; colorClass[c].reset(); }
        colorClass[c].set(v);
        colored.push_back({c, v});
    }
    
    for (auto& [c, v] : colored) colorClass[c].reset(v);
    
    sort(colored.begin(), colored.end());
    return maxColor;
}

void bnb(bitset<MAXN>& P, int depth) {
    if (timeUp) return;
    
    if (P.none()) {
        if (depth > bestSize) {
            bestSize = depth;
            bestClique = curClique;
        }
        return;
    }
    
    vector<pair<int,int>> colored;
    int ub = colorBound(P, colored);
    
    if (depth + ub <= bestSize) return;
    
    for (int i = (int)colored.size() - 1; i >= 0; i--) {
        if (timeUp) return;
        if (depth + colored[i].first <= bestSize) return;
        
        int v = colored[i].second;
        curClique.push_back(v);
        
        bitset<MAXN> newP = P & adj[v];
        P.reset(v);
        
        bnb(newP, depth + 1);
        curClique.pop_back();
        
        if ((i & 7) == 0 && elapsed_ms() > 1850) { timeUp = true; return; }
    }
}

vector<int> greedyClique(vector<int> order) {
    bitset<MAXN> cliqueSet;
    vector<int> clique;
    for (int v : order) {
        bitset<MAXN> tmp = cliqueSet & ~adj[v];
        if (tmp.none()) {
            clique.push_back(v);
            cliqueSet.set(v);
        }
    }
    return clique;
}

// Local search: try to improve a clique by swap (drop one, add two)
vector<int> localSearch(vector<int> clique, int maxIter) {
    bitset<MAXN> inClique;
    for (int v : clique) inClique.set(v);
    
    auto cliqueAdj = [&](int v) -> int {
        return (int)(adj[v] & inClique).count();
    };
    
    for (int iter = 0; iter < maxIter && elapsed_ms() < 1800; iter++) {
        bool improved = false;
        
        // Try adding a vertex
        for (int v = 1; v <= N; v++) {
            if (inClique.test(v)) continue;
            if (cliqueAdj(v) == (int)clique.size()) {
                clique.push_back(v);
                inClique.set(v);
                improved = true;
            }
        }
        if (improved) continue;
        
        // Try swap: remove one vertex, add two
        int sz = clique.size();
        for (int di = 0; di < sz && !improved; di++) {
            int drop = clique[di];
            inClique.reset(drop);
            
            // Find vertices connected to all in clique except drop
            bitset<MAXN> cand;
            for (int v = 1; v <= N; v++) {
                if (inClique.test(v) || v == drop) continue;
                if (cliqueAdj(v) == sz - 1) cand.set(v);
            }
            
            // Try to find two vertices in cand that are adjacent
            vector<int> candList;
            for (int v = cand._Find_first(); v < MAXN; v = cand._Find_next(v))
                candList.push_back(v);
            
            bool found = false;
            for (int a = 0; a < (int)candList.size() && !found; a++) {
                for (int b = a+1; b < (int)candList.size() && !found; b++) {
                    if (adj[candList[a]].test(candList[b])) {
                        // swap: remove drop, add candList[a] and candList[b]
                        clique.erase(clique.begin() + di);
                        clique.push_back(candList[a]);
                        clique.push_back(candList[b]);
                        inClique.set(candList[a]);
                        inClique.set(candList[b]);
                        found = true;
                        improved = true;
                    }
                }
            }
            
            if (!found) inClique.set(drop);
        }
        
        if (!improved) break;
    }
    return clique;
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    startTime = chrono::steady_clock::now();
    timeUp = false;
    
    cin >> N >> M;
    for (int i = 0; i < M; i++) {
        int u, v; cin >> u >> v;
        adj[u].set(v); adj[v].set(u);
    }
    
    bestSize = 0;
    
    vector<int> verts(N);
    iota(verts.begin(), verts.end(), 1);
    
    sort(verts.begin(), verts.end(), [](int a, int b){ return adj[a].count() > adj[b].count(); });
    auto gc = greedyClique(verts);
    gc = localSearch(gc, 100);
    updateBest(gc);
    
    for (int t = 0; t < 500 && elapsed_ms() < 400; t++) {
        shuffle(verts.begin(), verts.end(), rng);
        auto c = greedyClique(verts);
        c = localSearch(c, 50);
        updateBest(c);
    }
    
    // Degeneracy ordering for BnB
    vector<int> order;
    order.reserve(N);
    bitset<MAXN> rem;
    for (int i = 1; i <= N; i++) rem.set(i);
    for (int iter = 0; iter < N; iter++) {
        int best = -1, bd = N + 1;
        for (int v = rem._Find_first(); v < MAXN; v = rem._Find_next(v)) {
            int d = (int)(adj[v] & rem).count();
            if (d < bd) { bd = d; best = v; }
        }
        order.push_back(best);
        rem.reset(best);
    }
    
    for (int i = 0; i < N && !timeUp; i++) {
        if (elapsed_ms() > 1850) break;
        int v = order[i];
        bitset<MAXN> Pbits;
        for (int j = i + 1; j < N; j++)
            if (adj[v].test(order[j])) Pbits.set(order[j]);
        
        if ((int)Pbits.count() + 1 <= bestSize) continue;
        
        curClique.clear();
        curClique.push_back(v);
        bnb(Pbits, 1);
    }
    
    vector<int> res(N + 1, 0);
    for (int v : bestClique) res[v] = 1;
    for (int i = 1; i <= N; i++) cout << res[i] << "\n";
}
