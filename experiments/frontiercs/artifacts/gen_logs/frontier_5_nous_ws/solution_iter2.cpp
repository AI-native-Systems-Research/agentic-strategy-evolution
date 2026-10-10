#include <bits/stdc++.h>
using namespace std;

// ——— Globals ———
int N, M;
int jud[10];
vector<int> adj_out[500001], adj_in[500001];
bool has_edge_matrix[501][501]; // for small n only
bool useMatrix;

mt19937 rng_global(42);
chrono::high_resolution_clock::time_point T0;
double elapsed() {
    return chrono::duration<double>(chrono::high_resolution_clock::now() - T0).count();
}

// Edge check
inline bool hasEdge(int u, int v) {
    if (useMatrix) return has_edge_matrix[u][v];
    auto &a = adj_out[u];
    return binary_search(a.begin(), a.end(), v);
}

int bestLen = 0;
vector<int> bestPath;

// ——— SCC (Iterative Kosaraju) ———
vector<int> scc_id_arr;
vector<vector<int>> scc_members;
int num_sccs;

void computeSCCs() {
    scc_id_arr.assign(N + 1, -1);
    vector<bool> visited(N + 1, false);
    vector<int> order;
    order.reserve(N);

    // First pass: DFS on original graph, record finish order
    for (int start = 1; start <= N; start++) {
        if (visited[start]) continue;
        vector<pair<int,int>> stk;
        stk.push_back({start, 0});
        while (!stk.empty()) {
            auto &[v, i] = stk.back();
            if (!visited[v]) visited[v] = true;
            if (i < (int)adj_out[v].size()) {
                int w = adj_out[v][i++];
                if (!visited[w]) stk.push_back({w, 0});
            } else {
                order.push_back(v);
                stk.pop_back();
            }
        }
    }

    // Second pass: DFS on reverse graph in reverse finish order
    fill(visited.begin(), visited.end(), false);
    num_sccs = 0;
    for (int i = (int)order.size() - 1; i >= 0; i--) {
        int start = order[i];
        if (visited[start]) continue;
        vector<int> comp;
        vector<int> stk2;
        stk2.push_back(start);
        while (!stk2.empty()) {
            int v = stk2.back(); stk2.pop_back();
            if (visited[v]) continue;
            visited[v] = true;
            comp.push_back(v);
            scc_id_arr[v] = num_sccs;
            for (int w : adj_in[v]) {
                if (!visited[w]) stk2.push_back(w);
            }
        }
        scc_members.push_back(comp);
        num_sccs++;
    }
}

// ——— DAG-based solver for fragmented graphs ———
// Used when num_sccs is large (DAG-like structure)
void solveDAG() {
    // Build condensation DAG
    vector<set<int>> dag_adj(num_sccs);
    vector<int> dag_indeg(num_sccs, 0);
    for (int u = 1; u <= N; u++) {
        for (int v : adj_out[u]) {
            int su = scc_id_arr[u], sv = scc_id_arr[v];
            if (su != sv && !dag_adj[su].count(sv)) {
                dag_adj[su].insert(sv);
                dag_indeg[sv]++;
            }
        }
    }

    // For each SCC, precompute internal edges and Hamiltonian paths
    // with specified start and end vertices using bitmask DP
    // For SCCs with 1 vertex: trivial
    // For SCCs with <= 20 vertices: bitmask DP

    // First, find a Hamiltonian path in the condensation DAG
    // Greedy: start from a source (in-degree 0), always pick the neighbor
    // that leads to the most reachable vertices

    // BFS reachability in condensation DAG
    // For efficiency, just do greedy with "most out-neighbors" heuristic

    // Try multiple starting SCCs
    auto tryDAGPath = [&](int startSCC) -> vector<int> {
        vector<bool> visited(num_sccs, false);
        vector<int> dag_path;
        dag_path.push_back(startSCC);
        visited[startSCC] = true;

        while ((int)dag_path.size() < num_sccs) {
            int cur = dag_path.back();
            int best = -1, bestScore = -1;
            for (int nxt : dag_adj[cur]) {
                if (!visited[nxt]) {
                    // Score: number of unvisited out-neighbors
                    int score = 0;
                    for (int nn : dag_adj[nxt]) {
                        if (!visited[nn]) score++;
                    }
                    if (best == -1 || score > bestScore) {
                        bestScore = score;
                        best = nxt;
                    }
                }
            }
            if (best == -1) break; // stuck
            dag_path.push_back(best);
            visited[best] = true;
        }
        return dag_path;
    };

    // Find sources (in-degree 0)
    vector<int> sources;
    for (int i = 0; i < num_sccs; i++) {
        if (dag_indeg[i] == 0) sources.push_back(i);
    }
    if (sources.empty()) sources.push_back(0);

    vector<int> bestDAGPath;
    for (int s : sources) {
        auto p = tryDAGPath(s);
        if ((int)p.size() > (int)bestDAGPath.size()) bestDAGPath = p;
        if ((int)p.size() == num_sccs) break;
    }
    // Also try random starts
    for (int tries = 0; tries < 100 && elapsed() < 0.5; tries++) {
        int s = rng_global() % num_sccs;
        auto p = tryDAGPath(s);
        if ((int)p.size() > (int)bestDAGPath.size()) bestDAGPath = p;
        if ((int)p.size() == num_sccs) break;
    }

    // Now build the actual vertex path through the DAG path
    // For each consecutive pair of SCCs, we need:
    // - Exit vertex from current SCC (with edge to some vertex in next SCC)
    // - Entry vertex to next SCC
    // - Hamiltonian subpath within current SCC from entry to exit

    int dagLen = bestDAGPath.size();

    // Find inter-SCC edges
    // For each pair (scc_i, scc_j) in dag_path, find edges from scc_i to scc_j
    vector<vector<pair<int,int>>> interEdges(dagLen - 1);
    for (int i = 0; i < dagLen - 1; i++) {
        int si = bestDAGPath[i], sj = bestDAGPath[i + 1];
        for (int u : scc_members[si]) {
            for (int v : adj_out[u]) {
                if (scc_id_arr[v] == sj) {
                    interEdges[i].push_back({u, v});
                }
            }
        }
    }

    // For each SCC, find Hamiltonian path with given start/end constraints
    // Bitmask DP for small SCCs
    auto findHPInSCC = [&](int scc_idx, int mustStart, int mustEnd) -> vector<int> {
        auto &members = scc_members[scc_idx];
        int sz = members.size();
        if (sz == 1) return {members[0]};

        // Map global vertex IDs to local [0..sz-1]
        map<int, int> toLocal;
        for (int i = 0; i < sz; i++) toLocal[members[i]] = i;

        int startLocal = (mustStart >= 0) ? toLocal[mustStart] : -1;
        int endLocal = (mustEnd >= 0) ? toLocal[mustEnd] : -1;

        // Bitmask DP: dp[mask][v] = true if we can reach state (mask, v)
        // mask = set of visited vertices, v = current vertex
        int full = (1 << sz) - 1;
        vector<vector<int>> parent(1 << sz, vector<int>(sz, -1));
        vector<vector<bool>> dp(1 << sz, vector<bool>(sz, false));

        // Initialize
        for (int i = 0; i < sz; i++) {
            if (startLocal >= 0 && i != startLocal) continue;
            dp[1 << i][i] = true;
        }

        // Build internal adjacency
        vector<vector<int>> localAdj(sz);
        for (int i = 0; i < sz; i++) {
            for (int j = 0; j < sz; j++) {
                if (i != j && hasEdge(members[i], members[j])) {
                    localAdj[i].push_back(j);
                }
            }
        }

        for (int mask = 1; mask <= full; mask++) {
            for (int v = 0; v < sz; v++) {
                if (!dp[mask][v]) continue;
                for (int w : localAdj[v]) {
                    if (mask & (1 << w)) continue;
                    int nmask = mask | (1 << w);
                    if (!dp[nmask][w]) {
                        dp[nmask][w] = true;
                        parent[nmask][w] = v;
                    }
                }
            }
        }

        // Find path ending at mustEnd (or any vertex if mustEnd < 0)
        int endV = -1;
        if (endLocal >= 0 && dp[full][endLocal]) {
            endV = endLocal;
        } else if (endLocal < 0) {
            for (int v = 0; v < sz; v++) {
                if (dp[full][v]) { endV = v; break; }
            }
        }

        if (endV < 0) {
            // Can't find full HP with constraints, return best partial
            // Just return members in some order (greedy)
            return {members[0]};
        }

        // Reconstruct path
        vector<int> result;
        int mask = full, v = endV;
        while (v >= 0) {
            result.push_back(members[v]);
            int pv = parent[mask][v];
            mask ^= (1 << v);
            v = pv;
        }
        reverse(result.begin(), result.end());
        return result;
    };

    // Greedy assembly: for each SCC in dag_path order,
    // determine entry and exit vertices
    vector<int> fullPath;

    for (int i = 0; i < dagLen; i++) {
        int scc_idx = bestDAGPath[i];
        auto &members = scc_members[scc_idx];
        int sz = members.size();

        if (sz == 1) {
            fullPath.push_back(members[0]);
            continue;
        }

        if (sz > 20) {
            // Too large for bitmask DP, just add in some order
            // Try greedy Hamiltonian path within SCC
            for (int v : members) fullPath.push_back(v);
            continue;
        }

        // Determine entry vertex (must be reachable from previous SCC's exit)
        int mustStart = -1;
        if (i > 0 && !fullPath.empty()) {
            int prevExit = fullPath.back();
            for (int v : members) {
                if (hasEdge(prevExit, v)) {
                    mustStart = v;
                    break;
                }
            }
        }

        // Determine exit vertex (must have edge to next SCC's entry)
        int mustEnd = -1;
        if (i < dagLen - 1 && !interEdges[i].empty()) {
            // Try each possible exit vertex
            // Pick one that works with mustStart
            for (auto &[u, v] : interEdges[i]) {
                // u is exit from current SCC, v is entry to next SCC
                // Check if we can find HP starting at mustStart and ending at u
                auto tryPath = findHPInSCC(scc_idx, mustStart, u);
                if ((int)tryPath.size() == sz) {
                    for (int x : tryPath) fullPath.push_back(x);
                    mustEnd = u; // mark as handled
                    break;
                }
            }
            if (mustEnd < 0) {
                // Couldn't find constrained HP, try unconstrained
                auto tryPath = findHPInSCC(scc_idx, mustStart, -1);
                for (int x : tryPath) fullPath.push_back(x);
            }
        } else {
            auto tryPath = findHPInSCC(scc_idx, mustStart, -1);
            for (int x : tryPath) fullPath.push_back(x);
        }
    }

    // Validate path
    bool valid = true;
    set<int> seen;
    for (int i = 0; i < (int)fullPath.size(); i++) {
        if (seen.count(fullPath[i])) { valid = false; break; }
        seen.insert(fullPath[i]);
        if (i > 0 && !hasEdge(fullPath[i-1], fullPath[i])) { valid = false; break; }
    }

    if (valid && (int)fullPath.size() > bestLen) {
        bestLen = fullPath.size();
        bestPath = fullPath;
    }
}

// ——— Array-based rotation solver ———
void solveRotation(double timeLimit) {
    // State
    vector<int> path; path.reserve(N);
    vector<int> pos(N + 1, -1);
    vector<bool> used(N + 1, false);
    vector<int> dout(N + 1); // modified out-degree (unvisited neighbors only)

    auto reset = [&]() {
        path.clear();
        fill(pos.begin(), pos.end(), -1);
        fill(used.begin(), used.end(), false);
        for (int u = 1; u <= N; u++) dout[u] = adj_out[u].size();
    };

    auto markUsed = [&](int v) {
        used[v] = true;
        for (int u : adj_in[v]) {
            if (!used[u]) dout[u]--;
        }
    };

    auto addToPath = [&](int v) {
        pos[v] = path.size();
        path.push_back(v);
        markUsed(v);
    };

    auto updatePositions = [&](int from) {
        for (int i = from; i < (int)path.size(); i++) {
            pos[path[i]] = i;
        }
    };

    // Extension from tail (Warnsdorff)
    auto extendForward = [&]() -> bool {
        bool extended = false;
        while (true) {
            int tail = path.back();
            int bestD = INT_MAX, cnt = 0;
            int picks[16];
            for (int v : adj_out[tail]) {
                if (!used[v]) {
                    if (dout[v] < bestD) { bestD = dout[v]; cnt = 0; picks[cnt++] = v; }
                    else if (dout[v] == bestD && cnt < 16) picks[cnt++] = v;
                }
            }
            if (cnt == 0) break;
            int p = picks[rng_global() % cnt];
            addToPath(p);
            extended = true;
        }
        return extended;
    };

    // Extension from head (reverse Warnsdorff)
    auto extendBackward = [&]() -> bool {
        bool extended = false;
        while (true) {
            int head = path[0];
            int bestD = INT_MAX, cnt = 0;
            int picks[16];
            for (int u : adj_in[head]) {
                if (!used[u]) {
                    if (dout[u] < bestD) { bestD = dout[u]; cnt = 0; picks[cnt++] = u; }
                    else if (dout[u] == bestD && cnt < 16) picks[cnt++] = u;
                }
            }
            if (cnt == 0) break;
            int p = picks[rng_global() % cnt];
            // Prepend to path
            pos[p] = -1; // will be updated
            path.insert(path.begin(), p);
            markUsed(p);
            updatePositions(0);
            extended = true;
        }
        return extended;
    };

    // Insertion pass
    auto insertVertices = [&]() -> bool {
        bool changed = false;
        int len = path.size();
        for (int i = 0; i + 1 < len; i++) {
            int u = path[i], w = path[i + 1];
            for (int v : adj_out[u]) {
                if (!used[v] && hasEdge(v, w)) {
                    // Insert v between u and w
                    path.insert(path.begin() + i + 1, v);
                    markUsed(v);
                    updatePositions(i + 1);
                    len++;
                    changed = true;
                    // Continue from v's position
                    break; // move to next i
                }
            }
        }
        return changed;
    };

    // Forward Pósa rotation (from tail)
    auto rotateForward = [&]() -> bool {
        int len = path.size();
        if (len < 3) return false;
        int tail = path[len - 1];

        // Collect shortcuts: tail → vi where vi is on path and vi != tail
        vector<int> shortcuts;
        for (int v : adj_out[tail]) {
            if (used[v] && pos[v] >= 0 && v != tail) {
                shortcuts.push_back(v);
            }
        }
        if (shortcuts.empty()) return false;

        // Shuffle for diversity
        for (int i = shortcuts.size() - 1; i > 0; i--) {
            int j = rng_global() % (i + 1);
            swap(shortcuts[i], shortcuts[j]);
        }

        for (int vi : shortcuts) {
            int pvi = pos[vi];

            if (pvi == 0) {
                // Case 1: tail → head, forms cycle
                // Find a vertex on the path with unvisited out-neighbors
                vector<int> candidates;
                for (int i = 0; i < len - 1; i++) {
                    bool hasUnvis = false;
                    for (int w : adj_out[path[i]]) {
                        if (!used[w]) { hasUnvis = true; break; }
                    }
                    if (hasUnvis) candidates.push_back(i);
                }
                if (candidates.empty()) continue;
                int vj_idx = candidates[rng_global() % candidates.size()];

                // Rotate: new path starts at vj+1, goes to tail, then head to vj
                // path = [head, ..., vj, vj+1, ..., tail]
                // new:   [vj+1, ..., tail, head, ..., vj]
                rotate(path.begin(), path.begin() + vj_idx + 1, path.end());
                updatePositions(0);
                return true;
            } else {
                // Case 2: tail → vi, vi != head
                // e = path[pvi - 1]
                int e = path[pvi - 1];

                // Find break point: c in adj_out[e] where c is on path
                // and pos[c] > pvi (c is after vi)
                // Then vj = path[pos[c] - 1]
                vector<int> goodBreaks, anyBreaks; // indices of break points
                for (int c : adj_out[e]) {
                    if (!used[c] || pos[c] < 0) continue;
                    int pc = pos[c];
                    if (pc <= pvi || pc >= len) continue; // c must be after vi
                    int vj_idx = pc - 1; // vj = path[vj_idx]
                    // Check if vj has unvisited out-neighbors
                    bool hasUnvis = false;
                    for (int w : adj_out[path[vj_idx]]) {
                        if (!used[w]) { hasUnvis = true; break; }
                    }
                    if (hasUnvis) goodBreaks.push_back(vj_idx);
                    else anyBreaks.push_back(vj_idx);
                }

                int vj_idx = -1;
                if (!goodBreaks.empty()) vj_idx = goodBreaks[rng_global() % goodBreaks.size()];
                else if (!anyBreaks.empty()) vj_idx = anyBreaks[rng_global() % anyBreaks.size()];
                if (vj_idx < 0) continue;

                // Rotation:
                // path = [..., e, vi, ..., vj, c, ..., tail]
                //         [prefix] [seg B]    [seg C]
                // new:   [..., e, c, ..., tail, vi, ..., vj]
                //         [prefix] [seg C]      [seg B]
                // Use std::rotate on the subarray [pvi..len-1]
                // to bring [vj_idx+1..len-1] to the front
                rotate(path.begin() + pvi, path.begin() + vj_idx + 1, path.end());
                updatePositions(pvi);
                return true;
            }
        }
        return false;
    };

    // Backward Pósa rotation (from head)
    auto rotateBackward = [&]() -> bool {
        int len = path.size();
        if (len < 3) return false;
        int head = path[0];

        // Collect shortcuts: vi → head where vi is on path and vi != head
        vector<int> shortcuts;
        for (int v : adj_in[head]) {
            if (used[v] && pos[v] >= 0 && v != head) {
                shortcuts.push_back(v);
            }
        }
        if (shortcuts.empty()) return false;

        for (int i = shortcuts.size() - 1; i > 0; i--) {
            int j = rng_global() % (i + 1);
            swap(shortcuts[i], shortcuts[j]);
        }

        for (int vi : shortcuts) {
            int pvi = pos[vi];

            if (pvi == len - 1) {
                // tail → head, same as Case 1 in forward rotation
                vector<int> candidates;
                for (int i = 1; i < len; i++) {
                    bool hasUnvis = false;
                    for (int u : adj_in[path[i]]) {
                        if (!used[u]) { hasUnvis = true; break; }
                    }
                    if (hasUnvis) candidates.push_back(i);
                }
                if (candidates.empty()) continue;
                int vj_idx = candidates[rng_global() % candidates.size()];

                // Rotate: path = [head, ..., vj-1, vj, ..., tail]
                // new:   [vj, ..., tail, head, ..., vj-1]
                rotate(path.begin(), path.begin() + vj_idx, path.end());
                updatePositions(0);
                return true;
            } else {
                // Case 2: vi → head, vi != tail
                // f = path[pvi + 1] (vertex after vi)
                int f = path[pvi + 1];

                // Find break point: c in adj_in[f] where c is on path
                // and pos[c] < pvi (c is before vi)
                // Then vj = path[pos[c] + 1]
                vector<int> goodBreaks, anyBreaks;
                for (int c : adj_in[f]) {
                    if (!used[c] || pos[c] < 0) continue;
                    int pc = pos[c];
                    if (pc >= pvi || pc < 0) continue; // c must be before vi
                    int vj_idx = pc + 1; // vj = path[vj_idx]
                    bool hasUnvis = false;
                    for (int u : adj_in[path[vj_idx]]) {
                        if (!used[u]) { hasUnvis = true; break; }
                    }
                    if (hasUnvis) goodBreaks.push_back(vj_idx);
                    else anyBreaks.push_back(vj_idx);
                }

                int vj_idx = -1;
                if (!goodBreaks.empty()) vj_idx = goodBreaks[rng_global() % goodBreaks.size()];
                else if (!anyBreaks.empty()) vj_idx = anyBreaks[rng_global() % anyBreaks.size()];
                if (vj_idx < 0) continue;

                // Rotation:
                // path = [head, ..., c, vj, ..., vi, f, ..., tail]
                //         [seg A]     [seg B]       [suffix]
                // new:   [vj, ..., vi, head, ..., c, f, ..., tail]
                //         [seg B]      [seg A]      [suffix]
                // Use std::rotate on [0..pvi]
                rotate(path.begin(), path.begin() + vj_idx, path.begin() + pvi + 1);
                updatePositions(0);
                return true;
            }
        }
        return false;
    };

    // Single solve attempt
    auto solve = [&](int start) {
        reset();
        addToPath(start);

        // Phase 1: Greedy extension + insertion
        extendForward();
        extendBackward();
        for (int p = 0; p < 15; p++) {
            bool ch = insertVertices();
            if (ch) { extendForward(); extendBackward(); }
            else break;
        }

        // Phase 2: Rotation
        int stuckCount = 0;
        while ((int)path.size() < N && elapsed() < timeLimit) {
            bool extended = extendForward();
            if (extended) { stuckCount = 0; continue; }

            // Try backward extension
            extended = extendBackward();
            if (extended) { stuckCount = 0; continue; }

            // Try forward rotation
            bool rotated = rotateForward();
            if (rotated) { stuckCount = 0; continue; }

            // Try backward rotation
            rotated = rotateBackward();
            if (rotated) { stuckCount = 0; continue; }

            stuckCount++;
            if (stuckCount > 5) break;
        }

        // Phase 3: Final cleanup - insertion + extension
        for (int p = 0; p < 5 && elapsed() < timeLimit; p++) {
            bool ch = insertVertices();
            if (ch) { extendForward(); extendBackward(); }
            else break;
        }

        // Append/prepend individual vertices
        for (int iter = 0; iter < 3 && elapsed() < timeLimit; iter++) {
            bool ch = false;
            for (int v = 1; v <= N; v++) {
                if (used[v]) continue;
                if (hasEdge(v, path[0])) {
                    path.insert(path.begin(), v);
                    markUsed(v);
                    updatePositions(0);
                    ch = true;
                } else if (hasEdge(path.back(), v)) {
                    addToPath(v);
                    ch = true;
                }
            }
            if (!ch) break;
            insertVertices(); extendForward(); extendBackward();
        }

        // Update best
        if ((int)path.size() > bestLen) {
            bestLen = path.size();
            bestPath = path;
        }
    };

    // Start candidates
    vector<int> starts;
    vector<int> indeg(N + 1, 0), outdeg(N + 1, 0);
    for (int u = 1; u <= N; u++) {
        outdeg[u] = adj_out[u].size();
        indeg[u] = adj_in[u].size();
    }
    for (int u = 1; u <= N; u++) {
        if (indeg[u] == 0) starts.push_back(u);
    }
    // Add low in-degree vertices
    vector<int> order(N);
    iota(order.begin(), order.end(), 1);
    sort(order.begin(), order.end(), [&](int a, int b) { return indeg[a] < indeg[b]; });
    for (int i = 0; i < min(N, 20); i++) {
        bool dup = false;
        for (int s : starts) if (s == order[i]) dup = true;
        if (!dup) starts.push_back(order[i]);
    }
    // Add high out-degree minus in-degree
    sort(order.begin(), order.end(), [&](int a, int b) { return outdeg[a] - indeg[a] > outdeg[b] - indeg[b]; });
    for (int i = 0; i < min(N, 10); i++) {
        bool dup = false;
        for (int s : starts) if (s == order[i]) dup = true;
        if (!dup) starts.push_back(order[i]);
    }

    // Phase 1: Smart starts
    for (int s : starts) {
        if (bestLen == N || elapsed() > timeLimit * 0.4) break;
        solve(s);
    }
    // Phase 2: Random restarts
    while (bestLen < N && elapsed() < timeLimit) {
        int s = (rng_global() % N) + 1;
        solve(s);
    }
}

int main() {
    T0 = chrono::high_resolution_clock::now();

    scanf("%d %d", &N, &M);
    for (int i = 0; i < 10; i++) scanf("%d", &jud[i]);

    useMatrix = (N <= 500);
    if (useMatrix) memset(has_edge_matrix, 0, sizeof(has_edge_matrix));

    for (int i = 0; i < M; i++) {
        int u, v;
        scanf("%d %d", &u, &v);
        adj_out[u].push_back(v);
        adj_in[v].push_back(u);
        if (useMatrix) has_edge_matrix[u][v] = true;
    }

    // Sort adjacency lists for binary search
    for (int u = 1; u <= N; u++) {
        sort(adj_out[u].begin(), adj_out[u].end());
        sort(adj_in[u].begin(), adj_in[u].end());
    }

    // Compute SCCs
    computeSCCs();

    // Choose strategy based on graph structure
    if (num_sccs > 10) {
        // DAG-like graph: use SCC-aware construction
        solveDAG();
        // Also try rotation as fallback
        if (bestLen < N && elapsed() < 3.5) {
            solveRotation(3.7);
        }
    } else {
        // Dense/single-SCC: use rotation approach
        solveRotation(3.7);
    }

    printf("%d\n", bestLen);
    for (int i = 0; i < bestLen; i++) {
        if (i) printf(" ");
        printf("%d", bestPath[i]);
    }
    printf("\n");
    return 0;
}
