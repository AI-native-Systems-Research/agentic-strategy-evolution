#include <bits/stdc++.h>
using namespace std;

int N, K, total;
int eid[3001], ex[3001], ey[3001];
char et[3001];

double ecost(int i, int j) {
    long long dx = (long long)ex[i] - ex[j];
    long long dy = (long long)ey[i] - ey[j];
    double r = (double)(dx*dx + dy*dy);
    if (et[i] == 'C' && et[j] == 'C') return 1e18;
    if (et[i] != 'C' && et[j] != 'C' && (et[i] == 'S' || et[j] == 'S'))
        return 0.8 * r;
    return r;
}

int par[3001];
int find_p(int x) { return par[x] == x ? x : par[x] = find_p(par[x]); }
bool unite(int a, int b) {
    a = find_p(a); b = find_p(b);
    if (a == b) return false;
    par[a] = b;
    return true;
}

int main() {
    scanf("%d%d", &N, &K);
    total = N + K;
    for (int i = 0; i < total; i++) {
        char t[5];
        scanf("%d%d%d %s", &eid[i], &ex[i], &ey[i], t);
        et[i] = t[0];
    }

    // Build ALL valid edges (robot-robot and robot-relay, no C-C)
    struct Edge { int u, v; double w; };
    vector<Edge> edges;
    edges.reserve((long long)total * (total - 1) / 2);
    for (int i = 0; i < total; i++)
        for (int j = i + 1; j < total; j++) {
            if (et[i] == 'C' && et[j] == 'C') continue;
            edges.push_back({i, j, ecost(i, j)});
        }
    sort(edges.begin(), edges.end(), [](const Edge& a, const Edge& b) {
        return a.w < b.w;
    });

    // Kruskal MST of all nodes
    for (int i = 0; i < total; i++) par[i] = i;
    vector<set<int>> adj(total);
    int ec = 0;
    for (auto& e : edges) {
        if (unite(e.u, e.v)) {
            adj[e.u].insert(e.v);
            adj[e.v].insert(e.u);
            ec++;
            if (ec == total - 1) break;
        }
    }

    // Prune relay leaves
    bool changed = true;
    while (changed) {
        changed = false;
        for (int i = 0; i < total; i++) {
            if (et[i] == 'C' && !adj[i].empty() && (int)adj[i].size() <= 1) {
                int v = *adj[i].begin();
                adj[v].erase(i);
                adj[i].clear();
                changed = true;
            }
        }
    }

    // Remove unprofitable degree-2 relays (only if both neighbors are non-relay)
    changed = true;
    while (changed) {
        changed = false;
        for (int i = 0; i < total; i++) {
            if (et[i] == 'C' && (int)adj[i].size() == 2) {
                auto it = adj[i].begin();
                int a = *it++; int b = *it;
                if (et[a] == 'C' || et[b] == 'C') continue;
                double via_relay = ecost(a, i) + ecost(i, b);
                double direct = ecost(a, b);
                if (direct < via_relay - 1e-9) {
                    adj[i].clear();
                    adj[a].erase(i); adj[b].erase(i);
                    adj[a].insert(b); adj[b].insert(a);
                    changed = true;
                }
            }
        }
        // Re-prune after removing relays
        bool pruning = true;
        while (pruning) {
            pruning = false;
            for (int i = 0; i < total; i++) {
                if (et[i] == 'C' && !adj[i].empty() && (int)adj[i].size() <= 1) {
                    int v = *adj[i].begin();
                    adj[v].erase(i);
                    adj[i].clear();
                    pruning = true;
                }
            }
        }
    }

    // Greedy relay insertion into robot-robot edges
    set<int> relays_used;
    for (int i = 0; i < total; i++)
        if (et[i] == 'C' && !adj[i].empty())
            relays_used.insert(i);

    vector<int> relays;
    for (int i = 0; i < total; i++)
        if (et[i] == 'C') relays.push_back(i);

    for (int round = 0; round < 5; round++) {
        vector<pair<int,int>> rr_edges;
        for (int u = 0; u < total; u++)
            for (int v : adj[u])
                if (u < v && et[u] != 'C' && et[v] != 'C')
                    rr_edges.push_back({u, v});

        struct Cand { int c, u, v; double sav; };
        vector<Cand> cands;
        for (int c : relays) {
            if (relays_used.count(c)) continue;
            double best = 0; int bu = -1, bv = -1;
            for (auto& [u, v] : rr_edges) {
                double s = ecost(u, v) - ecost(u, c) - ecost(c, v);
                if (s > best) { best = s; bu = u; bv = v; }
            }
            if (best > 1e-9) cands.push_back({c, bu, bv, best});
        }
        sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
            return a.sav > b.sav;
        });
        bool improved = false;
        for (auto& [c, u, v, s] : cands) {
            if (relays_used.count(c) || !adj[u].count(v)) continue;
            adj[u].erase(v); adj[v].erase(u);
            adj[u].insert(c); adj[c].insert(u);
            adj[v].insert(c); adj[c].insert(v);
            relays_used.insert(c);
            improved = true;
        }
        if (!improved) break;
    }

    // Output
    set<int> out_relays;
    vector<pair<int,int>> out_edges;
    for (int i = 0; i < total; i++)
        for (int j : adj[i])
            if (i < j) {
                out_edges.push_back({eid[i], eid[j]});
                if (et[i] == 'C') out_relays.insert(eid[i]);
                if (et[j] == 'C') out_relays.insert(eid[j]);
            }

    if (out_relays.empty()) printf("#\n");
    else {
        bool first = true;
        for (int r : out_relays) {
            if (!first) printf("#");
            printf("%d", r);
            first = false;
        }
        printf("\n");
    }
    {
        bool first = true;
        for (auto& [a, b] : out_edges) {
            if (!first) printf("#");
            printf("%d-%d", a, b);
            first = false;
        }
        printf("\n");
    }
    return 0;
}
