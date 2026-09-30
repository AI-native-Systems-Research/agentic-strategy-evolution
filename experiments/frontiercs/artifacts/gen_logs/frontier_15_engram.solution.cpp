#include <bits/stdc++.h>
using namespace std;

int main(){
    int n;
    scanf("%d",&n);
    vector<int> p(n);
    for(int i=0;i<n;i++) scanf("%d",&p[i]);
    
    vector<pair<int,int>> ops;
    
    auto apply_op = [&](int x, int y){
        // Split: [0..x-1] [x..n-y-1] [n-y..n-1]
        // Result: [n-y..n-1] [x..n-y-1] [0..x-1]
        assert(x>0 && y>0 && x+y<n);
        vector<int> np;
        for(int i=n-y;i<n;i++) np.push_back(p[i]);
        for(int i=x;i<n-y;i++) np.push_back(p[i]);
        for(int i=0;i<x;i++) np.push_back(p[i]);
        p = np;
        ops.push_back({x,y});
    };
    
    for(int i=0; i<n-2; i++){
        // Find where value i+1 is
        int j = -1;
        for(int k=0;k<n;k++) if(p[k]==i+1) {j=k; break;}
        if(j==i) continue;
        
        // We need to move p[j] to position i
        // First, if j > i, we can try to get it to position i
        
        if(j == n-1){
            // element is at last position
            // Do op (i+1, 1) if i+1 + 1 < n, i.e., i+2 < n, i.e., i < n-2 (always true in loop)
            // This moves last element to position 0, then prefix of length i+1 goes to end
            // Result: [p[n-1]] [p[i+1]..p[n-2]] [p[0]..p[i]]
            // p[n-1] = i+1 goes to position 0, not position i
            // If i==0, this places it correctly!
            if(i==0){
                apply_op(1, 1); // moves last to front, front to back
                // Actually let me just handle generically
                j = 0; // After op, need to re-find
                // Undo - let me think differently
            }
            // Move element from position n-1 to position 0 first: op(1, 1) 
            // [p[n-1], p[1]..p[n-2], p[0]]
            apply_op(1, 1);
            j = 0;
            if(i==0) continue;
        }
        
        if(j > i){
            // element at position j, need at position i
            // op with x = j-i, y = n-j: prefix=[i..j-1-i+i]... 
            // Hmm, we want to move p[j] to position i
            // But positions 0..i-1 are already sorted, we don't want to disturb them
            // op(x=j, y=n-j): suffix is p[j..n-1], prefix is p[0..j-1]
            // result: [p[j]..p[n-1]] [nothing if middle empty... need x+y<n]
            // x+y = j + (n-j) = n, not < n. So can't do this.
            // op(x=i+1, y=n-j): result = [p[j]..p[n-1], p[i+1]..p[j-1], p[0]..p[i]]
            // p[0]..p[i] goes to end (those are sorted 1..i+1 except i+1 is at j)
            // Then do op to restore: put p[0..i-1] back
            int x1 = i+1, y1 = n-j;
            if(x1+y1<n){
                apply_op(x1, y1);
                // Now array: [p[j]..p[n-1], p[i+1]..p[j-1], p[0]..p[i]]
                // p[j]=i+1 is at position 0, sorted prefix p[0..i] is at end (length i+1)
                // Do op(1, i+1) to get: [sorted prefix, middle, i+1]... no
                // Do op(n-i-1, i): moves last i elements (which are 1..i) to front
                // Actually last i+1 elements are old p[0]..p[i] = 1,2,...,i, i+1_not_there
                // Let me just apply op(n-(i+1), i) ... need to think about what's at end
                // After first op, last i+1 positions hold old p[0]..p[i]
                // old p[0..i] = sorted 1..i plus whatever was at position i (not i+1)
                // This is getting complicated. Let me use a simpler 2-op approach.
                // second op: x2=1, y2=i+1 if 1+i+1<n
                if(1+i+1<n){
                    apply_op(1, i+1);
                }else if(i+1+1<n){
                    apply_op(i+1,1);
                }
                continue;
            }
        }
        // Fallback: bring to front then to position i
        if(j!=0 && j!=n-1 && j!=i){
            apply_op(j, 1);
            j=0;
        }
        if(j==0 && i>0 && i+1<n){
            apply_op(1, n-1-i);
        }
    }
    
    printf("%d\n",(int)ops.size());
    for(auto&[a,b]:ops) printf("%d %d\n",a,b);
}
