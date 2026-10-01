#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    
    vector<bool> is_prime(N+1,false);
    {
        vector<bool> sieve(N+1,true);
        if(N+1>0) sieve[0]=false;
        if(N+1>1) sieve[1]=false;
        for(int i=2;(long long)i*i<=N;i++)
            if(sieve[i]) for(int j=i*i;j<=N;j+=i) sieve[j]=false;
        for(int i=0;i<=N;i++) is_prime[i]=sieve[i];
    }
    
    auto d=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // Nearest neighbor from multiple starts
    auto buildNN=[&](int start)->vector<int>{
        vector<int> tour; tour.reserve(N+1);
        vector<bool> used(N,false);
        used[start]=true; tour.push_back(start);
        for(int s=1;s<N;s++){
            int last=tour.back(); int best=-1; double bd=1e18;
            for(int c=0;c<N;c++) if(!used[c]){double dd=d(last,c);if(dd<bd){bd=dd;best=c;}}
            tour.push_back(best); used[best]=true;
        }
        tour.push_back(start);
        return tour;
    };
    
    // step idx+1: from tour[idx] to tour[idx+1]. Penalty if (idx+1)%10==0 and tour[idx] not prime (1-indexed city = tour[idx]+1)
    auto mult=[&](vector<int>&tour,int idx)->double{
        int step=idx+1;
        int city1=tour[idx]+1; // 1-indexed
        return (step%10==0 && !is_prime[city1])?1.1:1.0;
    };
    auto ec=[&](vector<int>&tour,int idx)->double{
        return mult(tour,idx)*d(tour[idx],tour[idx+1]);
    };
    auto totalc=[&](vector<int>&tour)->double{
        double s=0; for(int i=0;i<N;i++) s+=ec(tour,i); return s;
    };
    
    vector<int> bestTour; double bestCost=1e18;
    int starts=min(N, N<=1000?10:1);
    for(int si=0;si<starts;si++){
        auto tour=buildNN(si);
        double c=totalc(tour);
        if(c<bestCost){bestCost=c;bestTour=tour;}
    }
    
    auto tour=bestTour; double tc=bestCost;
    auto st=chrono::steady_clock::now();
    mt19937 rng(42);
    double tl=1.9;
    double T0=tc/N*2, Tend=1e-8;
    
    for(long long it=0;;it++){
        if((it&0xFFF)==0){
            double t=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(t>=tl) break;
            double f=t/tl; T0=T0; // recompute T
        }
        double t=chrono::duration<double>(chrono::steady_clock::now()-st).count();
        if(t>=tl) break;
        double T=T0*pow(Tend/T0,t/tl);
        
        int i=rng()%(N-1), j=i+2+rng()%min(50,N-1-i);
        if(j>=N) j=N-1; if(j<=i+1) continue;
        double oldC=0; for(int k=i;k<=j;k++) oldC+=ec(tour,k);
        reverse(tour.begin()+i+1,tour.begin()+j+1);
        double newC=0; for(int k=i;k<=j;k++) newC+=ec(tour,k);
        double delta=newC-oldC;
        if(delta<0||(T>0&&exp(-delta/T)>((rng()&0x3FFF)/16384.0))){tc+=delta;}
        else reverse(tour.begin()+i+1,tour.begin()+j+1);
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]+1<<"\n";
}
