#include <bits/stdc++.h>
using namespace std;

// BFS at n=10 for k=5 endgame
// At n=10: small ops {1,2,3,4}, large ops {5,6,7,8} = {n-5,n-4,n-3,n-2}
// These don't overlap, so sequences generalize to any n>=10

const int N = 10;
const int NFACT = 3628800; // 10!

int fact[N+1];
void init_fact() {
    fact[0] = 1;
    for (int i = 1; i <= N; i++) fact[i] = fact[i-1] * i;
}

// Encode permutation to Lehmer index
int encode(const vector<int>& p) {
    int idx = 0;
    vector<bool> used(N, false);
    for (int i = 0; i < N; i++) {
        int cnt = 0;
        for (int j = 0; j < p[i]; j++) if (!used[j]) cnt++;
        idx += cnt * fact[N-1-i];
        used[p[i]] = true;
    }
    return idx;
}

// Decode Lehmer index to permutation
vector<int> decode(int idx) {
    vector<int> p(N);
    vector<int> avail;
    for (int i = 0; i < N; i++) avail.push_back(i);
    for (int i = 0; i < N; i++) {
        int f = fact[N-1-i];
        int k = idx / f;
        idx %= f;
        p[i] = avail[k];
        avail.erase(avail.begin() + k);
    }
    return p;
}

// Apply operation (x, y): [prefix_x | middle | suffix_y] -> [suffix | middle | prefix]
vector<int> apply_op(const vector<int>& p, int x, int y) {
    vector<int> q(N);
    for (int i = 0; i < y; i++) q[i] = p[N - y + i];
    int m = N - x - y;
    for (int i = 0; i < m; i++) q[y + i] = p[x + i];
    for (int i = 0; i < x; i++) q[N - x + i] = p[i];
    return q;
}

int main() {
    init_fact();

    // Interesting operations: x,y in {1,2,3,4,5,6,7,8} with x+y < 10
    vector<pair<int,int>> ops;
    set<int> interesting = {1,2,3,4,5,6,7,8};
    for (int x : interesting) {
        for (int y : interesting) {
            if (x + y < N) ops.emplace_back(x, y);
        }
    }
    printf("Number of interesting operations: %d\n", (int)ops.size());

    // Goal state: [0,1,2,...,9] (0-indexed)
    vector<int> goal(N);
    iota(goal.begin(), goal.end(), 0);
    int goal_idx = encode(goal);

    // Reverse BFS from goal
    vector<int> dist(NFACT, -1);
    vector<pair<int,int>> parent_op(NFACT, {-1,-1}); // operation that led here in reverse
    vector<int> parent_state(NFACT, -1);

    queue<int> bfs;
    dist[goal_idx] = 0;
    bfs.push(goal_idx);

    int max_dist = 0;
    int visited = 1;

    while (!bfs.empty()) {
        int cur = bfs.front(); bfs.pop();
        vector<int> p = decode(cur);

        if (dist[cur] >= 6) continue; // Don't explore beyond depth 6

        for (auto& [x, y] : ops) {
            // Reverse of (x,y) is (y,x) applied to current state
            vector<int> np = apply_op(p, y, x);
            int ni = encode(np);
            if (dist[ni] == -1) {
                dist[ni] = dist[cur] + 1;
                parent_op[ni] = {x, y}; // forward op that would go from np to p
                parent_state[ni] = cur;
                bfs.push(ni);
                visited++;
                max_dist = max(max_dist, dist[ni]);
            }
        }
    }

    printf("Max distance explored: %d, states visited: %d / %d\n", max_dist, visited, NFACT);

    // Now check all 120 starting permutations for k=5 endgame
    // Start: [0,1,2,3,4, perm(5,6,7,8,9)] (0-indexed: sorted prefix is 0..4, buffer is 5..9)
    vector<int> buffer_elems = {5,6,7,8,9};

    int max_endgame_ops = 0;
    int total_ops = 0;
    map<int, int> ops_histogram; // distance -> count

    printf("\n=== k=5 Endgame Results (n=10) ===\n");

    sort(buffer_elems.begin(), buffer_elems.end());
    int config_count = 0;
    do {
        vector<int> start = {0,1,2,3,4};
        start.insert(start.end(), buffer_elems.begin(), buffer_elems.end());
        int si = encode(start);

        if (si == goal_idx) continue; // already sorted

        config_count++;
        int d = dist[si];

        if (d == -1) {
            printf("CONFIG %d: UNREACHABLE! perm=[", config_count);
            for (int v : buffer_elems) printf("%d ", v+1);
            printf("]\n");
        } else {
            ops_histogram[d]++;
            max_endgame_ops = max(max_endgame_ops, d);
            total_ops += d;

            if (d >= 4) {
                // Print sequence for high-cost configs
                printf("CONFIG %d (cost=%d): buffer=[", config_count, d);
                for (int v : buffer_elems) printf("%d ", v+1);
                printf("] ops: ");

                // Trace path from start to goal
                int cur = si;
                while (cur != goal_idx) {
                    auto [ox, oy] = parent_op[cur];
                    // Map to n-dependent: values 5,6,7,8 -> n-5,n-4,n-3,n-2
                    string sx = (ox <= 4) ? to_string(ox) : "n-" + to_string(N-ox);
                    string sy = (oy <= 4) ? to_string(oy) : "n-" + to_string(N-oy);
                    printf("(%s,%s) ", sx.c_str(), sy.c_str());

                    // Apply forward op to get next state
                    vector<int> p = decode(cur);
                    vector<int> np = apply_op(p, ox, oy);
                    cur = encode(np);
                }
                printf("\n");
            }
        }
    } while (next_permutation(buffer_elems.begin(), buffer_elems.end()));

    printf("\n=== Summary ===\n");
    printf("Non-identity configs: %d\n", config_count);
    printf("Max endgame ops: %d\n", max_endgame_ops);
    printf("Average endgame ops: %.2f\n", (double)total_ops / config_count);
    printf("Histogram:\n");
    for (auto& [d, c] : ops_histogram) {
        printf("  %d ops: %d configs\n", d, c);
    }

    // Worst-case total for main algorithm
    // Element 1: <=2 ops
    // Main loop (elements 2..n-5): 2*(n-6) ops
    // Endgame (last 5 elements): max_endgame_ops ops
    // Total: 2 + 2*(n-6) + max_endgame_ops = 2n-10 + max_endgame_ops
    printf("\nWorst-case formula: 2n - 10 + %d = 2n - %d\n", max_endgame_ops, 10 - max_endgame_ops);
    printf("For n=1000: %d ops\n", 2*1000 - 10 + max_endgame_ops);

    return 0;
}
