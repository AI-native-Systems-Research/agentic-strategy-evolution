#include <bits/stdc++.h>
using namespace std;

int n;
int x_[200], y_[200];
long long r_[200];
int a_[200], b_[200], c_[200], d_[200];

// KD-tree initialization
void initPartition(vector<int>& ids, int ax, int ay, int cx, int cy, bool horiz) {
    if (ids.size() == 1) {
        int i = ids[0];
        a_[i] = ax; b_[i] = ay; c_[i] = cx; d_[i] = cy;
        return;
    }
    if (ids.empty()) return;
    
    long long totalR = 0;
    for (int i : ids) totalR += r_[i];
    
    // Sort by coordinate
    if (horiz) {
        sort(ids.begin(), ids.end(), [](int a, int b){ return x_[a] < x_[b]; });
    } else {
        sort(ids.begin(), ids.end(), [](int a, int b){ return y_[a] < y_[b]; });
    }
    
    // Find best split: try each split point, ensure all points are on correct side
    int bestSplit = -1;
    double bestCost = 1e18;
    long long cumR = 0;
    
    for (int k = 0; k < (int)ids.size() - 1; k++) {
        cumR += r_[ids[k]];
        double frac = (double)cumR / totalR;
        
        int splitPos;
        if (horiz) {
            splitPos = ax + (int)round(frac * (cx - ax));
            // Must be > x of ids[k] and <= x of ids[k+1]
            splitPos = max(splitPos, x_[ids[k]] + 1);
            splitPos = min(splitPos, x_[ids[k+1]] + 1);
            if (splitPos <= ax || splitPos >= cx) continue;
        } else {
            splitPos = ay + (int)round(frac * (cy - ay));
            splitPos = max(splitPos, y_[ids[k]] + 1);
            splitPos = min(splitPos, y_[ids[k+1]] + 1);
            if (splitPos <= ay || splitPos >= cy) continue;
        }
        
        double actualFrac;
        if (horiz) actualFrac = (double)(splitPos - ax) / (cx - ax);
        else actualFrac = (double)(splitPos - ay) / (cy - ay);
        
        double cost = abs(actualFrac - frac);
        if (cost < bestCost) {
            bestCost = cost;
            bestSplit = k;
        }
    }
    
    if (bestSplit < 0) {
        // Fallback: split in half by count
        bestSplit = (int)ids.size() / 2 - 1;
        if (bestSplit < 0) bestSplit = 0;
    }
    
    vector<int> left(ids.begin(), ids.begin() + bestSplit + 1);
    vector<int> right(ids.begin() + bestSplit + 1, ids.end());
    
    long long leftR = 0;
    for (int i : left) leftR += r_[i];
    double frac = (double)leftR / totalR;
    
    if (horiz) {
        int splitPos = ax + max(1, min((int)(cx - ax) - 1, (int)round(frac * (cx - ax))));
        // Ensure points are on correct side
        int minRight = 10001, maxLeft = -1;
        for (int i : left) maxLeft = max(maxLeft, x_[i]);
        for (int i : right) minRight = min(minRight, x_[i]);
        splitPos = max(splitPos, maxLeft + 1);
        splitPos = min(splitPos, minRight + 1);
        splitPos = max(splitPos, ax + 1);
        splitPos = min(splitPos, cx - 1);
        
        initPartition(left, ax, ay, splitPos, cy, !horiz);
        initPartition(right, splitPos, ay, cx, cy, !horiz);
    } else {
        int splitPos = ay + max(1, min((int)(cy - ay) - 1, (int)round(frac * (cy - ay))));
        int minRight = 10001, maxLeft = -1;
        for (int i : left) maxLeft = max(maxLeft, y_[i]);
        for (int i : right) minRight = min(minRight, y_[i]);
        splitPos = max(splitPos, maxLeft + 1);
        splitPos = min(splitPos, minRight + 1);
        splitPos = max(splitPos, ay + 1);
        splitPos = min(splitPos, cy - 1);
        
        initPartition(left, ax, ay, cx, splitPos, !horiz);
        initPartition(right, ax, splitPos, cx, cy, !horiz);
    }
}

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    cin >> n;
    for(int i = 0; i < n; i++){
        cin >> x_[i] >> y_[i] >> r_[i];
    }
    
    // Initialize with KD-tree partition
    vector<int> ids(n);
    iota(ids.begin(), ids.end(), 0);
    initPartition(ids, 0, 0, 10000, 10000, true);
    
    // Validate initialization - fallback to 1x1 if needed
    for(int i = 0; i < n; i++){
        if(a_[i] >= c_[i] || b_[i] >= d_[i] || 
           x_[i] < a_[i] || x_[i] >= c_[i] || y_[i] < b_[i] || y_[i] >= d_[i]){
            a_[i] = x_[i]; b_[i] = y_[i]; c_[i] = x_[i]+1; d_[i] = y_[i]+1;
        }
    }
    
    auto overlaps = [&](int i, int j) -> bool {
        return a_[i] < c_[j] && c_[i] > a_[j] && b_[i] < d_[j] && d_[i] > b_[j];
    };
    
    // Fix any overlaps by shrinking to 1x1
    for(int i = 0; i < n; i++){
        for(int j = i+1; j < n; j++){
            if(overlaps(i,j)){
                a_[j] = x_[j]; b_[j] = y_[j]; c_[j] = x_[j]+1; d_[j] = y_[j]+1;
            }
        }
    }
    
    auto score_i = [&](int i) -> double {
        long long si = (long long)(c_[i]-a_[i])*(d_[i]-b_[i]);
        if(si <= 0) return 0;
        if(x_[i] < a_[i] || x_[i] >= c_[i] || y_[i] < b_[i] || y_[i] >= d_[i]) return 0;
        double mn = min((double)r_[i], (double)si);
        double mx = max((double)r_[i], (double)si);
        double ratio = 1.0 - mn/mx;
        return 1.0 - ratio*ratio;
    };
    
    mt19937 rng(42);
    auto startTime = chrono::steady_clock::now();
    double timeLimit = 4.7;
    
    double T = 0.05;
    double Tend = 0.0001;
    
    for(int iter = 0; ; iter++){
        if((iter & 511) == 0){
            double elapsed = chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
            if(elapsed > timeLimit) break;
            double frac = elapsed / timeLimit;
            T = 0.05 * pow(Tend/0.05, frac);
        }
        
        int i = rng() % n;
        int dir = rng() % 4;
        double oldS = score_i(i);
        
        int oa=a_[i], ob=b_[i], oc=c_[i], od=d_[i];
        
        int mag = 1 + rng()%100;
        int delta = (rng()&1) ? mag : -mag;
        
        if(dir==0) a_[i]+=delta; else if(dir==1) b_[i]+=delta;
        else if(dir==2) c_[i]+=delta; else d_[i]+=delta;
        
        bool ok = a_[i]>=0 && b_[i]>=0 && c_[i]<=10000 && d_[i]<=10000 &&
                  a_[i]<c_[i] && b_[i]<d_[i] &&
                  x_[i]>=a_[i] && x_[i]<c_[i] && y_[i]>=b_[i] && y_[i]<d_[i];
        
        if(ok){
            for(int j=0;j<n&&ok;j++) if(j!=i) ok=!overlaps(i,j);
        }
        
        if(ok){
            double newS = score_i(i);
            double diff = newS - oldS;
            if(diff >= 0 || (double)(rng()%10000)/10000.0 < exp(diff/T)){
                // accept
            } else {
                a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;
            }
        } else {
            a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;
        }
    }
    
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a_[i],b_[i],c_[i],d_[i]);
}
