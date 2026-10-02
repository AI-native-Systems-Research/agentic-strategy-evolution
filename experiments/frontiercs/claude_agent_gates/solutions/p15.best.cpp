// Greedy: at each step, try all valid (x,y) and pick the operation giving
// the lexicographically smallest result. Stop when no improvement possible.
// Optimize by first finding best first element, then breaking ties.
#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n;
    cin >> n;
    vector<int> p(n);
    for(int i = 0; i < n; i++) cin >> p[i];
    
    vector<pair<int,int>> ops;
    
    // Apply operation: result = p[n-y..n-1] + p[x..n-y-1] + p[0..x-1]
    auto do_op = [&](vector<int>& v, int x, int y) {
        vector<int> nv;
        nv.reserve(n);
        for(int i = n - y; i < n; i++) nv.push_back(v[i]);
        for(int i = x; i < n - y; i++) nv.push_back(v[i]);
        for(int i = 0; i < x; i++) nv.push_back(v[i]);
        v = nv;
    };
    
    // Get element at position ri in the result of operation (x,y)
    auto get_result_elem = [&](const vector<int>& v, int x, int y, int ri) -> int {
        if(ri < y) return v[n - y + ri];
        else if(ri < n - x) return v[x + ri - y];
        else return v[ri - (n - x)];
    };
    
    for(int step = 0; step < 4 * n; step++){
        // Check if sorted
        bool sorted_flag = true;
        for(int i = 0; i < n; i++){
            if(p[i] != i + 1){ sorted_flag = false; break; }
        }
        if(sorted_flag) break;
        
        // Find the best (x,y) operation
        // Result of (x,y): first element = p[n-y]
        // n-y ranges from 2 to n-1 (since y from 1 to n-2)
        
        // Find minimum possible first element
        int min_first = n + 1;
        for(int j = 2; j < n; j++) min_first = min(min_first, p[j]);
        
        if(min_first > p[0]) break; // no operation can improve
        
        // Collect all y values where p[n-y] = min_first (if min_first < p[0])
        // or also consider min_first == p[0] case
        
        // Actually let's be more careful: compare against current (no-op)
        // If min_first > p[0], no improvement -> break
        // If min_first == p[0], we need to check further elements
        // If min_first < p[0], definitely use an operation with that first element
        
        int best_x = -1, best_y = -1;
        
        // We'll iterate over all (x,y) pairs but with pruning
        // Sort candidates by: first by the value of first element, then compare rest
        
        // Method: maintain best_result as a vector, compare new candidates
        vector<int> best_result = p; // no-op result
        bool found_better = false;
        
        for(int y = 1; y <= n - 2; y++){
            int first_elem = p[n - y];
            // Quick prune: if first element already worse than best, skip
            if(first_elem > best_result[0]) continue;
            
            for(int x = 1; x + y < n; x++){
                // Compare result of (x,y) with best_result
                bool is_better = false;
                bool is_worse = false;
                for(int ri = 0; ri < n; ri++){
                    int val = get_result_elem(p, x, y, ri);
                    if(val < best_result[ri]){ is_better = true; break; }
                    if(val > best_result[ri]){ is_worse = true; break; }
                }
                if(is_better){
                    best_x = x; best_y = y;
                    found_better = true;
                    best_result.clear();
                    best_result.reserve(n);
                    for(int ri = 0; ri < n; ri++){
                        best_result.push_back(get_result_elem(p, x, y, ri));
                    }
                }
            }
        }
        
        if(!found_better) break;
        
        do_op(p, best_x, best_y);
        ops.push_back({best_x, best_y});
    }
    
    cout << ops.size() << "\n";
    for(auto& [x, y] : ops){
        cout << x << " " << y << "\n";
    }
    
    return 0;
}
