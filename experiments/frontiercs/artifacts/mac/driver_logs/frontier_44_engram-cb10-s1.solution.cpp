#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double> X(N+1),Y(N+1);
    for(int i=1;i<=N;i++) cin>>X[i]>>Y[i];
    
    int mx=N+1;
    vector<bool> isp(mx,false);
    {vector<bool> s(mx,true);
    if(mx>0) s[0]=false;
    if(mx>1) s[1]=false;
    for(int i=2;(long long)i*i<mx;i++) if(s[i]) for(int j=i*i;j<mx;j+=i) s[j]=false;
    for(int i=0;i<mx;i++) isp[i]=s[i];}
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // tour[0..N] where tour[0]=tour[N]=1, cities 1-indexed
    // step k (1-indexed) is edge from tour[k-1] to tour[k]
    // multiplier for step k: if k%10==0 and tour[k-1] is not prime -> 1.1, else 1.0
    auto mult=[&](int step, int city)->double{
        return (step%10==0 && !isp[city])?1.1:1.0;
    };
    
    // Nearest neighbor
    vector<int> tour(N+1);
    {vector<bool> used(N+1,false);
    tour[0]=1; used[1]=true;
    for(int i=1;i<N;i++){
        int last=tour[i-1]; int best=-1; double bd=1e18;
        for(int c=1;c<=N;c++) if(!used[c]){
            double d=dist(last,c);
            if(d<bd){bd=d;best=c;}
        }
        tour[i]=best; used[best]=true;
    }
    tour[N]=1;}
    
    auto totalCost=[&]()->double{
        double c=0;
        for(int i=0;i<N;i++){
            int step=i+1;
            c+=mult(step,tour[i])*dist(tour[i],tour[i+1]);
        }
        return c;
    };
    
    double curCost=totalCost();
    vector<int> bestTour(tour);
    double bestCost=curCost;
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    mt19937 rng(12345);
    
    while(elapsed()<1.85){
        double frac=elapsed()/1.85;
        double T=curCost*0.01*pow(0.0001,frac);
        
        // 2-opt: reverse tour[i+1..j]
        int i=rng()%(N-1);
        int len=2+(rng()%min(N-1,60));
        int j=i+len;
        if(j>=N) continue;
        
        // Compute old cost for edges i..j
        double oldC=0,newC=0;
        for(int k=i;k<=j;k++) oldC+=mult(k+1,tour[k])*dist(tour[k],tour[k+1]);
        
        reverse(tour.begin()+i+1,tour.begin()+j+1);
        
        for(int k=i;k<=j;k++) newC+=mult(k+1,tour[k])*dist(tour[k],tour[k+1]);
        
        double delta=newC-oldC;
        if(delta<0||(T>0&&exp(-delta/T)>(rng()%10000)/10000.0)){
            curCost+=delta;
            if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
        } else {
            reverse(tour.begin()+i+1,tour.begin()+j+1);
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<bestTour[i]<<"\n";
}
