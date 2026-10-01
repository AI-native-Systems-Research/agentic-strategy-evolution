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
    if(N>0)sv[0]=false;if(N>1)sv[1]=false;
    for(int i=2;i<N;i++)if(sv[i]){isp[i]=true;for(long long j=(long long)i*i;j<N;j+=i)sv[j]=false;}}
    
    auto di=[&](int a,int b)->double{
        double dx=cx[a]-cx[b],dy=cy[a]-cy[b];return sqrt(dx*dx+dy*dy);};
    
    // Nearest neighbor
    vector<int> tour(N+1);
    {
        int GS=max(1,(int)(sqrt((double)N))+1);
        double mnx=*min_element(cx.begin(),cx.end()),mxx=*max_element(cx.begin(),cx.end());
        double mny=*min_element(cy.begin(),cy.end()),mxy=*max_element(cy.begin(),cy.end());
        double gw=(mxx-mnx)/GS+1e-9,gh=(mxy-mny)/GS+1e-9;
        vector<vector<int>> grid(GS*GS);
        auto cell=[&](int id)->int{int gx=min((int)((cx[id]-mnx)/gw),GS-1);int gy=min((int)((cy[id]-mny)/gh),GS-1);return gy*GS+gx;};
        for(int i=0;i<N;i++)grid[cell(i)].push_back(i);
        vector<bool> vis(N,false);
        tour[0]=0;vis[0]=true;
        for(int s=1;s<N;s++){
            int last=tour[s-1];
            int gx0=min(GS-1,(int)((cx[last]-mnx)/gw));
            int gy0=min(GS-1,(int)((cy[last]-mny)/gh));
            int best=-1;double bd=1e18;
            for(int r=0;r<=GS;r++){
                for(int dy2=-r;dy2<=r;dy2++)for(int dx2=-r;dx2<=r;dx2++){
                    if(abs(dx2)!=r&&abs(dy2)!=r)continue;
                    int nx2=gx0+dx2,ny2=gy0+dy2;
                    if(nx2<0||nx2>=GS||ny2<0||ny2>=GS)continue;
                    for(int c:grid[ny2*GS+nx2])if(!vis[c]){double d=di(last,c);if(d<bd){bd=d;best=c;}}
                }
                if(best>=0&&r>=1)break;
            }
            tour[s]=best;vis[best]=true;
            auto&g=grid[cell(best)];g.erase(find(g.begin(),g.end(),best));
        }
        tour[N]=0;
    }
    
    int*T=tour.data();
    auto mult=[&](int t,int src)->double{return(t%10==0&&!isp[src])?1.1:1.0;};
    auto ec=[&](int t)->double{return mult(t,T[t-1])*di(T[t-1],T[t]);};
    double curCost=0;for(int t=1;t<=N;t++)curCost+=ec(t);
    vector<int>bestTour(T,T+N+1);double bestCost=curCost;
    auto st=chrono::steady_clock::now();
    mt19937 rng(42);double tl=1.88;
    int maxSeg=min(N-1,max(5,(int)sqrt((double)N)*3));
    int iter=0;
    while(true){
        if((++iter&0xFFF)==0){if(chrono::duration<double>(chrono::steady_clock::now()-st).count()>=tl)break;}
        double f=chrono::duration<double>(chrono::steady_clock::now()-st).count()/tl;
        double temp=(curCost/N*0.04)*pow(1e-10/0.04,f);
        int i=1+rng()%(N-1),len=2+rng()%maxSeg,j=i+len-1;
        if(j>=N)continue;
        int lo=i,hi=min(j+1,N);double oC=0;for(int t=lo;t<=hi;t++)oC+=ec(t);
        reverse(T+i,T+j+1);double nC=0;for(int t=lo;t<=hi;t++)nC+=ec(t);
        double d=nC-oC;
        if(d<0||(temp>1e-18&&d/temp<20&&(rng()%65536)<65536*exp(-d/temp))){
            curCost+=d;if(curCost<bestCost){bestCost=curCost;bestTour.assign(T,T+N+1);}
        }else reverse(T+i,T+j+1);
    }
    cout<<N+1<<"\n";for(int i=0;i<=N;i++)cout<<bestTour[i]<<"\n";
}
