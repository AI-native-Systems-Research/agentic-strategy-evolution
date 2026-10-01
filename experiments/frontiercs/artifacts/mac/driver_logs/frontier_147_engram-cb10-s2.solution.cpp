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
    
    // Owner grid: which rectangle owns each cell
    // We won't use a full 10000x10000 grid, but we'll use rectangle-based collision
    
    struct Rect { int x1,y1,x2,y2; };
    
    // Recursive guillotine-cut initialization
    function<void(vector<int>&, Rect)> doPartition = [&](vector<int>& ids, Rect bound){
        if(ids.size() == 1){
            int i = ids[0];
            a[i] = bound.x1; b[i] = bound.y1;
            c[i] = bound.x2; d[i] = bound.y2;
            return;
        }
        if(ids.empty()) return;
        
        int W = bound.x2 - bound.x1;
        int H = bound.y2 - bound.y1;
        
        long long totalR = 0;
        for(int i : ids) totalR += r[i];
        
        auto trySplit = [&](bool horiz) -> tuple<double, int, vector<int>, vector<int>> {
            vector<int> sorted_ids = ids;
            if(horiz){
                sort(sorted_ids.begin(), sorted_ids.end(), [&](int aa, int bb){ return y[aa] < y[bb]; });
            } else {
                sort(sorted_ids.begin(), sorted_ids.end(), [&](int aa, int bb){ return x[aa] < x[bb]; });
            }
            
            double bestCost = 1e18;
            int bestK = -1;
            int bestSplit = -1;
            long long cumR = 0;
            
            for(int k = 0; k < (int)sorted_ids.size()-1; k++){
                cumR += r[sorted_ids[k]];
                double frac = (double)cumR / totalR;
                int splitPos;
                if(horiz){
                    int lo = y[sorted_ids[k]] + 1;
                    int hi = y[sorted_ids[k+1]];
                    if(lo > hi) continue;
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
                
                double actualFrac;
                if(horiz){
                    actualFrac = (double)(splitPos - bound.y1) / H;
                } else {
                    actualFrac = (double)(splitPos - bound.x1) / W;
                }
                double cost = (actualFrac - frac)*(actualFrac - frac);
                if(horiz){
                    double h1 = splitPos - bound.y1, h2 = bound.y2 - splitPos;
                    if(h1 < 1 || h2 < 1) continue;
                    double ar1 = (double)W / h1;
                    double ar2 = (double)W / h2;
                    cost += 0.001*(max(ar1,1.0/ar1) + max(ar2,1.0/ar2));
                } else {
                    double w1 = splitPos - bound.x1, w2 = bound.x2 - splitPos;
                    if(w1 < 1 || w2 < 1) continue;
                    double ar1 = w1 / (double)H;
                    double ar2 = w2 / (double)H;
                    cost += 0.001*(max(ar1,1.0/ar1) + max(ar2,1.0/ar2));
                }
                
                if(cost < bestCost){
                    bestCost = cost;
                    bestK = k;
                    bestSplit = splitPos;
                }
            }
            
            if(bestK < 0) return {1e18, 0, {}, {}};
            
            vector<int> left(sorted_ids.begin(), sorted_ids.begin()+bestK+1);
            vector<int> right(sorted_ids.begin()+bestK+1, sorted_ids.end());
            return {bestCost, bestSplit, left, right};
        };
        
        auto [costH, splitH, leftH, rightH] = trySplit(true);
        auto [costV, splitV, leftV, rightV] = trySplit(false);
        
        if(costH >= 1e17 && costV >= 1e17){
            for(int i : ids){
                a[i] = x[i]; b[i] = y[i]; c[i] = x[i]+1; d[i] = y[i]+1;
            }
            return;
        }
        
        if(costH < costV && costH < 1e17){
            Rect top = {bound.x1, bound.y1, bound.x2, splitH};
            Rect bot = {bound.x1, splitH, bound.x2, bound.y2};
            doPartition(leftH, top);
            doPartition(rightH, bot);
        } else {
            Rect lft = {bound.x1, bound.y1, splitV, bound.y2};
            Rect rgt = {splitV, bound.y1, bound.x2, bound.y2};
            doPartition(leftV, lft);
            doPartition(rightV, rgt);
        }
    };
    
    vector<int> allIds(n);
    iota(allIds.begin(), allIds.end(), 0);
    doPartition(allIds, {0, 0, 10000, 10000});
    
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
    
    // Build neighbor structure: for each rectangle, find overlapping rectangles on each side
    // We'll rebuild periodically
    
    // Interval overlap check
    auto overlaps1D = [](int a1, int a2, int b1, int b2) -> bool {
        return a1 < b2 && b1 < a2;
    };
    
    // For direction: 0=left(a[i]), 1=bottom(b[i]), 2=right(c[i]), 3=top(d[i])
    // Find max expand distance for rectangle i in direction dir
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
                if(!overlaps1D(b[i], d[i], b[j], d[j])) continue;
                if(dir == 0){
                    if(c[j] <= a[i]) hi = min(hi, a[i] - c[j]);
                } else {
                    if(a[j] >= c[i]) hi = min(hi, a[j] - c[i]);
                }
            } else {
                if(!overlaps1D(a[i], c[i], a[j], c[j])) continue;
                if(dir == 1){
                    if(d[j] <= b[i]) hi = min(hi, b[i] - d[j]);
                } else {
                    if(b[j] >= d[i]) hi = min(hi, b[j] - d[i]);
                }
            }
        }
        return max(hi, 0);
    };
    
    // Find the blocking neighbor for rectangle i in direction dir
    // Returns (neighbor_id, max_expand_for_i)
    auto findBlocker = [&](int i, int dir) -> pair<int, int> {
        int hi;
        if(dir == 0) hi = a[i];
        else if(dir == 1) hi = b[i];
        else if(dir == 2) hi = 10000 - c[i];
        else hi = 10000 - d[i];
        
        int blocker = -1;
        
        for(int j = 0; j < n; j++){
            if(j == i) continue;
            if(dir == 0 || dir == 2){
                if(!overlaps1D(b[i], d[i], b[j], d[j])) continue;
                if(dir == 0){
                    if(c[j] <= a[i]){
                        int gap = a[i] - c[j];
                        if(gap < hi){ hi = gap; blocker = j; }
                    }
                } else {
                    if(a[j] >= c[i]){
                        int gap = a[j] - c[i];
                        if(gap < hi){ hi = gap; blocker = j; }
                    }
                }
            } else {
                if(!overlaps1D(a[i], c[i], a[j], c[j])) continue;
                if(dir == 1){
                    if(d[j] <= b[i]){
                        int gap = b[i] - d[j];
                        if(gap < hi){ hi = gap; blocker = j; }
                    }
                } else {
                    if(b[j] >= d[i]){
                        int gap = b[j] - d[i];
                        if(gap < hi){ hi = gap; blocker = j; }
                    }
                }
            }
        }
        return {blocker, max(hi, 0)};
    };
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    // Phase 1: Greedy expansion - prioritize worst rectangles
    for(int pass = 0; pass < 500 && elapsed() < 1.0; pass++){
        vector<int> order(n);
        iota(order.begin(), order.end(), 0);
        sort(order.begin(), order.end(), [&](int i, int j){
            return score_i(i) < score_i(j);
        });
        
        for(int idx = 0; idx < n; idx++){
            int i = order[idx];
            long long target = r[i];
            
            // Try all 4 directions, pick the one that helps most
            for(int rep = 0; rep < 4; rep++){
                if(area_i(i) >= target) break;
                
                int bestDir = -1;
                int bestDelta = 0;
                double bestGain = -1;
                
                for(int dir = 0; dir < 4; dir++){
                    int mx = maxExpand(i, dir);
                    if(mx <= 0) continue;
                    int perpLen = (dir == 0 || dir == 2) ? (d[i]-b[i]) : (c[i]-a[i]);
                    long long need = target - area_i(i);
                    int wantDelta = (int)min((long long)mx, max(1LL, (need + perpLen - 1) / perpLen));
                    wantDelta = min(wantDelta, mx);
                    
                    // Compute score gain
                    int oa=a[i],ob=b[i],oc=c[i],od=d[i];
                    double oldS = score_i(i);
                    if(dir==0) a[i]-=wantDelta;
                    else if(dir==1) b[i]-=wantDelta;
                    else if(dir==2) c[i]+=wantDelta;
                    else d[i]+=wantDelta;
                    double newS = score_i(i);
                    a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                    
                    if(newS - oldS > bestGain){
                        bestGain = newS - oldS;
                        bestDir = dir;
                        bestDelta = wantDelta;
                    }
                }
                
                if(bestDir >= 0 && bestGain > 0){
                    if(bestDir==0) a[i]-=bestDelta;
                    else if(bestDir==1) b[i]-=bestDelta;
                    else if(bestDir==2) c[i]+=bestDelta;
                    else d[i]+=bestDelta;
                }
            }
        }
    }
    
    // Phase 2: SA with coordinated moves
    mt19937 rng(42);
    double timeLimit = 4.7;
    double T0 = 0.05, Tend = 0.0002;
    
    double totalScore = 0;
    vector<double> scores(n);
    for(int i = 0; i < n; i++){
        scores[i] = score_i(i);
        totalScore += scores[i];
    }
    
    long long iter = 0;
    long long accepted = 0;
    
    while(elapsed() < timeLimit){
        double t = elapsed();
        double frac = max(0.0, min(1.0, (t - 1.0) / (timeLimit - 1.0)));
        double T = T0 * pow(Tend/T0, frac);
        
        int moveType = rng() % 100;
        
        if(moveType < 50){
            // Single rectangle expand/shrink
            int i = rng() % n;
            int dir = rng() % 4;
            int oa=a[i],ob=b[i],oc=c[i],od=d[i];
            double oldS = scores[i];
            
            bool expand;
            long long si = area_i(i);
            if(si > r[i]){
                expand = (rng() % 10 < 2); // mostly shrink
            } else {
                expand = (rng() % 10 < 8); // mostly expand
            }
            
            int delta;
            if(expand){
                int mx = maxExpand(i, dir);
                if(mx <= 0){ continue; }
                // Scale max move by temperature
                int maxD = max(1, min(mx, (int)(50 * (1.0 - frac*0.8) + 1)));
                delta = 1 + rng() % maxD;
                delta = min(delta, mx);
                if(dir==0) a[i]-=delta; else if(dir==1) b[i]-=delta;
                else if(dir==2) c[i]+=delta; else d[i]+=delta;
            } else {
                int maxShrink;
                if(dir==0) maxShrink=x[i]-a[i];
                else if(dir==1) maxShrink=y[i]-b[i];
                else if(dir==2) maxShrink=c[i]-x[i]-1;
                else maxShrink=d[i]-y[i]-1;
                if(maxShrink<=0){ continue; }
                int maxD = max(1, min(maxShrink, (int)(50 * (1.0 - frac*0.8) + 1)));
                delta = 1 + rng() % maxD;
                delta = min(delta, maxShrink);
                if(dir==0) a[i]+=delta; else if(dir==1) b[i]+=delta;
                else if(dir==2) c[i]-=delta; else d[i]-=delta;
            }
            
            if(a[i]<0||b[i]<0||c[i]>10000||d[i]>10000||a[i]>=c[i]||b[i]>=d[i]){
                a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                continue;
            }
            
            double newS = score_i(i);
            double diff = newS - oldS;
            if(diff >= 0 || (double)(rng()%1000000)/1000000.0 < exp(diff/T)){
                scores[i] = newS;
                totalScore += diff;
                accepted++;
            } else {
                a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            }
        } else {
            // Coordinated move: expand i by shrinking neighbor j
            int i = rng() % n;
            int dir = rng() % 4;
            
            auto [blocker, gap] = findBlocker(i, dir);
            if(blocker < 0) {
                // No blocker, just try expand
                int mx = maxExpand(i, dir);
                if(mx <= 0) continue;
                int oa=a[i],ob=b[i],oc=c[i],od=d[i];
                int maxD = max(1, min(mx, (int)(50*(1.0-frac*0.8)+1)));
                int delta = 1 + rng() % maxD;
                delta = min(delta, mx);
                if(dir==0) a[i]-=delta; else if(dir==1) b[i]-=delta;
                else if(dir==2) c[i]+=delta; else d[i]+=delta;
                
                if(a[i]<0||b[i]<0||c[i]>10000||d[i]>10000||a[i]>=c[i]||b[i]>=d[i]){
                    a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                    continue;
                }
                double oldS = scores[i];
                double newS = score_i(i);
                double diff = newS - oldS;
                if(diff >= 0 || (double)(rng()%1000000)/1000000.0 < exp(diff/T)){
                    scores[i] = newS;
                    totalScore += diff;
                } else {
                    a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                }
                continue;
            }
            
            int j = blocker;
            
            // Determine max we can push the boundary between i and j
            // dir=0: i wants to expand left, j is to the left. Shrink j's right edge (c[j])
            // dir=1: i wants to expand down, j is below. Shrink j's top edge (d[j])
            // dir=2: i wants to expand right, j is to the right. Shrink j's left edge (a[j])
            // dir=3: i wants to expand up, j is above. Shrink j's bottom edge (b[j])
            
            int maxShrinkJ;
            if(dir==0) maxShrinkJ = c[j] - max(x[j]+1, a[j]+1); // c[j] can decrease to x[j]+1
            else if(dir==1) maxShrinkJ = d[j] - max(y[j]+1, b[j]+1);
            else if(dir==2) maxShrinkJ = min(c[j]-1, x[j]) - a[j];
            else maxShrinkJ = min(d[j]-1, y[j]) - b[j];
            
            if(maxShrinkJ <= 0) continue;
            
            // We can expand i by gap (free space) + shrinkJ (taking from j)
            int totalAvail = gap + maxShrinkJ;
            int maxD = max(1, min(totalAvail, (int)(40*(1.0-frac*0.8)+1)));
            int delta = 1 + rng() % maxD;
            delta = min(delta, totalAvail);
            
            int oa=a[i],ob=b[i],oc=c[i],od=d[i];
            int oaj=a[j],obj=b[j],ocj=c[j],odj=d[j];
            double oldSi = scores[i], oldSj = scores[j];
            
            // Apply move to i
            if(dir==0) a[i]-=delta;
            else if(dir==1) b[i]-=delta;
            else if(dir==2) c[i]+=delta;
            else d[i]+=delta;
            
            // Shrink j if needed
            int shrinkNeeded = delta - gap;
            if(shrinkNeeded > 0){
                if(dir==0) c[j] -= shrinkNeeded; // j shrinks from right
                else if(dir==1) d[j] -= shrinkNeeded; // j shrinks from top
                else if(dir==2) a[j] += shrinkNeeded; // j shrinks from left
                else b[j] += shrinkNeeded; // j shrinks from bottom
            }
            
            // Validate
            bool valid = true;
            if(a[i]<0||b[i]<0||c[i]>10000||d[i]>10000||a[i]>=c[i]||b[i]>=d[i]) valid=false;
            if(a[j]<0||b[j]<0||c[j]>10000||d[j]>10000||a[j]>=c[j]||b[j]>=d[j]) valid=false;
            if(valid && (x[i]<a[i]||x[i]>=c[i]||y[i]<b[i]||y[i]>=d[i])) valid=false;
            if(valid && (x[j]<a[j]||x[j]>=c[j]||y[j]<b[j]||y[j]>=d[j])) valid=false;
            
            // Check overlap between i and j
            if(valid){
                if(a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j]) valid=false;
            }
            
            // Check i doesn't overlap others (skip j)
            if(valid){
                for(int k = 0; k < n && valid; k++){
                    if(k==i||k==j) continue;
                    if(a[i]<c[k]&&c[i]>a[k]&&b[i]<d[k]&&d[i]>b[k]) valid=false;
                }
            }
            
            if(!valid){
                a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                a[j]=oaj;b[j]=obj;c[j]=ocj;d[j]=odj;
                continue;
            }
            
            double newSi = score_i(i);
            double newSj = score_i(j);
            double diff = (newSi + newSj) - (oldSi + oldSj);
            
            if(diff >= 0 || (double)(rng()%1000000)/1000000.0 < exp(diff/T)){
                scores[i] = newSi;
                scores[j] = newSj;
                totalScore += diff;
                accepted++;
            } else {
                a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                a[j]=oaj;b[j]=obj;c[j]=ocj;d[j]=odj;
            }
        }
        iter++;
    }
    
    for(int i = 0; i < n; i++){
        printf("%d %d %d %d\n", a[i], b[i], c[i], d[i]);
    }
}
