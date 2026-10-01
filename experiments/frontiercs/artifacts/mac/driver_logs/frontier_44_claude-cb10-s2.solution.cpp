#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> cx(N), cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,3), false);
    {
        vector<bool> sv(max(N,3), true);
        sv[0]=sv[1]=false;
        for(int i=2;i<N;i++){
            if(sv[i]){
                isp[i]=true;
                for(long long j=(long long)i*i;j<N;j+=i) sv[j]=false;
            }
        }
    }
    
    auto Dist=[&](int a, int b)->double{
        double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // Build initial tour using nearest neighbor with grid
    vector<int> tour(N+1);
    {
        int GS = max(1, (int)sqrt((double)N)+1);
        double mnx=cx[0], mxx=cx[0], mny=cy[0], mxy=cy[0];
        for(int i=0;i<N;i++){
            mnx=min(mnx,cx[i]); mxx=max(mxx,cx[i]);
            mny=min(mny,cy[i]); mxy=max(mxy,cy[i]);
        }
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
                        double d=Dist(last,c);
                        if(s%10==0 && !isp[last]) d*=1.1;
                        if((s+1)%10==0 && !isp[c]) d*=1.02;
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
    
    auto mult=[&](int t, int src)->double{
        return (t>=1 && t%10==0 && !isp[src]) ? 1.1 : 1.0;
    };
    
    auto edgeCost=[&](int t, int a, int b)->double{
        return mult(t, a)*Dist(a,b);
    };
    
    auto totalCost=[&]()->double{
        double s=0;
        for(int t=1;t<=N;t++) s+=edgeCost(t, tour[t-1], tour[t]);
        return s;
    };
    
    double curCost = totalCost();
    vector<int> bestTour(tour.begin(), tour.end());
    double bestCost = curCost;
    
    if(N<=2){
        cout<<N+1<<"\n";
        for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
        return 0;
    }
    
    auto st=chrono::steady_clock::now();
    mt19937 rng(42);
    double tl=1.82;
    
    // Precompute distances cache? No, too much memory for large N.
    // We'll do incremental 2-opt and or-opt.
    
    // For 2-opt reversal of [i..j], steps i to min(j+1,N) are affected.
    // For small segments this is fast.
    
    int maxSeg = N<=500 ? N-1 : N<=2000 ? 500 : N<=5000 ? 200 : N<=20000 ? 80 : N<=50000 ? 40 : 25;
    
    long long iter=0;
    double lastCheck=0;
    
    // SA parameters
    double T0 = curCost/N * 0.02;
    double Tf = curCost/N * 0.00001;
    
    while(true){
        iter++;
        if((iter&0x1FFF)==0){
            double elapsed=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(elapsed>=tl) break;
            double frac=elapsed/tl;
            lastCheck=frac;
        }
        
        double frac=lastCheck;
        double temp = T0 * pow(Tf/T0, frac);
        
        int op = rng()%100;
        
        if(op<75){
            // 2-opt: reverse [i..j]
            int i=1+rng()%(N-1);
            int len=2+rng()%min(maxSeg, N-1);
            int j=i+len-1;
            if(j>=N) continue;
            
            int lo=i, hi=min(j+1, N);
            double oC=0;
            for(int t=lo;t<=hi;t++) oC+=edgeCost(t, tour[t-1], tour[t]);
            
            reverse(tour.data()+i, tour.data()+j+1);
            
            double nC=0;
            for(int t=lo;t<=hi;t++) nC+=edgeCost(t, tour[t-1], tour[t]);
            
            double d=nC-oC;
            if(d<0||(temp>1e-30 && d<temp*15 && exp(-d/temp)>(double)(rng()%10000)/10000.0)){
                curCost+=d;
                if(curCost<bestCost){bestCost=curCost; bestTour.assign(tour.begin(),tour.end());}
            } else {
                reverse(tour.data()+i, tour.data()+j+1);
            }
        } else {
            // Or-opt: relocate city at pos i to after pos j
            int i=1+rng()%(N-1);
            int j=rng()%(N);
            if(j==0&&N>2) j=1;
            if(j==i||j==i-1) continue;
            
            // Remove cost
            int lo1=i, hi1=min(i+1,N);
            double oC=0;
            for(int t=lo1;t<=hi1;t++) oC+=edgeCost(t, tour[t-1], tour[t]);
            
            int city=tour[i];
            // After removal, reconnect: steps around i change
            // Then insert after position j (in new indexing)
            // Easiest: just do it and recompute affected region
            
            vector<int>& T=tour;
            int saved=T[i];
            if(i<j){
                for(int k=i;k<j;k++) T[k]=T[k+1];
                T[j]=saved;
                int lo2=max(1,i), hi2=min(j+1,N);
                double nC2=0;
                for(int t=lo2;t<=hi2;t++) nC2+=edgeCost(t,T[t-1],T[t]);
                double oC2=0;
                // need old cost for range [lo2..hi2]
                // but we already modified... let's just do full delta
                double newTotal=totalCost();
                double d2=newTotal-curCost;
                if(d2<0||(temp>1e-30 && d2<temp*15 && exp(-d2/temp)>(double)(rng()%10000)/10000.0)){
                    curCost=newTotal;
                    if(curCost<bestCost){bestCost=curCost;bestTour.assign(T.begin(),T.end());}
                } else {
                    int s2=T[j];
                    for(int k=j;k>i;k--) T[k]=T[k-1];
                    T[i]=s2;
                }
            } else {
                for(int k=i;k>j+1;k--) T[k]=T[k-1];
                T[j+1]=saved;
                double newTotal=totalCost();
                double d2=newTotal-curCost;
                if(d2<0||(temp>1e-30 && d2<temp*15 && exp(-d2/temp)>(double)(rng()%10000)/10000.0)){
                    curCost=newTotal;
                    if(curCost<bestCost){bestCost=curCost;bestTour.assign(T.begin(),T.end());}
                } else {
                    int s2=T[j+1];
                    for(int k=j+1;k<i;k++) T[k]=T[k+1];
                    T[i]=s2;
                }
            }
        }
    }
    
    // Final: try swapping cities at penalty positions to primes
    tour.assign(bestTour.begin(), bestTour.end());
    curCost=bestCost;
    
    // Greedy: for each penalty step (t%10==0), if tour[t-1] is not prime, try swapping with a nearby prime
    for(int pass=0;pass<3;pass++){
        for(int t=10;t<=N;t+=10){
            if(isp[tour[t-1]]) continue;
            int bestJ=-1; double bestD=0;
            // try swapping tour[t-1] with tour[k] for various k
            for(int tries=0;tries<200;tries++){
                int k=1+rng()%(N-1);
                if(k==t-1) continue;
                if(!isp[tour[k]]) continue;
                // compute delta of swapping positions t-1 and k
                int lo=min(t-1,k), hi=max(t-1,k);
                // affected steps: around t-1 and around k
                set<int> aff;
                for(int s=max(1,lo);s<=min(lo+1,N);s++) aff.insert(s);
                for(int s=max(1,hi);s<=min(hi+1,N);s++) aff.insert(s);
                double oC=0;
                for(int s:aff) oC+=edgeCost(s, tour[s-1], tour[s]);
                swap(tour[t-1], tour[k]);
                double nC=0;
                for(int s:aff) nC+=edgeCost(s, tour[s-1], tour[s]);
                double d=nC-oC;
                if(d<bestD){bestD=d;bestJ=k;}
                swap(tour[t-1], tour[k]);
            }
            if(bestJ>=0){
                swap(tour[t-1], tour[bestJ]);
                curCost+=bestD;
            }
        }
    }
    if(curCost<bestCost){bestCost=curCost;bestTour.assign(tour.begin(),tour.end());}
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
