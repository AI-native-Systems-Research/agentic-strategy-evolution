#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double> cx(N),cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,3),false);
    {vector<bool> sv(max(N,3),true);sv[0]=sv[1]=false;
    for(int i=2;i<(int)sv.size();i++)if(sv[i]){isp[i]=true;for(long long j=(long long)i*i;j<(int)sv.size();j+=i)sv[j]=false;}}
    
    auto Dist=[&](int a,int b)->double{double dx=cx[a]-cx[b],dy=cy[a]-cy[b];return sqrt(dx*dx+dy*dy);};
    
    // pos[k] = position in tour (1..N-1) of city k (for k!=0)
    vector<int> tour(N+1);
    // Start with input order
    for(int i=0;i<N;i++) tour[i]=i;
    tour[N]=0;
    
    auto costOf=[&](const vector<int>&t)->double{
        double s=0;
        for(int i=1;i<=N;i++){
            double m=(i%10==0&&!isp[t[i-1]])?1.1:1.0;
            s+=m*Dist(t[i-1],t[i]);
        }
        return s;
    };
    
    double curCost=costOf(tour);
    vector<int> bestTour=tour;
    double bestCost=curCost;
    
    if(N<=2){cout<<N+1<<"\n";for(int i=0;i<=N;i++)cout<<bestTour[i]<<"\n";return 0;}
    
    mt19937 rng(42);
    auto st=chrono::steady_clock::now();
    double tl=1.85;
    double T0=curCost/N*0.5,Tf=curCost/N*1e-8;
    long long iter=0;double frac=0;
    int maxSeg=min(N-1,N<=1000?N-1:N<=5000?400:N<=20000?150:80);
    
    while(true){
        iter++;
        if((iter&0xFFF)==0){
            double el=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(el>=tl)break;
            frac=el/tl;
        }
        double temp=T0*pow(Tf/T0,frac);
        
        int i=1+rng()%(N-1);
        int len=2+rng()%min(maxSeg,N-1);
        int j=i+len-1;
        if(j>=N)continue;
        
        int lo=i,hi=min(j+1,N);
        double oC=0,nC=0;
        for(int t=lo;t<=hi;t++){
            double m=(t%10==0&&!isp[tour[t-1]])?1.1:1.0;
            oC+=m*Dist(tour[t-1],tour[t]);
        }
        reverse(tour.data()+i,tour.data()+j+1);
        for(int t=lo;t<=hi;t++){
            double m=(t%10==0&&!isp[tour[t-1]])?1.1:1.0;
            nC+=m*Dist(tour[t-1],tour[t]);
        }
        double d=nC-oC;
        if(d<0||(temp>1e-30&&d/temp<20&&exp(-d/temp)>(rng()%10000)/10000.0)){
            curCost+=d;
            if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
        }else{
            reverse(tour.data()+i,tour.data()+j+1);
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++)cout<<bestTour[i]<<"\n";
}
