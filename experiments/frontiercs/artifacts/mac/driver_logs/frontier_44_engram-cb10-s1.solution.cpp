#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double> X(N+1),Y(N+1);
    for(int i=1;i<=N;i++) cin>>X[i]>>Y[i];
    int mx=N+2;
    vector<bool> isp(mx,true); isp[0]=isp[1]=false;
    for(int i=2;(long long)i*i<mx;i++) if(isp[i]) for(int j=i*i;j<mx;j+=i) isp[j]=false;
    vector<vector<double>> dist(N+1,vector<double>(N+1,0));
    for(int i=1;i<=N;i++) for(int j=i+1;j<=N;j++){
        double dx=X[i]-X[j],dy=Y[i]-Y[j];
        dist[i][j]=dist[j][i]=sqrt(dx*dx+dy*dy);
    }
    auto ml=[&](int step,int city)->double{ return (step%10==0&&!isp[city])?1.1:1.0; };
    // edge cost from step s-1 to step s
    auto ecost=[&](int s, int cfrom, int cto)->double{ return ml(s,cto)*dist[cfrom][cto]; };
    auto tourCost=[&](vector<int>&t)->double{
        double c=0; for(int s=1;s<=N;s++) c+=ecost(s,t[s-1],t[s]); return c;
    };
    auto buildNN=[&](int st)->vector<int>{
        vector<int> t(N+1); vector<bool> used(N+1,false);
        t[0]=st; used[st]=true;
        for(int s=1;s<N;s++){
            int last=t[s-1],best=-1;double bd=1e18;
            for(int i=1;i<=N;i++) if(!used[i]){double v=ecost(s,last,i);if(v<bd){bd=v;best=i;}}
            t[s]=best;used[best]=true;
        }
        t[N]=st; return t;
    };
    vector<int> best; double bestC=1e18;
    int tries=min(N,max(1,(N<=200)?N:5));
    for(int s=1;s<=tries;s++){auto t=buildNN(s);double c=tourCost(t);if(c<bestC){bestC=c;best=t;}}
    auto startT=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-startT).count();};
    mt19937 rng(42);
    vector<int> cur=best; double curC=bestC;
    // Or-opt and 2-opt style moves with incremental eval
    // Use 2-opt reversal on segments
    while(elapsed()<1.85){
        double frac=elapsed()/1.85;
        double T=bestC*0.02*pow(1e-5,frac);
        int a=rng()%(N-1)+1, b=rng()%(N-1)+1;
        if(a>b) swap(a,b);
        if(a==b) continue;
        // reverse segment [a..b]
        reverse(cur.begin()+a, cur.begin()+b+1);
        double nc=tourCost(cur);
        double delta=nc-curC;
        if(delta<0||(T>1e-15&&((double)(rng()&0xFFFF)/0xFFFF)<exp(-delta/T))){
            curC=nc; if(curC<bestC){bestC=curC;best=cur;}
        } else {
            reverse(cur.begin()+a, cur.begin()+b+1);
        }
    }
    for(int i=0;i<=N;i++) cout<<best[i]<<"\n";
}
