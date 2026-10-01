#include <bits/stdc++.h>
using namespace std;

int n;
int px[200], py[200];
long long r[200];
int a[200], b[200], c[200], d[200];

void solve(vector<int>& ids, int ax, int ay, int cx, int cy) {
    if (ids.empty()) return;
    if ((int)ids.size() == 1) {
        int i = ids[0];
        a[i] = ax; b[i] = ay; c[i] = cx; d[i] = cy;
        return;
    }

    long long totalR = 0;
    for (int i : ids) totalR += r[i];

    double bestScore = -1e18;
    int bestDir = -1, bestSplit = -1;
    vector<int> bestLeft, bestRight;

    for (int dir = 0; dir < 2; dir++) {
        vector<int> sorted_ids = ids;
        if (dir == 0) sort(sorted_ids.begin(), sorted_ids.end(), [](int u, int v){ return px[u] < px[v] || (px[u]==px[v] && py[u]<py[v]); });
        else sort(sorted_ids.begin(), sorted_ids.end(), [](int u, int v){ return py[u] < py[v] || (py[u]==py[v] && px[u]<px[v]); });

        long long cumR = 0;
        for (int k = 0; k < (int)sorted_ids.size() - 1; k++) {
            cumR += r[sorted_ids[k]];
            int coordLeft = (dir==0) ? px[sorted_ids[k]] : py[sorted_ids[k]];
            int coordRight = (dir==0) ? px[sorted_ids[k+1]] : py[sorted_ids[k+1]];
            if (coordLeft >= coordRight) continue;

            int lo = coordLeft + 1;
            int hi = coordRight;
            int base = (dir==0) ? ax : ay;
            int end = (dir==0) ? cx : cy;
            double frac = (double)cumR / totalR;
            int ideal = base + (int)round(frac * (end - base));
            int sp = max(lo, min(hi, ideal));
            if (sp <= base || sp >= end) continue;

            double totalA = (double)(cx-ax)*(cy-ay);
            double leftA = (dir==0) ? (double)(sp-ax)*(cy-ay) : (double)(cx-ax)*(sp-ay);
            double idealL = frac * totalA;
            double ratio = min(leftA, idealL) / max(leftA, idealL);

            if (ratio > bestScore) {
                bestScore = ratio;
                bestDir = dir;
                bestSplit = sp;
                bestLeft.assign(sorted_ids.begin(), sorted_ids.begin()+k+1);
                bestRight.assign(sorted_ids.begin()+k+1, sorted_ids.end());
            }
        }
    }

    if (bestDir == -1) {
        // Can't split - assign thin strips
        int sz = (int)ids.size();
        for (int idx = 0; idx < sz; idx++) {
            int i = ids[idx];
            int la = ax + (long long)(cx-ax)*idx/sz;
            int ra = ax + (long long)(cx-ax)*(idx+1)/sz;
            if (ra <= la) ra = la+1;
            a[i]=la; b[i]=ay; c[i]=min(ra,cx); d[i]=cy;
        }
        return;
    }

    if (bestDir==0) {
        solve(bestLeft, ax, ay, bestSplit, cy);
        solve(bestRight, bestSplit, ay, cx, cy);
    } else {
        solve(bestLeft, ax, ay, cx, bestSplit);
        solve(bestRight, ax, bestSplit, cx, cy);
    }
}

int main(){
    scanf("%d",&n);
    for(int i=0;i<n;i++) scanf("%d%d%lld",&px[i],&py[i],&r[i]);
    vector<int> ids(n);
    iota(ids.begin(),ids.end(),0);
    solve(ids,0,0,10000,10000);
    for(int i=0;i<n;i++){
        if(a[i]>=c[i]||b[i]>=d[i]||px[i]<a[i]||px[i]>=c[i]||py[i]<b[i]||py[i]>=d[i]){
            a[i]=px[i];b[i]=py[i];c[i]=px[i]+1;d[i]=py[i]+1;
        }
    }
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a[i],b[i],c[i],d[i]);
}
