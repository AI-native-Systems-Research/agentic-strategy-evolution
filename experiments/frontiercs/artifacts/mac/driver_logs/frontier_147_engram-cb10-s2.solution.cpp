#include <bits/stdc++.h>
using namespace std;

int n;
int x_[200], y_[200];
long long r_[200];
int a_[200], b_[200], c_[200], d_[200];

void solve_rec(vector<int>& ids, int ax, int ay, int cx, int cy, bool horiz) {
    if (ids.size() == 1) {
        int i = ids[0];
        a_[i] = ax; b_[i] = ay; c_[i] = cx; d_[i] = cy;
        return;
    }
    if (ids.empty()) return;
    
    long long totalR = 0;
    for (int i : ids) totalR += r_[i];
    
    // Sort by coordinate
    if (horiz) sort(ids.begin(), ids.end(), [](int a, int b){ return x_[a] < x_[b]; });
    else sort(ids.begin(), ids.end(), [](int a, int b){ return y_[a] < y_[b]; });
    
    // Find best split
    int bestK = -1;
    double bestCost = 1e18;
    long long cumR = 0;
    
    for (int k = 0; k < (int)ids.size() - 1; k++) {
        cumR += r_[ids[k]];
        double frac = (double)cumR / totalR;
        int splitPos;
        if (horiz) splitPos = ax + (int)round(frac * (cx - ax));
        else splitPos = ay + (int)round(frac * (cy - ay));
        
        // Check all points in left group are < splitPos, right group >= splitPos
        bool valid = true;
        if (horiz) {
            if (splitPos <= ax || splitPos >= cx) { valid = false; }
            for (int j = 0; j <= k && valid; j++) if (x_[ids[j]] >= splitPos) valid = false;
            for (int j = k+1; j < (int)ids.size() && valid; j++) if (x_[ids[j]] < splitPos) valid = false;
        } else {
            if (splitPos <= ay || splitPos >= cy) { valid = false; }
            for (int j = 0; j <= k && valid; j++) if (y_[ids[j]] >= splitPos) valid = false;
            for (int j = k+1; j < (int)ids.size() && valid; j++) if (y_[ids[j]] < splitPos) valid = false;
        }
        if (!valid) continue;
        
        // Cost: deviation from ideal area proportions
        double leftArea, rightArea;
        if (horiz) {
            leftArea = (double)(splitPos - ax) * (cy - ay);
            rightArea = (double)(cx - splitPos) * (cy - ay);
        } else {
            leftArea = (double)(cx - ax) * (splitPos - ay);
            rightArea = (double)(cx - ax) * (cy - splitPos);
        }
        double idealLeft = (double)cumR / totalR * (double)(cx-ax) * (cy-ay);
        double idealRight = (double)(totalR - cumR) / totalR * (double)(cx-ax) * (cy-ay);
        double cost = abs(leftArea - idealLeft) + abs(rightArea - idealRight);
        
        if (cost < bestCost) {
            bestCost = cost;
            bestK = k;
        }
    }
    
    if (bestK == -1) {
        // Fallback: try other direction
        if (ids.size() == 2) {
            // assign minimal rects
            for (int i : ids) {
                a_[i] = x_[i]; b_[i] = y_[i]; c_[i] = x_[i]+1; d_[i] = y_[i]+1;
            }
            return;
        }
        solve_rec(ids, ax, ay, cx, cy, !horiz);
        return;
    }
    
    long long cumR2 = 0;
    for (int k = 0; k <= bestK; k++) cumR2 += r_[ids[k]];
    double frac = (double)cumR2 / totalR;
    int splitPos;
    if (horiz) splitPos = ax + max(1, min((int)(cx-ax)-1, (int)round(frac * (cx - ax))));
    else splitPos = ay + max(1, min((int)(cy-ay)-1, (int)round(frac * (cy - ay))));
    
    // Adjust to ensure containment
    if (horiz) {
        int maxLeft = -1;
        for (int j = 0; j <= bestK; j++) maxLeft = max(maxLeft, x_[ids[j]]);
        int minRight = 10001;
        for (int j = bestK+1; j < (int)ids.size(); j++) minRight = min(minRight, x_[ids[j]]);
        splitPos = max(splitPos, maxLeft + 1);
        splitPos = min(splitPos, minRight);
    } else {
        int maxLeft = -1;
        for (int j = 0; j <= bestK; j++) maxLeft = max(maxLeft, y_[ids[j]]);
        int minRight = 10001;
        for (int j = bestK+1; j < (int)ids.size(); j++) minRight = min(minRight, y_[ids[j]]);
        splitPos = max(splitPos, maxLeft + 1);
        splitPos = min(splitPos, minRight);
    }
    
    vector<int> left(ids.begin(), ids.begin() + bestK + 1);
    vector<int> right(ids.begin() + bestK + 1, ids.end());
    
    if (horiz) {
        solve_rec(left, ax, ay, splitPos, cy, !horiz);
        solve_rec(right, splitPos, ay, cx, cy, !horiz);
    } else {
        solve_rec(left, ax, ay, cx, splitPos, !horiz);
        solve_rec(right, ax, splitPos, cx, cy, !horiz);
    }
}

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    cin >> n;
    for(int i=0;i<n;i++) cin >> x_[i] >> y_[i] >> r_[i];
    
    vector<int> ids(n);
    iota(ids.begin(), ids.end(), 0);
    solve_rec(ids, 0, 0, 10000, 10000, true);
    
    // Verify and fix
    for(int i=0;i<n;i++){
        if(a_[i]>=c_[i]||b_[i]>=d_[i]||x_[i]<a_[i]||x_[i]>=c_[i]||y_[i]<b_[i]||y_[i]>=d_[i]){
            a_[i]=x_[i]; b_[i]=y_[i]; c_[i]=x_[i]+1; d_[i]=y_[i]+1;
        }
    }
    
    // SA refinement
    auto score_i = [&](int i) -> double {
        long long si = (long long)(c_[i]-a_[i])*(d_[i]-b_[i]);
        double mn = min((double)r_[i], (double)si);
        double mx = max((double)r_[i], (double)si);
        double ratio = 1.0 - mn/mx;
        return 1.0 - ratio*ratio;
    };
    
    mt19937 rng(42);
    auto startTime = chrono::steady_clock::now();
    double timeLimit = 4.7;
    double T = 0.05;
    
    for(int iter=0;;iter++){
        if((iter&511)==0){
            double el = chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
            if(el > timeLimit) break;
            T = 0.05 * (1.0 - el/timeLimit) + 1e-6;
        }
        int i = rng()%n;
        int dir = rng()%4;
        double oldS = score_i(i);
        int oa=a_[i],ob=b_[i],oc=c_[i],od=d_[i];
        int delta = (rng()%2)?1:-1;
        if(rng()%3==0) delta *= (1+rng()%20);
        if(dir==0) a_[i]+=delta; else if(dir==1) b_[i]+=delta;
        else if(dir==2) c_[i]+=delta; else d_[i]+=delta;
        bool ok = a_[i]>=0&&b_[i]>=0&&c_[i]<=10000&&d_[i]<=10000&&a_[i]<c_[i]&&b_[i]<d_[i]&&x_[i]>=a_[i]&&x_[i]<c_[i]&&y_[i]>=b_[i]&&y_[i]<d_[i];
        if(ok) for(int j=0;j<n&&ok;j++) if(j!=i) if(a_[i]<c_[j]&&c_[i]>a_[j]&&b_[i]<d_[j]&&d_[i]>b_[j]) ok=false;
        if(ok){
            double newS = score_i(i);
            double diff = newS - oldS;
            if(diff < 0 && (double)(rng()%10000)/10000.0 > exp(diff/T)) ok = false;
        }
        if(!ok){ a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od; }
    }
    
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a_[i],b_[i],c_[i],d_[i]);
}
