#include <bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N;
    cin>>N;
    vector<double>X(N),Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    vector<bool>isp(N,false);
    if(N>2){
        for(int i=2;i<N;i++) isp[i]=true;
        for(int i=2;(long long)i*i<N;i++)
            if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;
    }
    auto dist=[&](int a,int b)->double{double dx=X[a]-X[b],dy=Y[a]-Y[b];return sqrt(dx*dx+dy*dy);};
    auto mult=[&](int step,int city)->double{return(step%10==0&&!isp[city])?1.1:1.0;};
    auto total_cost=[&](const vector<int>&t)->double{
        double c=0;for(int i=1;i<(int)t.size();i++)c+=mult(i,t[i-1])*dist(t[i-1],t[i]);return c;
    };
    // Nearest neighbor from city 0
    vector<bool>used(N,false);
    vector<int>tour(N+1);
    tour[0]=0;used[0]=true;
    for(int i=1;i<N;i++){
        int best=-1;double bd=1e18;
        for(int j=0;j<N;j++)if(!used[j]){
            double c=mult(i,tour[i-1])*dist(tour[i-1],j);
            if(c<bd){bd=c;best=j;}
        }
        tour[i]=best;used[best]=true;
    }
    tour[N]=0;
    double cur=total_cost(tour);
    vector<int>best_tour=tour;double best_cost=cur;
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    mt19937 rng(42);
    // Or-opt: remove city at pos i, insert at pos j
    while(elapsed()<1.85){
        bool any=false;
        for(int i=1;i<N&&elapsed()<1.85;i++){
            double old_cost=cur;
            int city=tour[i];
            vector<int>nt;nt.reserve(N+1);
            for(int k=0;k<=(int)N;k++)if(k!=i)nt.push_back(tour[k]);
            int bestj=-1;double bc=1e18;
            // Try inserting city after each position in nt
            int M=nt.size();
            for(int j=0;j<M-1;j++){
                vector<int>tt;tt.reserve(N+1);
                for(int k=0;k<=j;k++)tt.push_back(nt[k]);
                tt.push_back(city);
                for(int k=j+1;k<M;k++)tt.push_back(nt[k]);
                double c=total_cost(tt);
                if(c<bc){bc=c;bestj=j;}
            }
            if(bc<cur-1e-9){
                vector<int>tt;
                for(int k=0;k<=bestj;k++)tt.push_back(nt[k]);
                tt.push_back(city);
                for(int k=bestj+1;k<M;k++)tt.push_back(nt[k]);
                tour=tt;cur=bc;any=true;
                if(cur<best_cost){best_cost=cur;best_tour=tour;}
            }
        }
        if(!any)break;
    }
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++)cout<<best_tour[i]<<"\n";
}
