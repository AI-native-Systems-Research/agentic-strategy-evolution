#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin>>N;
    vector<double> cx(N),cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,2),false);
    {
        vector<bool> sieve(max(N,2),true);
        if(N>0) sieve[0]=false;
        if(N>1) sieve[1]=false;
        for(int i=2;i<N;i++){
            if(sieve[i]){
                isp[i]=true;
                for(long long j=(long long)i*i;j<N;j+=i) sieve[j]=false;
            }
        }
    }
    
    auto Dist=[&](int a,int b)->double{
        double dx=cx[a]-cx[b],dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // tour[0]=0, tour[N]=0, tour[1..N-1] = permutation of 1..N-1
    // step t goes from tour[t-1] to tour[t], t=1..N
    // penalty at step t if t%10==0 and tour[t-1] is not prime
    
    auto tourCost=[&](const vector<int>&tour)->double{
        double s=0;
        for(int t=1;t<=N;t++){
            double d=Dist(tour[t-1],tour[t]);
            if(t%10==0 && !isp[tour[t-1]]) d*=1.1;
            s+=d;
        }
        return s;
    };
    
    // Start with input order (which is sorted by x - a strong baseline)
    vector<int> tour(N+1);
    tour[0]=0;
    for(int i=1;i<N;i++) tour[i]=i;
    tour[N]=0;
    
    // Try NN construction too and pick best
    {
        vector<int> tour2; tour2.reserve(N+1);
        tour2.push_back(0);
        vector<bool> used(N,false);
        used[0]=true;
        
        vector<int> sortx(N);
        iota(sortx.begin(),sortx.end(),0);
        sort(sortx.begin(),sortx.end(),[&](int a,int b){return cx[a]<cx[b];});
        vector<int> xrank(N);
        for(int i=0;i<N;i++) xrank[sortx[i]]=i;
        
        for(int step=1;step<N;step++){
            int last=tour2.back();
            int r=xrank[last];
            int best=-1; double bestd=1e30;
            int checked=0;
            int lo=r-1, hi=r+1;
            double lx_=cx[last];
            bool penNow=(step%10==0 && !isp[last]);
            double mult=penNow?1.1:1.0;
            
            while((lo>=0||hi<N)&&checked<200){
                if(hi<N){
                    int c=sortx[hi]; hi++;
                    if(!used[c]){
                        if(mult*(cx[c]-lx_)>bestd){hi=N;}
                        else{
                            double d=mult*Dist(last,c);
                            if(d<bestd){bestd=d;best=c;}
                            checked++;
                        }
                    }
                }
                if(lo>=0){
                    int c=sortx[lo]; lo--;
                    if(!used[c]){
                        if(mult*(lx_-cx[c])>bestd){lo=-1;}
                        else{
                            double d=mult*Dist(last,c);
                            if(d<bestd){bestd=d;best=c;}
                            checked++;
                        }
                    }
                }
            }
            if(best==-1){for(int i=0;i<N;i++)if(!used[i]){best=i;break;}}
            used[best]=true;
            tour2.push_back(best);
        }
        tour2.push_back(0);
        if(tourCost(tour2)<tourCost(tour)) tour=tour2;
    }
    
    double curCost=tourCost(tour);
    
    auto startTime=chrono::steady_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    // For fast delta: compute step cost
    // stepCost(t) = m(t)*dist(tour[t-1],tour[t])
    auto stepMult=[&](int t, int city)->double{
        return (t%10==0 && !isp[city])?1.1:1.0;
    };
    auto sc=[&](int t)->double{
        return stepMult(t,tour[t-1])*Dist(tour[t-1],tour[t]);
    };
    
    mt19937 rng(12345);
    
    // Or-opt (relocate): remove city at position i, insert at position j
    // This is O(1) delta for non-penalty steps, but penalties complicate things
    // For simplicity, compute delta by recalculating affected steps
    
    // We'll do a mix of or-opt and swap moves with SA
    
    double T0=curCost/N*0.1;
    double Tend=curCost/N*1e-6;
    
    int iter=0;
    double bestCost=curCost;
    vector<int> bestTour=tour;
    
    while(elapsed()<1.85){
        double frac=elapsed()/1.85;
        double T=T0*pow(Tend/T0,frac);
        
        int mode=rng()%2;
        if(mode==0){
            // swap two random positions (not 0 or N)
            int i=1+(rng()%(N-1));
            int j=1+(rng()%(N-1));
            if(i==j) continue;
            // affected steps: i, i+1, j, j+1 (if i,j not adjacent)
            int mi=min(i,j), ma=max(i,j);
            double oldC=sc(mi)+sc(min(mi+1,N));
            if(ma!=mi+1) oldC+=sc(ma)+sc(min(ma+1,N));
            else oldC=sc(mi)+sc(mi+1)+sc(min(mi+2,N));
            
            swap(tour[i],tour[j]);
            
            double newC=sc(mi)+sc(min(mi+1,N));
            if(ma!=mi+1) newC+=sc(ma)+sc(min(ma+1,N));
            else newC=sc(mi)+sc(mi+1)+sc(min(mi+2,N));
            
            double delta=newC-oldC;
            if(delta<0||((double)(rng()%1000000)/1000000.0)<exp(-delta/T)){
                curCost+=delta;
                if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
            } else {
                swap(tour[i],tour[j]);
            }
        } else {
            // or-opt: move city at pos i to after pos j
            int i=1+(rng()%(N-1));
            int j=rng()%N; // insert after j (0..N-1), but not at i-1 or i
            if(j==i||j==i-1) continue;
            
            double oldC=sc(i)+sc(min(i+1,N))+sc(min(j+1,N));
            int city=tour[i];
            tour.erase(tour.begin()+i);
            int jj=j; if(j>i) jj--;
            tour.insert(tour.begin()+jj+1,city);
            // recompute affected region
            int lo2=min(i,jj+1)-1; if(lo2<0)lo2=0;
            int hi2=max(i+1,jj+2); if(hi2>N)hi2=N;
            double nc=tourCost(tour);
            double delta=nc-curCost;
            if(delta<0||((double)(rng()%1000000)/1000000.0)<exp(-delta/T)){
                curCost=nc;
                if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
            } else {
                tour.erase(tour.begin()+jj+1);
                tour.insert(tour.begin()+i,city);
            }
        }
        iter++;
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
