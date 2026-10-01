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
    if(N>=2){
        vector<bool> sieve(N,true);
        sieve[0]=true; // not prime
        if(N>1) sieve[1]=true; // not prime
        // Actually let me redo: isp[i]=true means i is prime
        for(int i=2;i<N;i++) isp[i]=true;
        for(int i=2;(long long)i*i<N;i++)
            if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;
    }
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // mult for step t (1-indexed), source city c = P[t-1]
    auto mult=[&](int t,int c)->double{
        return (t%10==0 && !isp[c])?1.1:1.0;
    };
    
    // Compute full cost
    auto fullCost=[&](const vector<int>&tr)->double{
        double c=0;
        for(int t=1;t<=N;t++)
            c+=mult(t,tr[t-1])*dist(tr[t-1],tr[t]);
        return c;
    };
    
    // Compute cost of steps from position i to position j (inclusive steps)
    // step t goes from tr[t-1] to tr[t]
    auto segCost=[&](const vector<int>&tr, int si, int ei)->double{
        double c=0;
        for(int t=si;t<=ei;t++)
            c+=mult(t,tr[t-1])*dist(tr[t-1],tr[t]);
        return c;
    };
    
    // Start with input-order tour (x-sorted baseline)
    vector<int>tour(N+1);
    for(int i=0;i<N;i++) tour[i]=i;
    tour[N]=0;
    
    // Nearest-neighbor construction
    {
        vector<bool>used(N,false);
        vector<int>nn(N+1);
        nn[0]=0; used[0]=true;
        
        // Simple grid spatial index
        double minx=*min_element(X.begin(),X.end());
        double maxx=*max_element(X.begin(),X.end());
        double miny=*min_element(Y.begin(),Y.end());
        double maxy=*max_element(Y.begin(),Y.end());
        
        int GS=max(1,(int)sqrt((double)N/4.0));
        double gw=(maxx-minx)/GS+1e-9;
        double gh=(maxy-miny)/GS+1e-9;
        if(gw<1e-12) gw=1;
        if(gh<1e-12) gh=1;
        
        vector<vector<int>>grid(GS*GS);
        auto getCell=[&](int id)->pair<int,int>{
            int cx=min((int)((X[id]-minx)/gw),GS-1);
            int cy=min((int)((Y[id]-miny)/gh),GS-1);
            return {cx,cy};
        };
        
        for(int i=0;i<N;i++){
            auto [cx,cy]=getCell(i);
            grid[cy*GS+cx].push_back(i);
        }
        
        for(int i=1;i<N;i++){
            int cur=nn[i-1];
            auto [cx,cy]=getCell(cur);
            int best=-1; double bd=1e18;
            
            for(int r=0;r<GS+1;r++){
                int x0=max(0,cx-r),x1=min(GS-1,cx+r);
                int y0=max(0,cy-r),y1=min(GS-1,cy+r);
                for(int gx=x0;gx<=x1;gx++){
                    for(int gy=y0;gy<=y1;gy++){
                        if(r>0 && gx>x0 && gx<x1 && gy>y0 && gy<y1) continue;
                        for(int id:grid[gy*GS+gx]){
                            if(used[id]) continue;
                            double d=dist(cur,id);
                            if(d<bd){bd=d;best=id;}
                        }
                    }
                }
                if(best>=0 && r>0) break;
            }
            if(best<0){for(int j=0;j<N;j++)if(!used[j]){best=j;break;}}
            nn[i]=best; used[best]=true;
        }
        nn[N]=0;
        
        if(fullCost(nn)<fullCost(tour)) tour=nn;
    }
    
    double bestCost=fullCost(tour);
    vector<int>bestTour=tour;
    
    auto start_time=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start_time).count();};
    
    mt19937 rng(42);
    
    // Iterative improvement
    while(elapsed()<1.8){
        bool improved=false;
        
        // 2-opt: try random segment reversals
        for(int iter=0;iter<100000 && elapsed()<1.75;iter++){
            int i,j;
            if(N<=2) break;
            i=1+rng()%(N-1);
            int maxlen=min(80,N-1);
            int len=2+rng()%maxlen;
            j=i+len-1;
            if(j>=N) continue;
            
            // Compute old cost for affected steps [i..j+1] if j+1<=N, else [i..j]
            int ts=i, te=min(N,j+1);
            double oldC=segCost(tour,ts,te);
            
            reverse(tour.begin()+i,tour.begin()+j+1);
            double newC=segCost(tour,ts,te);
            
            if(newC<oldC-1e-10){
                bestCost+=newC-oldC;
                improved=true;
            } else {
                reverse(tour.begin()+i,tour.begin()+j+1);
            }
        }
        
        // Or-opt: relocate single cities
        for(int iter=0;iter<100000 && elapsed()<1.8;iter++){
            if(N<=3) break;
            int from=1+rng()%(N-1); // position in tour to remove
            int city=tour[from];
            if(city==0) continue;
            
            // Cost of removing city from position 'from'
            int ts=from, te=min(N,from+1);
            double oldRemove=segCost(tour,ts,te);
            
            // Try inserting at a random position
            int to=1+rng()%(N-1);
            if(to==from||to==from-1) continue;
            
            // Actually perform the move and evaluate
            vector<int>tmp=tour;
            tmp.erase(tmp.begin()+from);
            int insertPos=(to>from)?to-1:to;
            tmp.insert(tmp.begin()+insertPos,city);
            
            // Recompute affected region cost
            int lo=min(from,insertPos), hi=min(N,max(from+1,insertPos+1));
            double oldSeg=segCost(tour,lo,hi);
            double newSeg=segCost(tmp,lo,hi);
            
            if(newSeg<oldSeg-1e-10){
                tour=tmp;
                bestCost+=newSeg-oldSeg;
                improved=true;
            }
        }
        
        if(!improved) break;
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
}
