#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n, m;
    cin >> n >> m;

    vector<vector<int>> adj(n);
    vector<pair<int,int>> edges;
    edges.reserve(m);
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v;
        u--; v--;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges.emplace_back(u, v);
    }

    if(m == 0){
        for(int i = 0; i < n; i++){
            if(i) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }

    mt19937 rng(chrono::steady_clock::now().time_since_epoch().count());

    auto computeCut = [&](const vector<int>& s) {
        int c = 0;
        for(auto& e : edges)
            if(s[e.first] != s[e.second]) c++;
        return c;
    };

    vector<int> bestSide(n, 0);
    int bestCut = -1;

    auto startTime = chrono::steady_clock::now();
    double timeLimit = 0.90;

    // Simulated annealing with restarts
    while(chrono::duration<double>(chrono::steady_clock::now() - startTime).count() < timeLimit){
        vector<int> s(n);
        for(int i = 0; i < n; i++) s[i] = rng() & 1;

        // Compute gain for each vertex (how much cut increases if flipped)
        vector<int> gain(n);
        for(int u = 0; u < n; u++)
            for(int v : adj[u])
                gain[u] += (s[u] == s[v]) ? 1 : -1;

        int cut = computeCut(s);

        // Greedy local search first
        {
            bool improved = true;
            while(improved){
                improved = false;
                for(int u = 0; u < n; u++){
                    if(gain[u] > 0){
                        s[u] ^= 1;
                        cut += gain[u];
                        gain[u] = -gain[u];
                        for(int v : adj[u]){
                            if(s[u] == s[v]) gain[v] += 2;
                            else gain[v] -= 2;
                        }
                        improved = true;
                    }
                }
            }
        }

        // SA phase
        double T = 2.0;
        double cooling = 0.9995;
        uniform_int_distribution<int> dist(0, n-1);
        uniform_real_distribution<double> prob(0.0, 1.0);

        for(int iter = 0; iter < 200000; iter++){
            if(T < 0.01) break;
            double elapsed = chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
            if(elapsed >= timeLimit) break;

            int u = dist(rng);
            int g = gain[u];
            if(g > 0 || prob(rng) < exp((double)g / T)){
                s[u] ^= 1;
                cut += g;
                gain[u] = -g;
                for(int v : adj[u]){
                    if(s[u] == s[v]) gain[v] += 2;
                    else gain[v] -= 2;
                }
            }
            T *= cooling;
        }

        if(cut > bestCut){
            bestCut = cut;
            bestSide = s;
        }
    }

    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << bestSide[i];
    }
    cout << '\n';
    return 0;
}
