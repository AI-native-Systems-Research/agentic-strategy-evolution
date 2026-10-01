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
        a[i]=x[i]; b[i]=y[i]; c[i]=x[i]+1; d[i]=y[i]+1;
    }
    
    vector<int> order(n);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int u, int v){ return r[u] > r[v]; });
    
    vector<bool> placed(n, false);
    
    // Check if rectangle i overlaps rectangle j
    auto overlaps = [&](int i, int j) -> bool {
        return a[i]<c[j] && c[i]>a[j] && b[i]<d[j] && d[i]>b[j];
    };
    
    // Binary search max expansion in direction dir for rectangle i
    auto maxExpand = [&](int i, int dir) -> int {
        int lo = 0, hi;
        if(dir==0) hi = a[i]; // expand left
        else if(dir==1) hi = b[i]; // expand up (decrease b)
        else if(dir==2) hi = 10000 - c[i]; // expand right
        else hi = 10000 - d[i]; // expand down
        
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        
        while(lo < hi){
            int mid = (lo+hi+1)/2;
            if(dir==0) a[i]=oa-mid;
            else if(dir==1) b[i]=ob-mid;
            else if(dir==2) c[i]=oc+mid;
            else d[i]=od+mid;
            
            bool ok = true;
            for(int j = 0; j < n; j++){
                if(j==i || !placed[j]) continue;
                if(overlaps(i,j)){ ok=false; break; }
            }
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            if(ok) lo=mid; else hi=mid-1;
        }
        return lo;
    };
    
    for(int idx = 0; idx < n; idx++){
        int i = order[idx];
        placed[i] = true;
        
        long long target = r[i];
        bool changed = true;
        while(changed){
            changed = false;
            long long cur = (long long)(c[i]-a[i])*(d[i]-b[i]);
            if(cur >= target) break;
            
            int dirs[] = {0,1,2,3};
            for(int dir : dirs){
                cur = (long long)(c[i]-a[i])*(d[i]-b[i]);
                if(cur >= target) break;
                int mx = maxExpand(i, dir);
                if(mx <= 0) continue;
                // Compute needed expansion
                int side = (dir<2) ? (c[i]-a[i]) : (d[i]-b[i]);
                int other = (dir<2) ? (d[i]-b[i]) : (c[i]-a[i]);
                long long need = (target + other - 1) / max(other,1) - side;
                int step = (int)min((long long)mx, max(1LL, need));
                if(dir==0) a[i]-=step;
                else if(dir==1) b[i]-=step;
                else if(dir==2) c[i]+=step;
                else d[i]+=step;
                changed = true;
            }
        }
    }
    
    // Refinement
    auto t0 = chrono::steady_clock::now();
    for(int pass=0; pass<500; pass++){
        if(chrono::duration<double>(chrono::steady_clock::now()-t0).count()>4.0) break;
        for(int idx=0; idx<n; idx++){
            int i=order[idx];
            long long cur=(long long)(c[i]-a[i])*(d[i]-b[i]);
            if(cur>=r[i]) continue;
            for(int dir=0;dir<4;dir++){
                int mx=maxExpand(i,dir);
                if(mx<=0) continue;
                int other=(dir<2)?(d[i]-b[i]):(c[i]-a[i]);
                int side=(dir<2)?(c[i]-a[i]):(d[i]-b[i]);
                long long need=(r[i]+other-1)/max(other,1)-side;
                int step=(int)min((long long)mx,max(1LL,need));
                if(dir==0) a[i]-=step;
                else if(dir==1) b[i]-=step;
                else if(dir==2) c[i]+=step;
                else d[i]+=step;
            }
        }
    }
    
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a[i],b[i],c[i],d[i]);
}
