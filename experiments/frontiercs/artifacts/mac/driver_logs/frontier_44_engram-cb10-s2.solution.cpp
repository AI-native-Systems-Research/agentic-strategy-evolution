#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double>X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    vector<bool>isp(N+1,false);
    for(int i=2;i<=N;i++) isp[i]=true;
    for(int i=2;(long long)i*i<=N;i++)
        if(isp[i]) for(int j=i*i;j<=N;j+=i) isp[j]=false;
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    // tour[0..N], tour[0]=tour[N]=0, step t: tour[t-1]->tour[t], mult depends on t and tour[t-1]
    // city indices are 0-based internally, output 1-based
    auto getmult=[&](int t,int c)->double{
        // c is 0-based city index, but prime check on 1-based
        int c1=c+1; // 1-based
        return (t%10==0 && !isp[c1])?1.1:1.0;
    };
    auto edgeCost=[&](int t,int from,int to)->double{
        return getmult(t,from)*dist(from,to);
    };
    auto fullCost=[&](const vector<int>&tr)->double{
        double c=0;
        for(int t=1;t<=N;t++) c+=edgeCost(t,tr[t-1],tr[t]);
        return c;
    };
    auto startTime=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();};
    // Nearest neighbor
    vector<bool>used(N,false);
    vector<int>tour(N+1);
    tour[0]=0; used[0]=true;
    for(int i=1;i<N;i++){
        int cur=tour[i-1]; int best=-1; double bd=1e18;
        for(int j=0;j<N;j++){
            if(used[j]) continue;
            double c=edgeCost(i,cur,j);
            if(c<bd){bd=c;best=j;}
        }
        tour[i]=best; used[best]=true;
    }
    tour[N]=0;
    double bestCost=fullCost(tour);
    vector<int>bestTour=tour;
    mt19937 rng(42);
    double T=bestCost*0.02;
    double Tmin=bestCost*1e-7;
    double curCost=bestCost;
    int iter=0;
    while(elapsed()<2.5){
        double alpha=1.0-elapsed()/2.5;
        double temp=Tmin+(T-Tmin)*alpha;
        // Or-opt: relocate city at position i to after position j
        int i=1+rng()%(N-1);
        int j=rng()%N;
        if(j==i||j==i-1) {iter++;continue;}
        // Remove city tour[i], reinsert after position j (in new indexing)
        vector<int>ntour=tour;
        int city=ntour[i];
        ntour.erase(ntour.begin()+i);
        int jj=j; if(j>i) jj--;
        if(jj<0||jj>=N-1){iter++;continue;}
        ntour.insert(ntour.begin()+jj+1,city);
        double nc=fullCost(ntour);
        double delta=nc-curCost;
        if(delta<0||((double)rng()/rng.max())<exp(-delta/temp)){
            tour=ntour; curCost=nc;
            if(curCost<bestCost){bestCost=curCost;bestTour=tour;}
        }
        iter++;
    }
    for(int i=0;i<=N;i++) cout<<bestTour[i]+1<<"\n";
}
