#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n, m;
    cin >> n >> m;

    vector<int> deg(n + 1, 0);
    vector<pair<int,int>> edges(m);
    for(int i = 0; i < m; i++){
        int u, v;
        cin >> u >> v;
        edges[i] = {u, v};
        deg[u]++; deg[v]++;
    }
    vector<int> pos(n + 2, 0);
    for(int i = 1; i <= n; i++) pos[i] = pos[i-1] + deg[i];
    pos[n+1] = pos[n];
    vector<int> adj(2 * m);
    vector<int> cur(n + 1, 0);
    for(int i = 1; i <= n; i++) cur[i] = pos[i-1];
    for(auto& [u, v] : edges){
        adj[cur[u]++] = v;
        adj[cur[v]++] = u;
    }

    if(m == 0){
        for(int i = 1; i <= n; i++){
            if(i > 1) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }

    mt19937 rng(31415);

    vector<int> side(n + 1);
    vector<int> gain(n + 1);
    int cut;

    auto flip_vertex = [&](int v) {
        side[v] ^= 1;
        cut += gain[v];
        gain[v] = -gain[v];
        for(int i = pos[v-1]; i < pos[v]; i++){
            int w = adj[i];
            if(side[v] == side[w]) gain[w] += 2;
            else gain[w] -= 2;
        }
    };

    auto calc_state = [&]() {
        fill(gain.begin() + 1, gain.begin() + n + 1, 0);
        cut = 0;
        for(int u = 1; u <= n; u++){
            for(int i = pos[u-1]; i < pos[u]; i++){
                int w = adj[i];
                if(side[u] == side[w]) gain[u]++;
                else { gain[u]--; cut++; }
            }
        }
        cut /= 2;
    };

    auto greedy_improve = [&]() {
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    flip_vertex(v);
                    improved = true;
                }
            }
        }
    };

    int global_best_cut = -1;
    vector<int> global_best_side(n + 1);
    uniform_real_distribution<double> unif(0.0, 1.0);

    // 6 restarts, longer SA + heavy ILS
    int num_restarts = 6;

    for(int restart = 0; restart < num_restarts; restart++){
        if(restart < 3) {
            vector<int> order(n);
            iota(order.begin(), order.end(), 1);
            shuffle(order.begin(), order.end(), rng);
            for(int i = 1; i <= n; i++) side[i] = 0;
            for(int v : order){
                int in0 = 0, in1 = 0;
                for(int i = pos[v-1]; i < pos[v]; i++){
                    int w = adj[i];
                    if(side[w] == 0) in0++;
                    else in1++;
                }
                side[v] = (in0 >= in1) ? 1 : 0;
            }
        } else {
            for(int i = 1; i <= n; i++) side[i] = rng() % 2;
        }

        calc_state();
        greedy_improve();
        int best_cut = cut;
        vector<int> best_side(side.begin(), side.begin() + n + 1);

        // SA: slightly slower cooling for deeper search
        double T = 3.0, T_min = 0.0005, alpha = 0.999975;
        while(T > T_min){
            int v = (rng() % n) + 1;
            int g = gain[v];
            if(g > 0 || unif(rng) < exp((double)g / T)){
                flip_vertex(v);
                if(cut > best_cut){
                    best_cut = cut;
                    copy(side.begin(), side.begin() + n + 1, best_side.begin());
                }
            }
            T *= alpha;
        }

        copy(best_side.begin(), best_side.begin() + n + 1, side.begin());
        calc_state();
        greedy_improve();
        if(cut > best_cut){
            best_cut = cut;
            copy(side.begin(), side.begin() + n + 1, best_side.begin());
        }

        // Heavy ILS: 30 perturbation cycles with varying strength
        for(int p = 0; p < 30; p++){
            copy(best_side.begin(), best_side.begin() + n + 1, side.begin());
            calc_state();
            // Vary perturbation: stronger early, weaker later
            int k = max(1, n / (10 + p * 2));
            for(int j = 0; j < k; j++){
                int v = (rng() % n) + 1;
                flip_vertex(v);
            }
            greedy_improve();
            if(cut > best_cut){
                best_cut = cut;
                copy(side.begin(), side.begin() + n + 1, best_side.begin());
            }
        }

        if(best_cut > global_best_cut){
            global_best_cut = best_cut;
            copy(best_side.begin(), best_side.begin() + n + 1, global_best_side.begin());
        }
    }

    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << global_best_side[i];
    }
    cout << '\n';

    return 0;
}
