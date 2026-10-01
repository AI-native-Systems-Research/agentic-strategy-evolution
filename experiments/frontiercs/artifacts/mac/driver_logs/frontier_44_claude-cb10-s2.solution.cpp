#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int N; cin>>N;
    vector<double> cx(N),cy(N);
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    
    vector<bool> isp(max(N,2),false);
    {vector<bool> sv(max(N,2),true);
    if(N>0)sv[0]=false; if(N>1)sv[1]=false;
    for(int i=2;i<N;i++) if(sv[i]){isp[i]=true;for(long long j=(long long)i*i;j<N;j+=i)sv[j]=false;}}
    
    auto D=[&](int a,int b)->double{
        double dx=cx[a]-cx[b],dy=cy[a]-cy[b];return sqrt(dx*dx+dy*dy);};
    
    // Build initial tour with NN + grid
    vector<int> tour(N+1);
    {
        int GS=max(1,(int)sqrt((double)N)+1);
        double mnx=*min_element(cx.begin(),cx.end()),mxx=*max_element(cx.begin(),cx.end());
        double mny=*min_element(cy.begin(),cy.end()),mxy=*max_element(cy.begin(),cy.end());
        double gw=(mxx-mnx)/GS+1e-9,gh=(mxy-mny)/GS+1e-9;
        vector<vector<int>> grid(GS*GS);
        auto cell=[&](int id)->int{int gx=min((int)((cx[id]-mnx)/gw),GS-1);int gy=min((int)((cy[id]-mny)/gh),GS-1);return gy*GS+gx;};
        for(int i=0;i<N;i++) grid[cell(i)].push_back(i);
        vector<bool> vis(N,false); tour[0]=0; vis[0]=true;
        for(int s=1;s<N;s++){
            int last=tour[s-1];
            int gx0=min(GS-1,(int)((cx[last]-mnx)/gw)),gy0=min(GS-1,(int)((cy[last]-mny)/gh));
            int best=-1; double bd=1e18;
            for(int r=0;r<=GS;r++){
                for(int dy2=-r;dy2<=r;dy2++) for(int dx2=-r;dx2<=r;dx2++){
                    if(abs(dx2)!=r&&abs(dy2)!=r) continue;
                    int nx=gx0+dx2,ny=gy0+dy2;
                    if(nx<0||nx>=GS||ny<0||ny>=GS) continue;
                    for(int c:grid[ny*GS+nx]) if(!vis[c]){
                        double d=D(last,c);
                        // penalty aware: if step s+1 is multiple of 10 and last is not prime
                        if((s+1)%10==0 && !isp[last]) d*=1.1;
                        if(d<bd){bd=d;best=c;}
                    }
                }
                if(best>=0 && r>=1) break;
            }
            tour[s]=best; vis[best]=true;
            auto&g=grid[cell(best)]; g.erase(find(g.begin(),g.end(),best));
        }
        tour[N]=0;
    }
    
    // pos[city] = position in tour (0..N)
    vector<int> pos(N);
    for(int i=0;i<N;i++) pos[tour[i]]=i;
    
    auto stepCost=[&](int*T, int t)->double{
        double d=D(T[t-1],T[t]);
        if(t%10==0 && !isp[T[t-1]]) d*=1.1;
        return d;
    };
    
    int*T=tour.data();
    double curCost=0;
    for(int t=1;t<=N;t++) curCost+=stepCost(T,t);
    
    vector<int> best(tour); double bestCost=curCost;
    
    // Try to swap primes into penalty positions
    // Penalty positions: tour index p where (p+1)%10==0, i.e. p=9,19,29,...
    // We want T[p] to be prime
    {
        vector<int> penPos;
        for(int p=9;p<N;p+=10) penPos.push_back(p);
        // For each penalty position that doesn't have a prime, try swapping with nearest prime
        for(int p : penPos){
            if(isp[T[p]]) continue;
            // find best prime to swap with
            int bestJ=-1; double bestDelta=0;
            // Check nearby positions
            for(int j=max(1,p-200);j<min(N,p+200);j++){
                if(j==p) continue;
                if(!isp[T[j]]) continue;
                // compute delta of swapping T[p] and T[j]
                // affected steps: p, p+1, j, j+1 (if they exist and are in range)
                set<int> affected;
                if(p>=1) affected.insert(p);
                if(p+1<=N) affected.insert(p+1);
                if(j>=1) affected.insert(j);
                if(j+1<=N) affected.insert(j+1);
                double oldC=0,newC=0;
                for(int t:affected) oldC+=stepCost(T,t);
                swap(T[p],T[j]);
                for(int t:affected) newC+=stepCost(T,t);
                swap(T[p],T[j]);
                double delta=newC-oldC;
                if(delta<bestDelta){bestDelta=delta;bestJ=j;}
            }
            if(bestJ>=0){
                curCost+=bestDelta;
                pos[T[p]]=bestJ; pos[T[bestJ]]=p;
                swap(T[p],T[bestJ]);
            }
        }
        if(curCost<bestCost){bestCost=curCost;best.assign(T,T+N+1);}
    }
    
    auto st=chrono::steady_clock::now();
    mt19937 rng(42);
    double tl=1.80;
    
    int iter=0;
    while(1){
        if((++iter&0xFFF)==0){
            double e=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(e>=tl) break;
        }
        double e=chrono::duration<double>(chrono::steady_clock::now()-st).count();
        if(e>=tl) break;
        double f=e/tl;
        double temp=(curCost/N*0.2)*pow(1e-7/0.2,f);
        
        int r=rng()%100;
        if(r<70){
            // 2-opt
            int i=1+rng()%(N-1);
            int len=1+rng()%min(N-1,max(5,(int)(80000.0/N)));
            int j=i+len; if(j>=N) continue;
            int lo=max(1,i-1),hi=min(N,j+1);
            double oC=0; for(int t=lo;t<=hi;t++) oC+=stepCost(T,t);
            reverse(T+i,T+j+1);
            double nC=0; for(int t=lo;t<=hi;t++) nC+=stepCost(T,t);
            double d=nC-oC;
            if(d<0||((rng()&0xFFFF)/65536.0)<exp(-d/temp)){
                curCost+=d;
                if(curCost<bestCost){bestCost=curCost;best.assign(T,T+N+1);}
            } else reverse(T+i,T+j+1);
        } else {
            // or-opt: relocate 1-3 cities
            int segLen=1+rng()%3;
            int i=1+rng()%(N-1);
            int j=i+segLen-1; if(j>=N) continue;
            int dest=1+rng()%(N-segLen-1); if(dest>=i) dest+=segLen; if(dest>=N) continue;
            // Just do it via copy
            vector<int> seg(T+i,T+j+1);
            // remove seg
            vector<int> tmp; tmp.reserve(N+1);
            for(int k=0;k<=N;k++) if(k<i||k>j) tmp.push_back(T[k]);
            // insert at dest (adjusted)
            int ins=dest; if(dest>i) ins-=segLen;
            if(ins<1) ins=1; if(ins>=(int)tmp.size()) continue;
            vector<int> ntour; ntour.reserve(N+1);
            for(int k=0;k<ins;k++) ntour.push_back(tmp[k]);
            for(int c:seg) ntour.push_back(c);
            for(int k=ins;k<(int)tmp.size();k++) ntour.push_back(tmp[k]);
            if((int)ntour.size()!=N+1) continue;
            double nCost=0;
            for(int t=1;t<=N;t++){double dd=D(ntour[t-1],ntour[t]);if(t%10==0&&!isp[ntour[t-1]])dd*=1.1;nCost+=dd;}
            double d=nCost-curCost;
            if(d<0||((rng()&0xFFFF)/65536.0)<exp(-d/temp)){
                curCost=nCost; memcpy(T,ntour.data(),(N+1)*sizeof(int));
                if(curCost<bestCost){bestCost=curCost;best.assign(T,T+N+1);}
            }
        }
    }
    
    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<best[i]<<"\n";
}
