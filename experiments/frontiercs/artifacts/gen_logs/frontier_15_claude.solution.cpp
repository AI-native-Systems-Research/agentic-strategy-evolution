#include <bits/stdc++.h>
using namespace std;
int main(){
    int n;
    scanf("%d",&n);
    vector<int> p(n);
    for(int i=0;i<n;i++) scanf("%d",&p[i]);
    
    vector<pair<int,int>> ops;
    
    auto apply_op = [&](int x, int y){
        vector<int> np;
        for(int i=n-y;i<n;i++) np.push_back(p[i]);
        for(int i=x;i<n-y;i++) np.push_back(p[i]);
        for(int i=0;i<x;i++) np.push_back(p[i]);
        p=np;
        ops.push_back({x,y});
    };
    
    for(int i=0;i<n-2 && (int)ops.size()<4*n-2;i++){
        int j=-1;
        for(int k=i;k<n;k++) if(p[k]==i+1){j=k;break;}
        if(j==i) continue;
        
        // Element i+1 is at position j, want it at position i
        // Step 1: move it to position i using at most 2 ops
        
        if(j == n-1){
            // suffix of length n-i-1 won't work directly if middle is empty
            // x=i+1, y=n-1-i => x+y=n, invalid. Use x=i+1, y=n-2-i if n-2-i>0
            if(n-2-i > 0 && i+1 > 0){
                apply_op(i+1, n-2-i); // moves last to pos i+1... recalc
                for(int k=i;k<n;k++) if(p[k]==i+1){j=k;break;}
                if(j==i) continue;
            }
        }
        // Now j is in [i+1, n-2]
        if(j > i && j < n){
            int x = j - i;
            int y = n - j;
            // x+y = n-i, need < n => i > 0
            if(i > 0 && x > 0 && y > 0 && x+y < n){
                apply_op(x, y); // suffix=p[j..n-1] goes to front, prefix=p[0..x-1] goes to end
                // p[j]=target goes to position 0, then we need it at position i
                for(int k=i;k<n;k++) if(p[k]==i+1){j=k;break;}
                if(j==i) continue;
            }
            if(j > i){
                int xx = j, yy = n - j;
                if(xx > 0 && yy > 0 && xx+yy < n){ apply_op(xx,yy); for(int k=i;k<n;k++) if(p[k]==i+1){j=k;break;} }
                if(j > i && j < n){ xx=j-i; yy=n-j; if(xx>0&&yy>0&&xx+yy<n){ apply_op(xx,yy); }}
            }
        }
    }
    printf("%d\n",(int)ops.size());
    for(auto&[x,y]:ops) printf("%d %d\n",x,y);
}
