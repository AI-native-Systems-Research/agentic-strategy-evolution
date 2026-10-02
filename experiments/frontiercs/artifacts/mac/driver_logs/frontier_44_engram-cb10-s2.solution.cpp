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
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b],dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // mult for step t, source city c
    auto mult=[&](int t,int c)->double{
        return (t%10==0 && !isp[c])?1.1:1.0;
    };
    
    // Start with input-order tour (which is x-sorted - the baseline)
    vector<int>tour(N+1);
    for(int i=0;i<N;i++) tour[i]=i;
    tour[N]=0;
    
    // Compute full cost
    auto fullCost=[&](const vector<int>&tr)->double{
        double c=0;
        for(int t=1;t<=N;t++)
            c+=mult(t,tr[t-1])*dist(tr[t-1],tr[t]);
        return c;
    };
    
    // Try nearest-neighbor construction with grid
    {
        // Grid-based spatial index
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
        auto getCell=[&](int id)->int{
            int cx=min((int)((X[id]-minx)/gw),GS-1);
            int cy=min((int)((Y[id]-miny)/gh),GS-1);
            return cy*GS+cx;
        };
        
        for(int i=0;i<N;i++) grid[getCell(i)].push_back(i);
        
        vector<bool>used(N,false);
        vector<int>nn_tour(N+1);
        nn_tour[0]=0; used[0]=true;
        
        for(int i=1;i<N;i++){
            int cur=nn_tour[i-1];
            int cx=min((int)((X[cur]-minx)/gw),GS-1);
            int cy=min((int)((Y[cur]-miny)/gh),GS-1);
            double m=mult(i,cur);
            int best=-1; double bd=1e18;
            for(int r=0;r<GS;r++){
                if(best>=0){
                    double dx2=max(0.0,(double)(abs(cx-min(max(0,cx-r),GS-1)))*gw-gw);
                    double dy2=max(0.0,(double)(abs(cy-min(max(0,cy-r),GS-1)))*gh-gh);
                    if(m*sqrt(dx2*dx2+dy2*dy2)>bd) break;
                }
                int x0=max(0,cx-r),x1=min(GS-1,cx+r);
                int y0=max(0,cy-r),y1=min(GS-1,cy+r);
                for(int gx=x0;gx<=x1;gx++)for(int gy=y0;gy<=y1;gy++){
                    if(gx>x0&&gx<x1&&gy>y0&&gy<y1) continue;
                    for(int id:grid[gy*GS+gx]){
                        if(used[id]) continue;
                        double c=m*dist(cur,id);
                        if(c<bd){bd=c;best=id;}
                    }
                }
                if(best>=0&&r>0) break;
            }
            if(best<0){for(int j=0;j<N;j++)if(!used[j]){best=j;break;}}
            nn_tour[i]=best; used[best]=true;
        }
        nn_tour[N]=0;
        
        double nn_cost=fullCost(nn_tour);
        double base_cost=fullCost(tour);
        if(nn_cost<base_cost) tour=nn_tour;
    }
    
    double cur=fullCost(tour);
    
    // Position lookup
    vector<int>pos(N);
    for(int i=0;i<=N;i++) if(i<N) pos[tour[i]]=i;
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    
    mt19937 rng(12345);
    
    // 2-opt with segment cost recomputation
    while(elapsed()<1.85){
        bool improved=false;
        for(int iter=0;iter<50000&&elapsed()<1.85;iter++){
            int i=1+rng()%(N-1);
            int len=2+rng()%min(50,N-1);
            int j=i+len-1;
            if(j>=N) continue;
            
            // Cost of segment [i..j] before and after reverse
            double oldC=0,newC=0;
            // Also edges i-1->i and j->j+1 change
            for(int t=max(1,i);t<=min(N,j+1);t++)
                oldC+=mult(t,tour[t-1])*dist(tour[t-1],tour[t]);
            
            reverse(tour.begin()+i,tour.begin()+j+1);
            for(int t=max(1,i);t<=min(N,j+1);t++)
                newC+=mult(t,tour[t-1])*dist(tour[t-1],tour[t]);
            
            if(newC<oldC-1e-9){
                cur+=newC-oldC;
                improved=true;
            } else {
                reverse(tour.begin()+i,tour.begin()+j+1);
            }
        }
        if(!improved) break;
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
}
