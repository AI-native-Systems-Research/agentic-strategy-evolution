#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1002;
bitset<MAXN> adj[MAXN];
int N, M;
vector<int> bestClique;
int bestSize = 0;
chrono::steady_clock::time_point startTime;

inline int elapsed_ms() {
    return (int)chrono::duration_cast<chrono::milliseconds>(
        chrono::steady_clock::now() - startTime).count();
}

int timeLimitMs = 1900;
bool timeUp = false;

// Greedy coloring on subset given as vector, returns upper bound
int greedyColor(const vector<int>& P, vector<int>& order) {
    int np = P.size();
    vector<int> color(np, 0);
    int maxColor = 0;
    
    for (int i = 0; i < np; i++) {
        bitset<MAXN> used;
        for (int j = 0; j < i; j++) {
            if (adj[P[i]].test(P[j])) used.set(color[j]);
        }
        int c = 1;
        while (used.test(c)) c++;
        color[i] = c;
        if (c > maxColor) maxColor = c;
    }
    
    // Sort by color for branching order
    vector<pair<int,int>> cv(np);
    for (int i = 0; i < np; i++) cv[i] = {color[i], P[i]};
    sort(cv.begin(), cv.end());
    order.resize(np);
    for (int i = 0; i < np; i++) order[i] = cv[i].second;
    // Return colors in same order
    // We need color info for pruning - store in order
    return maxColor;
}

vector<int> colorBuf;

void expand(vector<int>& clique, vector<int>& P) {
    if (timeUp) return;
    if (elapsed_ms() > timeLimitMs) { timeUp = true; return; }
    
    if (P.empty()) {
        if ((int)clique.size() > bestSize) {
            bestSize = clique.size();
            bestClique = clique;
        }
        return;
    }
    
    int np = P.size();
    // Greedy coloring for upper bound
    vector<int> color(np);
    int maxColor = 0;
    
    for (int i = 0; i < np; i++) {
        int used[1002]; // small enough
        int nu = 0;
        for (int j = 0; j < i; j++) {
            if (adj[P[i]].test(P[j])) used[nu++] = color[j];
        }
        sort(used, used + nu);
        int c = 1;
        for (int k = 0; k < nu; k++) {
            if (used[k] == c) c++;
            else if (used[k] > c) break;
        }
        color[i] = c;
        if (c > maxColor) maxColor = c;
    }
    
    if ((int)clique.size() + maxColor <= bestSize) return;
    
    // Sort by color
    vector<pair<int,int>> cv(np);
    for (int i = 0; i < np; i++) cv[i] = {color[i], P[i]};
    sort(cv.begin(), cv.end());
    
    for (int i = np - 1; i >= 0; i--) {
        if (timeUp) return;
        if ((int)clique.size() + cv[i].first <= bestSize) return;
        
        int v = cv[i].second;
        clique.push_back(v);
        
        vector<int> newP;
        newP.reserve(i);
        for (int j = 0; j < i; j++) {
            if (adj[v].test(cv[j].second)) newP.push_back(cv[j].second);
        }
        
        expand(clique, newP);
        clique.pop_back();
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    startTime = chrono::steady_clock::now();
    
    cin >> N >> M;
    for (int i = 0; i < M; i++) {
        int u, v; cin >> u >> v;
        adj[u].set(v); adj[v].set(u);
    }
    
    // Degeneracy ordering
    vector<int> degOrder;
    {
        vector<int> d(N+1);
        for (int i = 1; i <= N; i++) d[i] = (int)adj[i].count();
        vector<bool> rem(N+1, false);
        for (int it = 0; it < N; it++) {
            int best = -1, bd = N+1;
            for (int i = 1; i <= N; i++) if (!rem[i] && d[i] < bd) { bd = d[i]; best = i; }
            rem[best] = true; degOrder.push_back(best);
            for (int j = 1; j <= N; j++) if (!rem[j] && adj[best].test(j)) d[j]--;
        }
        reverse(degOrder.begin(), degOrder.end());
    }
    
    mt19937 rng(42);
    
    // Greedy from every vertex with multiple strategies
    for (int i = 1; i <= N; i++) {
        vector<int> cands;
        for (int j = 1; j <= N; j++) if (j != i && adj[i].test(j)) cands.push_back(j);
        
        // Strategy 1: by connectivity to current clique neighborhood
        bitset<MAXN> cn = adj[i];
        sort(cands.begin(), cands.end(), [&](int a, int b){
            return (adj[a]&cn).count() > (adj[b]&cn).count();
        });
        vector<int> clique = {i};
        for (int v : cands) {
            if (cn.test(v)) { clique.push_back(v); cn &= adj[v]; }
        }
        if ((int)clique.size() > bestSize) { bestSize = clique.size(); bestClique = clique; }
        
        // Strategy 2: by degree
        sort(cands.begin(), cands.end(), [&](int a, int b){
            return adj[a].count() > adj[b].count();
        });
        cn = adj[i];
        clique = {i};
        for (int v : cands) {
            if (cn.test(v)) { clique.push_back(v); cn &= adj[v]; }
        }
        if ((int)clique.size() > bestSize) { bestSize = clique.size(); bestClique = clique; }
    }
    
    // Local search: plateau-based with tabu
    {
        auto doLocalSearch = [&](int maxMs) {
            // Start from best clique, try improve
            vector<int> clique = bestClique;
            set<int> cliqueSet(clique.begin(), clique.end());
            
            // Compute tightness: for each vertex, how many clique members it's adjacent to
            vector<int> tight(N+1, 0);
            for (int v = 1; v <= N; v++) {
                for (int u : clique) {
                    if (adj[v].test(u)) tight[v]++;
                }
            }
            
            unordered_map<int, int> tabu; // vertex -> iteration until tabu expires
            int iter = 0;
            
            while (elapsed_ms() < maxMs) {
                iter++;
                int cs = clique.size();
                
                // Try ADD: find vertex not in clique adjacent to all clique members
                {
                    int bestV = -1;
                    int bestDeg = -1;
                    for (int v = 1; v <= N; v++) {
                        if (cliqueSet.count(v)) continue;
                        if (tight[v] == cs) {
                            auto it = tabu.find(v);
                            if (it != tabu.end() && it->second > iter && cs + 1 <= bestSize) continue;
                            int d = adj[v].count();
                            if (d > bestDeg) { bestDeg = d; bestV = v; }
                        }
                    }
                    if (bestV != -1) {
                        clique.push_back(bestV);
                        cliqueSet.insert(bestV);
                        for (int u = 1; u <= N; u++) {
                            if (adj[bestV].test(u)) tight[u]++;
                        }
                        cs++;
                        if (cs > bestSize) { bestSize = cs; bestClique = clique; }
                        continue;
                    }
                }
                
                // SWAP: remove one vertex, add one or two
                // Find vertex in clique with minimum degree within clique's neighborhood potential
                {
                    bool improved = false;
                    // Try swap1: remove u, add v where tight[v] == cs-1 and !adj[u][v]
                    vector<int> perm(clique);
                    shuffle(perm.begin(), perm.end(), rng);
                    
                    for (int u : perm) {
                        if (elapsed_ms() > maxMs) break;
                        // Candidates: vertices v not in clique where tight[v] == cs-1 and the only missing neighbor is u
                        vector<int> addCands;
                        for (int v = 1; v <= N; v++) {
                            if (cliqueSet.count(v)) continue;
                            if (tight[v] == cs - 1 && !adj[v].test(u)) {
                                auto it = tabu.find(v);
                                if (it != tabu.end() && it->second > iter && cs <= bestSize) continue;
                                addCands.push_back(v);
                            }
                        }
                        if (addCands.empty()) continue;
                        
                        // Check if any pair in addCands are mutually adjacent (swap1->+1)
                        bool found2 = false;
                        if (addCands.size() >= 2 && cs + 1 > bestSize - 1) {
                            for (int a = 0; a < min((int)addCands.size(), 50); a++) {
                                for (int b = a+1; b < min((int)addCands.size(), 50); b++) {
                                    if (adj[addCands[a]].test(addCands[b])) {
                                        // Remove u, add addCands[a] and addCands[b]
                                        cliqueSet.erase(u);
                                        for (int w = 1; w <= N; w++) if (adj[u].test(w)) tight[w]--;
                                        auto it2 = std::find(clique.begin(), clique.end(), u);
                                        clique.erase(it2);
                                        
                                        int va = addCands[a], vb = addCands[b];
                                        clique.push_back(va); cliqueSet.insert(va);
                                        for (int w = 1; w <= N; w++) if (adj[va].test(w)) tight[w]++;
                                        clique.push_back(vb); cliqueSet.insert(vb);
                                        for (int w = 1; w <= N; w++) if (adj[vb].test(w)) tight[w]++;
                                        
                                        tabu[u] = iter + cs + 2;
                                        cs = clique.size();
                                        if (cs > bestSize) { bestSize = cs; bestClique = clique; }
                                        found2 = true;
                                        improved = true;
                                        break;
                                    }
                                }
                                if (found2) break;
                            }
                        }
                        if (found2) break;
                        
                        // Plateau move: swap u for random candidate
                        if (!addCands.empty()) {
                            int v = addCands[rng() % addCands.size()];
                            cliqueSet.erase(u);
                            for (int w = 1; w <= N; w++) if (adj[u].test(w)) tight[w]--;
                            auto it2 = std::find(clique.begin(), clique.end(), u);
                            clique.erase(it2);
                            
                            clique.push_back(v); cliqueSet.insert(v);
                            for (int w = 1; w <= N; w++) if (adj[v].test(w)) tight[w]++;
                            
                            tabu[u] = iter + cs + 2;
                            improved = true;
                            break;
                        }
                    }
                    if (!improved) {
                        // Perturb: remove random vertex
                        if (!clique.empty()) {
                            int idx = rng() % clique.size();
                            int u = clique[idx];
                            cliqueSet.erase(u);
                            for (int w = 1; w <= N; w++) if (adj[u].test(w)) tight[w]--;
                            clique.erase(clique.begin() + idx);
                            tabu[u] = iter + cs + 5;
                        }
                    }
                }
            }
        };
        
        doLocalSearch(800);
    }
    
    // BnB with degeneracy ordering
    timeUp = false;
    for (int idx = 0; idx < N && !timeUp && elapsed_ms() < timeLimitMs; idx++) {
        int v = degOrder[idx];
        vector<int> cand;
        for (int j = idx+1; j < N; j++) if (adj[v].test(degOrder[j])) cand.push_back(degOrder[j]);
        if ((int)cand.size() + 1 <= bestSize) continue;
        bitset<MAXN> cBS; for (int u : cand) cBS.set(u);
        sort(cand.begin(), cand.end(), [&](int a, int b){ return (adj[a]&cBS).count() < (adj[b]&cBS).count(); });
        vector<int> cl = {v};
        expand(cl, cand);
    }
    
    vector<bool> inC(N+1, false);
    for (int v : bestClique) inC[v] = true;
    for (int i = 1; i <= N; i++) cout << (inC[i] ? 1 : 0) << "\n";
}
