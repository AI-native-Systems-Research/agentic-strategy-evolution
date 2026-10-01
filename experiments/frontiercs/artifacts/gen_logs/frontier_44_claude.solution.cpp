#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin >> N;
    vector<double> X(N), Y(N);
    for(int i=0;i<N;i++) cin >> X[i] >> Y[i];
    
    // Sieve primes
    vector<bool> is_prime(N, false);
    if(N > 2){
        vector<bool> sieve(N, true);
        sieve[0] = sieve[1] = false;
        for(int i=2;i*i<N;i++) if(sieve[i]) for(int j=i*i;j<N;j+=i) sieve[j]=false;
        is_prime = sieve;
    }
    
    auto dist = [&](int a, int b) -> double {
        double dx = X[a]-X[b], dy = Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // Start with input order: 0,1,2,...,N-1,0
    vector<int> tour(N+1);
    tour[0] = 0;
    for(int i=1;i<N;i++) tour[i] = i;
    tour[N] = 0;
    
    auto cost = [&](const vector<int>& P) -> double {
        double s = 0;
        for(int t=1;t<=N;t++){
            double d = dist(P[t-1], P[t]);
            if(t % 10 == 0 && !is_prime[P[t-1]]) d *= 1.1;
            s += d;
        }
        return s;
    };
    
    // 2-opt with time limit
    auto start_time = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now()-start_time).count();
    };
    
    bool improved = true;
    while(improved && elapsed() < 1.8){
        improved = false;
        for(int i=1;i<N-1 && elapsed()<1.8;i++){
            for(int j=i+1;j<N && j-i<50;j++){
                // Try reversing segment [i..j]
                // Approximate: just check edge costs
                int a=tour[i-1], b=tour[i], c=tour[j], d=tour[j+1];
                auto edgecost=[&](int t, int u, int v) -> double {
                    double dd = dist(u,v);
                    if(t%10==0 && !is_prime[u]) dd*=1.1;
                    return dd;
                };
                double old_c = edgecost(i,a,b) + edgecost(j+1,c,d);
                double new_c = edgecost(i,a,c) + edgecost(j+1,b,d);
                // This is approximate since interior penalties change too
                if(new_c < old_c - 1e-10){
                    reverse(tour.begin()+i, tour.begin()+j+1);
                    improved = true;
                }
            }
        }
    }
    
    cout << N+1 << "\n";
    for(int i=0;i<=N;i++) cout << tour[i] << "\n";
    
    return 0;
}
