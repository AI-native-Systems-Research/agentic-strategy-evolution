#include <bits/stdc++.h>
using namespace std;

int main(){
    int n;
    scanf("%d",&n);
    vector<int> p(n);
    for(int i=0;i<n;i++) scanf("%d",&p[i]);
    
    vector<pair<int,int>> ops;
    
    auto apply_op = [&](int x, int y){
        // swap prefix of length x with suffix of length y
        vector<int> np;
        for(int i=n-y;i<n;i++) np.push_back(p[i]);
        for(int i=x;i<n-y;i++) np.push_back(p[i]);
        for(int i=0;i<x;i++) np.push_back(p[i]);
        p = np;
        ops.push_back({x,y});
    };
    
    for(int k=0;k<n-2;k++){
        // place k+1 at position k
        int pos = -1;
        for(int i=k;i<n;i++) if(p[i]==k+1){ pos=i; break; }
        if(pos==k) continue;
        
        // First, bring element to position n-1 if not there
        if(pos != n-1){
            // op: x=pos+1, y=n-1-pos -> swaps [0..pos] with [pos+1..n-1] ... no
            // Use: x=1, y=n-1-pos: moves p[pos+1..n-1] to front... 
            // Better: x=pos+1, y=n-pos-1 (if valid)
            int x1 = pos+1, y1 = n-1-pos;
            if(x1>0 && y1>0 && x1+y1<n) apply_op(x1,y1); 
            else { // pos==n-1 already handled, pos==0: x=1,y need n-1-0=... 
                apply_op(1, n-1-pos-1>0? n-1-pos-1 : 1);
                pos = -1; for(int i=k;i<n;i++) if(p[i]==k+1){pos=i;break;}
                if(pos==k) continue;
            }
            pos=n-1;
        }
        // Now element is at position n-1
        int y2 = n-k-1;
        int x2 = k>0?k:1; // must be >0
        if(x2+y2<n && x2>0 && y2>0) apply_op(x2,y2);
    }
    
    printf("%d\n",(int)ops.size());
    for(auto [a,b]:ops) printf("%d %d\n",a,b);
}
