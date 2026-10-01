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

    mt19937 rng(42);

    int global_best_cut = -1;
    vector<int> global_best_side;

    for(int restart = 0; restart < 50; restart++){
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

        // Greedy local search until no improvement
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

        if(cut > global_best_cut){
            global_best_cut = cut;
            global_best_side = side;
        }
    }

    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << global_best_side[i];
    }
    cout << '\n';

    return 0;
}
