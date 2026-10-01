#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin>>N;
    vector<double> cx(N),cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> is_prime(N,false);
    {
        vector<bool> sieve(N,true);
        if(N>0) sieve[0]=false;
        if(N>1) sieve[1]=false;
        for(int i=2;i<N;i++){
            if(sieve[i]){is_prime[i]=true;for(long long j=(long long)i*i;j<N;j+=i)sieve[j]=false;}
        }
    }
    
    auto ddist=[&](int a,int b)->double{
        double dx=cx[a]-cx[b],dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    auto mult=[&](int t,int c)->double{
        return (t%10==0 && !is_prime[c])?1.1:1.0;
    };
    
    auto startT=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-startT).count();};
    
    // Build spatial grid for fast NN
    double minx=*min_element(cx.begin(),cx.end());
    double maxx=*max_element(cx.begin(),cx.end());
    double miny=*min_element(cy.begin(),cy.end());
    double maxy=*max_element(cy.begin(),cy.end());
    
    int GRID=max(1,(int)sqrt((double)N/4.0));
    double gw=(maxx-minx)/GRID+1e-9;
    double gh=(maxy-miny)/GRID+1e-9;
    
    vector<vector<int>> grid(GRID*GRID);
    auto getCell=[&](double x,double y)->pair<int,int>{
        int gx=min(GRID-1,max(0,(int)((x-minx)/gw)));
        int gy=min(GRID-1,max(0,(int)((y-miny)/gh)));
        return {gx,gy};
    };
    for(int i=0;i<N;i++){
        auto [gx,gy]=getCell(cx[i],cy[i]);
        grid[gx*GRID+gy].push_back(i);
    }
    
    // NN with grid
    vector<int> tour;
    {
        vector<bool> used(N,false);
        tour.push_back(0); used[0]=true;
        for(int step=1;step<N;step++){
            int prev=tour.back();
            double px=cx[prev],py=cy[prev];
            auto [pgx,pgy]=getCell(px,py);
            double bestD=1e18; int bestC=-1;
            for(int rad=0;rad<=2*GRID;rad++){
                // If we found something and the grid cell distance is larger, break
                if(bestC>=0){
                    double cellDist=max(0.0,(double)(rad-1))*min(gw,gh);
                    if(cellDist>bestD) break;
                }
                for(int dx=-rad;dx<=rad;dx++){
                    for(int dy=-rad;dy<=rad;dy++){
                        if(abs(dx)!=rad && abs(dy)!=rad) continue;
                        int nx=pgx+dx, ny=pgy+dy;
                        if(nx<0||nx>=GRID||ny<0||ny>=GRID) continue;
                        for(int c:grid[nx*GRID+ny]){
                            if(!used[c]){
                                double d=ddist(prev,c);
                                if(d<bestD){bestD=d;bestC=c;}
                            }
                        }
                    }
                }
                if(bestC>=0 && rad>=1) {
                    double cellDist=max(0.0,(double)(rad))*min(gw,gh)*0.5;
                    if(cellDist>bestD*1.5) break;
                }
            }
            tour.push_back(bestC); used[bestC]=true;
        }
        tour.push_back(0);
    }
    
    // Remove used grid entries - rebuild for later if needed
    
    auto calcCost=[&](vector<int>&p)->double{
        double s=0;for(int t=1;t<=N;t++) s+=ddist(p[t-1],p[t])*mult(t,p[t-1]);return s;
    };
    
    double curCost=calcCost(tour);
    double bestCost=curCost;
    vector<int> bestTour=tour;
    mt19937 rng(42);
    
    // Precompute step costs
    vector<double> sc(N+1);
    for(int t=1;t<=N;t++) sc[t]=ddist(tour[t-1],tour[t])*mult(t,tour[t-1]);
    
    double T0=curCost/N*0.5;
    double Tend=T0*1e-7;
    double timeLimit=1.85;
    
    // Position lookup: pos[city] = index in tour (1..N-1 for cities, 0 and N for city 0)
    
    int iter=0;
    while(true){
        double t=elapsed();
        if(t>=timeLimit) break;
        iter++;
        double frac=t/timeLimit;
        double temp=T0*exp(log(Tend/T0)*frac);
        
        int moveType=rng()%100;
        
        if(moveType<70){
            // 2-opt: reverse segment [i..j]
            int i=1+(rng()%(N-1));
            int maxW=max(2,min(N-2,(int)(5+200*(1.0-frac))));
            int span=2+(rng()%maxW);
            int j=i+span;
            if(j>=N) j=N-1;
            if(j<=i) continue;
            
            int lo=i,hi=min(j+1,N);
            double oldC=0;for(int s=lo;s<=hi;s++) oldC+=sc[s];
            reverse(tour.begin()+i,tour.begin()+j+1);
            double newC=0;for(int s=lo;s<=hi;s++) newC+=ddist(tour[s-1],tour[s])*mult(s,tour[s-1]);
            double delta=newC-oldC;
            if(delta<0||(temp>1e-30&&exp(-delta/temp)>((rng()&0xFFFF)/65536.0))){
                for(int s=lo;s<=hi;s++) sc[s]=ddist(tour[s-1],tour[s])*mult(s,tour[s-1]);
                curCost+=delta;
                if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
            }else{
                reverse(tour.begin()+i,tour.begin()+j+1);
            }
        } else {
            // Or-opt: move a single city to another position
            int i=1+(rng()%(N-1));
            int j=1+(rng()%(N-1));
            if(i==j) continue;
            
            int lo=min(i,j), hi=max(i,j);
            double oldC=0;for(int s=lo;s<=min(hi+1,N);s++) oldC+=sc[s];
            
            int city=tour[i];
            tour.erase(tour.begin()+i);
            int jj=j; if(j>i) jj--;
            tour.insert(tour.begin()+jj,city);
            
            double newC=0;for(int s=lo;s<=min(hi+1,N);s++) newC+=ddist(tour[s-1],tour[s])*mult(s,tour[s-1]);
            double delta=newC-oldC;
            if(delta<0||(temp>1e-30&&exp(-delta/temp)>((rng()&0xFFFF)/65536.0))){
                for(int s=lo;s<=min(hi+1,N);s++) sc[s]=ddist(tour[s-1],tour[s])*mult(s,tour[s-1]);
                curCost+=delta;
                if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
            }else{
                // undo
                tour.erase(tour.begin()+jj);
                tour.insert(tour.begin()+i,city);
            }
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
