#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin>>N;
    vector<double>X(N+1),Y(N+1);
    for(int i=1;i<=N;i++) cin>>X[i]>>Y[i];
    
    vector<bool>isp(N+1,false);
    for(int i=2;i<=N;i++) isp[i]=true;
    for(int i=2;(long long)i*i<=N;i++)
        if(isp[i]) for(int j=i*i;j<=N;j+=i) isp[j]=false;
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // step t (1-indexed), from city c
    auto getmult=[&](int t,int c)->double{
        return (t%10==0 && !isp[c])?1.1:1.0;
    };
    
    // tour: tour[0..N], tour[0]=tour[N]=1 (city 1 is start)
    // step t goes from tour[t-1] to tour[t]
    auto fullCost=[&](const vector<int>&tr)->double{
        double c=0;
        for(int t=1;t<=N;t++)
            c+=getmult(t,tr[t-1])*dist(tr[t-1],tr[t]);
        return c;
    };
    
    auto startTime=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();};
    
    mt19937 rng(42);
    
    // Build NN tour starting from city 1
    auto buildNN=[&](int s)->vector<int>{
        vector<bool>used(N+1,false);
        vector<int>order; order.reserve(N);
        order.push_back(s); used[s]=true;
        for(int i=1;i<N;i++){
            int cur=order.back();
            int best=-1; double bd=1e18;
            for(int j=1;j<=N;j++){
                if(used[j]) continue;
                double c=dist(cur,j);
                if(c<bd){bd=c;best=j;}
            }
            order.push_back(best);
            used[best]=true;
        }
        // Rotate so city 1 is first
        int pos=0;
        for(int i=0;i<N;i++) if(order[i]==1){pos=i;break;}
        vector<int>tour(N+1);
        for(int i=0;i<N;i++) tour[i]=order[(pos+i)%N];
        tour[N]=1;
        return tour;
    };
    
    vector<int>bestTour=buildNN(1);
    double bestCost=fullCost(bestTour);
    
    for(int s=2;s<=min(N,20);s++){
        if(elapsed()>0.3)break;
        auto t=buildNN(s);
        double c=fullCost(t);
        if(c<bestCost){bestCost=c;bestTour=t;}
    }
    
    vector<int>tour=bestTour;
    double cur=bestCost;
    double temp=bestCost*0.01;
    uniform_real_distribution<double>ud(0.0,1.0);
    
    while(elapsed()<1.85){
        for(int it=0;it<50000&&elapsed()<1.85;it++){
            int i=1+rng()%(N-1);
            int len=2+rng()%min(N-1,200);
            int j=i+len-1;
            if(j>=N) continue;
            int lo=i,hi=min(N,j+1);
            double oldC=0;
            for(int t=lo;t<=hi;t++) oldC+=getmult(t,tour[t-1])*dist(tour[t-1],tour[t]);
            reverse(tour.begin()+i,tour.begin()+j+1);
            double newC=0;
            for(int t=lo;t<=hi;t++) newC+=getmult(t,tour[t-1])*dist(tour[t-1],tour[t]);
            double delta=newC-oldC;
            if(delta<0||(temp>1e-15&&ud(rng)<exp(-delta/temp))){
                cur+=delta;
                if(cur<bestCost){bestCost=cur;bestTour=tour;}
            } else {
                reverse(tour.begin()+i,tour.begin()+j+1);
            }
            temp*=0.99999;
        }
    }
    
    tour=bestTour;
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
}
