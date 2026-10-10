#include <bits/stdc++.h>
using namespace std;

// Generate the k=5 endgame solution by:
// 1. Running BFS at n=11
// 2. Extracting operation sequences
// 3. Testing the complete algorithm at n=1000
// 4. Outputting the solution.cpp code

const int BFS_N = 11;
int fact_arr[BFS_N+1];

void init_fact() {
    fact_arr[0] = 1;
    for (int i = 1; i <= BFS_N; i++) fact_arr[i] = fact_arr[i-1] * i;
}

int encode(const int* p) {
    int idx = 0;
    bool used[BFS_N] = {};
    for (int i = 0; i < BFS_N; i++) {
        int cnt = 0;
        for (int j = 0; j < p[i]; j++) if (!used[j]) cnt++;
        idx += cnt * fact_arr[BFS_N-1-i];
        used[p[i]] = true;
    }
    return idx;
}

void decode(int idx, int* p) {
    int avail[BFS_N];
    for (int i = 0; i < BFS_N; i++) avail[i] = i;
    int sz = BFS_N;
    for (int i = 0; i < BFS_N; i++) {
        int f = fact_arr[BFS_N-1-i];
        int k = idx / f;
        idx %= f;
        p[i] = avail[k];
        for (int j = k; j < sz-1; j++) avail[j] = avail[j+1];
        sz--;
    }
}

void apply_bfs_op(const int* p, int x, int y, int* q) {
    for (int i = 0; i < y; i++) q[i] = p[BFS_N - y + i];
    int m = BFS_N - x - y;
    for (int i = 0; i < m; i++) q[y + i] = p[x + i];
    for (int i = 0; i < x; i++) q[BFS_N - x + i] = p[i];
}

struct Op {
    bool x_ndep; int x_val; // x_ndep: true means "n - x_val", false means literal x_val
    bool y_ndep; int y_val;
    pair<int,int> resolve(int n) const {
        return { x_ndep ? n - x_val : x_val, y_ndep ? n - y_val : y_val };
    }
};

struct EndgameEntry {
    int offsets[5]; // 1..5 mapping to n-4..n
    vector<Op> ops;
};

int main() {
    init_fact();
    int NFACT = fact_arr[BFS_N];

    // Interesting operations
    vector<pair<int,int>> bfs_ops;
    for (int x : {1,2,3,4,6,7,8,9})
        for (int y : {1,2,3,4,6,7,8,9})
            if (x + y < BFS_N) bfs_ops.emplace_back(x, y);

    // Reverse BFS from goal
    vector<signed char> dist(NFACT, -1);
    int goal_p[BFS_N];
    for (int i = 0; i < BFS_N; i++) goal_p[i] = i;
    int goal_idx = encode(goal_p);

    queue<int> bfs;
    dist[goal_idx] = 0;
    bfs.push(goal_idx);

    while (!bfs.empty()) {
        int cur = bfs.front(); bfs.pop();
        int d = dist[cur];
        if (d >= 7) continue;
        int p[BFS_N];
        decode(cur, p);
        for (auto& [x, y] : bfs_ops) {
            int np[BFS_N];
            apply_bfs_op(p, y, x, np);
            int ni = encode(np);
            if (dist[ni] == -1) {
                dist[ni] = d + 1;
                bfs.push(ni);
            }
        }
    }

    // Build endgame table
    vector<EndgameEntry> table;
    vector<int> buf = {6,7,8,9,10};
    sort(buf.begin(), buf.end());

    do {
        int start[BFS_N] = {0,1,2,3,4,5};
        for (int i = 0; i < 5; i++) start[6+i] = buf[i];
        int si = encode(start);
        if (si == goal_idx) continue;

        EndgameEntry entry;
        for (int i = 0; i < 5; i++) entry.offsets[i] = buf[i] - 5; // 1..5

        // Trace path using greedy forward search guided by distance
        int cur = si;
        while (cur != goal_idx) {
            int cur_d = dist[cur];
            int p[BFS_N];
            decode(cur, p);
            bool found = false;
            for (auto& [x, y] : bfs_ops) {
                int np[BFS_N];
                apply_bfs_op(p, x, y, np);
                int ni = encode(np);
                if (dist[ni] == cur_d - 1) {
                    Op op;
                    op.x_ndep = (x > 4);
                    op.x_val = (x > 4) ? BFS_N - x : x;
                    op.y_ndep = (y > 4);
                    op.y_val = (y > 4) ? BFS_N - y : y;
                    entry.ops.push_back(op);
                    cur = ni;
                    found = true;
                    break;
                }
            }
            if (!found) { fprintf(stderr, "BUG: stuck!\n"); exit(1); }
        }
        table.push_back(entry);
    } while (next_permutation(buf.begin(), buf.end()));

    fprintf(stderr, "Endgame table: %d entries\n", (int)table.size());

    // ======= VERIFICATION at n=1000 =======
    fprintf(stderr, "\nVerifying at n=1000 with random permutations...\n");

    auto apply_fn = [](vector<int>& p, int x, int y) {
        int n = p.size();
        vector<int> q(n);
        for (int i = 0; i < y; i++) q[i] = p[n - y + i];
        int m = n - x - y;
        for (int i = 0; i < m; i++) q[y + i] = p[x + i];
        for (int i = 0; i < x; i++) q[n - x + i] = p[i];
        p = q;
    };

    auto is_sorted_fn = [](const vector<int>& p) {
        for (int i = 0; i < (int)p.size(); i++) if (p[i] != i+1) return false;
        return true;
    };

    auto run_algo = [&](vector<int> p) -> pair<bool, int> {
        int n = p.size();
        int ops_count = 0;

        auto do_op = [&](int x, int y) {
            apply_fn(p, x, y);
            ops_count++;
        };

        if (is_sorted_fn(p)) return {true, 0};

        if (n <= 5) {
            // Fallback for small n (same as k=4 solution)
            // Place element 1
            int pos = -1;
            for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }
            if (pos == 1) { do_op(2, 1); do_op(1, 1); }
            else if (pos >= 2) { do_op(1, n - pos); }

            int cf = 1;
            for (int targ = 2; targ <= n - 2; targ++) {
                int j = -1;
                for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }
                if (j == cf) { cf++; continue; }
                int l = n - cf, d = j - cf, d1, d2;
                if (d >= 2) { d1 = 1; d2 = d - 1; }
                else { d1 = 2; d2 = l - 1; }
                do_op(cf, l - d1);
                do_op(d2, cf);
                cf++;
            }
            if (!is_sorted_fn(p)) {
                do_op(1,1); do_op(1,2); do_op(1,1); do_op(2,1); do_op(1,1);
            }
            return {is_sorted_fn(p), ops_count};
        }

        // n >= 6: Place element 1
        {
            int pos = -1;
            for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }
            if (pos == 1) { do_op(2, 1); do_op(1, 1); }
            else if (pos >= 2) { do_op(1, n - pos); }
        }

        int cf = 1;

        // Main loop: elements 2..n-5
        for (int targ = 2; targ <= n - 5; targ++) {
            int j = -1;
            for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }
            if (j == cf) { cf++; continue; }
            int l = n - cf, d = j - cf, d1, d2;
            if (d >= 2) { d1 = 1; d2 = d - 1; }
            else { d1 = 2; d2 = l - 1; }
            do_op(cf, l - d1);
            do_op(d2, cf);
            cf++;
        }

        // k=5 endgame
        if (!is_sorted_fn(p)) {
            // Identify the configuration
            int a = p[n-5], b = p[n-4], c = p[n-3], d = p[n-2], e = p[n-1];
            // Convert to offsets: val - (n-4) + 1, giving 1..5
            int oa = a - (n-4) + 1, ob = b - (n-4) + 1, oc = c - (n-4) + 1;
            int od = d - (n-4) + 1, oe = e - (n-4) + 1;

            // Find matching entry in table
            bool found = false;
            for (auto& entry : table) {
                if (entry.offsets[0] == oa && entry.offsets[1] == ob &&
                    entry.offsets[2] == oc && entry.offsets[3] == od &&
                    entry.offsets[4] == oe) {
                    for (auto& op : entry.ops) {
                        auto [rx, ry] = op.resolve(n);
                        do_op(rx, ry);
                    }
                    found = true;
                    break;
                }
            }
            if (!found) {
                fprintf(stderr, "No matching endgame entry for offsets [%d,%d,%d,%d,%d]\n",
                        oa, ob, oc, od, oe);
                return {false, ops_count};
            }
        }

        return {is_sorted_fn(p), ops_count};
    };

    // Test with random permutations
    mt19937 rng(42);
    int test_n = 1000;
    int num_tests = 200;
    int max_ops = 0, min_ops = INT_MAX;
    long long total = 0;
    int failures = 0;

    for (int t = 0; t < num_tests; t++) {
        vector<int> perm(test_n);
        iota(perm.begin(), perm.end(), 1);
        shuffle(perm.begin(), perm.end(), rng);

        auto [ok, ops] = run_algo(perm);
        if (!ok) {
            failures++;
            if (failures <= 3) {
                fprintf(stderr, "FAIL on test %d\n", t);
            }
        } else {
            max_ops = max(max_ops, ops);
            min_ops = min(min_ops, ops);
            total += ops;
        }
    }

    fprintf(stderr, "Random tests: %d/%d pass\n", num_tests - failures, num_tests);
    fprintf(stderr, "Ops: min=%d, max=%d, avg=%.1f\n", min_ops, max_ops, (double)total / (num_tests - failures));
    fprintf(stderr, "Theoretical worst case: 2n-5 = %d\n", 2*test_n - 5);

    // Also test all 119 endgame configs directly at n=1000
    fprintf(stderr, "\nVerifying all 119 endgame configs at n=1000...\n");
    int eg_errors = 0;
    for (auto& entry : table) {
        vector<int> p(test_n);
        for (int i = 0; i < test_n - 5; i++) p[i] = i + 1; // sorted prefix
        for (int i = 0; i < 5; i++) p[test_n-5+i] = (test_n-4) + entry.offsets[i] - 1;

        for (auto& op : entry.ops) {
            auto [rx, ry] = op.resolve(test_n);
            apply_fn(p, rx, ry);
        }

        if (!is_sorted_fn(p)) {
            eg_errors++;
            if (eg_errors <= 3) {
                fprintf(stderr, "FAIL: offsets=[%d,%d,%d,%d,%d]\n",
                    entry.offsets[0], entry.offsets[1], entry.offsets[2], entry.offsets[3], entry.offsets[4]);
            }
        }
    }
    fprintf(stderr, "Endgame direct test: %d/119 pass (%d errors)\n", 119 - eg_errors, eg_errors);

    // ======= GENERATE SOLUTION CODE =======
    if (failures == 0 && eg_errors == 0) {
        fprintf(stderr, "\n=== ALL TESTS PASSED — Generating solution.cpp ===\n");

        // Output the solution to stdout
        printf("#include <bits/stdc++.h>\n");
        printf("using namespace std;\n\n");
        printf("int main() {\n");
        printf("    ios::sync_with_stdio(false);\n");
        printf("    cin.tie(nullptr);\n\n");
        printf("    int n;\n");
        printf("    cin >> n;\n");
        printf("    vector<int> p(n);\n");
        printf("    for (int i = 0; i < n; i++) cin >> p[i];\n\n");
        printf("    vector<pair<int,int>> ops;\n\n");
        printf("    auto apply = [&](int x, int y) {\n");
        printf("        vector<int> q(n);\n");
        printf("        for (int i = 0; i < y; i++) q[i] = p[n - y + i];\n");
        printf("        int m = n - x - y;\n");
        printf("        for (int i = 0; i < m; i++) q[y + i] = p[x + i];\n");
        printf("        for (int i = 0; i < x; i++) q[n - x + i] = p[i];\n");
        printf("        p = q;\n");
        printf("        ops.emplace_back(x, y);\n");
        printf("    };\n\n");
        printf("    auto is_sorted_fn = [&]() {\n");
        printf("        for (int i = 0; i < n; i++) if (p[i] != i + 1) return false;\n");
        printf("        return true;\n");
        printf("    };\n\n");
        printf("    if (is_sorted_fn()) {\n");
        printf("        cout << 0 << \"\\n\";\n");
        printf("        return 0;\n");
        printf("    }\n\n");

        // Small n fallback
        printf("    if (n <= 5) {\n");
        printf("        // Fallback for small n\n");
        printf("        if (n == 3) {\n");
        printf("            if (p[2] < p[0]) apply(1, 1);\n");
        printf("            cout << ops.size() << \"\\n\";\n");
        printf("            for (auto& op : ops) cout << op.first << \" \" << op.second << \"\\n\";\n");
        printf("            return 0;\n");
        printf("        }\n");
        printf("        // n=4 or 5\n");
        printf("        int pos = -1;\n");
        printf("        for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }\n");
        printf("        if (pos == 1) { apply(2, 1); apply(1, 1); }\n");
        printf("        else if (pos >= 2) { apply(1, n - pos); }\n");
        printf("        int cf = 1;\n");
        printf("        for (int targ = 2; targ <= n - 2; targ++) {\n");
        printf("            int j = -1;\n");
        printf("            for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }\n");
        printf("            if (j == cf) { cf++; continue; }\n");
        printf("            int l = n - cf, d = j - cf, d1, d2;\n");
        printf("            if (d >= 2) { d1 = 1; d2 = d - 1; } else { d1 = 2; d2 = l - 1; }\n");
        printf("            apply(cf, l - d1); apply(d2, cf); cf++;\n");
        printf("        }\n");
        printf("        if (!is_sorted_fn()) { apply(1,1); apply(1,2); apply(1,1); apply(2,1); apply(1,1); }\n");
        printf("        cout << ops.size() << \"\\n\";\n");
        printf("        for (auto& op : ops) cout << op.first << \" \" << op.second << \"\\n\";\n");
        printf("        return 0;\n");
        printf("    }\n\n");

        // Main algorithm for n >= 6
        printf("    // n >= 6: Place element 1\n");
        printf("    {\n");
        printf("        int pos = -1;\n");
        printf("        for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }\n");
        printf("        if (pos == 1) { apply(2, 1); apply(1, 1); }\n");
        printf("        else if (pos >= 2) { apply(1, n - pos); }\n");
        printf("    }\n\n");

        printf("    int cf = 1;\n\n");
        printf("    // Main loop: place elements 2 through n-5\n");
        printf("    for (int targ = 2; targ <= n - 5; targ++) {\n");
        printf("        int j = -1;\n");
        printf("        for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }\n");
        printf("        if (j == cf) { cf++; continue; }\n");
        printf("        int l = n - cf, d = j - cf, d1, d2;\n");
        printf("        if (d >= 2) { d1 = 1; d2 = d - 1; } else { d1 = 2; d2 = l - 1; }\n");
        printf("        apply(cf, l - d1); apply(d2, cf); cf++;\n");
        printf("    }\n\n");

        printf("    // k=5 endgame: handle last 5 elements\n");
        printf("    if (!is_sorted_fn()) {\n");
        printf("        int a = p[n-5], b = p[n-4], c = p[n-3], d = p[n-2], e = p[n-1];\n\n");

        // Generate all 119 cases
        bool first = true;
        for (auto& entry : table) {
            // offsets 1..5 map to n-4..n
            // a == n-4+offsets[0]-1 == n-5+offsets[0]
            string cond = "";
            const char* vars[] = {"a", "b", "c", "d", "e"};
            for (int i = 0; i < 5; i++) {
                if (i > 0) cond += " && ";
                int off = entry.offsets[i]; // 1..5
                // off=1 → n-4, off=2 → n-3, off=3 → n-2, off=4 → n-1, off=5 → n
                string val;
                if (off == 1) val = "n-4";
                else if (off == 2) val = "n-3";
                else if (off == 3) val = "n-2";
                else if (off == 4) val = "n-1";
                else val = "n";
                cond += string(vars[i]) + "==" + val;
            }

            if (first) {
                printf("        if      (%s) {", cond.c_str());
                first = false;
            } else {
                printf("        else if (%s) {", cond.c_str());
            }

            for (auto& op : entry.ops) {
                string sx = op.x_ndep ? "n-" + to_string(op.x_val) : to_string(op.x_val);
                string sy = op.y_ndep ? "n-" + to_string(op.y_val) : to_string(op.y_val);
                printf(" apply(%s,%s);", sx.c_str(), sy.c_str());
            }
            printf(" }\n");
        }

        printf("    }\n\n");
        printf("    cout << ops.size() << \"\\n\";\n");
        printf("    for (auto& op : ops) cout << op.first << \" \" << op.second << \"\\n\";\n");
        printf("    return 0;\n");
        printf("}\n");
    }

    return 0;
}
