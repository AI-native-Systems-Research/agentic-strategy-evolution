#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> cx(N), cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(N,false);
    {
        vector<bool> sv(max(N,2),true);
        sv[0]=false; sv[1]=false;
        for(int i=2;i<N;i++){
            if(sv[i]){
                isp[i]=true;
                for(long long j=(long long)i*i;j<N;j+=i) sv[j]=false;
            }
        }
    }
    
    auto dist=[&](int a,int b)->double{
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
    
    // Grid-based nearest neighbor
    vector<int> tour(N+1);
    {
        // Build grid
        struct P2{double x,y;int id;};
        int gsz=max(1,(int)sqrt((double)N/4.0));
        double mnx=*min_element(cx.begin(),cx.end());
        double mxx=*max_element(cx.begin(),cx.end());
        double mny=*min_element(cy.begin(),cy.end());
        double mxy=*max_element(cy.begin(),cy.end());
        double gw=(mxx-mnx)/gsz+1e-9;
        double gh=(mxy-mny)/gsz+1e-9;
        if(gw<1e-12) gw=1;
        if(gh<1e-12) gh=1;
        
        unordered_map<long long,vector<int>> grid;
        auto gkey=[&](int i)->long long{
            int gx=(int)((cx[i]-mnx)/gw);
            int gy=(int)((cy[i]-mny)/gh);
            return (long long)gx*1000000LL+gy;
        };
        for(int i=0;i<N;i++) grid[gkey(i)].push_back(i);
        
        vector<bool> used(N,false);
        tour[0]=0; used[0]=true;
        for(int step=1;step<N;step++){
            int prev=tour[step-1];
            int pgx=(int)((cx[prev]-mnx)/gw);
            int pgy=(int)((cy[prev]-mny)/gh);
            double bd=1e30; int bc=-1;
            for(int r=0;r<=gsz+1&&bc==-1||r<=2;r++){
                for(int dx=-r;dx<=r;dx++){
                    for(int dy=-r;dy<=r;dy++){
                        if(abs(dx)!=r&&abs(dy)!=r) continue;
                        long long k=(long long)(pgx+dx)*1000000LL+(pgy+dy);
                        auto it2=grid.find(k);
                        if(it2==grid.end()) continue;
                        auto &v=it2->second;
                        for(int idx=(int)v.size()-1;idx>=0;idx--){
                            int c=v[idx];
                            if(used[c]) {v[idx]=v.back();v.pop_back();continue;}
                            double d=dist(prev,c);
                            if(d<bd){bd=d;bc=c;}
                        }
                    }
                }
                if(bc!=-1&&r>=1) break;
            }
            tour[step]=bc; used[bc]=true;
        }
        tour[N]=0;
    }
    
    auto calcCost=[&](vector<int>&p)->double{
        double s=0;
        for(int t=1;t<=N;t++) s+=dist(p[t-1],p[t])*gm(t,p[t-1]);
        return s;
    };
    
    double curCost=calcCost(tour);
    double bestCost=curCost;
    vector<int> bestTour=tour;
    
    mt19937 rng(42);
    double timeLimit=1.88;
    double T0=curCost/N*0.5;
    double Te=T0*1e-7;
    long long it=0;
    double cT=0;
    
    while(true){
        if((++it&2047)==0){cT=elapsed();if(cT>=timeLimit)break;}
        double f=cT/timeLimit;
        double temp=T0*pow(Te/T0,f);
        
        int op=rng()%3;
        if(op<=1){
            // 2-opt
            int i=1+(rng()%(N-1));
            int mxS=min(N<=1000?N-1:N<=10000?300:N<=50000?100:50,N-1);
            int sp=2+(rng()%mxS);
            int j=i+sp-1;
            if(j>=N) continue;
            int lo=i,hi=min(j+1,N);
            double oC=0,nC=0;
            for(int s=lo;s<=hi;s++) oC+=dist(tour[s-1],tour[s])*gm(s,tour[s-1]);
            reverse(tour.begin()+i,tour.begin()+j+1);
            for(int s=lo;s<=hi;s++) nC+=dist(tour[s-1],tour[s])*gm(s,tour[s-1]);
            double d=nC-oC;
            if(d<0||(temp>1e-30&&d/temp<30.0&&(rng()%65536)<65536.0*exp(-d/temp))){
                curCost+=d;
                if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
            } else {
                reverse(tour.begin()+i,tour.begin()+j+1);
            }
        } else {
            // Or-opt: relocate single city
            int i=1+(rng()%(N-1));
            int j=1+(rng()%(N-1));
            if(i==j) continue;
            // Remove city at position i, insert before position j
            int city=tour[i];
            double oC=dist(tour[i-1],tour[i])*gm(i,tour[i-1])+dist(tour[i],tour[i+1])*gm(i+1,tour[i]);
            double nCrem=dist(tour[i-1],tour[i+1]);
            // This is complex with step renumbering; use full swap instead
            // Simple swap of two positions
            int ci=tour[i], cj=tour[j];
            int lo=min(i,j)-1; if(lo<0)lo=0;
            int hi=max(i,j)+1; if(hi>N)hi=N;
            double oldC=0;
            for(int s=max(1,lo+1);s<=hi;s++) oldC+=dist(tour[s-1],tour[s])*gm(s,tour[s-1]);
            swap(tour[i],tour[j]);
            double newC=0;
            for(int s=max(1,lo+1);s<=hi;s++) newC+=dist(tour[s-1],tour[s])*gm(s,tour[s-1]);
            double d=newC-oldC;
            if(d<0||(temp>1e-30&&d/temp<30.0&&(rng()%65536)<65536.0*exp(-d/temp))){
                curCost+=d;
                if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
            } else {
                swap(tour[i],tour[j]);
            }
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
