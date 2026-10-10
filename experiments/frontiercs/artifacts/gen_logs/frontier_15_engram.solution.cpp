#include <bits/stdc++.h>
using namespace std;

int main(){
    int n;
    scanf("%d",&n);
    vector<int> p(n);
    for(int i=0;i<n;i++) scanf("%d",&p[i]);
    
    vector<pair<int,int>> ops;
    
    // Try to place elements 1,2,...,n into positions 0,1,...,n-1
    for(int placed=0; placed<n-2; placed++){
        // Find where (placed+1) is
        int pos=-1;
        for(int i=placed;i<n;i++) if(p[i]==placed+1){pos=i;break;}
        if(pos==placed) continue; // already in place
        
        // We need to bring p[pos] to position 'placed'
        // Current active range is [0..n-1] but we operate on entire array
        // Step 1: if pos != n-1, move element to end: x=pos+1, y=n-1-pos => but need x+y<n => pos+1+n-1-pos=n, not <n
        // So first move it: use x=pos, y=1 if pos>0 and pos+1<n => brings last elem to front, first pos elems to end
        // Actually let me just use: bring element to position n-1 first, then bring it to 'placed'
        
        if(pos < n-1){
            // op: x=1, y=n-1-pos, need 1+(n-1-pos)<n => n-pos<n => pos>0, true since pos>=placed and if placed=0, pos>0 since not in place
            if(pos==0){// element at pos 0, need to move. x=1,y could move it but it stays in prefix. Use x=pos+1=1, y=n-pos-1=n-1. x+y=n, not <n. Use x=1,y=n-2.
                ops.push_back({1,n-2}); // moves pos0 to position n-2, last n-2 to front
                // simulate
                int x=1,y=n-2; vector<int> np(p.begin()+n-y,p.end()); np.insert(np.end(),p.begin()+x,p.begin()+n-y); np.insert(np.end(),p.begin(),p.begin()+x); p=np;
                pos=n-2; // now element is at n-2... wait let me recheck
                for(int i=0;i<n;i++) if(p[i]==placed+1){pos=i;break;}
            }
            if(pos<n-1){
                int x=pos+1, y=n-1-pos;
                if(x+y<n && x>0 && y>0){
                    ops.push_back({x,y});
                    vector<int> np(p.begin()+n-y,p.end()); np.insert(np.end(),p.begin()+x,p.begin()+n-y); np.insert(np.end(),p.begin(),p.begin()+x); p=np;
                    for(int i=0;i<n;i++) if(p[i]==placed+1){pos=i;break;}
                } else {
                    // x+y=n means middle is empty, not allowed. x=pos+1, y=n-1-pos, x+y=n. Need middle>=1.
                    // Use y=n-2-pos instead if pos+1+n-2-pos=n-1<n, y=n-2-pos>0 => pos<n-2
                    if(pos<n-2){
                        int xx=pos+1, yy=n-2-pos;
                        ops.push_back({xx,yy});
                        vector<int> np(p.begin()+n-yy,p.end()); np.insert(np.end(),p.begin()+xx,p.begin()+n-yy); np.insert(np.end(),p.begin(),p.begin()+xx); p=np;
                        for(int i=0;i<n;i++) if(p[i]==placed+1){pos=i;break;}
                    }
                }
            }
        }
        // Now try to bring from pos to 'placed'
        if(pos==placed) continue;
        // element is at pos (hopefully n-1 or close)
        {
            int x=placed+1, y=n-pos;
            if(x>0 && y>0 && x+y<n && pos>=placed){
                // This would put suffix [pos..n-1] at front, prefix [0..placed] at end
                // Element at pos goes to position pos-placed (within suffix block: position in suffix = 0)
                // Actually suffix is p[n-y..n-1] = p[pos..n-1], goes to positions [0..y-1]
                // Element is at p[pos], which is first in suffix, goes to position 0
                // But we want it at position 'placed', not 0
                // Let me reconsider
            }
        }
        // Simple approach: bring to end then bring to placed position
        if(pos!=n-1) continue; // skip if couldn't get to end
        // element at n-1. x=placed+1, y=1: need placed+1+1<n => placed<n-2 (true)
        if(placed+2<n){
            int x=placed+1, y=1;
            ops.push_back({x,y});
            vector<int> np(p.begin()+n-y,p.end()); np.insert(np.end(),p.begin()+x,p.begin()+n-y); np.insert(np.end(),p.begin(),p.begin()+x); p=np;
        }
    }
    
    printf("%d\n",(int)ops.size());
    for(auto&[x,y]:ops) printf("%d %d\n",x,y);
}
