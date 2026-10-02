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
        int u, v;
        cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
        edges[i] = {u, v};
    }
    
    if(m == 0){
        for(int i = 1; i <= n; i++) cout << 0 << " \n"[i==n];
        return 0;
    }
    
    auto countCut = [&](vector<int>& s) -> int {
        int c = 0;
        for(auto& [u,v] : edges) c += (s[u] != s[v]);
        return c;
    };
    
    // gain[v] = increase in cut if we flip v
    auto computeGain = [&](vector<int>& s, vector<int>& gain){
        fill(gain.begin(), gain.end(), 0);
        for(auto& [u,v] : edges){
            if(s[u] == s[v]){
                gain[u]++;
                gain[v]++;
            } else {
                gain[u]--;
                gain[v]--;
            }
        }
    };
    
    vector<int> bestS(n+1, 0);
    int bestCut = -1;
    
    mt19937 rng(42);
    
    auto localSearch = [&](vector<int>& s, vector<int>& gain) {
        bool improved = true;
        while(improved){
            improved = false;
            for(int v = 1; v <= n; v++){
                if(gain[v] > 0){
                    s[v] ^= 1;
                    for(int u : adj[v]){
                        if(s[u] == s[v]){
                            gain[u]++;
                            gain[v]++;
                        } else {
                            gain[u]--;
                            gain[v]--;
                        }
                    }
                    // Recompute gain[v] after flip by negating old contributions
                    // Actually the loop above already updated gain[v] correctly
                    // Wait, let me just recompute gain properly
                    // Simpler: recompute gain[v] from scratch
                    gain[v] = 0;
                    for(int u : adj[v]){
                        if(s[u] == s[v]) gain[v]++;
                        else gain[v]--;
                    }
                    improved = true;
                }
            }
        }
    };
    
    int maxRestarts = max(1, min(500, (int)(2000000 / (m + n + 1))));
    
    vector<int> s(n+1), gain(n+1);
    
    for(int restart = 0; restart < maxRestarts; restart++){
        // Random initial
        for(int i = 1; i <= n; i++) s[i] = rng() & 1;
        
        computeGain(s, gain);
        localSearch(s, gain);
        
        // Perturbation: flip a few random vertices and re-do local search
        for(int pert = 0; pert < 50; pert++){
            vector<int> s2 = s;
            int flips = max(1, (int)(n * 0.05));
            for(int f = 0; f < flips; f++){
                int v = rng() % n + 1;
                s2[v] ^= 1;
            }
            vector<int> g2(n+1);
            computeGain(s2, g2);
            localSearch(s2, g2);
            int c2 = countCut(s2);
            if(c2 > countCut(s)){
                s = s2;
                gain = g2;
            }
        }
        
        int c = countCut(s);
        if(c > bestCut){
            bestCut = c;
            bestS = s;
        }
    }
    
    for(int i = 1; i <= n; i++){
        cout << bestS[i];
        if(i < n) cout << ' ';
    }
    cout << '\n';
    
    return 0;
}
