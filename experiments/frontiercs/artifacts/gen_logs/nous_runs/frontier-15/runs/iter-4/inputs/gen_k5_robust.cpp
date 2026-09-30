#include <bits/stdc++.h>
using namespace std;

// Robust k=5 endgame solution generator
// Key fix: path tracing verifies each sequence at n=100 before accepting

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
    bool x_ndep; int x_val;
    bool y_ndep; int y_val;
    pair<int,int> resolve(int n) const {
        return { x_ndep ? n - x_val : x_val, y_ndep ? n - y_val : y_val };
    }
};

void apply_gen(vector<int>& p, int x, int y) {
    int n = p.size();
    vector<int> q(n);
    for (int i = 0; i < y; i++) q[i] = p[n - y + i];
    int m = n - x - y;
    for (int i = 0; i < m; i++) q[y + i] = p[x + i];
    for (int i = 0; i < x; i++) q[n - x + i] = p[i];
    p = q;
}

bool is_sorted_gen(const vector<int>& p) {
    for (int i = 0; i < (int)p.size(); i++) if (p[i] != i + 1) return false;
    return true;
}

// Verify a sequence of operations on a given n
bool verify_sequence(const int* offsets, const vector<Op>& ops, int n) {
    vector<int> p(n);
    for (int i = 0; i < n - 5; i++) p[i] = i + 1;
    for (int i = 0; i < 5; i++) p[n-5+i] = (n-4) + offsets[i] - 1;

    for (auto& op : ops) {
        auto [rx, ry] = op.resolve(n);
        if (rx <= 0 || ry <= 0 || rx + ry >= n) return false;
        apply_gen(p, rx, ry);
    }
    return is_sorted_gen(p);
}

int main() {
    init_fact();
    int NFACT = fact_arr[BFS_N];

    vector<pair<int,int>> bfs_ops;
    for (int x : {1,2,3,4,6,7,8,9})
        for (int y : {1,2,3,4,6,7,8,9})
            if (x + y < BFS_N) bfs_ops.emplace_back(x, y);

    // Reverse BFS
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

    struct EndgameEntry {
        int offsets[5];
        vector<Op> ops;
    };
    vector<EndgameEntry> table;

    // For each config, find a path that works at MULTIPLE n values
    vector<int> buf = {6,7,8,9,10};
    sort(buf.begin(), buf.end());

    int verify_ns[] = {20, 50, 100, 500, 1000};

    do {
        int start[BFS_N] = {0,1,2,3,4,5};
        for (int i = 0; i < 5; i++) start[6+i] = buf[i];
        int si = encode(start);
        if (si == goal_idx) continue;

        EndgameEntry entry;
        for (int i = 0; i < 5; i++) entry.offsets[i] = buf[i] - 5;

        int target_d = dist[si];

        // DFS with backtracking to find a path that generalizes
        struct Frame {
            int state_idx;
            int op_idx; // which operation to try next
        };

        vector<Frame> stack;
        vector<Op> current_ops;
        stack.push_back({si, 0});
        bool found = false;

        while (!stack.empty() && !found) {
            auto& frame = stack.back();
            int cur_d = dist[frame.state_idx];

            if (frame.state_idx == goal_idx) {
                // Check if current_ops works at all verify_ns
                bool all_pass = true;
                for (int vn : verify_ns) {
                    if (!verify_sequence(entry.offsets, current_ops, vn)) {
                        all_pass = false;
                        break;
                    }
                }
                if (all_pass) {
                    entry.ops = current_ops;
                    found = true;
                    break;
                }
                // This path doesn't generalize, backtrack
                stack.pop_back();
                if (!current_ops.empty()) current_ops.pop_back();
                continue;
            }

            // Try next operation from frame.op_idx
            bool advanced = false;
            int p[BFS_N];
            decode(frame.state_idx, p);

            while (frame.op_idx < (int)bfs_ops.size()) {
                auto [x, y] = bfs_ops[frame.op_idx];
                frame.op_idx++;

                int np[BFS_N];
                apply_bfs_op(p, x, y, np);
                int ni = encode(np);

                if (dist[ni] == cur_d - 1) {
                    Op op;
                    op.x_ndep = (x > 4);
                    op.x_val = (x > 4) ? BFS_N - x : x;
                    op.y_ndep = (y > 4);
                    op.y_val = (y > 4) ? BFS_N - y : y;
                    current_ops.push_back(op);
                    stack.push_back({ni, 0});
                    advanced = true;
                    break;
                }
            }

            if (!advanced) {
                // No more operations to try at this level, backtrack
                stack.pop_back();
                if (!current_ops.empty()) current_ops.pop_back();
            }
        }

        if (!found) {
            // Try paths of length target_d + 1 as fallback
            fprintf(stderr, "WARNING: No generalizable path of length %d for offsets [%d,%d,%d,%d,%d]. Trying length %d...\n",
                    target_d, entry.offsets[0], entry.offsets[1], entry.offsets[2], entry.offsets[3], entry.offsets[4], target_d+1);

            // Simple: try all 2-step sequences from here to goal, checking generalization
            // Actually let's use a BFS approach at target_d+1
            // For simplicity, iterate over pairs of first operation + optimal remainder
            stack.clear();
            current_ops.clear();

            // BFS all states reachable in 1 step from si
            int p_start[BFS_N];
            decode(si, p_start);

            for (auto& [x1, y1] : bfs_ops) {
                int mid[BFS_N];
                apply_bfs_op(p_start, x1, y1, mid);
                int mid_idx = encode(mid);

                if (dist[mid_idx] != target_d && dist[mid_idx] != target_d - 1) continue; // not helpful

                // Now find optimal path from mid_idx to goal
                vector<Op> test_ops;
                Op op1;
                op1.x_ndep = (x1 > 4); op1.x_val = (x1 > 4) ? BFS_N - x1 : x1;
                op1.y_ndep = (y1 > 4); op1.y_val = (y1 > 4) ? BFS_N - y1 : y1;
                test_ops.push_back(op1);

                // Greedy trace from mid_idx
                int cur = mid_idx;
                bool trace_ok = true;
                while (cur != goal_idx) {
                    int cur_d2 = dist[cur];
                    int pp[BFS_N];
                    decode(cur, pp);
                    bool step_found = false;
                    for (auto& [x2, y2] : bfs_ops) {
                        int np2[BFS_N];
                        apply_bfs_op(pp, x2, y2, np2);
                        int ni2 = encode(np2);
                        if (dist[ni2] == cur_d2 - 1) {
                            Op op2;
                            op2.x_ndep = (x2 > 4); op2.x_val = (x2 > 4) ? BFS_N - x2 : x2;
                            op2.y_ndep = (y2 > 4); op2.y_val = (y2 > 4) ? BFS_N - y2 : y2;
                            test_ops.push_back(op2);
                            cur = ni2;
                            step_found = true;
                            break;
                        }
                    }
                    if (!step_found) { trace_ok = false; break; }
                }

                if (!trace_ok) continue;

                // Verify at all n values
                bool all_pass = true;
                for (int vn : verify_ns) {
                    if (!verify_sequence(entry.offsets, test_ops, vn)) {
                        all_pass = false;
                        break;
                    }
                }

                if (all_pass) {
                    entry.ops = test_ops;
                    found = true;
                    fprintf(stderr, "  Found at length %d\n", (int)test_ops.size());
                    break;
                }
            }
        }

        if (!found) {
            fprintf(stderr, "FATAL: No generalizable path found for offsets [%d,%d,%d,%d,%d]\n",
                    entry.offsets[0], entry.offsets[1], entry.offsets[2], entry.offsets[3], entry.offsets[4]);
            // Use empty ops (will fail)
        }

        table.push_back(entry);
    } while (next_permutation(buf.begin(), buf.end()));

    fprintf(stderr, "Table: %d entries\n", (int)table.size());

    // Final verification
    int total_errors = 0;
    int max_ops_found = 0;
    for (auto& entry : table) {
        max_ops_found = max(max_ops_found, (int)entry.ops.size());
        for (int vn : verify_ns) {
            if (!verify_sequence(entry.offsets, entry.ops, vn)) {
                total_errors++;
                fprintf(stderr, "VERIFY FAIL: offsets=[%d,%d,%d,%d,%d] at n=%d\n",
                    entry.offsets[0], entry.offsets[1], entry.offsets[2], entry.offsets[3], entry.offsets[4], vn);
            }
        }
    }
    fprintf(stderr, "Final verification: %d errors, max ops per config: %d\n", total_errors, max_ops_found);

    // Full algorithm test at n=1000
    fprintf(stderr, "\nFull algorithm test at n=1000 (200 random perms)...\n");

    auto run_algo = [&](vector<int> p) -> pair<bool, int> {
        int n = p.size();
        int ops_count = 0;
        auto do_op = [&](int x, int y) { apply_gen(p, x, y); ops_count++; };

        if (is_sorted_gen(p)) return {true, 0};
        if (n <= 5) {
            if (n == 3) { if (p[2] < p[0]) do_op(1, 1); return {is_sorted_gen(p), ops_count}; }
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
                if (d >= 2) { d1 = 1; d2 = d - 1; } else { d1 = 2; d2 = l - 1; }
                do_op(cf, l - d1); do_op(d2, cf); cf++;
            }
            if (!is_sorted_gen(p)) { do_op(1,1); do_op(1,2); do_op(1,1); do_op(2,1); do_op(1,1); }
            return {is_sorted_gen(p), ops_count};
        }

        { int pos = -1;
          for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }
          if (pos == 1) { do_op(2, 1); do_op(1, 1); }
          else if (pos >= 2) { do_op(1, n - pos); }
        }
        int cf = 1;
        for (int targ = 2; targ <= n - 5; targ++) {
            int j = -1;
            for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }
            if (j == cf) { cf++; continue; }
            int l = n - cf, d = j - cf, d1, d2;
            if (d >= 2) { d1 = 1; d2 = d - 1; } else { d1 = 2; d2 = l - 1; }
            do_op(cf, l - d1); do_op(d2, cf); cf++;
        }

        if (!is_sorted_gen(p)) {
            int a = p[n-5], b = p[n-4], c = p[n-3], d = p[n-2], e = p[n-1];
            int oa = a-(n-4)+1, ob = b-(n-4)+1, oc = c-(n-4)+1, od = d-(n-4)+1, oe = e-(n-4)+1;
            bool found = false;
            for (auto& entry : table) {
                if (entry.offsets[0]==oa && entry.offsets[1]==ob && entry.offsets[2]==oc &&
                    entry.offsets[3]==od && entry.offsets[4]==oe) {
                    for (auto& op : entry.ops) {
                        auto [rx, ry] = op.resolve(n);
                        do_op(rx, ry);
                    }
                    found = true; break;
                }
            }
            if (!found) return {false, ops_count};
        }
        return {is_sorted_gen(p), ops_count};
    };

    mt19937 rng(42);
    int test_n = 1000, num_tests = 200, failures = 0;
    int max_ops = 0, min_ops = INT_MAX;
    long long total = 0;
    for (int t = 0; t < num_tests; t++) {
        vector<int> perm(test_n);
        iota(perm.begin(), perm.end(), 1);
        shuffle(perm.begin(), perm.end(), rng);
        auto [ok, ops] = run_algo(perm);
        if (!ok) { failures++; }
        else { max_ops = max(max_ops, ops); min_ops = min(min_ops, ops); total += ops; }
    }
    fprintf(stderr, "Random tests: %d/%d pass\n", num_tests - failures, num_tests);
    fprintf(stderr, "Ops: min=%d, max=%d, avg=%.1f\n", min_ops, max_ops, (double)total/(num_tests-failures));

    if (failures > 0 || total_errors > 0) {
        fprintf(stderr, "ERRORS REMAIN — not generating solution\n");
        return 1;
    }

    // Generate solution code to stdout
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
    printf("    if (is_sorted_fn()) { cout << 0 << \"\\n\"; return 0; }\n\n");

    // Small n fallback
    printf("    if (n <= 5) {\n");
    printf("        if (n == 3) { if (p[2] < p[0]) apply(1, 1); }\n");
    printf("        else {\n");
    printf("            int pos = -1;\n");
    printf("            for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }\n");
    printf("            if (pos == 1) { apply(2, 1); apply(1, 1); }\n");
    printf("            else if (pos >= 2) { apply(1, n - pos); }\n");
    printf("            int cf = 1;\n");
    printf("            for (int targ = 2; targ <= n - 2; targ++) {\n");
    printf("                int j = -1;\n");
    printf("                for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }\n");
    printf("                if (j == cf) { cf++; continue; }\n");
    printf("                int l = n - cf, d = j - cf, d1, d2;\n");
    printf("                if (d >= 2) { d1 = 1; d2 = d - 1; } else { d1 = 2; d2 = l - 1; }\n");
    printf("                apply(cf, l - d1); apply(d2, cf); cf++;\n");
    printf("            }\n");
    printf("            if (!is_sorted_fn()) { apply(1,1); apply(1,2); apply(1,1); apply(2,1); apply(1,1); }\n");
    printf("        }\n");
    printf("        cout << ops.size() << \"\\n\";\n");
    printf("        for (auto& op : ops) cout << op.first << \" \" << op.second << \"\\n\";\n");
    printf("        return 0;\n");
    printf("    }\n\n");

    printf("    // n >= 6: Place element 1\n");
    printf("    {\n");
    printf("        int pos = -1;\n");
    printf("        for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }\n");
    printf("        if (pos == 1) { apply(2, 1); apply(1, 1); }\n");
    printf("        else if (pos >= 2) { apply(1, n - pos); }\n");
    printf("    }\n\n");
    printf("    int cf = 1;\n");
    printf("    for (int targ = 2; targ <= n - 5; targ++) {\n");
    printf("        int j = -1;\n");
    printf("        for (int i = cf; i < n; i++) if (p[i] == targ) { j = i; break; }\n");
    printf("        if (j == cf) { cf++; continue; }\n");
    printf("        int l = n - cf, d = j - cf, d1, d2;\n");
    printf("        if (d >= 2) { d1 = 1; d2 = d - 1; } else { d1 = 2; d2 = l - 1; }\n");
    printf("        apply(cf, l - d1); apply(d2, cf); cf++;\n");
    printf("    }\n\n");

    printf("    // k=5 BFS-optimal endgame\n");
    printf("    if (!is_sorted_fn()) {\n");
    printf("        int a = p[n-5], b = p[n-4], c = p[n-3], d = p[n-2], e = p[n-1];\n\n");

    bool first = true;
    for (auto& entry : table) {
        const char* vars[] = {"a", "b", "c", "d", "e"};
        string cond = "";
        for (int i = 0; i < 5; i++) {
            if (i > 0) cond += " && ";
            int off = entry.offsets[i];
            string val;
            if (off == 1) val = "n-4";
            else if (off == 2) val = "n-3";
            else if (off == 3) val = "n-2";
            else if (off == 4) val = "n-1";
            else val = "n";
            cond += string(vars[i]) + "==" + val;
        }

        if (first) { printf("        if      (%s) {", cond.c_str()); first = false; }
        else printf("        else if (%s) {", cond.c_str());

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

    return 0;
}
