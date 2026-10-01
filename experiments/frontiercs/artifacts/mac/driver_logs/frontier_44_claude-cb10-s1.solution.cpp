#include <bits/stdc++.h>
using namespace std;

static int N;
static double *cx, *cy;
static bool *isp;
static int *tour;
static int *pos; // pos[city] = index in tour

inline double dist2(int a, int b){
    double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
    return sqrt(dx*dx+dy*dy);
}

inline double gm(int t, int src){
    return (t%10==0 && !isp[src]) ? 1.1 : 1.0;
}

inline double ec(int t, int from, int to){
    return dist2(from,to) * gm(t, from);
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    cin>>N;
    cx=new double[N]; cy=new double[N];
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    isp=new bool[max(N,2)]();
    {
        vector<bool> sv(max(N,2),true);
        sv[0]=false; if(N>1) sv[1]=false;
        for(int i=2;i<N;i++) if(sv[i]){isp[i]=true; for(long long j=(long long)i*i;j<N;j+=i) sv[j]=false;}
    }
    
    tour=new int[N+1];
    pos=new int[N];
    for(int i=0;i<N;i++){tour[i]=i;pos[i]=i;}
    tour[N]=0;
    
    auto calcCost=[&]()->double{
        double s=0;
        for(int t=1;t<=N;t++) s+=ec(t,tour[t-1],tour[t]);
        return s;
    };
    
    double curCost=calcCost();
    vector<int> best(tour,tour+N+1); double bestCost=curCost;
    
    mt19937 rng(42);
    auto st=chrono::steady_clock::now();
    auto el=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-st).count();};
    
    double tl=1.85;
    double T0=bestCost/N*0.5, Te=bestCost/N*1e-7;
    
    long long it=0;
    while(true){
        if((it&4095)==0 && el()>=tl) break;
        double f=el()/tl; if(f>=1.0) break;
        double temp=T0*pow(Te/T0,f);
        it++;
        
        // 2-opt
        int i=1+(rng()%(N-1));
        int maxL=min(N-i, max(2, (int)(60*(1.0-f*0.7))));
        int len=2+(rng()%maxL);
        int j=min(i+len-1, N-1);
        
        int lo=i, hi=min(j+1,N);
        double oC=0; for(int t=lo;t<=hi;t++) oC+=ec(t,tour[t-1],tour[t]);
        reverse(tour+i, tour+j+1);
        double nC=0; for(int t=lo;t<=hi;t++) nC+=ec(t,tour[t-1],tour[t]);
        double d=nC-oC;
        if(d<0||(temp>1e-30&&d/temp<30&&exp(-d/temp)>(rng()%1000000)*1e-6)){
            curCost+=d;
            if(curCost<bestCost){bestCost=curCost;memcpy(best.data(),tour,(N+1)*sizeof(int));}
        } else reverse(tour+i, tour+j+1);
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<best[i]<<"\n";
    
    delete[] cx; delete[] cy; delete[] isp; delete[] tour; delete[] pos;
}
