#include <bits/stdc++.h>
using namespace std;

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    int n; cin>>n;
    vector<int> x(n),y(n); vector<long long> r(n);
    for(int i=0;i<n;i++) cin>>x[i]>>y[i]>>r[i];
    
    // Grid-based ownership: grid[gx][gy] = id of rectangle owning that cell, or -1
    // We'll use a 2D array of shorts for the 10000x10000 grid - too large (100M).
    // Instead, use interval-based approach with a sweep or just optimize the overlap check.
    
    // Actually let's use a different spatial structure: for each rectangle, store its bounds.
    // Use a 2D grid of coarse cells to accelerate overlap detection.
    
    const int G = 100; // grid cells of size 100x100
    vector<vector<vector<int>>> grid(G, vector<vector<int>>(G));
    
    vector<int> a(n),b(n),c(n),d(n);
    
    auto addToGrid = [&](int i){
        int gx0 = a[i]*G/10000, gy0 = b[i]*G/10000;
        int gx1 = (c[i]-1)*G/10000, gy1 = (d[i]-1)*G/10000;
        gx0=max(0,min(G-1,gx0)); gy0=max(0,min(G-1,gy0));
        gx1=max(0,min(G-1,gx1)); gy1=max(0,min(G-1,gy1));
        for(int gx=gx0;gx<=gx1;gx++)
            for(int gy=gy0;gy<=gy1;gy++)
                grid[gx][gy].push_back(i);
    };
    
    auto removeFromGrid = [&](int i){
        int gx0 = a[i]*G/10000, gy0 = b[i]*G/10000;
        int gx1 = (c[i]-1)*G/10000, gy1 = (d[i]-1)*G/10000;
        gx0=max(0,min(G-1,gx0)); gy0=max(0,min(G-1,gy0));
        gx1=max(0,min(G-1,gx1)); gy1=max(0,min(G-1,gy1));
        for(int gx=gx0;gx<=gx1;gx++)
            for(int gy=gy0;gy<=gy1;gy++){
                auto &v=grid[gx][gy];
                v.erase(find(v.begin(),v.end(),i));
            }
    };
    
    auto overlaps = [&](int i, int na, int nb, int nc, int nd) -> bool {
        int gx0 = na*G/10000, gy0 = nb*G/10000;
        int gx1 = (nc-1)*G/10000, gy1 = (nd-1)*G/10000;
        gx0=max(0,min(G-1,gx0)); gy0=max(0,min(G-1,gy0));
        gx1=max(0,min(G-1,gx1)); gy1=max(0,min(G-1,gy1));
        for(int gx=gx0;gx<=gx1;gx++)
            for(int gy=gy0;gy<=gy1;gy++)
                for(int j:grid[gx][gy]){
                    if(j==i) continue;
                    if(na<c[j]&&a[j]<nc&&nb<d[j]&&b[j]<nd) return true;
                }
        return false;
    };
    
    // Find max expansion in a direction without overlap
    auto maxExpand = [&](int i, int dir, int maxAmt) -> int {
        int lo=1,hi=maxAmt,best=0;
        while(lo<=hi){
            int mid=(lo+hi)/2;
            int na=a[i],nb=b[i],nc=c[i],nd=d[i];
            if(dir==0) na=a[i]-mid;
            else if(dir==1) nc=c[i]+mid;
            else if(dir==2) nb=b[i]-mid;
            else nd=d[i]+mid;
            if(na<0||nb<0||nc>10000||nd>10000){hi=mid-1;continue;}
            if(!overlaps(i,na,nb,nc,nd)){best=mid;lo=mid+1;}
            else hi=mid-1;
        }
        return best;
    };
    
    mt19937 rng(42);
    
    auto computeScore = [&]() -> double {
        double score=0;
        for(int i=0;i<n;i++){
            double si=(double)(c[i]-a[i])*(double)(d[i]-b[i]);
            double ri=(double)r[i];
            double ratio=min(ri,si)/max(ri,si);
            score += 1.0 - (1.0-ratio)*(1.0-ratio);
        }
        return score;
    };
    
    vector<int> bestA(n),bestB(n),bestC(n),bestD(n);
    double bestScore=-1;
    
    auto start=chrono::steady_clock::now();
    
    for(int attempt=0;;attempt++){
        if(chrono::duration<double>(chrono::steady_clock::now()-start).count()>4.0) break;
        
        // Reset
        for(int gx=0;gx<G;gx++) for(int gy=0;gy<G;gy++) grid[gx][gy].clear();
        for(int i=0;i<n;i++){a[i]=x[i];b[i]=y[i];c[i]=x[i]+1;d[i]=y[i]+1;addToGrid(i);}
        
        vector<int> ord(n); iota(ord.begin(),ord.end(),0);
        if(attempt%4==0) sort(ord.begin(),ord.end(),[&](int u,int v){return r[u]>r[v];});
        else if(attempt%4==1) sort(ord.begin(),ord.end(),[&](int u,int v){return r[u]<r[v];});
        else shuffle(ord.begin(),ord.end(),rng);
        
        for(int round=0;round<300;round++){
            bool changed=false;
            for(int i:ord){
                long long area=(long long)(c[i]-a[i])*(d[i]-b[i]);
                if(area>=r[i]) continue;
                int dirs[]={0,1,2,3};
                shuffle(dirs,dirs+4,rng);
                for(int dir:dirs){
                    area=(long long)(c[i]-a[i])*(d[i]-b[i]);
                    if(area>=r[i]) break;
                    long long need=r[i]-area;
                    int side=(dir<2)?(d[i]-b[i]):(c[i]-a[i]);
                    if(side==0) continue;
                    int maxExp=min(10000,(int)min((long long)10000,(need+side-1)/side));
                    removeFromGrid(i);
                    int best=maxExpand(i,dir,maxExp);
                    if(best>0){
                        if(dir==0)a[i]-=best;else if(dir==1)c[i]+=best;else if(dir==2)b[i]-=best;else d[i]+=best;
                        changed=true;
                    }
                    addToGrid(i);
                }
            }
            if(!changed) break;
        }
        
        double score=computeScore();
        if(score>bestScore){bestScore=score;bestA=a;bestB=b;bestC=c;bestD=d;}
    }
    
    for(int i=0;i<n;i++) cout<<bestA[i]<<" "<<bestB[i]<<" "<<bestC[i]<<" "<<bestD[i]<<"\n";
}
