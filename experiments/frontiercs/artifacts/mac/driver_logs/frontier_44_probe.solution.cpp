#include <bits/stdc++.h>
using namespace std;

static int N;
static vector<double> cx, cy;
static vector<bool> is_prime_v;

inline double dist2(int a, int b){
    double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
    return dx*dx+dy*dy;
}
inline double ddist(int a, int b){
    double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
    return sqrt(dx*dx+dy*dy);
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    cin>>N;
    cx.resize(N); cy.resize(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    is_prime_v.assign(N,false);
    if(N>=3){
        fill(is_prime_v.begin()+2,is_prime_v.end(),true);
        for(int i=2;(long long)i*i<N;i++)
            if(is_prime_v[i])
                for(int j=i*i;j<N;j+=i)
                    is_prime_v[j]=false;
    }
    
    auto startTime=chrono::steady_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    // Grid-based nearest neighbor
    // Build grid
    double minx=*min_element(cx.begin(),cx.end());
    double maxx=*max_element(cx.begin(),cx.end());
    double miny=*min_element(cy.begin(),cy.end());
    double maxy=*max_element(cy.begin(),cy.end());
    
    int gsz=max(1,(int)sqrt((double)N/4.0));
    double gw=(maxx-minx)/gsz+1e-9;
    double gh=(maxy-miny)/gsz+1e-9;
    if(gw<1e-12) gw=1.0;
    if(gh<1e-12) gh=1.0;
    
    vector<vector<int>> grid(gsz*gsz);
    auto getCell=[&](int id)->pair<int,int>{
        int gx=min((int)((cx[id]-minx)/gw),gsz-1);
        int gy=min((int)((cy[id]-miny)/gh),gsz-1);
        return {gx,gy};
    };
    for(int i=0;i<N;i++){
        auto [gx,gy]=getCell(i);
        grid[gx*gsz+gy].push_back(i);
    }
    
    vector<bool> used(N,false);
    vector<int> tour;
    tour.reserve(N+1);
    tour.push_back(0);
    used[0]=true;
    
    for(int step=1;step<N;step++){
        int cur=tour.back();
        auto [cgx,cgy]=getCell(cur);
        int best=-1;
        double bestd=1e30;
        
        for(int rad=0;rad<=2*gsz;rad++){
            if(best>=0){
                double mindist_possible=(rad-1)*min(gw,gh);
                if(mindist_possible*mindist_possible>bestd) break;
            }
            for(int dx2=-rad;dx2<=rad;dx2++){
                for(int dy2=-rad;dy2<=rad;dy2++){
                    if(abs(dx2)!=rad && abs(dy2)!=rad) continue;
                    int nx=cgx+dx2, ny=cgy+dy2;
                    if(nx<0||nx>=gsz||ny<0||ny>=gsz) continue;
                    auto &cell=grid[nx*gsz+ny];
                    for(int j:cell){
                        if(used[j]) continue;
                        double d=dist2(cur,j);
                        if(d<bestd){bestd=d;best=j;}
                    }
                }
            }
            if(best>=0 && rad>=1) break;
        }
        tour.push_back(best);
        used[best]=true;
    }
    tour.push_back(0);
    
    // Multiplier for step t (1-indexed)
    auto mult=[&](int t, int src)->double{
        return (t%10==0 && !is_prime_v[src])?1.1:1.0;
    };
    
    auto tourCost=[&]()->double{
        double s=0;
        for(int t=1;t<=N;t++)
            s+=mult(t,tour[t-1])*ddist(tour[t-1],tour[t]);
        return s;
    };
    
    // Or-opt (move single city) + 2-opt, time limited
    // Use random perturbations
    mt19937 rng(42);
    
    double bestCost=tourCost();
    vector<int> bestTour=tour;
    
    while(elapsed()<1.85){
        bool imp=false;
        // Random or-opt: pick random city, try reinserting
        for(int iter=0;iter<N&&elapsed()<1.85;iter++){
            int pos=1+(rng()%(N-1)); // position in tour[1..N-1]
            // Remove city at pos, reinsert at best position
            int city=tour[pos];
            
            // Cost of removing: steps pos and pos+1 affected, replaced by direct link
            // Old: mult(pos,tour[pos-1])*dist(pos-1,pos) + mult(pos+1,tour[pos])*dist(pos,pos+1)
            // New link from pos-1 to pos+1 at step pos, then everything shifts...
            // Shifting is complex. Let's do swap-based local search instead.
            
            // Simple swap: swap tour[pos] with tour[pos2]
            int pos2=1+(rng()%(N-1));
            if(pos==pos2) continue;
            
            // Compute affected steps
            auto costAround=[&](int p)->double{
                double c=0;
                c+=mult(p,tour[p-1])*ddist(tour[p-1],tour[p]);
                if(p+1<=(int)tour.size()-1)
                    c+=mult(p+1,tour[p])*ddist(tour[p],tour[p+1]);
                return c;
            };
            
            int lo=min(pos,pos2), hi=max(pos,pos2);
            double oldC=0;
            // Affected positions: lo and hi, and their neighbors
            set<int> affected;
            affected.insert(lo); affected.insert(lo+1);
            affected.insert(hi); affected.insert(hi+1);
            
            for(int t:affected) if(t>=1&&t<=N) oldC+=mult(t,tour[t-1])*ddist(tour[t-1],tour[t]);
            
            swap(tour[lo],tour[hi]);
            
            double newC=0;
            for(int t:affected) if(t>=1&&t<=N) newC+=mult(t,tour[t-1])*ddist(tour[t-1],tour[t]);
            
            if(newC<oldC-1e-10){
                bestCost+=newC-oldC;
                imp=true;
            } else {
                swap(tour[lo],tour[hi]);
            }
        }
        
        // 2-opt on random segments
        for(int iter=0;iter<N/2&&elapsed()<1.85;iter++){
            int i=1+(rng()%(N-1));
            int len=2+rng()%min(50,N-1);
            int j=min(i+len,N-1);
            if(j<=i) continue;
            
            double oldC=0;
            for(int t=i;t<=min(j+1,N);t++)
                oldC+=mult(t,tour[t-1])*ddist(tour[t-1],tour[t]);
            
            reverse(tour.begin()+i,tour.begin()+j+1);
            
            double newC=0;
            for(int t=i;t<=min(j+1,N);t++)
                newC+=mult(t,tour[t-1])*ddist(tour[t-1],tour[t]);
            
            if(newC<oldC-1e-10){
                bestCost+=newC-oldC;
            } else {
                reverse(tour.begin()+i,tour.begin()+j+1);
            }
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
    return 0;
}
