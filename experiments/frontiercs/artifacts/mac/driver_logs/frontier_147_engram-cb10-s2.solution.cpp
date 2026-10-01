#include <bits/stdc++.h>
using namespace std;

int n;
int px[1001], py[1001];
long long r[1001];
int xa[1001], ya[1001], xb[1001], yb[1001]; // [xa,xb) x [ya,yb)

bool overlaps(int i, int j) {
    return xa[i] < xb[j] && xb[i] > xa[j] && ya[i] < yb[j] && yb[i] > ya[j];
}

long long area(int i) { return (long long)(xb[i]-xa[i])*(yb[i]-ya[i]); }

double score(int i) {
    long long s = area(i);
    if (s <= 0) return 0;
    double mn = min((double)r[i], (double)s);
    double mx = max((double)r[i], (double)s);
    double rat = 1.0 - mn/mx;
    return 1.0 - rat*rat;
}

// Max expand in direction dir (0=left,1=up,2=right,3=down) without overlap
int maxExpand(int i, int dir) {
    int lim;
    if (dir == 0) lim = xa[i];
    else if (dir == 1) lim = ya[i];
    else if (dir == 2) lim = 10000 - xb[i];
    else lim = 10000 - yb[i];
    
    for (int j = 0; j < n; j++) {
        if (j == i) continue;
        if (dir == 0 || dir == 2) {
            // horizontal expansion - need vertical overlap
            if (ya[i] >= yb[j] || yb[i] <= ya[j]) continue;
            if (dir == 0) { // expand left
                if (xb[j] <= xa[i]) lim = min(lim, xa[i] - xb[j]);
                else if (xa[j] < xb[i] && xb[j] > xa[i]) lim = 0; // already overlapping or blocking
            } else { // expand right
                if (xa[j] >= xb[i]) lim = min(lim, xa[j] - xb[i]);
                else if (xb[j] > xa[i] && xa[j] < xb[i]) lim = 0;
            }
        } else {
            if (xa[i] >= xb[j] || xb[i] <= xa[j]) continue;
            if (dir == 1) {
                if (yb[j] <= ya[i]) lim = min(lim, ya[i] - yb[j]);
                else if (ya[j] < yb[i] && yb[j] > ya[i]) lim = 0;
            } else {
                if (ya[j] >= yb[i]) lim = min(lim, ya[j] - yb[i]);
                else if (yb[j] > ya[i] && ya[j] < yb[i]) lim = 0;
            }
        }
    }
    return max(lim, 0);
}

int main(){
    scanf("%d", &n);
    for (int i = 0; i < n; i++) {
        scanf("%d%d%lld", &px[i], &py[i], &r[i]);
        xa[i] = px[i]; ya[i] = py[i]; xb[i] = px[i]+1; yb[i] = py[i]+1;
    }
    
    auto T0 = chrono::steady_clock::now();
    auto elapsed = [&]() { return chrono::duration<double>(chrono::steady_clock::now()-T0).count(); };
    
    // Greedy expansion passes
    for (int pass = 0; pass < 50000 && elapsed() < 4.5; pass++) {
        bool any = false;
        for (int i = 0; i < n; i++) {
            long long s = area(i), t = r[i];
            if (s >= t) continue;
            for (int dir = 0; dir < 4; dir++) {
                int mx = maxExpand(i, dir);
                if (mx <= 0) continue;
                int perp = (dir <= 1) ? (xb[i]-xa[i]) : (yb[i]-ya[i]);
                if (dir == 0 || dir == 2) perp = yb[i]-ya[i]; else perp = xb[i]-xa[i];
                long long need = t - area(i);
                if (need <= 0) break;
                int want = (int)min((long long)mx, max(1LL, (need + perp - 1) / perp));
                double os = score(i);
                int oa=xa[i],ob=ya[i],oc=xb[i],od=yb[i];
                if (dir==0) xa[i]-=want; else if(dir==1) ya[i]-=want;
                else if(dir==2) xb[i]+=want; else yb[i]+=want;
                if (score(i) <= os) { xa[i]=oa; ya[i]=ob; xb[i]=oc; yb[i]=od; }
                else any = true;
            }
        }
        if (!any) break;
    }
    
    mt19937 rng(42);
    while (elapsed() < 4.8) {
        int i = rng() % n;
        int dir = rng() % 4;
        bool expand = (rng() % 3 > 0);
        double os = score(i);
        int oa=xa[i],ob=ya[i],oc=xb[i],od=yb[i];
        if (expand) {
            int mx = maxExpand(i, dir); if (mx <= 0) continue;
            int delta = 1 + rng() % mx;
            if (dir==0) xa[i]-=delta; else if(dir==1) ya[i]-=delta;
            else if(dir==2) xb[i]+=delta; else yb[i]+=delta;
        } else {
            int ms2;
            if(dir==0) ms2=px[i]-xa[i]; else if(dir==1) ms2=py[i]-ya[i];
            else if(dir==2) ms2=xb[i]-px[i]-1; else ms2=yb[i]-py[i]-1;
            if(ms2<=0) continue;
            int delta = 1 + rng() % ms2;
            if(dir==0) xa[i]+=delta; else if(dir==1) ya[i]+=delta;
            else if(dir==2) xb[i]-=delta; else yb[i]-=delta;
        }
        if(score(i) <= os) { xa[i]=oa; ya[i]=ob; xb[i]=oc; yb[i]=od; }
    }
    
    for (int i = 0; i < n; i++)
        printf("%d %d %d %d\n", xa[i], ya[i], xb[i], yb[i]);
}
