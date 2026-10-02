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

        // Compute initial cut value and per-vertex gain
        // gain[v] = (edges to opposite side) - (edges to same side)
        // flipping v changes cut by gain[v]
        vector<int> gain(n + 1, 0);
        int cut = 0;
        for(int u = 1; u <= n; u++){
            for(int v : adj[u]){
                if(side[u] != side[v]) gain[u]--;
                else gain[u]++;
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

        // Simulated annealing
        double T = 2.0;
        double T_min = 0.001;
        double alpha = 0.9999;
        int steps = 0;
        int max_steps = 5000000;

        uniform_real_distribution<double> unif(0.0, 1.0);

        while(T > T_min && steps < max_steps){
            int v = (gen() % n) + 1;
            int g = gain[v]; // change in cut if we flip v

            if(g > 0 || unif(gen) < exp((double)g / T)){
                // Flip v
                side[v] ^= 1;
                cut += g;
                // Update gains: for each neighbor w of v
                for(int w : adj[v]){
                    if(side[v] == side[w]){
                        // v moved to same side as w: this edge no longer cut
                        gain[w]++;  // flipping w would now cut this edge
                        gain[v]--;  // wait, we need to recalc gain[v] too
                    } else {
                        // v moved to opposite side of w: this edge now cut
                        gain[w]--;
                        gain[v]++;
                    }
                }
                // Actually, let's just recalculate gain[v] after flip
                // The loop above correctly updates gain[w] for neighbors
                // but gain[v] needs full recalc
                gain[v] = 0;
                for(int w : adj[v]){
                    if(side[v] != side[w]) gain[v]--;
                    else gain[v]++;
                }

                if(cut > best_cut){
                    best_cut = cut;
                    best_side = side;
                }
            }

            T *= alpha;
            steps++;
        }

        return {best_cut, best_side};
    };

    // Multi-start SA
    int best_cut = -1;
    vector<int> best_side;

    for(int restart = 0; restart < 10; restart++){
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
