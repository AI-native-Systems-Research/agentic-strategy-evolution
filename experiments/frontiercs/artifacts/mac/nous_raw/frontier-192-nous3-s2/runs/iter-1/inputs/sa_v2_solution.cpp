#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n, m;
    cin >> n >> m;

    vector<vector<int>> adj(n + 1);
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
    }

    if(m == 0){
        for(int i = 1; i <= n; i++){
            if(i > 1) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }

    mt19937 rng(12345);

    auto run_sa = [&](unsigned seed) -> pair<int, vector<int>> {
        mt19937 gen(seed);
        vector<int> side(n + 1);
        for(int i = 1; i <= n; i++) side[i] = gen() % 2;

        // gain[v] = improvement in cut if we flip v
        // = (edges to same side) - (edges to opposite side)
        vector<int> gain(n + 1, 0);
        int cut = 0;
        for(int u = 1; u <= n; u++){
            for(int v : adj[u]){
                if(side[u] == side[v]) gain[u]++;
                else gain[u]--;
            }
        }
        for(int u = 1; u <= n; u++){
            for(int v : adj[u]){
                if(side[u] != side[v]) cut++;
            }
        }
        cut /= 2;

        int best_cut = cut;
        vector<int> best_side = side;

        // Greedy local search first
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    // Flip v
                    side[v] ^= 1;
                    cut += gain[v];
                    gain[v] = -gain[v];
                    for(int w : adj[v]){
                        if(side[v] == side[w]){
                            gain[w] += 2;
                        } else {
                            gain[w] -= 2;
                        }
                    }
                    improved = true;
                    if(cut > best_cut){
                        best_cut = cut;
                        best_side = side;
                    }
                }
            }
        }

        // Simulated annealing from local optimum
        double T = 1.5;
        double T_min = 0.01;
        int max_steps = 2000000;
        double alpha = exp(log(T_min / T) / max_steps);

        uniform_real_distribution<double> unif(0.0, 1.0);

        for(int step = 0; step < max_steps; step++){
            int v = (gen() % n) + 1;
            int g = gain[v];

            if(g > 0 || unif(gen) < exp((double)g / T)){
                side[v] ^= 1;
                cut += g;
                gain[v] = -g;
                for(int w : adj[v]){
                    if(side[v] == side[w]){
                        gain[w] += 2;
                    } else {
                        gain[w] -= 2;
                    }
                }
                if(cut > best_cut){
                    best_cut = cut;
                    best_side = side;
                }
            }

            T *= alpha;
        }

        return {best_cut, best_side};
    };

    // Multi-start
    int best_cut = -1;
    vector<int> best_side;

    for(int restart = 0; restart < 20; restart++){
        auto [c, s] = run_sa(rng());
        if(c > best_cut){
            best_cut = c;
            best_side = s;
        }
    }

    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << best_side[i];
    }
    cout << '\n';

    return 0;
}
