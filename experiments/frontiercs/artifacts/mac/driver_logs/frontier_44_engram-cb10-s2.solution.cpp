#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N;
    cin>>N;
    vector<double>X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    vector<bool>isp(N+2,false);
    {vector<bool>s(N+2,true);s[0]=s[1]=false;
    for(int i=2;i<=N;i++){if(s[i]){isp[i]=true;for(long long j=(long long)i*i;j<=N;j+=i)s[j]=false;}}}
    auto dist=[&](int a,int b)->double{double dx=X[a]-X[b],dy=Y[a]-Y[b];return sqrt(dx*dx+dy*dy);};
    auto pen=[&](int step,int c0)->double{int c1=c0+1;return(step%10==0&&!isp[c1])?1.1:1.0;};
    auto tourCost=[&](const vector<int>&tr)->double{double c=0;for(int t=1;t<=N;t++)c+=pen(t,tr[t-1])*dist(tr[t-1],tr[t]);return c;};
    auto buildNN=[&](int start)->vector<int>{vector<bool>used(N,false);vector<int>tour(N+1);tour[0]=start;used[start]=true;for(int i=1;i<N;i++){int cur=tour[i-1];int best=-1;double bd=1e18;for(int j=0;j<N;j++){if(used[j])continue;double c=dist(cur,j);if(c<bd){bd=c;best=j;}}tour[i]=best;used[best]=true;}tour[N]=start;return tour;};
    int tries=min(N,N<=500?N:N<=2000?20:5);
    vector<int>best_tour=buildNN(0);double best_cost=tourCost(best_tour);
    for(int s=0;s<tries;s++){auto t=buildNN(s);double c=tourCost(t);if(c<best_cost){best_cost=c;best_tour=t;}}
    vector<int>tour=best_tour;double cur=best_cost;
    auto stime=chrono::steady_clock::now();
    auto el=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-stime).count();};
    mt19937 rng(42);double T=cur*0.02,Tend=cur*1e-8,tlimit=1.85;
    while(el()<tlimit){int i=rng()%(N-1)+1,j=rng()%(N-1)+1;if(i==j)continue;if(i>j)swap(i,j);
    int lo=max(1,i),hi=min(N,j+1);double oldC=0;for(int t=lo;t<=hi;t++)oldC+=pen(t,tour[t-1])*dist(tour[t-1],tour[t]);
    reverse(tour.begin()+i,tour.begin()+j+1);double newC=0;for(int t=lo;t<=hi;t++)newC+=pen(t,tour[t-1])*dist(tour[t-1],tour[t]);
    double delta=newC-oldC;double frac=el()/tlimit;double Tcur=T*pow(Tend/T,frac);
    if(delta<0||((double)(rng()%1000000)/1000000.0<exp(-delta/Tcur))){cur+=delta;if(cur<best_cost){best_cost=cur;best_tour=tour;}}
    else{reverse(tour.begin()+i,tour.begin()+j+1);}}
    for(int i=0;i<=N;i++) cout<<best_tour[i]+1<<"\n";
}
