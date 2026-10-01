#include <bits/stdc++.h>
using namespace std;

int n;
int X[205], Y[205];
long long R[205];
int A[205], B[205], C[205], D[205];

void solve(vector<int>& ids, int ax, int ay, int cx, int cy) {
    if (ids.empty()) return;
    if (ids.size() == 1) {
        int i = ids[0];
        A[i] = ax; B[i] = ay; C[i] = cx; D[i] = cy;
        return;
    }

    long long total_r = 0;
    for (int i : ids) total_r += R[i];

    double best_score = -1e18;
    vector<int> best_left, best_right;
    int best_split = 0;
    int best_horiz = 0;

    for (int horiz = 0; horiz < 2; horiz++) {
        int span = horiz ? (cy - ay) : (cx - ax);
        if (span < (int)ids.size() * 2) continue; // need enough room

        vector<int> sorted_ids = ids;
        if (horiz)
            sort(sorted_ids.begin(), sorted_ids.end(), [](int a, int b){ return Y[a] < Y[b] || (Y[a]==Y[b] && X[a]<X[b]); });
        else
            sort(sorted_ids.begin(), sorted_ids.end(), [](int a, int b){ return X[a] < X[b] || (X[a]==X[b] && Y[a]<Y[b]); });

        int sz = sorted_ids.size();
        long long r_left = 0;
        for (int k = 1; k < sz; k++) {
            r_left += R[sorted_ids[k-1]];
            double frac = (double)r_left / total_r;

            int coord_left = horiz ? Y[sorted_ids[k-1]] : X[sorted_ids[k-1]];
            int coord_right = horiz ? Y[sorted_ids[k]] : X[sorted_ids[k]];

            int lo = coord_left + 1;
            int hi = coord_right;
            int base = horiz ? ay : ax;
            int end = horiz ? cy : cx;
            lo = max(lo, base + 1);
            hi = min(hi, end - 1);
            if (lo > hi) continue;

            int ideal = (int)round(base + frac * (end - base));
            int split = max(lo, min(hi, ideal));

            double actual_frac = (double)(split - base) / (end - base);
            double diff = frac - actual_frac;
            double score = -diff * diff;

            if (score > best_score) {
                best_score = score;
                best_left.assign(sorted_ids.begin(), sorted_ids.begin() + k);
                best_right.assign(sorted_ids.begin() + k, sorted_ids.end());
                best_split = split;
                best_horiz = horiz;
            }
        }
    }

    if (best_score < -0.99e18) {
        // Fallback: assign all area to heaviest
        int heavy = ids[0];
        for (int i : ids) if (R[i] > R[heavy]) heavy = i;
        A[heavy]=ax; B[heavy]=ay; C[heavy]=cx; D[heavy]=cy;
        for (int i : ids) {
            if (i == heavy) continue;
            A[i]=max(ax, X[i]-1); B[i]=max(ay, Y[i]-1);
            C[i]=min(cx, X[i]+1); D[i]=min(cy, Y[i]+1);
        }
        return;
    }

    if (best_horiz) {
        solve(best_left, ax, ay, cx, best_split);
        solve(best_right, ax, best_split, cx, cy);
    } else {
        solve(best_left, ax, ay, best_split, cy);
        solve(best_right, best_split, ay, cx, cy);
    }
}

int main(){
    scanf("%d",&n);
    for(int i=0;i<n;i++) scanf("%d%d%lld",&X[i],&Y[i],&R[i]);
    vector<int> ids(n); iota(ids.begin(),ids.end(),0);
    solve(ids, 0, 0, 10000, 10000);
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",A[i],B[i],C[i],D[i]);
}
