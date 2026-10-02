#include <iostream>
#include <vector>
#include <algorithm>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n;
    cin >> n;
    vector<int> p(n);
    for(int i=0;i<n;i++) cin >> p[i];
    
    vector<pair<int,int>> ops;
    
    // Greedy: place elements 1,2,...,n in order
    // We maintain a "locked" prefix of length `locked` that is already sorted.
    // But operations act on the whole array, so we can't truly lock.
    // Instead, we work on the full array each time.
    
    // Strategy: to place the minimum remaining element at position `locked`:
    // Find where it is (position pos). We need to move p[pos] to p[locked].
    // We can do this with at most 2 operations.
    
    auto doOp = [&](int x, int y){
        if(x<=0||y<=0||x+y>=n) return;
        ops.push_back({x,y});
        // Apply: [suffix | middle | prefix]
        vector<int> np;
        for(int i=n-y;i<n;i++) np.push_back(p[i]);
        for(int i=x;i<n-y;i++) np.push_back(p[i]);
        for(int i=0;i<x;i++) np.push_back(p[i]);
        p = np;
    };
    
    for(int locked=0; locked<n-2 && (int)ops.size()<4*n-2; locked++){
        // Find position of element (locked+1)
        int pos = -1;
        for(int i=locked;i<n;i++) if(p[i]==locked+1){pos=i;break;}
        if(pos==locked) continue; // already in place
        
        // We want to move p[pos] to p[locked].
        // Operation with x, y: new array = [p[n-y..n-1], p[x..n-y-1], p[0..x-1]]
        // We need element at pos to end up at position locked.
        
        // Step 1: move element to position 0 (if not already there)
        if(pos > 0 && pos < n-1){
            // Use x=pos, y=1 (or similar) - actually let's rotate element to front
            // x=pos, y= n-pos => but x+y=n not < n. 
            // Use x=1, y=n-pos: element at pos goes to position 0? 
            // new[0..y-1] = p[n-y..n-1] = p[pos..n-1], so new[0]=p[pos]. Yes!
            int y = n - pos;
            int x = 1;
            if(x+y<n) doOp(x,y);
            else { doOp(pos, 1); /* moves p[pos] to end, then fix */ 
                   // Actually p[pos] goes to position n-1. Then move to front.
                   doOp(1, 1); // This just rotates
                   pos = -1; // recalc
                   for(int i=0;i<n;i++) if(p[i]==locked+1){pos=i;break;}
                   if(pos==locked) continue;
                   if(pos>0 && pos<n-1){ int yy=n-pos; doOp(1,yy); }
                   else if(pos==n-1){ doOp(1,1); pos=0; /* not quite */ for(int i=0;i<n;i++) if(p[i]==locked+1){pos=i;break;} if(pos==locked) continue;}
            }
            for(int i=0;i<n;i++) if(p[i]==locked+1){pos=i;break;}
            if(pos==locked) continue;
        }
        if(pos==n-1){
            doOp(1,1);
            for(int i=0;i<n;i++) if(p[i]==locked+1){pos=i;break;}
            if(pos==locked) continue;
        }
        // Now element should be at position 0 (pos==0) ideally
        if(pos==0 && locked>0){
            // Move from 0 to locked: use y=n-locked, x=locked? 
            // new = [p[n-y..n-1], p[x..n-y-1], p[0..x-1]]
            // p[0] goes to position n-x = n-locked. Not what we want.
            // Use x=1, y=n-locked: new[0..n-locked-1]=p[locked..n-1], new[n-locked..n-2]=p[1..locked-1], new[n-1]=p[0]
            // That puts it at n-1. Then use x=n-1-locked, y=locked+1: 
            // Hmm, let me just try: x=n-locked, y=locked
            // new = [p[n-locked..n-1], p[n-locked..n-locked-1(empty?)], p[0..n-locked-1]]
            // x+y = n, not valid.
            // x=n-locked-1, y=locked: x+y=n-1<n. middle=p[n-locked-1..n-locked-1]={p[n-locked-1]}
            // new=[p[n-locked..n-1], p[n-locked-1], p[0..n-locked-2]]
            // p[0] goes to position locked+1+1-1 = n-1-(n-locked-2) = locked+1... not locked.
            // Let me just brute force: try all (x,y) and pick one that places element correctly.
            bool done=false;
            for(int x=1;x<n&&!done;x++) for(int y=1;x+y<n&&!done;y++){
                // p[0] goes to position y+(n-x-y)-1+1-1 = n-x-1... no.
                // In new array, p[0..x-1] goes to end, starting at position n-x.
                // So p[0] goes to position n-x.
                if(n-x==locked){doOp(x,y);done=true;}
            }
            if(done) continue;
        }
        // Fallback: just continue
    }
    
    cout << ops.size() << "\n";
    for(auto [x,y]:ops) cout << x << " " << y << "\n";
}