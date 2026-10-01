#include <bits/stdc++.h>
using namespace std;

static int N;
static double *cx, *cy;
static bool *isp;
static int *tour;
static int *pos;

struct RNG {
    uint64_t s;
    RNG(uint64_t seed=98765ULL):s(seed){}
    inline uint64_t next(){s^=s<<13;s^=s>>7;s^=s<<17;return s;}
    inline int nextInt(int n){return next()%n;}
    inline double nextDouble(){return(next()&0xFFFFFFFFFFFFFULL)*(1.0/(1ULL<<52));}
};

inline double distv(int a, int b){
    double dx=cx[a]-cx[b],dy=cy[a]-cy[b];
    return sqrt(dx*dx+dy*dy);
}

void sieve(int m){
    isp=new bool[m+1];
    fill(isp,isp+m+1,true);
    isp[0]=isp[1]=false;
    for(int i=2;(long long)i*i<=m;i++)
        if(isp[i]) for(int j=i*i;j<=m;j+=i) isp[j]=false;
}

inline double mult(int t){
    return (t%10==0 && !isp[tour[t-1]])?1.1:1.0;
}
inline double ec(int t){return mult(t)*distv(tour[t-1],tour[t]);}

double totalCost(){
    double c=0; for(int t=1;t<=N;t++) c+=ec(t); return c;
}

void constructNN(){
    int gs=max(1,(int)sqrt((double)N));
    double mnx=1e18,mxx=-1e18,mny=1e18,mxy=-1e18;
    for(int i=0;i<N;i++){mnx=min(mnx,cx[i]);mxx=max(mxx,cx[i]);mny=min(mny,cy[i]);mxy=max(mxy,cy[i]);}
    double cw=(mxx-mnx+1.0)/gs, ch=(mxy-mny+1.0)/gs;
    vector<vector<int>> grid(gs*gs);
    for(int i=0;i<N;i++){
        int gx=min(gs-1,(int)((cx[i]-mnx)/cw));
        int gy=min(gs-1,(int)((cy[i]-mny)/ch));
        grid[gy*gs+gx].push_back(i);
    }
    vector<bool> vis(N,false);
    tour[0]=0; vis[0]=true;
    for(int step=1;step<N;step++){
        int cur=tour[step-1];
        int gcx2=min(gs-1,(int)((cx[cur]-mnx)/cw));
        int gcy2=min(gs-1,(int)((cy[cur]-mny)/ch));
        double bd=1e30; int bc=-1;
        for(int r=0;r<=gs;r++){
            if(bc!=-1&&r>1){double mp=(r-1.0)*min(cw,ch);if(mp*mp>bd)break;}
            int x0=max(0,gcx2-r),x1=min(gs-1,gcx2+r);
            int y0=max(0,gcy2-r),y1=min(gs-1,gcy2+r);
            for(int gy2=y0;gy2<=y1;gy2++)
                for(int gx2=x0;gx2<=x1;gx2++){
                    if(r>0&&gx2>x0&&gx2<x1&&gy2>y0&&gy2<y1)continue;
                    for(int c:grid[gy2*gs+gx2])
                        if(!vis[c]){double dx2=cx[cur]-cx[c],dy2=cy[cur]-cy[c];double d=dx2*dx2+dy2*dy2;if(d<bd){bd=d;bc=c;}}
                }
            if(bc!=-1&&r>=1)break;
        }
        tour[step]=bc; vis[bc]=true;
    }
    tour[N]=0;
}

static int KNN;
static int **nnlist;

void buildNN(){
    int gs2=max(1,(int)sqrt((double)N));
    double mnx=1e18,mxx=-1e18,mny=1e18,mxy=-1e18;
    for(int i=0;i<N;i++){mnx=min(mnx,cx[i]);mxx=max(mxx,cx[i]);mny=min(mny,cy[i]);mxy=max(mxy,cy[i]);}
    double cw2=(mxx-mnx+1.0)/gs2, ch2=(mxy-mny+1.0)/gs2;
    vector<vector<int>> grid2(gs2*gs2);
    for(int i=0;i<N;i++){
        int gx=min(gs2-1,(int)((cx[i]-mnx)/cw2));
        int gy=min(gs2-1,(int)((cy[i]-mny)/ch2));
        grid2[gy*gs2+gx].push_back(i);
    }
    KNN=min(12,N-1);
    nnlist=new int*[N];
    for(int city=0;city<N;city++){
        nnlist[city]=new int[KNN];
        int gcx2=min(gs2-1,(int)((cx[city]-mnx)/cw2));
        int gcy2=min(gs2-1,(int)((cy[city]-mny)/ch2));
        priority_queue<pair<double,int>> pq;
        for(int r=0;r<=gs2;r++){
            if((int)pq.size()>=KNN){double mp=(r-1.0)*min(cw2,ch2);if(mp*mp>pq.top().first)break;}
            int x0=max(0,gcx2-r),x1=min(gs2-1,gcx2+r);
            int y0=max(0,gcy2-r),y1=min(gs2-1,gcy2+r);
            for(int gy=y0;gy<=y1;gy++)
                for(int gx=x0;gx<=x1;gx++){
                    if(r>0&&gx>x0&&gx<x1&&gy>y0&&gy<y1)continue;
                    for(int c:grid2[gy*gs2+gx]){
                        if(c==city)continue;
                        double dx2=cx[city]-cx[c],dy2=cy[city]-cy[c];
                        double d=dx2*dx2+dy2*dy2;
                        if((int)pq.size()<KNN){pq.push({d,c});}
                        else if(d<pq.top().first){pq.pop();pq.push({d,c});}
                    }
                }
            if((int)pq.size()>=KNN&&r>=1)break;
        }
        int sz=pq.size();
        for(int i2=sz-1;i2>=0;i2--){nnlist[city][i2]=pq.top().second;pq.pop();}
        if(sz<KNN) for(int i2=sz;i2<KNN;i2++) nnlist[city][i2]=nnlist[city][0];
    }
}

// Efficient 2-opt delta for reversing tour[i..j]
inline double twoOptDeltaFast(int i, int j){
    double oldE1 = (i%10==0 && !isp[tour[i-1]]) ? 1.1*distv(tour[i-1],tour[i]) : distv(tour[i-1],tour[i]);
    double newE1 = (i%10==0 && !isp[tour[i-1]]) ? 1.1*distv(tour[i-1],tour[j]) : distv(tour[i-1],tour[j]);
    double oldE2=0, newE2=0;
    if(j+1<=N){
        oldE2 = ((j+1)%10==0 && !isp[tour[j]]) ? 1.1*distv(tour[j],tour[j+1]) : distv(tour[j],tour[j+1]);
        newE2 = ((j+1)%10==0 && !isp[tour[i]]) ? 1.1*distv(tour[i],tour[j+1]) : distv(tour[i],tour[j+1]);
    }
    double delta = (newE1-oldE1) + (newE2-oldE2);
    int firstPen = ((i+1+9)/10)*10;
    for(int t=firstPen; t<=j; t+=10){
        int oldSrc = tour[t-1];
        int newSrc = tour[i+j-t+1];
        double oldPF = isp[oldSrc] ? 0.0 : 0.1;
        double newPF = isp[newSrc] ? 0.0 : 0.1;
        if(oldPF == 0.0 && newPF == 0.0) continue;
        double oldDist = distv(tour[t-1], tour[t]);
        double newDist = distv(tour[i+j-t+1], tour[i+j-t]);
        delta += newPF * newDist - oldPF * oldDist;
    }
    return delta;
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto T0=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-T0).count();};

    cin>>N;
    cx=new double[N]; cy=new double[N];
    for(int i=0;i<N;i++) cin>>cx[i]>>cy[i];
    sieve(N);
    tour=new int[N+1];
    pos=new int[N];

    if(N<=3){
        cout<<N+1<<"\n"<<0<<"\n";
        for(int i=1;i<N;i++) cout<<i<<"\n";
        cout<<0<<"\n";
        return 0;
    }

    constructNN();
    buildNN();

    double curCost=totalCost();
    double bestCost=curCost;
    int *bestTour=new int[N+1];
    memcpy(bestTour,tour,(N+1)*sizeof(int));
    for(int i=0;i<N;i++) pos[tour[i]]=i;

    RNG rng(42);
    double tl=1.78;
    double initTemp=curCost/(N*2.0);

    while(true){
        double t=elapsed();
        if(t>=tl)break;
        double prog=t/tl;
        double Temp=initTemp*pow(1e-4,prog);

        for(int b=0;b<3000;b++){
            int mv=rng.nextInt(100);

            if(mv<70){
                // NN-guided 2-opt with fast delta
                int city=rng.nextInt(N);
                int nbr=nnlist[city][rng.nextInt(KNN)];
                int pi2=pos[city],qi2=pos[nbr];
                if(pi2==qi2)continue;
                int i2,j2;
                if(pi2<qi2){i2=pi2+1;j2=qi2;} else {i2=qi2+1;j2=pi2;}
                if(i2<1||j2>=N||i2>=j2)continue;
                int segLen=j2-i2+1;
                if(segLen>5000)continue;

                double delta=twoOptDeltaFast(i2,j2);

                if(delta<0||rng.nextDouble()<exp(-delta/Temp)){
                    reverse(tour+i2,tour+j2+1);
                    for(int s=i2;s<=j2;s++) pos[tour[s]]=s;
                    curCost+=delta;
                    if(curCost<bestCost){bestCost=curCost;memcpy(bestTour,tour,(N+1)*sizeof(int));}
                }
            } else if(mv<85){
                // Random short 2-opt
                int i2=1+rng.nextInt(N-1);
                int len=2+rng.nextInt(min(20,N-2));
                int j2=i2+len-1;
                if(j2>=N)continue;

                double delta=twoOptDeltaFast(i2,j2);
                if(delta<0||rng.nextDouble()<exp(-delta/Temp)){
                    reverse(tour+i2,tour+j2+1);
                    for(int s=i2;s<=j2;s++) pos[tour[s]]=s;
                    curCost+=delta;
                    if(curCost<bestCost){bestCost=curCost;memcpy(bestTour,tour,(N+1)*sizeof(int));}
                }
            } else {
                // Or-opt: relocate single city
                int i2=1+rng.nextInt(N-1);
                int maxS=min(15,N/3);
                int shift=1+rng.nextInt(maxS);
                if(rng.nextInt(2))shift=-shift;
                int j;
                if(shift>0){j=i2+shift;if(j>=N)continue;}
                else{j=i2+shift;if(j<0)continue;}

                int lo=min(i2,j+1)-1,hi=max(i2,j)+1;
                if(lo<1)lo=1;if(hi>N)hi=N;
                double oldC=0;for(int s=lo;s<=hi;s++)oldC+=ec(s);

                int city=tour[i2];
                if(j>i2){memmove(tour+i2,tour+i2+1,(j-i2)*sizeof(int));tour[j]=city;}
                else{memmove(tour+j+2,tour+j+1,(i2-j-1)*sizeof(int));tour[j+1]=city;}
                int lo2=min(i2,j>i2?j:j+1),hi2=max(i2,j>i2?j:j+1);
                for(int s=lo2;s<=hi2;s++) pos[tour[s]]=s;

                double newC=0;for(int s=lo;s<=hi;s++)newC+=ec(s);
                double delta=newC-oldC;
                if(delta<0||rng.nextDouble()<exp(-delta/Temp)){
                    curCost+=delta;
                    if(curCost<bestCost){bestCost=curCost;memcpy(bestTour,tour,(N+1)*sizeof(int));}
                } else {
                    if(j>i2){int c=tour[j];memmove(tour+i2+1,tour+i2,(j-i2)*sizeof(int));tour[i2]=c;}
                    else{int c=tour[j+1];memmove(tour+j+1,tour+j+2,(i2-j-1)*sizeof(int));tour[i2]=c;}
                    for(int s=lo2;s<=hi2;s++) pos[tour[s]]=s;
                }
            }
        }
    }

    // Prime scheduling
    memcpy(tour,bestTour,(N+1)*sizeof(int));
    for(int pass=0;pass<2;pass++){
        for(int t=10;t<=N;t+=10){
            int pi=t-1;
            if(isp[tour[pi]])continue;
            double bestDelta2=0;int bestQi=-1;
            for(int off=1;off<=min(80,N/2);off++){
                for(int dir=-1;dir<=1;dir+=2){
                    int qi=pi+dir*off;
                    if(qi<1||qi>=N)continue;
                    if(!isp[tour[qi]])continue;
                    if((qi+1)%10==0)continue;
                    int lo2=min(pi,qi),hi2=max(pi,qi)+1;
                    if(hi2>N)hi2=N;
                    double oC=0;for(int s=lo2;s<=hi2;s++)oC+=ec(s);
                    swap(tour[pi],tour[qi]);
                    double nC=0;for(int s=lo2;s<=hi2;s++)nC+=ec(s);
                    double d2=nC-oC;
                    swap(tour[pi],tour[qi]);
                    if(d2<bestDelta2){bestDelta2=d2;bestQi=qi;}
                }
                if(bestQi!=-1&&off>5)break;
            }
            if(bestQi!=-1)swap(tour[pi],tour[bestQi]);
        }
    }
    double fc=totalCost();
    if(fc<bestCost){bestCost=fc;memcpy(bestTour,tour,(N+1)*sizeof(int));}

    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++)cout<<bestTour[i]<<"\n";
    return 0;
}
