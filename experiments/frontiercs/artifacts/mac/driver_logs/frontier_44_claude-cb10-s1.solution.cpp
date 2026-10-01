#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> cx(N),cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,2),false);
    {
        vector<bool> sv(max(N,2),true);
        sv[0]=false; if(N>1)sv[1]=false;
        for(int i=2;i<N;i++){
            if(sv[i]){
                isp[i]=true;
                for(long long j=(long long)i*i;j<N;j+=i)sv[j]=false;
            }
        }
    }
    
    auto distf=[&](int a,int b)->double{
        double dx=cx[a]-cx[b],dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // step t (1-indexed), source city c
    auto gm=[&](int t,int c)->double{
        return(t%10==0&&!isp[c])?1.1:1.0;
    };
    
    auto calcCost=[&](vector<int>&p)->double{
        double s=0;
        for(int t=1;t<=N;t++)
            s+=distf(p[t-1],p[t])*gm(t,p[t-1]);
        return s;
    };
    
    // Start with input order
    vector<int> tour(N+1);
    tour[0]=0;
    for(int i=1;i<N;i++) tour[i]=i;
    tour[N]=0;
    
    // Try to place primes at penalty positions (index 9,19,29,... which is step 10,20,30,...)
    // Greedy swap: for each penalty position, find nearest prime and swap
    {
        vector<int> pos(N);
        for(int i=0;i<=N;i++) if(i<N) pos[tour[i]]=i;
        
        for(int idx=9;idx<N;idx+=10){
            if(isp[tour[idx]]) continue;
            // find a prime city nearby that's not at a penalty position
            int bestJ=-1; double bestDist=1e18;
            int lo=max(1,idx-200), hi=min(N-1,idx+200);
            for(int j=lo;j<=hi;j++){
                if(j==idx) continue;
                if(!isp[tour[j]]) continue;
                if((j%10==9)&&isp[tour[j]]) continue; // don't steal from another penalty pos
                double d=abs(j-idx)*1.0;
                if(d<bestDist){bestDist=d;bestJ=j;}
            }
            if(bestJ>=0){
                swap(tour[idx],tour[bestJ]);
                pos[tour[idx]]=idx;
                pos[tour[bestJ]]=bestJ;
            }
        }
    }
    
    double curCost=calcCost(tour);
    double bestCost=curCost;
    vector<int> bestTour=tour;
    
    mt19937 rng(42);
    auto startT=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-startT).count();};
    double timeLimit=1.80;
    
    double T0=bestCost/N*0.3, Te=T0*1e-8;
    int maxSeg=min(N-1,max(20, N<=500?N-1:N<=5000?300:N<=20000?100:N<=100000?40:25));
    
    long long it=0;
    while(true){
        if((++it&2047)==0){if(elapsed()>=timeLimit)break;}
        double f=elapsed()/timeLimit; if(f>=1.0)break;
        double temp=T0*pow(Te/T0,f);
        
        int i=1+(rng()%(N-1));
        int sp=2+(rng()%maxSeg);
        int j=i+sp-1; if(j>=N) continue;
        
        int lo=i,hi=min(j+1,N);
        double oC=0; for(int t=lo;t<=hi;t++) oC+=distf(tour[t-1],tour[t])*gm(t,tour[t-1]);
        reverse(tour.begin()+i,tour.begin()+j+1);
        double nC=0; for(int t=lo;t<=hi;t++) nC+=distf(tour[t-1],tour[t])*gm(t,tour[t-1]);
        double d=nC-oC;
        if(d<0||(temp>1e-30&&d<temp*16&&(rng()%65536)<65536.0*exp(-d/temp))){
            curCost+=d;
            if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
        } else {
            reverse(tour.begin()+i,tour.begin()+j+1);
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
