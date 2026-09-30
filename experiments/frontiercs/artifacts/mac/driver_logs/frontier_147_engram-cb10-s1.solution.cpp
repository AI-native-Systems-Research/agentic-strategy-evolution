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
    int bestSplit = -1;
    bool bestUseX = true;
    vector<int> bestL, bestR;

    for (int useX = 0; useX < 2; useX++) {
        vector<int> sidx = ids;
        if (useX) sort(sidx.begin(), sidx.end(), [](int a, int b){ return px_[a] < px_[b] || (px_[a]==px_[b] && py_[a]<py_[b]); });
        else sort(sidx.begin(), sidx.end(), [](int a, int b){ return py_[a] < py_[b] || (py_[a]==py_[b] && px_[a]<px_[b]); });

        long long cumR = 0;
        for (int k = 1; k < sz; k++) {
            cumR += rr[sidx[k-1]];
            int prev_coord = useX ? px_[sidx[k-1]] : py_[sidx[k-1]];
            int next_coord = useX ? px_[sidx[k]] : py_[sidx[k]];
            if (prev_coord == next_coord) continue;
            
            int sp = prev_coord + 1; // split so that prev_coord < sp <= next_coord
            int lo = useX ? lx : ly;
            int hi = useX ? ux : uy;
            if (sp <= lo || sp >= hi) continue;
            
            double frac = (double)cumR / totalR;
            double afrac = (double)(sp - lo) / (hi - lo);
            
            // Try the proportional split
            int ideal = lo + (int)round(frac * (hi - lo));
            ideal = max(ideal, prev_coord + 1);
            ideal = min(ideal, next_coord);
            ideal = max(ideal, lo + 1);
            ideal = min(ideal, hi - 1);
            
            double af2 = (double)(ideal - lo) / (hi - lo);
            double cost = (frac - af2) * (frac - af2);
            if (cost < bestCost) {
                bestCost = cost;
                bestSplit = ideal;
                bestUseX = (useX == 1);
                bestL.assign(sidx.begin(), sidx.begin() + k);
                bestR.assign(sidx.begin() + k, sidx.end());
            }
        }
    }

    if (bestSplit < 0) {
        for (int i : ids) { ra[i]=lx; rb[i]=ly; rc[i]=lx+1; rd[i]=ly+1; }
        return;
    }

    if (bestUseX) {
        solve(bestL, lx, ly, bestSplit, uy);
        solve(bestR, bestSplit, ly, ux, uy);
    } else {
        solve(bestL, lx, ly, ux, bestSplit);
        solve(bestR, lx, bestSplit, ux, uy);
    }
}

int main(){
    ios::sync_with_stdio(false); cin.tie(nullptr);
    cin >> n;
    for(int i=0;i<n;i++) cin >> px_[i] >> py_[i] >> rr[i];
    vector<int> ids(n);
    iota(ids.begin(), ids.end(), 0);
    solve(ids, 0, 0, 10000, 10000);
    for(int i=0;i<n;i++)
        cout << ra[i] << " " << rb[i] << " " << rc[i] << " " << rd[i] << "\n";
}
