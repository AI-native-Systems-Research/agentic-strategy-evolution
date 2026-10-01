#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 1001;

bitset<MAXN> adj[MAXN];
int N, M;
int bestSize;
vector<int> bestClique;
vector<int> currentClique;
chrono::steady_clock::time_point startTime;
bool timeLimitReached;

inline long long elapsed_ms() {
    return chrono::duration_cast<chrono::milliseconds>(
        chrono::steady_clock::now() - startTime).count();
}

// Greedy coloring on subset P, returns number of colors and assigns colors
int greedyColor(const vector<int>& P, vector<int>& color) {
    int np = P.size();
    color.resize(np);
    int numColors = 0;
    
    // For each vertex, find smallest color not used by non-adjacent vertices in P
    // Use bitset for efficiency
    vector<bitset<MAXN>> colorClass; // colorClass[c] = set of vertices with color c
    
    for (int i = 0; i < np; i++) {
        int v = P[i];
        // Find first color class where v is adjacent to all members
        // Equivalently, find first color where no non-neighbor exists
        int c = -1;
        for (int j = 0; j < numColors; j++) {
            // Check if v is adjacent to all vertices in colorClass[j]
            // colorClass[j] should be a subset of adj[v]
            // i.e., colorClass[j] & ~adj[v] == 0
            if ((colorClass[j] & ~adj[v]).none()) {
                // Wait, this is independent set coloring for complement = clique coloring
                // No. Greedy coloring for the ORIGINAL graph gives chromatic number upper bound on clique.
                // We need: color c is valid if v is NOT adjacent to any vertex with color c
                // i.e., v has no neighbor with that color → colorClass[j] & adj[v] == 0? No.
                // Standard graph coloring: two adjacent vertices must have different colors.
                // χ(G) ≥ ω(G), so coloring the graph gives upper bound on clique.
                // For color c to be usable: no vertex in colorClass[c] is adjacent to v.
                // (colorClass[j] & adj[v]).none()
                break;
            }
        }
        // Redo: standard graph coloring
        // Find smallest color not used by any neighbor of v in P
        // A color c is "used" if some neighbor of v has that color
        // So find first c where colorClass[c] & adj[v] is empty... NO
        // colorClass[c] has vertices with color c. If any of them is adjacent to v, can't use c.
        c = -1;
        for (int j = 0; j < numColors; j++) {
            bitset<MAXN>& cc = colorClass[j];
            if ((cc & adj[v]).none()) {
                c = j;
                break;
            }
        }
        if (c == -1) {
            c = numColors++;
            colorClass.push_back(bitset<MAXN>());
        }
        colorClass[c].set(v);
        color[i] = c + 1; // 1-indexed
    }
    return numColors;
}

void expand(vector<int>& P) {
    if (timeLimitReached) return;
    
    if (P.empty()) {
        if ((int)currentClique.size() > bestSize) {
            bestSize = currentClique.size();
            bestClique = currentClique;
        }
        return;
    }
    
    vector<int> color;
    int numColors = greedyColor(P, color);
    
    if ((int)currentClique.size() + numColors <= bestSize) return;
    
    // Sort by color
    vector<pair<int,int>> cv(P.size());
    for (int i = 0; i < (int)P.size(); i++) cv[i] = {color[i], P[i]};
    sort(cv.begin(), cv.end());
    
    for (int i = (int)cv.size() - 1; i >= 0; i--) {
        if (timeLimitReached) return;
        if (elapsed_ms() > 1850) { timeLimitReached = true; return; }
        
        if ((int)currentClique.size() + cv[i].first <= bestSize) return;
        
        int v = cv[i].second;
        
        vector<int> newP;
        for (int j = 0; j < i; j++) {
            if (adj[v].test(cv[j].second)) {
                newP.push_back(cv[j].second);
            }
        }
        
        currentClique.push_back(v);
        expand(newP);
        currentClique.pop_back();
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    startTime = chrono::steady_clock::now();
    timeLimitReached = false;
    
    cin >> N >> M;
    for (int i = 0; i < M; i++) {
        int u, v; cin >> u >> v;
        adj[u].set(v); adj[v].set(u);
    }
    
    // Degeneracy ordering
    vector<int> deg(N + 1);
    for (int i = 1; i <= N; i++) deg[i] = (int)adj[i].count();
    
    vector<bool> removed(N + 1, false);
    vector<int> order;
    // Use bucket queue
    int maxDeg = *max_element(deg.begin()+1, deg.begin()+N+1);
    vector<set<int>> buckets(maxDeg + 1);
    for (int i = 1; i <= N; i++) buckets[deg[i]].insert(i);
    
    for (int iter = 0; iter < N; iter++) {
        int best = -1;
        for (int d = 0; d <= maxDeg; d++) {
            while (!buckets[d].empty()) {
                int v = *buckets[d].begin();
                if (removed[v] || deg[v] != d) { buckets[d].erase(buckets[d].begin()); continue; }
                best = v; break;
            }
            if (best != -1) break;
        }
        removed[best] = true;
        buckets[deg[best]].erase(best);
        order.push_back(best);
        for (int j = 1; j <= N; j++) {
            if (!removed[j] && adj[best].test(j)) {
                buckets[deg[j]].erase(j);
                deg[j]--;
                buckets[deg[j]].insert(j);
            }
        }
    }
    
    // Initial greedy clique
    bestSize = 0;
    {
        vector<int> sorted_v(order.rbegin(), order.rend());
        vector<int> clique;
        bitset<MAXN> cliqueAdj; cliqueAdj.set(); // all bits set initially
        for (int v : sorted_v) {
            if (cliqueAdj.test(v)) {
                clique.push_back(v);
                cliqueAdj &= adj[v];
                cliqueAdj.set(v);
            }
        }
        if ((int)clique.size() > bestSize) {
            bestSize = clique.size();
            bestClique = clique;
        }
    }
    
    // Branch and bound in reverse degeneracy order
    for (int idx = N - 1; idx >= 0; idx--) {
        if (timeLimitReached) break;
        int v = order[idx];
        vector<int> P;
        for (int j = idx + 1; j < N; j++) {
            if (adj[v].test(order[j])) P.push_back(order[j]);
        }
        if ((int)P.size() + 1 <= bestSize) continue;
        currentClique.clear();
        currentClique.push_back(v);
        expand(P);
    }
    
    vector<int> inClique(N + 1, 0);
    for (int v : bestClique) inClique[v] = 1;
    for (int i = 1; i <= N; i++) cout << inClique[i] << "\n";
    return 0;
}
