#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double> X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    int mx=N+2;
    vector<bool> isp(mx,false);
    {vector<bool> s(mx,true);s[0]=s[1]=false;
    for(int i=2;(long long)i*i<mx;i++)if(s[i])for(int j=i*i;j<mx;j+=i)s[j]=false;
    for(int i=0;i<mx;i++)isp[i]=s[i];}
    vector<vector<float>>D(N,vector<float>(N));
    for(int i=0;i<N;i++)for(int j=i+1;j<N;j++){
        float dx=X[i]-X[j],dy=Y[i]-Y[j];
        D[i][j]=D[j][i]=sqrtf(dx*dx+dy*dy);}
    auto M=[&](int step1,int city)->double{return(step1%10==0&&!isp[city])?1.1:1.0;};
    auto edgeCost=[&](int step1,int c1,int c2)->double{return M(step1,c1)*D[c1][c2];};
    auto tourCost=[&](vector<int>&t)->double{
        double c=0;for(int i=0;i<N;i++)c+=edgeCost(i+1,t[i],t[(i+1)%N]);return c;};
    vector<int>tour(N);
    {vector<bool>used(N,false);tour[0]=0;used[0]=true;
    for(int i=1;i<N;i++){int b=-1;float bd=1e18f;
    for(int c=0;c<N;c++)if(!used[c]&&D[tour[i-1]][c]<bd){bd=D[tour[i-1]][c];b=c;}
    tour[i]=b;used[b]=true;}}
    double cost=tourCost(tour);
    vector<int>best=tour;double bestC=cost;
    for(int s=0;s<min(N,50);s++){
        vector<int>t(N);vector<bool>u(N,false);t[0]=s;u[s]=true;
        for(int i=1;i<N;i++){int b=-1;float bd=1e18f;
        for(int c=0;c<N;c++)if(!u[c]&&D[t[i-1]][c]<bd){bd=D[t[i-1]][c];b=c;}
        t[i]=b;u[b]=true;}
        double c=tourCost(t);if(c<bestC){bestC=c;best=t;}}
    tour=best;cost=bestC;
    auto T0=chrono::steady_clock::now();
    auto el=[&](){return chrono::duration<double>(chrono::steady_clock::now()-T0).count();};
    mt19937 rng(42);
    double tl=1.8;
    while(el()<tl){
        double f=el()/tl,temp=cost/N*(0.5*(1-f)+1e-6);
        for(int r=0;r<500&&el()<tl;r++){
            int i=rng()%N,j=rng()%N;if(i==j)continue;
            if(i>j)swap(i,j);
            int pi=(i-1+N)%N,ni=(i+1)%N,pj=(j-1+N)%N,nj=(j+1)%N;
            double oldE=edgeCost(pi+1,tour[pi],tour[i])+edgeCost(i+1,tour[i],tour[ni]);
            if(ni!=j)oldE+=edgeCost(pj+1,tour[pj],tour[j])+edgeCost(j+1,tour[j],tour[nj]);
            else oldE+=edgeCost(j+1,tour[j],tour[nj]);
            swap(tour[i],tour[j]);
            double newE=edgeCost(pi+1,tour[pi],tour[i])+edgeCost(i+1,tour[i],tour[ni]);
            if(ni!=j)newE+=edgeCost(pj+1,tour[pj],tour[j])+edgeCost(j+1,tour[j],tour[nj]);
            else newE+=edgeCost(j+1,tour[j],tour[nj]);
            double d=newE-oldE;
            if(d<0||(temp>1e-15&&exp(-d/temp)>(rng()%10000)/10000.0)){
                cost+=d;if(cost<bestC){bestC=cost;best=tour;}
            }else swap(tour[i],tour[j]);
        }
    }
    cout<<N+1<<"\n";
    for(int i=0;i<N;i++)cout<<best[i]<<"\n";
    cout<<best[0]<<"\n";
}
