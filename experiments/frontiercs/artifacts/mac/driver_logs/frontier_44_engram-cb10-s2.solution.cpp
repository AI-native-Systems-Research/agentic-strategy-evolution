#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin>>N;
    vector<double> X(N), Y(N);
    for(int i=0;i<N;i++) cin>>X[i]>>Y[i];
    
    vector<bool> is_prime(N+1, true);
    is_prime[0]=is_prime[1]=false;
    for(int i=2;(long long)i*i<=N;i++)
        if(is_prime[i]) for(int j=i*i;j<=N;j+=i) is_prime[j]=false;
    
    auto ddist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // step t (1-based): edge from tour[t-1] to tour[t]
    // penalty 1.1 if step%10==0 and tour[t] (destination city, 1-based: tour[t]+1) is NOT prime
    auto get_mult=[&](int step, int dest_city)->double{
        if(step%10==0 && !is_prime[dest_city+1]) return 1.1;
        return 1.0;
    };
    
    auto edge_cost=[&](int step, int from, int to)->double{
        return get_mult(step, to)*ddist(from,to);
    };
    
    auto tour_cost=[&](const vector<int>& tour)->double{
        double c=0;
        for(int t=1;t<=N;t++) c+=edge_cost(t,tour[t-1],tour[t]);
        return c;
    };
    
    vector<bool> used(N,false);
    vector<int> tour(N+1);
    tour[0]=0; used[0]=true;
    for(int i=1;i<N;i++){
        int best=-1; double bd=1e18;
        for(int j=0;j<N;j++){
            if(used[j]) continue;
            double cost=edge_cost(i,tour[i-1],j);
            if(cost<bd){bd=cost;best=j;}
        }
        tour[i]=best; used[best]=true;
    }
    tour[N]=0;
    
    double cur_cost=tour_cost(tour);
    vector<int> best_tour=tour;
    double best_cost=cur_cost;
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    mt19937 rng(42);
    double time_limit=1.8;
    
    while(elapsed()<time_limit){
        double frac=elapsed()/time_limit;
        double T=best_cost*0.01*(1.0-frac)+1e-10;
        for(int it=0;it<500&&elapsed()<time_limit;it++){
            int i=1+rng()%(N-1), j=1+rng()%(N-1);
            if(i>j) swap(i,j);
            if(i==j) continue;
            int lo=max(1,i), hi=min(j+1,N);
            double old_c=0,new_c=0;
            for(int k=lo;k<=hi;k++) old_c+=edge_cost(k,tour[k-1],tour[k]);
            reverse(tour.begin()+i,tour.begin()+j+1);
            for(int k=lo;k<=hi;k++) new_c+=edge_cost(k,tour[k-1],tour[k]);
            double delta=new_c-old_c;
            if(delta<0||(T>1e-12&&exp(-delta/T)>(rng()%10000)/10000.0)){
                cur_cost+=delta;
                if(cur_cost<best_cost){best_cost=cur_cost;best_tour=tour;}
            } else reverse(tour.begin()+i,tour.begin()+j+1);
        }
    }
    
    for(int i=0;i<=N;i++) cout<<best_tour[i]+1<<"\n";
}
