#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> cx(N), cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,2),false);
    {
        vector<bool> sv(max(N,2),true);
        sv[0]=false; if(N>1) sv[1]=false;
        for(int i=2;i<N;i++){
            if(sv[i]){
                isp[i]=true;
                for(long long j=(long long)i*i;j<N;j+=i) sv[j]=false;
            }
        }
    }
    
    auto distf=[&](int a,int b)->double{
        double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    auto startT=chrono::steady_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-startT).count();
    };
    
    auto gm=[&](int t, int city)->double{
        return (t%10==0 && !isp[city]) ? 1.1 : 1.0;
    };
    
    // Nearest neighbor construction
    vector<int> tour(N+1);
    {
        vector<bool> used(N,false);
        tour[0]=0; used[0]=true;
        
        // Build a KD-like spatial index using grid
        int gsz=max(1,(int)sqrt((double)N));
        double mnx=cx[0], mxx=cx[0], mny=cy[0], mxy=cy[0];
        for(int i=0;i<N;i++){
            mnx=min(mnx,cx[i]); mxx=max(mxx,cx[i]);
            mny=min(mny,cy[i]); mxy=max(mxy,cy[i]);
        }
        double gw=(mxx-mnx)/gsz+1e-9;
        double gh=(mxy-mny)/gsz+1e-9;
        if(gw<1e-12) gw=1;
        if(gh<1e-12) gh=1;
        
        unordered_map<long long,vector<int>> grid;
        auto gkey=[&](double x, double y)->long long{
            int gx=(int)((x-mnx)/gw);
            int gy=(int)((y-mny)/gh);
            return (long long)gx*1000001LL+gy;
        };
        for(int i=0;i<N;i++) grid[gkey(cx[i],cy[i])].push_back(i);
        
        for(int step=1;step<N;step++){
            int prev=tour[step-1];
            int pgx=(int)((cx[prev]-mnx)/gw);
            int pgy=(int)((cy[prev]-mny)/gh);
            double bd=1e30; int bc=-1;
            double mult=gm(step,prev);
            
            for(int r=0;r<=gsz+1;r++){
                for(int dx=-r;dx<=r;dx++){
                    for(int dy=-r;dy<=r;dy++){
                        if(abs(dx)!=r&&abs(dy)!=r) continue;
                        long long k=(long long)(pgx+dx)*1000001LL+(pgy+dy);
                        auto it2=grid.find(k);
                        if(it2==grid.end()) continue;
                        auto &v=it2->second;
                        for(int idx=(int)v.size()-1;idx>=0;idx--){
                            int c=v[idx];
                            if(used[c]){v[idx]=v.back();v.pop_back();continue;}
                            double d=distf(prev,c)*mult;
                            // Prefer primes at positions before multiples of 10
                            if((step+1)%10==0 && step+1<=N && isp[c]) d*=0.95;
                            if(d<bd){bd=d;bc=c;}
                        }
                    }
                }
                if(bc!=-1&&r>=1) break;
            }
            if(bc==-1){
                for(int i=0;i<N;i++) if(!used[i]){bc=i;break;}
            }
            tour[step]=bc; used[bc]=true;
        }
        tour[N]=0;
    }
    
    // Prime placement optimization
    {
        vector<int> penPos;
        for(int t=10;t<=N;t+=10) penPos.push_back(t-1);
        
        for(int pp : penPos){
            if(pp<=0||pp>=N) continue;
            if(isp[tour[pp]]) continue;
            double bestGain=-1e-9;
            int bestJ=-1;
            int lo=max(1,pp-300), hi=min(N-1,pp+300);
            for(int j=lo;j<=hi;j++){
                if(j==pp) continue;
                if(!isp[tour[j]]) continue;
                // Check j isn't also a penalty position
                bool jIsPen=false;
                if((j+1)%10==0 && j+1<=N) jIsPen=true;
                if(jIsPen) continue;
                
                int si=min(pp,j), sj=max(pp,j);
                int rlo=si, rhi=min(sj+1,N);
                double oldC=0,newC=0;
                for(int s=rlo;s<=rhi;s++) oldC+=distf(tour[s-1],tour[s])*gm(s,tour[s-1]);
                swap(tour[pp],tour[j]);
                for(int s=rlo;s<=rhi;s++) newC+=distf(tour[s-1],tour[s])*gm(s,tour[s-1]);
                double gain=oldC-newC;
                if(gain>bestGain){bestGain=gain;bestJ=j;}
                swap(tour[pp],tour[j]);
            }
            if(bestJ!=-1&&bestGain>-1e-9){
                swap(tour[pp],tour[bestJ]);
            }
        }
    }
    
    auto calcCost=[&](vector<int>&p)->double{
        double s=0;
        for(int t=1;t<=N;t++) s+=distf(p[t-1],p[t])*gm(t,p[t-1]);
        return s;
    };
    
    double curCost=calcCost(tour);
    double bestCost=curCost;
    vector<int> bestTour=tour;
    
    mt19937 rng(42);
    double timeLimit=1.88;
    double T0=curCost/N*0.5, Te=T0*1e-7;
    if(N<=500){T0=curCost/N*3.0;Te=T0*1e-8;}
    else if(N<=5000){T0=curCost/N*1.5;Te=T0*1e-7;}
    
    long long it=0;
    int maxSeg=N<=500?N-1:N<=2000?400:N<=10000?150:N<=50000?60:30;
    double cT=0;
    
    while(true){
        if((++it&2047)==0){cT=elapsed();if(cT>=timeLimit)break;}
        double f=cT/timeLimit;
        double temp=T0*pow(Te/T0,f);
        
        // 2-opt or swap
        int i=1+(rng()%(N-1));
        int sp=2+(rng()%maxSeg);
        int j=i+sp-1;
        if(j>=N) continue;
        int lo=i,hi=min(j+1,N);
        double oC=0,nC=0;
        for(int s=lo;s<=hi;s++) oC+=distf(tour[s-1],tour[s])*gm(s,tour[s-1]);
        reverse(tour.begin()+i,tour.begin()+j+1);
        for(int s=lo;s<=hi;s++) nC+=distf(tour[s-1],tour[s])*gm(s,tour[s-1]);
        double d=nC-oC;
        if(d<0||(temp>1e-30&&d<30*temp&&(rng()%65536)<65536.0*exp(-d/temp))){
            curCost+=d;
            if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
        } else {
            reverse(tour.begin()+i,tour.begin()+j+1);
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
