#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin>>N;
    vector<double> X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    
    vector<bool> isp(max(N+1,2),false);
    {
        vector<bool> sieve(max(N+1,2),true);
        sieve[0]=sieve[1]=false;
        for(int i=2;(long long)i*i<=N;i++)
            if(sieve[i]) for(int j=i*i;j<=N;j+=i) sieve[j]=false;
        for(int i=0;i<=N;i++) isp[i]=sieve[i];
    }
    
    // 1-indexed primes check: city labels are 1..N, city 0 in 0-indexed = city 1 in 1-indexed
    // The problem likely uses 1-indexed cities
    // isp1[c] = is (1-indexed city c) prime?
    // We'll work 0-indexed internally, output 1-indexed
    // For multiplier: step s (1-indexed), the "from" city in 1-indexed
    // If step%10==0 and from_city(1-indexed) is NOT prime => multiply by 1.1
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // multiplier for step s, from city c (0-indexed internally, but 1-indexed for prime check)
    auto mult=[&](int step, int c)->double{
        int c1=c+1; // 1-indexed
        if(step%10==0 && !isp[c1]) return 1.1;
        return 1.0;
    };
    
    // tour: perm[0..N-1] where perm[0]=0 (city 0 = start = city 1 in 1-indexed)
    // route: perm[0], perm[1], ..., perm[N-1], perm[0]
    // step i goes from perm[i-1] to perm[i] for i=1..N (perm[N]=perm[0])
    
    auto totalCost=[&](vector<int>&perm)->double{
        double s=0;
        for(int i=0;i<N;i++){
            int step=i+1;
            int from=perm[i], to=perm[(i+1)%N];
            s+=mult(step,from)*dist(from,to);
        }
        return s;
    };
    
    // Nearest neighbor from city 0
    vector<int> perm;
    perm.reserve(N);
    perm.push_back(0);
    vector<bool> used(N,false);
    used[0]=true;
    for(int i=1;i<N;i++){
        int last=perm.back(); double bd=1e18; int bn=-1;
        for(int j=0;j<N;j++) if(!used[j]){
            double d=dist(last,j);
            if(d<bd){bd=d;bn=j;}
        }
        perm.push_back(bn);
        used[bn]=true;
    }
    
    double curCost=totalCost(perm);
    vector<int> bestPerm=perm;
    double bestCost=curCost;
    
    mt19937 rng(42);
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    double tLim=1.85;
    double T0=curCost*0.02, Tf=curCost*1e-7;
    
    while(elapsed()<tLim){
        double frac=elapsed()/tLim;
        double temp=T0*pow(Tf/T0,frac);
        // 2-opt: pick i,j in [1,N-1], reverse perm[i..j]
        int i=1+rng()%(N-1), j=1+rng()%(N-1);
        if(i>j) swap(i,j);
        if(i==j) continue;
        
        reverse(perm.begin()+i,perm.begin()+j+1);
        double nc=totalCost(perm);
        double delta=nc-curCost;
        if(delta<0 || (temp>0 && exp(-delta/temp)>(rng()%10000)/10000.0)){
            curCost=nc;
            if(curCost<bestCost){bestCost=curCost;bestPerm=perm;}
        } else {
            reverse(perm.begin()+i,perm.begin()+j+1);
        }
    }
    
    perm=bestPerm;
    // Output 1-indexed
    cout<<N+1<<"\n";
    for(int i=0;i<N;i++) cout<<perm[i]+1<<"\n";
    cout<<perm[0]+1<<"\n";
}
