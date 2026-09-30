#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    cin >> n;
    vector<int> p(n);
    for (int i = 0; i < n; i++) cin >> p[i];

    vector<pair<int,int>> ops;

    // Apply operation: [prefix x | middle | suffix y] -> [suffix | middle | prefix]
    auto apply = [&](int x, int y) {
        vector<int> q(n);
        for (int i = 0; i < y; i++) q[i] = p[n - y + i];
        int m = n - x - y;
        for (int i = 0; i < m; i++) q[y + i] = p[x + i];
        for (int i = 0; i < x; i++) q[n - x + i] = p[i];
        p = q;
        ops.emplace_back(x, y);
    };

    auto is_sorted_fn = [&]() {
        for (int i = 0; i < n; i++) if (p[i] != i + 1) return false;
        return true;
    };

    if (is_sorted_fn()) {
        cout << 0 << "\n";
        return 0;
    }

    if (n == 3) {
        if (p[2] < p[0]) apply(1, 1);
        cout << ops.size() << "\n";
        for (auto& op : ops) cout << op.first << " " << op.second << "\n";
        return 0;
    }

    // n >= 4: Place element 1 at position 0
    {
        int pos = -1;
        for (int i = 0; i < n; i++) if (p[i] == 1) { pos = i; break; }
        if (pos == 1) {
            apply(2, 1);
            apply(1, 1);
        } else if (pos >= 2) {
            apply(1, n - pos);
        }
    }

    int cf = 1;

    if (n <= 5) {
        // For small n, use iter-1 algorithm (main loop to n-2, 5-op endgame)
        for (int targ = 2; targ <= n - 2; targ++) {
            int j = -1;
            for (int i = cf; i < n; i++) {
                if (p[i] == targ) { j = i; break; }
            }
            if (j == cf) { cf++; continue; }

            int l = n - cf;
            int d = j - cf;
            int d1, d2;
            if (d >= 2) { d1 = 1; d2 = d - 1; }
            else { d1 = 2; d2 = l - 1; }
            apply(cf, l - d1);
            apply(d2, cf);
            cf++;
        }

        // 5-op endgame for last 2 elements
        if (!is_sorted_fn()) {
            apply(1, 1); apply(1, 2); apply(1, 1); apply(2, 1); apply(1, 1);
        }
    } else {
        // n >= 6: main loop to n-4, then k=4 endgame
        for (int targ = 2; targ <= n - 4; targ++) {
            int j = -1;
            for (int i = cf; i < n; i++) {
                if (p[i] == targ) { j = i; break; }
            }
            if (j == cf) { cf++; continue; }

            int l = n - cf;
            int d = j - cf;
            int d1, d2;
            if (d >= 2) { d1 = 1; d2 = d - 1; }
            else { d1 = 2; d2 = l - 1; }
            apply(cf, l - d1);
            apply(d2, cf);
            cf++;
        }

        // k=4 endgame: handle last 4 elements with precomputed BFS-optimal sequences
        if (!is_sorted_fn()) {
            int a = p[n-4], b = p[n-3], c = p[n-2], d = p[n-1];

            // 5 cases where a = n-3 (reduces to k=3 endgame patterns)
            if      (a==n-3 && b==n-2 && c==n   && d==n-1) { apply(1,2); apply(1,n-2); apply(1,2); apply(2,2); }
            else if (a==n-3 && b==n-1 && c==n-2 && d==n)   { apply(1,1); apply(1,2); apply(2,2); apply(2,1); }
            else if (a==n-3 && b==n-1 && c==n   && d==n-2) { apply(n-3,2); apply(1,n-3); }
            else if (a==n-3 && b==n   && c==n-2 && d==n-1) { apply(n-3,1); apply(2,n-3); }
            else if (a==n-3 && b==n   && c==n-1 && d==n-2) { apply(1,1); apply(1,3); apply(1,n-2); }
            // 6 cases where a = n-2
            else if (a==n-2 && b==n-3 && c==n-1 && d==n)   { apply(1,2); apply(1,2); apply(2,2); apply(3,1); }
            else if (a==n-2 && b==n-3 && c==n   && d==n-1) { apply(1,3); apply(3,2); apply(1,2); apply(1,n-2); }
            else if (a==n-2 && b==n-1 && c==n-3 && d==n)   { apply(1,1); apply(1,2); apply(2,3); apply(3,1); }
            else if (a==n-2 && b==n-1 && c==n   && d==n-3) { apply(n-4,2); apply(1,n-4); }
            else if (a==n-2 && b==n   && c==n-3 && d==n-1) { apply(1,3); apply(3,2); apply(n-3,1); apply(2,n-4); }
            else if (a==n-2 && b==n   && c==n-1 && d==n-3) { apply(1,1); apply(1,2); apply(n-3,2); apply(1,n-4); }
            // 6 cases where a = n-1
            else if (a==n-1 && b==n-3 && c==n-2 && d==n)   { apply(1,1); apply(1,3); apply(1,2); apply(2,n-3); }
            else if (a==n-1 && b==n-3 && c==n   && d==n-2) { apply(1,2); apply(2,2); apply(1,3); apply(2,n-3); }
            else if (a==n-1 && b==n-2 && c==n-3 && d==n)   { apply(n-4,3); apply(1,n-2); apply(1,n-2); }
            else if (a==n-1 && b==n-2 && c==n   && d==n-3) { apply(1,3); apply(3,2); apply(n-3,2); apply(1,n-4); }
            else if (a==n-1 && b==n   && c==n-3 && d==n-2) { apply(n-4,1); apply(3,n-4); }
            else if (a==n-1 && b==n   && c==n-2 && d==n-3) { apply(n-3,1); apply(1,1); apply(2,n-3); }
            // 6 cases where a = n
            else if (a==n   && b==n-3 && c==n-2 && d==n-1) { apply(n-4,1); apply(2,n-4); }
            else if (a==n   && b==n-3 && c==n-1 && d==n-2) { apply(1,1); apply(1,3); apply(1,2); apply(1,n-3); }
            else if (a==n   && b==n-2 && c==n-3 && d==n-1) { apply(1,1); apply(1,2); apply(1,3); apply(1,n-3); }
            else if (a==n   && b==n-2 && c==n-1 && d==n-3) { apply(n-3,1); apply(1,1); apply(1,n-3); }
            else if (a==n   && b==n-1 && c==n-3 && d==n-2) { apply(1,2); apply(2,3); apply(1,n-2); }
            else if (a==n   && b==n-1 && c==n-2 && d==n-3) { apply(n-4,2); apply(1,n-2); apply(1,n-2); }
        }
    }

    cout << ops.size() << "\n";
    for (auto& op : ops) cout << op.first << " " << op.second << "\n";
    return 0;
}
