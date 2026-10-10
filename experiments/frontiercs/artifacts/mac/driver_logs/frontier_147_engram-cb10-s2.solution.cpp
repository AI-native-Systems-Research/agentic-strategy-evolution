#include <bits/stdc++.h>
using namespace std;

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    int n;
    cin >> n;
    
    vector<int> x(n), y(n);
    vector<long long> r(n);
    vector<int> a(n), b(n), c(n), d(n);
    
    for(int i = 0; i < n; i++){
        cin >> x[i] >> y[i] >> r[i];
    }
    
    // Recursive guillotine-cut initialization
    struct Rect { int x1,y1,x2,y2; };
    
    function<void(vector<int>&, Rect)> partition = [&](vector<int>& ids, Rect bound){
        if(ids.size() == 1){
            int i = ids[0];
            a[i] = bound.x1; b[i] = bound.y1;
            c[i] = bound.x2; d[i] = bound.y2;
            return;
        }
        if(ids.empty()) return;
        
        int W = bound.x2 - bound.x1;
        int H = bound.y2 - bound.y1;
        
        // Try both axes, pick the one that works better
        // For each axis, sort points, find a split that separates into two groups
        // with area ratio matching sum of r values
        
        long long totalR = 0;
        for(int i : ids) totalR += r[i];
        
        auto trySplit = [&](bool horiz) -> tuple<double, int, vector<int>, vector<int>> {
            // horiz: split with horizontal line (divides y)
            vector<int> sorted_ids = ids;
            if(horiz){
                sort(sorted_ids.begin(), sorted_ids.end(), [&](int a, int b){ return y[a] < y[b]; });
            } else {
                sort(sorted_ids.begin(), sorted_ids.end(), [&](int a, int b){ return x[a] < x[b]; });
            }
            
            double bestCost = 1e18;
            int bestK = -1;
            long long cumR = 0;
            
            for(int k = 0; k < (int)sorted_ids.size()-1; k++){
                cumR += r[sorted_ids[k]];
                // Split position: between sorted_ids[k] and sorted_ids[k+1]
                double frac = (double)cumR / totalR;
                int splitPos;
                if(horiz){
                    int lo = y[sorted_ids[k]] + 1;
                    int hi = y[sorted_ids[k+1]];
                    if(lo > hi) continue; // can't split here
                    splitPos = bound.y1 + max(1, min((int)round(frac * H), H-1));
                    splitPos = max(splitPos, lo);
                    splitPos = min(splitPos, hi);
                    if(splitPos <= bound.y1 || splitPos >= bound.y2) continue;
                } else {
                    int lo = x[sorted_ids[k]] + 1;
                    int hi = x[sorted_ids[k+1]];
                    if(lo > hi) continue;
                    splitPos = bound.x1 + max(1, min((int)round(frac * W), W-1));
                    splitPos = max(splitPos, lo);
                    splitPos = min(splitPos, hi);
                    if(splitPos <= bound.x1 || splitPos >= bound.x2) continue;
                }
                
                // Cost: how far the area ratio is from desired
                double actualFrac;
                if(horiz){
                    actualFrac = (double)(splitPos - bound.y1) / H;
                } else {
                    actualFrac = (double)(splitPos - bound.x1) / W;
                }
                double cost = (actualFrac - frac)*(actualFrac - frac);
                // Also penalize bad aspect ratios
                if(horiz){
                    double ar1 = (double)W / max(1, splitPos - bound.y1);
                    double ar2 = (double)W / max(1, bound.y2 - splitPos);
                    cost += 0.001*(max(ar1,1.0/ar1) + max(ar2,1.0/ar2));
                } else {
                    double ar1 = (double)(splitPos - bound.x1) / max(1,H);
                    double ar2 = (double)(bound.x2 - splitPos) / max(1,H);
                    cost += 0.001*(max(ar1,1.0/ar1) + max(ar2,1.0/ar2));
                }
                
                if(cost < bestCost){
                    bestCost = cost;
                    bestK = k;
                }
            }
            
            if(bestK < 0) return {1e18, 0, {}, {}};
            
            cumR = 0;
            for(int k = 0; k <= bestK; k++) cumR += r[sorted_ids[k]];
            double frac = (double)cumR / totalR;
            
            int splitPos;
            if(horiz){
                int lo = y[sorted_ids[bestK]] + 1;
                int hi = y[sorted_ids[bestK+1]];
                splitPos = bound.y1 + max(1, min((int)round(frac * H), H-1));
                splitPos = max(splitPos, lo);
                splitPos = min(splitPos, hi);
            } else {
                int lo = x[sorted_ids[bestK]] + 1;
                int hi = x[sorted_ids[bestK+1]];
                splitPos = bound.x1 + max(1, min((int)round(frac * W), W-1));
                splitPos = max(splitPos, lo);
                splitPos = min(splitPos, hi);
            }
            
            vector<int> left(sorted_ids.begin(), sorted_ids.begin()+bestK+1);
            vector<int> right(sorted_ids.begin()+bestK+1, sorted_ids.end());
            return {bestCost, splitPos, left, right};
        };
        
        auto [costH, splitH, leftH, rightH] = trySplit(true);
        auto [costV, splitV, leftV, rightV] = trySplit(false);
        
        if(costH >= 1e17 && costV >= 1e17){
            // Fallback: just assign 1x1 cells
            for(int i : ids){
                a[i] = x[i]; b[i] = y[i]; c[i] = x[i]+1; d[i] = y[i]+1;
            }
            return;
        }
        
        if(costH < costV && costH < 1e17){
            Rect top = {bound.x1, bound.y1, bound.x2, splitH};
            Rect bot = {bound.x1, splitH, bound.x2, bound.y2};
            partition(leftH, top);
            partition(rightH, bot);
        } else {
            Rect lft = {bound.x1, bound.y1, splitV, bound.y2};
            Rect rgt = {splitV, bound.y1, bound.x2, bound.y2};
            partition(leftV, lft);
            partition(rightV, rgt);
        }
    };
    
    vector<int> allIds(n);
    iota(allIds.begin(), allIds.end(), 0);
    partition(allIds, {0, 0, 10000, 10000});
    
    // Verify all points are contained; fix if not
    for(int i = 0; i < n; i++){
        if(x[i] < a[i] || x[i] >= c[i] || y[i] < b[i] || y[i] >= d[i]){
            a[i] = x[i]; b[i] = y[i]; c[i] = x[i]+1; d[i] = y[i]+1;
        }
    }
    
    auto area_i = [&](int i) -> long long {
        return (long long)(c[i]-a[i])*(long long)(d[i]-b[i]);
    };
    
    auto score_i = [&](int i) -> double {
        long long si = area_i(i);
        if(si <= 0) return 0;
        if(x[i] < a[i] || x[i] >= c[i] || y[i] < b[i] || y[i] >= d[i]) return 0;
        double mn = min((double)r[i], (double)si);
        double mx = max((double)r[i], (double)si);
        double ratio = 1.0 - mn/mx;
        return 1.0 - ratio*ratio;
    };
    
    auto maxExpand = [&](int i, int dir) -> int {
        int hi;
        if(dir == 0) hi = a[i];
        else if(dir == 1) hi = b[i];
        else if(dir == 2) hi = 10000 - c[i];
        else hi = 10000 - d[i];
        
        if(hi <= 0) return 0;
        
        for(int j = 0; j < n; j++){
            if(j == i) continue;
            if(dir == 0 || dir == 2){
                if(b[i] >= d[j] || d[i] <= b[j]) continue;
                if(dir == 0){
                    if(c[j] <= a[i]) hi = min(hi, a[i] - c[j]);
                } else {
                    if(a[j] >= c[i]) hi = min(hi, a[j] - c[i]);
                }
            } else {
                if(a[i] >= c[j] || c[i] <= a[j]) continue;
                if(dir == 1){
                    if(d[j] <= b[i]) hi = min(hi, b[i] - d[j]);
                } else {
                    if(b[j] >= d[i]) hi = min(hi, b[j] - d[i]);
                }
            }
        }
        return max(hi, 0);
    };
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    // Phase 1: Greedy expansion
    for(int pass = 0; pass < 300 && elapsed() < 1.5; pass++){
        vector<int> order(n);
        iota(order.begin(), order.end(), 0);
        sort(order.begin(), order.end(), [&](int i, int j){
            return score_i(i) < score_i(j);
        });
        
        for(int idx = 0; idx < n; idx++){
            int i = order[idx];
            long long si = area_i(i);
            long long target = r[i];
            
            for(int dir = 0; dir < 4; dir++){
                if(area_i(i) >= target) break;
                int mx = maxExpand(i, dir);
                if(mx <= 0) continue;
                int perpLen = (dir == 0 || dir == 2) ? (d[i]-b[i]) : (c[i]-a[i]);
                long long need = target - area_i(i);
                int wantDelta = (int)min((long long)mx, (need + perpLen - 1) / perpLen);
                wantDelta = max(1, min(wantDelta, mx));
                if(dir == 0) a[i] -= wantDelta;
                else if(dir == 1) b[i] -= wantDelta;
                else if(dir == 2) c[i] += wantDelta;
                else d[i] += wantDelta;
            }
        }
    }
    
    // Phase 2: SA
    mt19937 rng(42);
    double timeLimit = 4.8;
    double T0 = 0.03, Tend = 0.0001;
    int iter = 0;
    
    while(elapsed() < timeLimit){
        double t = elapsed();
        double frac = max(0.0, min(1.0, (t - 1.5) / (timeLimit - 1.5)));
        double T = T0 * pow(Tend/T0, frac);
        
        int i = rng() % n;
        int dir = rng() % 4;
        double oldS = score_i(i);
        
        bool expand = (rng() % 2 == 0);
        int delta;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        
        if(expand){
            int mx = maxExpand(i, dir);
            if(mx <= 0) continue;
            int maxD = max(1, (int)(mx * (1.0 - frac*0.9)));
            delta = 1 + rng() % maxD;
            if(dir==0) a[i]-=delta; else if(dir==1) b[i]-=delta;
            else if(dir==2) c[i]+=delta; else d[i]+=delta;
        } else {
            int maxShrink;
            if(dir==0) maxShrink=x[i]-a[i];
            else if(dir==1) maxShrink=y[i]-b[i];
            else if(dir==2) maxShrink=c[i]-x[i]-1;
            else maxShrink=d[i]-y[i]-1;
            if(maxShrink<=0) continue;
            int maxD = max(1, (int)(maxShrink * (1.0 - frac*0.9)));
            delta = 1 + rng() % maxD;
            if(dir==0) a[i]+=delta; else if(dir==1) b[i]+=delta;
            else if(dir==2) c[i]-=delta; else d[i]-=delta;
        }
        
        if(a[i]<0||b[i]<0||c[i]>10000||d[i]>10000||a[i]>=c[i]||b[i]>=d[i]||
           x[i]<a[i]||x[i]>=c[i]||y[i]<b[i]||y[i]>=d[i]){
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            continue;
        }
        
        double newS = score_i(i);
        double diff = newS - oldS;
        if(diff >= 0 || (double)(rng()%10000)/10000.0 < exp(diff/T)){
            // accept
        } else {
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
        }
        iter++;
    }
    
    for(int i = 0; i < n; i++){
        printf("%d %d %d %d\n", a[i], b[i], c[i], d[i]);
    }
}
