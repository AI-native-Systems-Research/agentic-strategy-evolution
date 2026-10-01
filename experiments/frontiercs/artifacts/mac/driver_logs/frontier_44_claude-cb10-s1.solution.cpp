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
     for(int i=2;i<N;i++){if(sv[i]){isp[i]=true;for(long long j=(long long)i*i;j<N;j+=i)sv[j]=false;}}}
    auto df=[&](int a,int b)->double{double dx=cx[a]-cx[b],dy=cy[a]-cy[b];return sqrt(dx*dx+dy*dy);};
    auto gm=[&](int t,int c)->double{return(t%10==0&&!isp[c])?1.1:1.0;};
    auto calcCost=[&](vector<int>&p)->double{double s=0;for(int t=1;t<=N;t++)s+=df(p[t-1],p[t])*gm(t,p[t-1]);return s;};
    // NN tour
    auto nnTour=[&]()->vector<int>{
        vector<int> xo(N);iota(xo.begin(),xo.end(),0);sort(xo.begin(),xo.end(),[&](int a,int b){return cx[a]<cx[b];});
        vector<int> xr(N);for(int i=0;i<N;i++)xr[xo[i]]=i;
        vector<int> t(N+1);vector<bool> u(N,false);t[0]=0;u[0]=true;
        for(int i=1;i<N;i++){int p=t[i-1];int b=-1;double bd=1e30;int lo=xr[p],hi=lo;
            for(int ck=0;ck<min(N,1500);){
                if(lo>0){lo--;int j=xo[lo];if(!u[j]){double d=df(p,j);if(d<bd){bd=d;b=j;}}ck++;if(cx[p]-cx[xo[lo]]>bd&&hi>=N-1)break;}
                if(hi<N-1){hi++;int j=xo[hi];if(!u[j]){double d=df(p,j);if(d<bd){bd=d;b=j;}}ck++;if(cx[xo[hi]]-cx[p]>bd&&lo<=0)break;}
                if(lo<=0&&hi>=N-1)break;}
            if(b<0)for(int j=0;j<N;j++)if(!u[j]){b=j;break;}
            t[i]=b;u[b]=true;}t[N]=0;return t;};
    vector<int> tour=nnTour();
    {vector<int> t2(N+1);t2[0]=0;for(int i=1;i<N;i++)t2[i]=i;t2[N]=0;if(calcCost(t2)<calcCost(tour))tour=t2;}
    double curCost=calcCost(tour);vector<int> best=tour;double bestCost=curCost;
    mt19937 rng(42);auto st=chrono::steady_clock::now();
    auto el=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-st).count();};
    double tl=1.8,T0=curCost/N*0.4,Te=curCost/N*1e-7;
    int ms=min(N-1,max(60,N<=500?N-1:N<=5000?500:N<=20000?200:N<=50000?80:50));
    for(long long it=0;;it++){
        if((it&4095)==0&&el()>=tl)break;double f=el()/tl;if(f>=1.0)break;
        double temp=T0*pow(Te/T0,f);
        int i=1+(rng()%(N-1)),sp=2+(rng()%ms),j=i+sp-1;if(j>=N)continue;
        int lo=max(1,i-1),hi=min(N,j+1);
        double oC=0;for(int t=lo;t<=hi;t++)oC+=df(tour[t-1],tour[t])*gm(t,tour[t-1]);
        reverse(tour.begin()+i,tour.begin()+j+1);
        double nC=0;for(int t=lo;t<=hi;t++)nC+=df(tour[t-1],tour[t])*gm(t,tour[t-1]);
        double d=nC-oC;
        if(d<0||(temp>1e-30&&d<temp*30&&(rng()%65536)<65536.0*exp(-d/temp))){curCost+=d;if(curCost<bestCost){bestCost=curCost;best=tour;}}
        else reverse(tour.begin()+i,tour.begin()+j+1);
    }
    tour=best;curCost=bestCost;
    for(int pass=0;pass<10;pass++)for(int t=10;t<=N;t+=10){if(isp[tour[t-1]])continue;
        int bj=-1;double bd=0;for(int jj=max(1,t-1-80);jj<=min(N-1,t-1+80);jj++){if(jj==t-1||!isp[tour[jj]])continue;
        int mn=max(1,min(jj,t-1)-1),mx=min(N,max(jj,t-1)+2);double o2=0;for(int tt=mn;tt<=mx;tt++)o2+=df(tour[tt-1],tour[tt])*gm(tt,tour[tt-1]);
        swap(tour[t-1],tour[jj]);double n2=0;for(int tt=mn;tt<=mx;tt++)n2+=df(tour[tt-1],tour[tt])*gm(tt,tour[tt-1]);swap(tour[t-1],tour[jj]);
        double dd=n2-o2;if(dd<bd){bd=dd;bj=jj;}}if(bj>=0){swap(tour[t-1],tour[bj]);curCost+=bd;}}
    if(curCost<bestCost){bestCost=curCost;best=tour;}
    cout<<N+1<<"\n";for(int i=0;i<=N;i++)cout<<best[i]<<"\n";
}
