#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N; cin>>N;
    vector<double>X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    
    vector<bool>isp(N,false);
    if(N>=2){
        for(int i=2;i<N;i++) isp[i]=true;
        for(int i=2;(long long)i*i<N;i++)
            if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;
    }
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // mult(t, c): step t uses city c as the "from" city
    // bonus when t%10==0 and c is composite (not prime)
    auto mult=[&](int t,int c)->double{
        return (t%10==0 && !isp[c])?1.1:1.0;
    };
    
    auto fullCost=[&](const vector<int>&tr)->double{
        double c=0;
        for(int t=1;t<=N;t++)
            c+=mult(t,tr[t-1])*dist(tr[t-1],tr[t]);
        return c;
    };
    
    // pos[i] = position index in tour (0..N), tour[pos[i]]=i
    // tour: tour[0]=start, tour[N]=tour[0]
    
    // NN heuristic
    auto buildNN=[&](int start)->vector<int>{
        vector<int>tr(N+1);
        vector<bool>used(N,false);
        tr[0]=start; used[start]=true;
        for(int i=1;i<N;i++){
            int cur=tr[i-1], best=-1; double bd=1e18;
            for(int j=0;j<N;j++) if(!used[j]){
                double d=dist(cur,j);
                if(d<bd){bd=d;best=j;}
            }
            tr[i]=best; used[best]=true;
        }
        tr[N]=start;
        return tr;
    };
    
    vector<int>bestTour;
    double bestCost=1e18;
    
    auto start_time=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start_time).count();};
    
    int tries=min(N,(N<=1000)?10:3);
    mt19937 rng(42);
    for(int t=0;t<tries&&elapsed()<0.5;t++){
        int s=(t==0)?0:(int)(rng()%N);
        auto tr=buildNN(s);
        double c=fullCost(tr);
        if(c<bestCost){bestCost=c;bestTour=tr;}
    }
    
    // SA with segment reverse
    vector<int>&tour=bestTour;
    double curCost=bestCost;
    double T0=curCost/(N>1?N:1)*0.5, Tf=1e-8;
    int iters=0;
    while(elapsed()<1.9){
        double frac=min(1.0,elapsed()/1.9);
        double T=T0*pow(Tf/T0,frac);
        int i=1+rng()%(N-1);
        int len=2+rng()%min(50,N-1);
        int j=i+len-1;
        if(j>=N) {iters++;continue;}
        int lo=i,hi=min(j+1,N);
        double oldC=0;
        for(int t=lo;t<=hi;t++) oldC+=mult(t,tour[t-1])*dist(tour[t-1],tour[t]);
        reverse(tour.begin()+i,tour.begin()+j+1);
        double newC=0;
        for(int t=lo;t<=hi;t++) newC+=mult(t,tour[t-1])*dist(tour[t-1],tour[t]);
        double delta=newC-oldC;
        if(delta<0||((double)(rng()%1000000)/1000000.0)<exp(-delta/T)){
            curCost+=delta;
        } else {
            reverse(tour.begin()+i,tour.begin()+j+1);
        }
        iters++;
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
}
