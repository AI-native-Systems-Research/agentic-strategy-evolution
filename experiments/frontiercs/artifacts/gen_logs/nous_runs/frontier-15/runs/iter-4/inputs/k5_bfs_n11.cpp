#include <bits/stdc++.h>
using namespace std;

// BFS at n=11 for k=5 endgame
// At n=11: small ops {1,2,3,4}, large ops {6,7,8,9} = {n-5,n-4,n-3,n-2}
// Gap at {5} ensures no ambiguity

const int N = 11;
const int K = 5; // endgame size

int fact_arr[N+1];
void init_fact() {
    fact_arr[0] = 1;
    for (int i = 1; i <= N; i++) fact_arr[i] = fact_arr[i-1] * i;
}

int encode(const int* p) {
    int idx = 0;
    bool used[N] = {};
    for (int i = 0; i < N; i++) {
        int cnt = 0;
        for (int j = 0; j < p[i]; j++) if (!used[j]) cnt++;
        idx += cnt * fact_arr[N-1-i];
        used[p[i]] = true;
    }
    return idx;
}

void decode(int idx, int* p) {
    int avail[N];
    for (int i = 0; i < N; i++) avail[i] = i;
    int sz = N;
    for (int i = 0; i < N; i++) {
        int f = fact_arr[N-1-i];
        int k = idx / f;
        idx %= f;
        p[i] = avail[k];
        // Remove avail[k]
        for (int j = k; j < sz-1; j++) avail[j] = avail[j+1];
        sz--;
    }
}

void apply_op(const int* p, int x, int y, int* q) {
    for (int i = 0; i < y; i++) q[i] = p[N - y + i];
    int m = N - x - y;
    for (int i = 0; i < m; i++) q[y + i] = p[x + i];
    for (int i = 0; i < x; i++) q[N - x + i] = p[i];
}

int main() {
    init_fact();
    int NFACT = fact_arr[N];
    printf("N=%d, N!=%d\n", N, NFACT);

    // Interesting operations: x,y in {1,2,3,4,6,7,8,9} with x+y < N
    vector<pair<int,int>> ops;
    vector<int> interesting = {1,2,3,4,6,7,8,9};
    for (int x : interesting)
        for (int y : interesting)
            if (x + y < N) ops.emplace_back(x, y);
    printf("Number of interesting operations: %d\n", (int)ops.size());

    // BFS using char array for distances
    vector<signed char> dist(NFACT, -1);

    // Goal: [0,1,2,...,10] (0-indexed)
    int goal_p[N];
    for (int i = 0; i < N; i++) goal_p[i] = i;
    int goal_idx = encode(goal_p);

    // Reverse BFS from goal
    queue<int> bfs;
    dist[goal_idx] = 0;
    bfs.push(goal_idx);

    int max_dist = 0;
    long long visited = 1;

    while (!bfs.empty()) {
        int cur = bfs.front(); bfs.pop();
        int d = dist[cur];
        if (d >= 7) continue; // don't explore too deep

        int p[N];
        decode(cur, p);

        for (auto& [x, y] : ops) {
            int np[N];
            // Reverse of forward op (x,y) is applying (y,x) to current state
            apply_op(p, y, x, np);
            int ni = encode(np);
            if (dist[ni] == -1) {
                dist[ni] = d + 1;
                bfs.push(ni);
                visited++;
                max_dist = max(max_dist, d + 1);
            }
        }
    }

    printf("Max distance explored: %d, states visited: %lld / %d\n", max_dist, visited, NFACT);

    // Check all 120 starting permutations for k=5 endgame
    // Sorted prefix: [0,1,2,3,4,5] (values 0..5 in positions 0..5)
    // Buffer: positions [6,7,8,9,10] contain a permutation of {6,7,8,9,10}
    vector<int> buf = {6,7,8,9,10};
    sort(buf.begin(), buf.end());

    int max_endgame_ops = 0;
    int total_ops = 0;
    map<int, int> histogram;
    int unreachable = 0;

    do {
        int start[N] = {0,1,2,3,4,5};
        for (int i = 0; i < 5; i++) start[6+i] = buf[i];
        int si = encode(start);
        if (si == goal_idx) continue;

        int d = dist[si];
        if (d == -1) {
            unreachable++;
            printf("UNREACHABLE: buf=[");
            for (int v : buf) printf("%d ", v+1);
            printf("]\n");
        } else {
            histogram[d]++;
            max_endgame_ops = max(max_endgame_ops, d);
            total_ops += d;
        }
    } while (next_permutation(buf.begin(), buf.end()));

    printf("\n=== k=5 Endgame Results (n=%d, interesting ops only) ===\n", N);
    printf("Non-identity configs: %d\n", 119);
    printf("Unreachable: %d\n", unreachable);
    printf("Max endgame ops: %d\n", max_endgame_ops);
    printf("Average endgame ops: %.2f\n", (double)total_ops / (119 - unreachable));
    printf("Histogram:\n");
    for (auto& [d, c] : histogram) printf("  %d ops: %d configs\n", d, c);
    printf("\nWorst-case formula: 2n - 10 + %d = 2n - %d\n", max_endgame_ops, 10 - max_endgame_ops);
    printf("For n=1000: %d ops\n", 2*1000 - 10 + max_endgame_ops);

    // Now trace paths for all configs and output the operation sequences
    // We need to redo BFS with parent tracking for this
    // But only for configs that need sequences - store them
    printf("\n=== Tracing optimal sequences ===\n");

    // Redo smaller BFS with parent info, limited to states reachable within max_endgame_ops
    // Actually, just do forward BFS from each starting state
    sort(buf.begin(), buf.end());
    buf = {6,7,8,9,10};

    do {
        int start[N] = {0,1,2,3,4,5};
        for (int i = 0; i < 5; i++) start[6+i] = buf[i];
        int si = encode(start);
        if (si == goal_idx) continue;

        int target_d = dist[si];
        if (target_d == -1) { continue; }

        // Forward DFS guided by distance: from start, always move closer to goal
        printf("buf=[");
        for (int v : buf) printf("%d,", v - 5); // offset from n-5 (0-indexed)
        printf("] cost=%d ops: ", target_d);

        int cur = si;
        while (cur != goal_idx) {
            int cur_d = dist[cur];
            int p[N];
            decode(cur, p);

            bool found = false;
            for (auto& [x, y] : ops) {
                int np[N];
                apply_op(p, x, y, np);
                int ni = encode(np);
                if (dist[ni] == cur_d - 1) {
                    // Map operation to n-dependent form
                    string sx = (x <= 4) ? to_string(x) : "n-" + to_string(N - x);
                    string sy = (y <= 4) ? to_string(y) : "n-" + to_string(N - y);
                    printf("(%s,%s) ", sx.c_str(), sy.c_str());
                    cur = ni;
                    found = true;
                    break;
                }
            }
            if (!found) { printf("STUCK! "); break; }
        }
        printf("\n");
    } while (next_permutation(buf.begin(), buf.end()));

    return 0;
}
