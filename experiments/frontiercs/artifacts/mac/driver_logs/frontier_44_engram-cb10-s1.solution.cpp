#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin >> N;
    vector<double> X(N), Y(N);
    for(int i=0;i<N;i++) cin >> X[i] >> Y[i];
    
    int mx = max(N,2);
    vector<bool> is_prime(mx, false);
    {
        vector<bool> sieve(mx, true);
        if(mx>0) sieve[0]=false;
        if(mx>1) sieve[1]=false;
        for(int i=2;(long long)i*i<mx;i++)
            if(sieve[i]) for(int j=i*i;j<mx;j+=i) sieve[j]=false;
        for(int i=0;i<mx;i++) is_prime[i]=sieve[i];
    }
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // Nearest neighbor with grid-based spatial hashing
    vector<int> order(N);
    {
        vector<bool> used(N,false);
        used[0]=true;
        order[0]=0;
        
        // Build grid
        double minx=*min_element(X.begin(),X.end());
        double maxx=*max_element(X.begin(),X.end());
        double miny=*min_element(Y.begin(),Y.end());
        double maxy=*max_element(Y.begin(),Y.end());
        int G=max(1,(int)sqrt((double)N/4.0));
        double gw=(maxx-minx)/G+1e-9, gh=(maxy-miny)/G+1e-9;
        
        vector<vector<int>> grid(G*G);
        auto cellof=[&](int c)->int{
            int cx=min((int)((X[c]-minx)/gw),G-1);
            int cy=min((int)((Y[c]-miny)/gh),G-1);
            return cy*G+cx;
        };
        for(int i=0;i<N;i++) grid[cellof(i)].push_back(i);
        
        for(int step=1;step<N;step++){
            int last=order[step-1];
            int cx=min((int)((X[last]-minx)/gw),G-1);
            int cy=min((int)((Y[last]-miny)/gh),G-1);
            int best=-1; double bd=1e18;
            for(int r=0;r<=2*G;r++){
                for(int dx=-r;dx<=r;dx++) for(int dy=-r;dy<=r;dy++){
                    if(abs(dx)!=r&&abs(dy)!=r) continue;
                    int nx=cx+dx,ny=cy+dy;
                    if(nx<0||nx>=G||ny<0||ny>=G) continue;
                    for(int c:grid[ny*G+nx]) if(!used[c]){
                        double d=dist(last,c);
                        if(d<bd){bd=d;best=c;}
                    }
                }
                if(best>=0 && r>=1) break;
            }
            order[step]=best;
            used[best]=true;
            auto &gv=grid[cellof(best)];
            gv.erase(find(gv.begin(),gv.end(),best));
        }
    }
    
    vector<int> tour(N+1);
    for(int i=0;i<N;i++) tour[i]=order[i];
    tour[N]=0;
    
    auto getmult=[&](int idx)->double{
        int step=idx+1;
        return (step%10==0 && !is_prime[tour[idx]])?1.1:1.0;
    };
    auto ecost=[&](int idx)->double{
        return getmult(idx)*dist(tour[idx],tour[idx+1]);
    };
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    
    mt19937 rng(42);
    int maxSeg=min(N-1,60);
    while(elapsed()<1.8){
        int i=rng()%(N-1);
        int len=2+(rng()%maxSeg);
        int j=min(i+len,N-1);
        if(i==0&&j==N-1) continue;
        double oldC=0;
        for(int k=i;k<=j;k++) oldC+=ecost(k);
        reverse(tour.begin()+i+1,tour.begin()+j+1);
        double newC=0;
        for(int k=i;k<=j;k++) newC+=ecost(k);
        if(newC<oldC-1e-12){}
        else reverse(tour.begin()+i+1,tour.begin()+j+1);
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
}
