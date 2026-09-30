#include <bits/stdc++.h>
using namespace std;

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    int n;
    cin >> n;
    vector<int> x(n), y(n);
    vector<long long> r(n);
    for(int i=0;i<n;i++) cin >> x[i] >> y[i] >> r[i];
    
    vector<int> a(n),b(n),c(n),d(n);
    
    // BSP recursive partition
    // Each leaf maps to exactly one company
    struct Rect { int x0,y0,x1,y1; };
    
    function<void(vector<int>&, Rect, bool)> partition = [&](vector<int>& ids, Rect reg, bool splitX){
        if(ids.size()==1){
            int i=ids[0];
            a[i]=reg.x0; b[i]=reg.y0; c[i]=reg.x1; d[i]=reg.y1;
            return;
        }
        if(ids.empty()) return;
        
        // Sort by coordinate
        if(splitX){
            sort(ids.begin(), ids.end(), [&](int u, int v){ return x[u]<x[v] || (x[u]==x[v] && y[u]<y[v]); });
        } else {
            sort(ids.begin(), ids.end(), [&](int u, int v){ return y[u]<y[v] || (y[u]==y[v] && x[u]<x[v]); });
        }
        
        long long totalR=0;
        for(int i:ids) totalR+=r[i];
        
        // Find best split point
        int bestK=1;
        double bestScore=1e18;
        long long cumR=0;
        
        for(int k=1;k<(int)ids.size();k++){
            cumR+=r[ids[k-1]];
            double frac=(double)cumR/totalR;
            
            // Check that split is valid (all points in left go to left region, etc.)
            double splitPos;
            if(splitX){
                splitPos = reg.x0 + frac*(reg.x1-reg.x0);
                // All points in left half must have x < splitPos, right half x >= splitPos
                int maxLeft = x[ids[k-1]];
                int minRight = x[ids[k]];
                if(maxLeft >= minRight && maxLeft == minRight){
                    // They share same x, not ideal but try
                }
                // Compute actual split coordinate
                int sp = (int)round(splitPos);
                sp = max(sp, max(x[ids[k-1]]+1, reg.x0+1));
                sp = min(sp, min(x[ids[k]], reg.x1-1));
                if(sp <= reg.x0 || sp >= reg.x1) { 
                    // Can't split here on X, try anyway with best effort
                    double penalty = abs(frac - 0.5);
                    if(penalty < bestScore){ bestScore=penalty; bestK=k; }
                    continue;
                }
                double score = abs(frac - (double)(sp-reg.x0)/(reg.x1-reg.x0));
                if(score < bestScore){ bestScore=score; bestK=k; }
            } else {
                splitPos = reg.y0 + frac*(reg.y1-reg.y0);
                int sp = (int)round(splitPos);
                sp = max(sp, max(y[ids[k-1]]+1, reg.y0+1));
                sp = min(sp, min(y[ids[k]], reg.y1-1));
                if(sp <= reg.y0 || sp >= reg.y1){
                    double penalty = abs(frac - 0.5);
                    if(penalty < bestScore){ bestScore=penalty; bestK=k; }
                    continue;
                }
                double score = abs(frac - (double)(sp-reg.y0)/(reg.y1-reg.y0));
                if(score < bestScore){ bestScore=score; bestK=k; }
            }
        }
        
        int k = bestK;
        cumR=0;
        for(int i=0;i<k;i++) cumR+=r[ids[i]];
        double frac=(double)cumR/totalR;
        
        vector<int> left(ids.begin(), ids.begin()+k);
        vector<int> right(ids.begin()+k, ids.end());
        
        if(splitX){
            int sp = reg.x0 + (int)round(frac*(reg.x1-reg.x0));
            // Ensure all left points < sp and all right points >= sp
            int maxLeftX = -1;
            for(int i:left) maxLeftX = max(maxLeftX, x[i]);
            int minRightX = 10001;
            for(int i:right) minRightX = min(minRightX, x[i]);
            sp = max(sp, maxLeftX+1);
            sp = min(sp, minRightX);
            sp = max(sp, reg.x0+1);
            sp = min(sp, reg.x1-1);
            
            if(sp <= maxLeftX || sp > minRightX || sp <= reg.x0 || sp >= reg.x1){
                // Fallback: split on Y instead
                partition(ids, reg, !splitX);
                return;
            }
            
            Rect lr = {reg.x0, reg.y0, sp, reg.y1};
            Rect rr = {sp, reg.y0, reg.x1, reg.y1};
            partition(left, lr, !splitX);
            partition(right, rr, !splitX);
        } else {
            int sp = reg.y0 + (int)round(frac*(reg.y1-reg.y0));
            int maxLeftY = -1;
            for(int i:left) maxLeftY = max(maxLeftY, y[i]);
            int minRightY = 10001;
            for(int i:right) minRightY = min(minRightY, y[i]);
            sp = max(sp, maxLeftY+1);
            sp = min(sp, minRightY);
            sp = max(sp, reg.y0+1);
            sp = min(sp, reg.y1-1);
            
            if(sp <= maxLeftY || sp > minRightY || sp <= reg.y0 || sp >= reg.y1){
                partition(ids, reg, !splitX);
                return;
            }
            
            Rect lr = {reg.x0, reg.y0, reg.x1, sp};
            Rect rr = {reg.x0, sp, reg.x1, reg.y1};
            partition(left, lr, !splitX);
            partition(right, rr, !splitX);
        }
    };
    
    vector<int> ids(n);
    iota(ids.begin(), ids.end(), 0);
    partition(ids, {0,0,10000,10000}, true);
    
    // Validate and fix
    for(int i=0;i<n;i++){
        if(a[i]>=c[i]||b[i]>=d[i]||a[i]<0||b[i]<0||c[i]>10000||d[i]>10000){
            a[i]=x[i]; b[i]=y[i]; c[i]=x[i]+1; d[i]=y[i]+1;
        }
        if(!(a[i]<=x[i]&&c[i]>=x[i]+1&&b[i]<=y[i]&&d[i]>=y[i]+1)){
            a[i]=x[i]; b[i]=y[i]; c[i]=x[i]+1; d[i]=y[i]+1;
        }
    }
    
    // SA
    auto contains_point=[&](int i)->bool{
        return a[i]<=x[i] && c[i]>=x[i]+1 && b[i]<=y[i] && d[i]>=y[i]+1;
    };
    auto sat=[&](int i)->double{
        if(!contains_point(i)) return 0.0;
        long long si=(long long)(c[i]-a[i])*(d[i]-b[i]);
        double ratio=(double)min(r[i],si)/max(r[i],si);
        double v=1.0-ratio;
        return 1.0-v*v;
    };
    auto overlap=[&](int i, int j)->bool{
        return a[i]<c[j]&&a[j]<c[i]&&b[i]<d[j]&&b[j]<d[i];
    };
    
    mt19937 rng(42);
    auto now=chrono::steady_clock::now;
    auto start=now();
    
    for(int iter=0;;iter++){
        if((iter&0x1FF)==0){
            if(chrono::duration<double>(now()-start).count()>4.7) break;
        }
        double elapsed=chrono::duration<double>(now()-start).count();
        double temp=max(0.0001, 0.05*(1.0-elapsed/4.8));
        
        int i=rng()%n;
        int edge=rng()%4;
        int delta=(rng()%2)?1:-1;
        if(rng()%5<2) delta*=(1+rng()%50);
        
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        double os=sat(i);
        if(edge==0) a[i]+=delta; else if(edge==1) c[i]+=delta;
        else if(edge==2) b[i]+=delta; else d[i]+=delta;
        
        bool ok=(a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&contains_point(i));
        if(ok) for(int j=0;j<n&&ok;j++) if(j!=i&&overlap(i,j)) ok=false;
        if(!ok){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;continue;}
        double ns=sat(i);
        double diff=ns-os;
        if(diff>=0||exp(diff/temp)>uniform_real_distribution<double>(0,1)(rng)){
        } else {a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}
    }
    
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a[i],b[i],c[i],d[i]);
}
