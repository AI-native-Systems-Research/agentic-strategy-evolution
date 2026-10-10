#include <bits/stdc++.h>
using namespace std;

int main(){
    int n;
    scanf("%d",&n);
    vector<int> p(n);
    for(int i=0;i<n;i++) scanf("%d",&p[i]);
    
    vector<pair<int,int>> ops;
    
    auto apply=[&](int x,int y){
        vector<int> np(n);
        // [0..x-1 | x..n-y-1 | n-y..n-1] -> [n-y..n-1 | x..n-y-1 | 0..x-1]
        for(int j=0;j<y;j++) np[j]=p[n-y+j];
        for(int j=0;j<n-x-y;j++) np[y+j]=p[x+j];
        for(int j=0;j<x;j++) np[n-x+j]=p[j];
        p=np;
        ops.push_back({x,y});
    };
    
    for(int i=0;i<n-2;i++){
        if(p[i]==i+1) continue;
        int pos=-1;
        for(int j=i;j<n;j++) if(p[j]==i+1){pos=j;break;}
        
        // Step 1: Move element from pos to position 0
        if(pos>0){
            if(pos<=n-2){
                // x=pos, y can be anything >=1 with x+y<n => y<=n-pos-1>=1
                // element at pos is first of middle, goes to position y
                // Want it at 0: use suffix approach
                // element at pos: if we set y=n-pos, element is at start of suffix, goes to 0
                // need x>=1, x+y<n => x < pos, and x>=1 => pos>1
                if(pos<n-1 && pos>1){
                    apply(1, n-pos); // element at pos = n-(n-pos) = pos, in suffix start, goes to 0
                } else if(pos==1){
                    // x=1,y must satisfy 1+y<n, element at pos=1 is middle start, goes to y
                    // want y=0 impossible. Use: x=pos=1, y=n-2 => element at 1 goes to middle start = y=n-2. Then move from n-2 to 0.
                    apply(1, 1); // pos1 -> middle start -> pos 1... 
                    // Actually element at pos=1, x=1: in middle, goes to pos 1-1+y = y
                    if(p[0]==i+1) {continue;} // check
                    pos=0; for(int j=0;j<n;j++) if(p[j]==i+1){pos=j;break;}
                    if(pos>0 && pos<n-1) apply(1, n-pos);
                    else if(pos==n-1) apply(1,1);
                } else { // pos==n-1
                    apply(1,1);
                }
            }
        }
        // Now element should be at position 0
        int cur=0; for(int j=0;j<n;j++) if(p[j]==i+1){cur=j;break;}
        if(cur!=0){ i--; continue; } // retry
        if(i==0) continue;
        // Move from 0 to i: x=n-i, y=1 => element at 0 (in prefix) goes to n-(n-i)+0 = i
        if(n-i+1<n && n-i>=1) apply(n-i,1);
    }
    printf("%d\n",(int)ops.size());
    for(auto&[a,b]:ops) printf("%d %d\n",a,b);
}
