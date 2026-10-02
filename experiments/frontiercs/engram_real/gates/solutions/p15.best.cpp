// Approach: 
// - For n=3: orbit is {p, reverse(p)}, pick lex min.
// - For small n (<=10): BFS to find shortest path to identity.
// - For larger n: greedy placement using 2 ops per element (Cases A, B).
//   Handle last 3 elements with meet-in-the-middle search.
#include <bits/stdc++.h>
using namespace std;

int n;

vector<int> do_op(const vector<int>& p, int x, int y) {
    int sz = p.size();
    vector<int> np(sz);
    for(int i = 0; i < y; i++) np[i] = p[sz-y+i];
    for(int i = x; i < sz-y; i++) np[y+i-x] = p[i];
    for(int i = 0; i < x; i++) np[sz-x+i] = p[i];
    return np;
}

struct VectorHash {
    size_t operator()(const vector<int>& v) const {
        size_t seed = v.size();
        for (auto& i : v) {
            seed ^= i + 0x9e3779b9 + (seed << 6) + (seed >> 2);
        }
        return seed;
    }
};

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    cin >> n;
    vector<int> p(n);
    for(int i = 0; i < n; i++) cin >> p[i];
    
    vector<pair<int,int>> ops;
    
    auto apply_op = [&](int x, int y) {
        p = do_op(p, x, y);
        ops.push_back({x, y});
    };
    
    if(n == 3) {
        vector<int> rev_p = {p[2], p[1], p[0]};
        if(rev_p < p) {
            apply_op(1, 1);
        }
        cout << ops.size() << "\n";
        for(auto& [x,y] : ops) cout << x << " " << y << "\n";
        return 0;
    }
    
    // n >= 4: target is sorted [1, 2, ..., n]
    vector<int> target(n);
    for(int i = 0; i < n; i++) target[i] = i + 1;
    
    if(p == target) {
        cout << 0 << "\n";
        return 0;
    }
    
    // For small n, use BFS
    if(n <= 10) {
        unordered_map<vector<int>, pair<vector<int>, pair<int,int>>, VectorHash> parent;
        queue<vector<int>> q;
        q.push(p);
        parent[p] = {p, {-1, -1}};
        
        bool found = false;
        while(!q.empty() && !found) {
            auto cur = q.front(); q.pop();
            for(int x = 1; x < n && !found; x++) {
                for(int y = 1; x + y < n && !found; y++) {
                    auto nxt = do_op(cur, x, y);
                    if(parent.find(nxt) == parent.end()) {
                        parent[nxt] = {cur, {x, y}};
                        if(nxt == target) {
                            found = true;
                        }
                        q.push(nxt);
                    }
                }
            }
        }
        
        if(found) {
            vector<pair<int,int>> path;
            auto cur = target;
            while(cur != p) {
                auto& [prev, op] = parent[cur];
                path.push_back(op);
                cur = prev;
            }
            reverse(path.begin(), path.end());
            cout << path.size() << "\n";
            for(auto& [x,y] : path) cout << x << " " << y << "\n";
        } else {
            cout << 0 << "\n";
        }
        return 0;
    }
    
    // For larger n: greedy placement
    auto find_pos = [&](int val) -> int {
        for(int i = 0; i < n; i++) if(p[i] == val) return i;
        return -1;
    };
    
    // Place elements 1 through n-4
    // (we'll handle the last 3 elements separately)
    for(int k = 0; k <= n-4; k++) {
        int val = k + 1;
        int pos = find_pos(val);
        if(pos == k) continue;
        
        if(k == 0) {
            if(pos > 1) {
                apply_op(1, n - pos);
            } else {
                // pos == 1
                apply_op(2, 1);
                apply_op(1, 1);
            }
        } else {
            // k >= 1, pos > k
            if(pos < n - 1) {
                // Case A: 2 ops
                apply_op(k, n - pos - 1);
                apply_op(n - k - 1, k);
            } else {
                // pos == n-1, Case B
                // Need k < n-2
                if(k < n - 2) {
                    apply_op(k, n - k - 1);
                    apply_op(n - k - 2, k);
                } else {
                    // k == n-2 shouldn't happen in this loop (we go to n-4)
                }
            }
        }
    }
    
    // Now positions 0..n-4 should have [1,...,n-3]
    // Positions n-3, n-2, n-1 have some permutation of {n-2, n-1, n}
    
    if(p == target) {
        cout << ops.size() << "\n";
        for(auto& [x,y] : ops) cout << x << " " << y << "\n";
        return 0;
    }
    
    // Sort last 3 elements using additional operations
    // Strategy: try 1 op, then meet-in-middle for 2 ops, then 3 ops
    
    // Try 1 op
    bool fixed = false;
    for(int x = 1; x < n && !fixed; x++) {
        for(int y = 1; x + y < n && !fixed; y++) {
            if(do_op(p, x, y) == target) {
                apply_op(x, y);
                fixed = true;
            }
        }
    }
    
    if(!fixed) {
        // Meet-in-middle for 2 ops
        // Forward: states reachable from p in 1 op
        // Backward: states reachable from target in 1 op (inverse reaches target)
        
        unordered_map<vector<int>, pair<int,int>, VectorHash> backward;
        for(int x = 1; x < n; x++) {
            for(int y = 1; x + y < n; y++) {
                auto state = do_op(target, x, y);
                if(backward.find(state) == backward.end()) {
                    backward[state] = {x, y};
                }
            }
        }
        
        for(int x = 1; x < n && !fixed; x++) {
            for(int y = 1; x + y < n && !fixed; y++) {
                auto mid_state = do_op(p, x, y);
                auto it = backward.find(mid_state);
                if(it != backward.end()) {
                    auto [x2, y2] = it->second;
                    // do_op(target, x2, y2) = mid_state
                    // inverse: do_op(mid_state, y2, x2) = target
                    apply_op(x, y);
                    apply_op(y2, x2);
                    fixed = true;
                }
            }
        }
    }
    
    if(!fixed) {
        // 3 ops: try forward 2 steps, backward 1 step (meet in middle)
        // Build backward set (already have it? let me rebuild)
        
        unordered_map<vector<int>, pair<int,int>, VectorHash> backward;
        for(int x = 1; x < n; x++) {
            for(int y = 1; x + y < n; y++) {
                auto state = do_op(target, x, y);
                if(backward.find(state) == backward.end()) {
                    backward[state] = {x, y};
                }
            }
        }
        
        // Forward 2 steps from p
        for(int x1 = 1; x1 < n && !fixed; x1++) {
            for(int y1 = 1; x1 + y1 < n && !fixed; y1++) {
                auto s1 = do_op(p, x1, y1);
                for(int x2 = 1; x2 < n && !fixed; x2++) {
                    for(int y2 = 1; x2 + y2 < n && !fixed; y2++) {
                        auto s2 = do_op(s1, x2, y2);
                        auto it = backward.find(s2);
                        if(it != backward.end()) {
                            auto [x3, y3] = it->second;
                            apply_op(x1, y1);
                            apply_op(x2, y2);
                            apply_op(y3, x3);
                            fixed = true;
                        }
                    }
                }
            }
        }
    }
    
    if(!fixed) {
        // This shouldn't happen, but just in case, try more ops
        // Fallback: brute force more
        cerr << "ERROR: Could not sort last 3 elements" << endl;
    }
    
    cout << ops.size() << "\n";
    for(auto& [x,y] : ops) cout << x << " " << y << "\n";
    
    return 0;
}
