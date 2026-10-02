#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> cx(N), cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,2), false);
    {
        vector<bool> sv(max(N,2), true);
        if(N>0) sv[0]=false;
        if(N>1) sv[1]=false;
        for(int i=2;i<N;i++) if(sv[i]){
            isp[i]=true;
            for(long long j=(long long)i*i;j<N;j+=i) sv[j]=false;
        }
    }
    
    auto di=[&](int a, int b)->double{
        double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    vector<int> tour(N+1);
    
    // Nearest neighbor from city 0
    {
        // Grid-based NN
        int GS = max(1, (int)sqrt((double)N)+1);
        double mnx=*min_element(cx.begin(),cx.end()), mxx=*max_element(cx.begin(),cx.end());
        double mny=*min_element(cy.begin(),cy.end()), mxy=*max_element(cy.begin(),cy.end());
        double gw=(mxx-mnx)/GS+1e-9, gh=(mxy-mny)/GS+1e-9;
        vector<vector<int>> grid(GS*GS);
        for(int i=0;i<N;i++){
            int gx_=min(GS-1,(int)((cx[i]-mnx)/gw));
            int gy_=min(GS-1,(int)((cy[i]-mny)/gh));
            grid[gy_*GS+gx_].push_back(i);
        }
        vector<bool> vis(N,false);
        tour[0]=0; vis[0]=true;
        for(int s=1;s<N;s++){
            int last=tour[s-1];
            int gx0=min(GS-1,(int)((cx[last]-mnx)/gw));
            int gy0=min(GS-1,(int)((cy[last]-mny)/gh));
            int best=-1; double bd=1e18;
            for(int r=0;r<=GS;r++){
                for(int dy2=-r;dy2<=r;dy2++) for(int dx2=-r;dx2<=r;dx2++){
                    if(abs(dx2)!=r && abs(dy2)!=r) continue;
                    int nx2=gx0+dx2, ny2=gy0+dy2;
                    if(nx2<0||nx2>=GS||ny2<0||ny2>=GS) continue;
                    for(int c:grid[ny2*GS+nx2]) if(!vis[c]){
                        double d=di(last,c);
                        if(d<bd){bd=d;best=c;}
                    }
                }
                if(best>=0 && r>=1) break;
            }
            tour[s]=best; vis[best]=true;
            int gx_=min(GS-1,(int)((cx[best]-mnx)/gw));
            int gy_=min(GS-1,(int)((cy[best]-mny)/gh));
            auto& g=grid[gy_*GS+gx_];
            g.erase(find(g.begin(),g.end(),best));
        }
        tour[N]=0;
    }
    
    // Precompute penalty step positions
    // Step t: tour[t-1] -> tour[t], penalty if t%10==0 and !isp[tour[t-1]]
    
    auto mult=[&](int t, int src)->double{
        return (t%10==0 && !isp[src]) ? 1.1 : 1.0;
    };
    
    int* T = tour.data();
    
    auto edgeCost=[&](int t)->double{
        return mult(t, T[t-1]) * di(T[t-1], T[t]);
    };
    
    auto totalCost=[&]()->double{
        double s=0;
        for(int t=1;t<=N;t++) s+=edgeCost(t);
        return s;
    };
    
    // Collect penalty positions (steps that are multiples of 10)
    vector<int> penSteps;
    for(int t=10;t<=N;t+=10) penSteps.push_back(t);
    
    // For a 2-opt reversal of tour[i..j], steps affected: i to j+1 (if j+1<=N)
    // But reversing changes the cities at positions i..j, so ALL steps from i to min(j+1,N) change.
    // The key insight: after reversal, tour[i..j] is reversed.
    // Steps i..j+1 change. For steps not at multiples of 10, multiplier is 1.0.
    // So we only need to recompute: boundary edges + any penalty steps in [i, min(j+1,N)].
    
    double curCost = totalCost();
    vector<int> bestTour(T, T+N+1);
    double bestCost = curCost;
    
    auto st=chrono::steady_clock::now();
    mt19937 rng(42);
    double tl=1.90;
    int iter=0;
    
    // Adaptive segment length
    int maxSeg = min(N-1, max(5, N < 1000 ? N-1 : (N < 10000 ? 200 : 100)));
    
    while(true){
        if((++iter&0x1FFF)==0){
            double elapsed=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(elapsed>=tl) break;
        }
        
        double f=chrono::duration<double>(chrono::steady_clock::now()-st).count()/tl;
        double temp=(curCost/N*0.015)*exp(-12.0*f);
        
        // Choose move type
        int moveType = rng()%4; // 0,1,2: 2-opt, 3: or-opt (relocate)
        
        if(moveType < 3 && N > 2) {
            // 2-opt
            int i=1+rng()%(N-1);
            int len=2+rng()%min(maxSeg, N-1);
            int j=i+len-1;
            if(j>=N) continue;
            
            int lo=i, hi=min(j+1, N);
            // Compute old cost for affected steps
            double oC=0;
            for(int t=lo;t<=hi;t++) oC+=edgeCost(t);
            
            reverse(T+i, T+j+1);
            
            double nC=0;
            for(int t=lo;t<=hi;t++) nC+=edgeCost(t);
            
            double d=nC-oC;
            if(d<0 || (temp>1e-20 && d/temp<20 && (rng()%65536)<65536*exp(-d/temp))){
                curCost+=d;
                if(curCost<bestCost){bestCost=curCost; bestTour.assign(T,T+N+1);}
            } else {
                reverse(T+i, T+j+1);
            }
        } else if(N > 3) {
            // Or-opt: relocate city at position i to after position j
            int i=1+rng()%(N-1);
            int j=rng()%N;
            if(j==i || j==i-1) continue;
            
            int city = T[i];
            // Remove city from position i: costs change at steps i and i+1
            // Insert after position j: costs change at step j+1
            
            // Old costs
            double oC = edgeCost(i);
            if(i+1<=N) oC += edgeCost(i+1);
            
            // After removal, step i connects T[i-1] to T[i+1]
            double remC = mult(i, T[i-1]) * di(T[i-1], T[i+1<=N?i+1:0]);
            // But this changes all positions after i... too complex for simple delta
            // Skip or-opt for now, just do 2-opt
            continue;
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
