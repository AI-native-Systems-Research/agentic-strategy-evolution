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

    auto start_time = chrono::steady_clock::now();
    auto elapsed_ms = [&]() -> double {
        auto now = chrono::steady_clock::now();
        return chrono::duration<double, milli>(now - start_time).count();
    };

    double TIME_LIMIT = 1800.0; // 1.8 seconds to be safe

    mt19937 rng(42);

    int global_best_cut = -1;
    vector<int> global_best_side;

    while(elapsed_ms() < TIME_LIMIT) {
        // Random init
        vector<int> side(n + 1);
        for(int i = 1; i <= n; i++) side[i] = rng() % 2;

        // gain[v] = improvement in cut if we flip v
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

        // Greedy local search
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    side[v] ^= 1;
                    cut += gain[v];
                    gain[v] = -gain[v];
                    for(int w : adj[v]){
                        if(side[v] == side[w]) gain[w] += 2;
                        else gain[w] -= 2;
                    }
                    improved = true;
                }
            }
        }

        int best_cut = cut;
        vector<int> best_side = side;

        // SA phase
        double T = 1.0;
        uniform_real_distribution<double> unif(0.0, 1.0);
        int iter = 0;
        double remaining = TIME_LIMIT - elapsed_ms();
        double sa_limit = min(remaining * 0.8, 200.0); // SA budget per restart
        auto sa_start = chrono::steady_clock::now();

        while(true){
            if(iter % 1000 == 0){
                double sa_elapsed = chrono::duration<double, milli>(
                    chrono::steady_clock::now() - sa_start).count();
                if(sa_elapsed > sa_limit) break;
                // Cool based on fraction of time used
                T = 1.0 * (1.0 - sa_elapsed / sa_limit);
                if(T < 0.01) T = 0.01;
            }

            int v = (rng() % n) + 1;
            int g = gain[v];

            if(g > 0 || (T > 0.01 && unif(rng) < exp((double)g / T))){
                side[v] ^= 1;
                cut += g;
                gain[v] = -g;
                for(int w : adj[v]){
                    if(side[v] == side[w]) gain[w] += 2;
                    else gain[w] -= 2;
                }
                if(cut > best_cut){
                    best_cut = cut;
                    best_side = side;
                }
            }
            iter++;
        }

        if(best_cut > global_best_cut){
            global_best_cut = best_cut;
            global_best_side = best_side;
        }
    }

    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << global_best_side[i];
    }
    cout << '\n';

    return 0;
}
