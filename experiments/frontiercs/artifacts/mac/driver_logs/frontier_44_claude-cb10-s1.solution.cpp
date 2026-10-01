#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double> cx(N),cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    vector<bool> isp(max(N,2),false);
    {vector<bool> sv(max(N,2),true); sv[0]=false; if(N>1)sv[1]=false;
     for(int i=2;i<N;i++) if(sv[i]){isp[i]=true;for(long long j=(long long)i*i;j<N;j+=i)sv[j]=false;}}
    auto Dist=[&](int a,int b)->double{double dx=cx[a]-cx[b],dy=cy[a]-cy[b];return sqrt(dx*dx+dy*dy);};
    auto gm=[&](int t,int src)->double{return(t%10==0&&!isp[src])?1.1:1.0;};
    auto calcCost=[&](vector<int>&p)->double{double s=0;for(int t=1;t<=N;t++)s+=Dist(p[t-1],p[t])*gm(t,p[t-1]);return s;};
    // Nearest neighbor initial tour
    vector<bool> used(N,false);
    vector<int> tour(N+1);
    tour[0]=0; used[0]=true;
    for(int i=1;i<N;i++){
        int prev=tour[i-1];
        double bd=1e18; int bc=-1;
        // For large N, sample random candidates
        if(N<=5000){
            for(int j=0;j<N;j++) if(!used[j]){double d=Dist(prev,j);if(d<bd){bd=d;bc=j;}}
        } else {
            // Check nearby by x-coordinate using sorted order
            // cities are sorted by x already (id=index)
            int lo=max(1,prev-500),hi=min(N-1,prev+500);
            for(int j=lo;j<=hi;j++) if(!used[j]){double d=Dist(prev,j);if(d<bd){bd=d;bc=j;}}
            if(bc==-1) for(int j=0;j<N;j++) if(!used[j]){double d=Dist(prev,j);if(d<bd){bd=d;bc=j;}}
        }
        tour[i]=bc; used[bc]=true;
    }
    tour[N]=0;
    double curCost=calcCost(tour);
    vector<int> best=tour; double bestCost=curCost;
    mt19937 rng(42);
    auto st=chrono::steady_clock::now();
    auto el=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-st).count();};
    double tl=1.85;
    double T0=curCost/N*2.0, Te=curCost/N*1e-8;
    for(long long it=0;;it++){
        if((it&4095)==0 && el()>=tl) break;
        double f=el()/tl; if(f>=1.0) break;
        double temp=T0*pow(Te/T0,f);
        int i=1+(rng()%(N-1));
        int segLen=2+(rng()%min(N-1,max(2,(int)(60*(1.0-f*0.7)))));
        int j=i+segLen-1; if(j>=N) j=N-1;
        int lo=i, hi=min(j+1,N);
        double oC=0;
        for(int t=lo;t<=hi;t++) oC+=Dist(tour[t-1],tour[t])*gm(t,tour[t-1]);
        reverse(tour.begin()+i,tour.begin()+j+1);
        double nC=0;
        for(int t=lo;t<=hi;t++) nC+=Dist(tour[t-1],tour[t])*gm(t,tour[t-1]);
        double d=nC-oC;
        if(d<0||(temp>1e-30&&d/temp<30&&exp(-d/temp)>(rng()%1000000)/1e6)){
            curCost+=d;
            if(curCost<bestCost){bestCost=curCost;best=tour;}
        } else reverse(tour.begin()+i,tour.begin()+j+1);
    }
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<best[i]<<"\n";
}
