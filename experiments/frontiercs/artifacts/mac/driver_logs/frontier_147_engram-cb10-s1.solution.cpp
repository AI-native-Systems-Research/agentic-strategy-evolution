#include <bits/stdc++.h>
using namespace std;

int n;
int px_[5001], py_[5001];
long long rr[5001];
int ra[5001], rb[5001], rc[5001], rd[5001];

void solve(vector<int>& ids, int lx, int ly, int ux, int uy) {
    if (ids.empty()) return;
    if (ids.size() == 1) {
        int i = ids[0];
        ra[i] = lx; rb[i] = ly; rc[i] = ux; rd[i] = uy;
        return;
    }
    int sz = ids.size();
    long long totalR = 0;
    for (int i : ids) totalR += rr[i];

    double bestCost = 1e18;
    int bestK = -1, bestSplit = -1;
    bool bestUseX = true;
    vector<int> bestOrder;

    for (int useX = 0; useX < 2; useX++) {
        vector<int> sidx = ids;
        if (useX) sort(sidx.begin(), sidx.end(), [](int a, int b) { return px_[a] < px_[b]; });
        else sort(sidx.begin(), sidx.end(), [](int a, int b) { return py_[a] < py_[b]; });

        long long cumR = 0;
        for (int k = 1; k < sz; k++) {
            cumR += rr[sidx[k - 1]];
            double frac = (double)cumR / totalR;
            int lo, hi;
            if (useX) {
                lo = px_[sidx[k - 1]] + 1;
                hi = px_[sidx[k]] + 1;
                if (lo > hi) swap(lo, hi);
                // split must be in [lx+1, ux-1] and [lo, hi]
                int slo = max(lx + 1, lo);
                int shi = min(ux - 1, hi);
                if (slo > shi) continue;
                int sp = lx + (int)round(frac * (ux - lx));
                sp = max(sp, slo);
                sp = min(sp, shi);
                double af = (double)(sp - lx) / (ux - lx);
                double c = (frac - af) * (frac - af);
                if (c < bestCost) { bestCost = c; bestK = k; bestSplit = sp; bestUseX = true; bestOrder = sidx; }
            } else {
                lo = py_[sidx[k - 1]] + 1;
                hi = py_[sidx[k]] + 1;
                if (lo > hi) swap(lo, hi);
                int slo = max(ly + 1, lo);
                int shi = min(uy - 1, hi);
                if (slo > shi) continue;
                int sp = ly + (int)round(frac * (uy - ly));
                sp = max(sp, slo);
                sp = min(sp, shi);
                double af = (double)(sp - ly) / (uy - ly);
                double c = (frac - af) * (frac - af);
                if (c < bestCost) { bestCost = c; bestK = k; bestSplit = sp; bestUseX = false; bestOrder = sidx; }
            }
        }
    }

    if (bestK < 0) {
        // fallback: assign minimal rectangles
        for (int i : ids) { ra[i] = px_[i]; rb[i] = py_[i]; rc[i] = px_[i] + 1; rd[i] = py_[i] + 1; }
        return;
    }

    vector<int> L(bestOrder.begin(), bestOrder.begin() + bestK);
    vector<int> R(bestOrder.begin() + bestK, bestOrder.end());
    if (bestUseX) {
        solve(L, lx, ly, bestSplit, uy);
        solve(R, bestSplit, ly, ux, uy);
    } else {
        solve(L, lx, ly, ux, bestSplit);
        solve(R, lx, bestSplit, ux, uy);
    }
}

int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    cin >> n;
    for (int i = 0; i < n; i++) cin >> px_[i] >> py_[i] >> rr[i];
    vector<int> ids(n);
    iota(ids.begin(), ids.end(), 0);
    solve(ids, 0, 0, 10000, 10000);
    for (int i = 0; i < n; i++)
        cout << ra[i] << " " << rb[i] << " " << rc[i] << " " << rd[i] << "\n";
}
