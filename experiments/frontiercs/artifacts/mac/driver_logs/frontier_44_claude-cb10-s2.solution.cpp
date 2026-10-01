#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double> cx(N), cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,3),false);
    {
        vector<bool> sv(max(N,3),true); sv[0]=sv[1]=false;
        for(int i=2;i<(int)sv.size();i++)
            if(sv[i]){isp[i]=true;for(long long j=(long long)i*i;j<(int)sv.size();j+=i)sv[j]=false;}
    }
    
    auto ddist=[&](int a,int b)->double{
        double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // pos2tour: tour[0..N], tour[0]=tour[N]=0
    vector<int> tour(N+1);
    
    auto mult=[&](int step, int city)->double{
        return (step%10==0 && !isp[city]) ? 1.1 : 1.0;
    };
    
    auto getCost=[&](const vector<int>& t)->double{
        double s=0;
        for(int i=1;i<=N;i++)
            s += mult(i, t[i-1]) * ddist(t[i-1], t[i]);
        return s;
    };
    
    // Start with input order
    for(int i=0;i<N;i++) tour[i]=i; tour[N]=0;
    double cur=getCost(tour);
    
    vector<int> best=tour; double bc=cur;
    mt19937 rng(42);
    auto st=chrono::steady_clock::now();
    double timeLimit=1.85;
    
    auto edgeCost=[&](int p)->double{return mult(p,tour[p-1])*ddist(tour[p-1],tour[p]);};
    
    long long it=0;
    while(true){
        it++;
        if((it&0x3FF)==0){
            double e=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(e>=timeLimit) break;
        }
        double e=chrono::duration<double>(chrono::steady_clock::now()-st).count();
        double fr=e/timeLimit;
        double T=cur/N*0.15*(1.0-fr);
        if(fr>=1.0) break;
        
        // Random swap of two positions in [1, N-1]
        int i=1+(rng()%(N-1));
        int j=1+(rng()%(N-1));
        if(i==j) continue;
        
        // Compute affected edges
        int lo=min(i,j), hi=max(i,j);
        double oC=0, nC=0;
        // Affected positions: i-1->i, i->i+1, j-1->j, j->j+1 (if distinct)
        vector<int> aff;
        for(int k:{i,j}){
            if(k>=1&&k<=N) aff.push_back(k);
            if(k+1>=1&&k+1<=N) aff.push_back(k+1);
        }
        sort(aff.begin(),aff.end());
        aff.erase(unique(aff.begin(),aff.end()),aff.end());
        
        for(int p:aff) oC+=edgeCost(p);
        swap(tour[i],tour[j]);
        for(int p:aff) nC+=edgeCost(p);
        
        double d2=nC-oC;
        if(d2<0||(T>1e-30&&d2/T<15&&exp(-d2/T)>(rng()%1000000)*1e-6)){
            cur+=d2;
            if(cur<bc){bc=cur;best=tour;}
        } else {
            swap(tour[i],tour[j]);
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<best[i]<<"\n";
}
