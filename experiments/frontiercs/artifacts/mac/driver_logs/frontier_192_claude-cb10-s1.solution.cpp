#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n, m;
    cin >> n >> m;
    
    vector<pair<int,int>> edges(m);
    vector<vector<int>> adj(n);
    
    for(int i = 0; i < m; i++){
        int u, v; cin >> u >> v; u--; v--;
        edges[i] = {u, v};
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    
    if(m == 0){
        for(int i = 0; i < n; i++){
            if(i) cout << ' ';
            cout << 0;
        }
        cout << '\n';
        return 0;
    }
    
    vector<int> best(n, 0), s(n), gain(n);
    int bestCut = -1;
    mt19937 rng(12345);
    
    auto calcGain = [&](){
        for(int u = 0; u < n; u++){
            int g = 0;
            for(int v : adj[u]) g += (s[u] == s[v]) ? 1 : -1;
            gain[u] = g;
        }
    };
    
    auto flipNode = [&](int u){
        s[u] ^= 1;
        gain[u] = -gain[u];
        for(int v : adj[u]){
            if(s[u] == s[v]) gain[v] -= 2;
            else gain[v] += 2;
        }
    };
    
    auto localSearch = [&](){
        bool imp = true;
        while(imp){
            imp = false;
            for(int u = 0; u < n; u++){
                if(gain[u] > 0){ flipNode(u); imp = true; }
            }
        }
    };
    
    auto calcCut = [&]() -> int {
        int c = 0;
        for(auto&[u,v]:edges) if(s[u]!=s[v]) c++;
        return c;
    };
    
    auto t0 = chrono::steady_clock::now();
    auto elapsed = [&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-t0).count();
    };
    
    double timeLimit = 0.9;
    
    while(elapsed() < timeLimit){
        for(int i = 0; i < n; i++) s[i] = rng() & 1;
        calcGain();
        localSearch();
        
        int curCut = calcCut();
        if(curCut > bestCut){ bestCut = curCut; best = s; }
        
        double startTime = elapsed();
        double remaining = timeLimit - startTime;
        if(remaining < 0.005) break;
        double runTime = min(remaining * 0.5, 0.3);
        
        double T0 = max(2.0, 0.5 + m * 0.001);
        double Tmin = 0.01;
        
        int iters = 0;
        while(true){
            if((iters & 255) == 0 && elapsed() - startTime > runTime) break;
            int u = rng() % n;
            int d = gain[u];
            if(d > 0){
                flipNode(u);
            } else {
                double progress = min(1.0, (double)iters / (double)(n * 200));
                double T = T0 * pow(Tmin / T0, progress);
                if(d == 0 || exp((double)d / T) > (double)(rng()%10000)/10000.0){
                    flipNode(u);
                }
            }
            iters++;
            if(iters % (n * 5) == 0){
                localSearch();
                int c = calcCut();
                if(c > bestCut){ bestCut = c; best = s; }
            }
        }
        localSearch();
        int c = calcCut();
        if(c > bestCut){ bestCut = c; best = s; }
    }
    
    for(int i = 0; i < n; i++){
        if(i) cout << ' ';
        cout << best[i];
    }
    cout << '\n';
}
