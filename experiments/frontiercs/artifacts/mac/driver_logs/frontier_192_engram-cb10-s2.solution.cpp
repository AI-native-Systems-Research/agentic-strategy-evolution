#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<vector<int>> adj(n+1);
    vector<pair<int,int>> edges(m);
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    if(m == 0){
        for(int i = 1; i <= n; i++){
            if(i > 1) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }
    
    auto calcCut = [&](vector<int>& s) -> int {
        int cut = 0;
        for(auto& [u,v] : edges)
            if(s[u] != s[v]) cut++;
        return cut;
    };
    
    vector<int> bestS(n+1, 0);
    int bestCut = -1;
    
    mt19937 rng(42);
    auto startTime = chrono::steady_clock::now();
    
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    int restarts = 0;
    while(elapsed() < 1.8){
        restarts++;
        vector<int> s(n+1, 0);
        
        // Greedy init with random order
        vector<int> order(n);
        iota(order.begin(), order.end(), 1);
        shuffle(order.begin(), order.end(), rng);
        
        for(int v : order){
            int c0 = 0, c1 = 0;
            for(int u : adj[v]){
                if(s[u] == 0) c0++; else c1++;
            }
            s[v] = (c0 >= c1) ? 1 : 0;
        }
        
        // Compute gains
        vector<int> gain(n+1, 0);
        for(int v = 1; v <= n; v++)
            for(int u : adj[v])
                if(s[u] == s[v]) gain[v]++; else gain[v]--;
        
        // 1-flip local search
        bool imp = true;
        while(imp){
            imp = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    s[v] ^= 1;
                    gain[v] = -gain[v];
                    for(int u : adj[v]){
                        if(s[u] == s[v]) gain[u] += 2;
                        else gain[u] -= 2;
                    }
                    imp = true;
                }
            }
        }
        
        // Simulated annealing phase
        int curCut = calcCut(s);
        double temp = 2.0;
        double coolRate = 0.9995;
        int iters = 0;
        int maxIters = (n <= 100) ? 100000 : (n <= 500) ? 50000 : 20000;
        
        while(iters < maxIters && elapsed() < 1.75){
            int v = (rng() % n) + 1;
            int delta = -gain[v]; // negative of gain means worsening
            // flipping v changes cut by gain[v]
            if(gain[v] > 0 || (uniform_real_distribution<double>(0,1)(rng) < exp((double)gain[v] / temp))){
                s[v] ^= 1;
                curCut += gain[v];
                gain[v] = -gain[v];
                for(int u : adj[v]){
                    if(s[u] == s[v]) gain[u] += 2;
                    else gain[u] -= 2;
                }
            }
            temp *= coolRate;
            if(temp < 0.01) temp = 0.01;
            iters++;
        }
        
        curCut = calcCut(s);
        if(curCut > bestCut){
            bestCut = curCut;
            bestS = s;
        }
    }
    
    for(int i = 1; i <= n; i++){
        if(i > 1) cout << ' ';
        cout << bestS[i];
    }
    cout << '\n';
    return 0;
}
