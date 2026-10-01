#include <bits/stdc++.h>
using namespace std;

int N;
int X[5001],Y[5001];
long long R[5001];
int A[5001],B[5001],C[5001],D[5001];

static const int GS=100;
static vector<int> grid[GS][GS];
int cellSz;

void initGrid(){cellSz=max(1,(10000+GS-1)/GS);for(int i=0;i<GS;i++)for(int j=0;j<GS;j++)grid[i][j].clear();}

inline void gridAdd(int id){
    int gx1=A[id]/cellSz,gy1=B[id]/cellSz,gx2=(C[id]-1)/cellSz,gy2=(D[id]-1)/cellSz;
    gx1=max(0,min(GS-1,gx1));gy1=max(0,min(GS-1,gy1));gx2=max(0,min(GS-1,gx2));gy2=max(0,min(GS-1,gy2));
    for(int i=gx1;i<=gx2;i++)for(int j=gy1;j<=gy2;j++)grid[i][j].push_back(id);
}
inline void gridRemove(int id){
    int gx1=A[id]/cellSz,gy1=B[id]/cellSz,gx2=(C[id]-1)/cellSz,gy2=(D[id]-1)/cellSz;
    gx1=max(0,min(GS-1,gx1));gy1=max(0,min(GS-1,gy1));gx2=max(0,min(GS-1,gx2));gy2=max(0,min(GS-1,gy2));
    for(int i=gx1;i<=gx2;i++)for(int j=gy1;j<=gy2;j++){auto&v=grid[i][j];for(int k=0;k<(int)v.size();k++)if(v[k]==id){v[k]=v.back();v.pop_back();break;}}
}

inline bool overlaps(int i,int j){return A[i]<C[j]&&C[i]>A[j]&&B[i]<D[j]&&D[i]>B[j];}

bool hasOverlap(int id){
    int gx1=A[id]/cellSz,gy1=B[id]/cellSz,gx2=(C[id]-1)/cellSz,gy2=(D[id]-1)/cellSz;
    gx1=max(0,min(GS-1,gx1));gy1=max(0,min(GS-1,gy1));gx2=max(0,min(GS-1,gx2));gy2=max(0,min(GS-1,gy2));
    for(int i=gx1;i<=gx2;i++)for(int j=gy1;j<=gy2;j++)for(int o:grid[i][j])if(o!=id&&overlaps(id,o))return true;
    return false;
}

// Find max expansion in direction dir without overlap
// dir: 0=left(A--), 1=down(B--), 2=right(C++), 3=up(D++)
int maxExpand(int id, int dir, int limit){
    int oa=A[id],ob=B[id],oc=C[id],od=D[id];
    int lo=0,hi=limit,best=0;
    while(lo<=hi){
        int mid=(lo+hi)/2;
        if(dir==0) A[id]=oa-mid;
        else if(dir==1) B[id]=ob-mid;
        else if(dir==2) C[id]=oc+mid;
        else D[id]=od+mid;
        if(!hasOverlap(id)){best=mid;lo=mid+1;}else hi=mid-1;
        A[id]=oa;B[id]=ob;C[id]=oc;D[id]=od;
    }
    return best;
}

double score_i(int i){
    long long si=(long long)(C[i]-A[i])*(D[i]-B[i]);
    if(si<=0)return 0;
    double mn=min((double)R[i],(double)si),mx=max((double)R[i],(double)si);
    double r=1.0-mn/mx;return 1.0-r*r;
}

struct Rect{int x1,y1,x2,y2;};

void partition(vector<int>&ids,Rect b){
    if(ids.size()==1){int i=ids[0];A[i]=b.x1;B[i]=b.y1;C[i]=b.x2;D[i]=b.y2;return;}
    if(ids.empty())return;
    int W=b.x2-b.x1,H=b.y2-b.y1;
    if(W<=0||H<=0){for(int i:ids){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}return;}
    long long totR=0;for(int i:ids)totR+=R[i];
    double bestCost=1e18;int bestSplit=-1;bool bestH=false;
    vector<int>bestL,bestR2;
    for(int h=0;h<2;h++){
        vector<int>si=ids;
        if(h)sort(si.begin(),si.end(),[](int a,int b){return Y[a]<Y[b];});
        else sort(si.begin(),si.end(),[](int a,int b){return X[a]<X[b];});
        long long cum=0;
        for(int k=0;k<(int)si.size()-1;k++){
            cum+=R[si[k]];double frac=(double)cum/totR;
            int lo2,hi2,sp;
            if(h){lo2=Y[si[k]]+1;hi2=Y[si[k+1]];if(lo2>hi2)continue;sp=b.y1+(int)round(frac*H);sp=max(sp,lo2);sp=min(sp,hi2);if(sp<=b.y1||sp>=b.y2)continue;}
            else{lo2=X[si[k]]+1;hi2=X[si[k+1]];if(lo2>hi2)continue;sp=b.x1+(int)round(frac*W);sp=max(sp,lo2);sp=min(sp,hi2);if(sp<=b.x1||sp>=b.x2)continue;}
            double af=h?(double)(sp-b.y1)/H:(double)(sp-b.x1)/W;
            double c=(af-frac)*(af-frac);
            if(c<bestCost){bestCost=c;bestSplit=sp;bestH=h;bestL.assign(si.begin(),si.begin()+k+1);bestR2.assign(si.begin()+k+1,si.end());}
        }
    }
    if(bestSplit<0){for(int i:ids){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}return;}
    if(bestH){partition(bestL,{b.x1,b.y1,b.x2,bestSplit});partition(bestR2,{b.x1,bestSplit,b.x2,b.y2});}
    else{partition(bestL,{b.x1,b.y1,bestSplit,b.y2});partition(bestR2,{bestSplit,b.y1,b.x2,b.y2});}
}

int main(){
    scanf("%d",&N);
    for(int i=0;i<N;i++)scanf("%d%d%lld",&X[i],&Y[i],&R[i]);
    vector<int>all(N);iota(all.begin(),all.end(),0);
    partition(all,{0,0,10000,10000});
    for(int i=0;i<N;i++){if(X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}}
    // Shrink oversized
    for(int i=0;i<N;i++){
        long long t=R[i];long long cur=(long long)(C[i]-A[i])*(D[i]-B[i]);
        if(cur<=t)continue;
        for(int it=0;it<40;it++){cur=(long long)(C[i]-A[i])*(D[i]-B[i]);if(cur<=t)break;
            int sl[4]={X[i]-A[i],Y[i]-B[i],C[i]-X[i]-1,D[i]-Y[i]-1};int b=-1,bs=0;
            for(int d=0;d<4;d++)if(sl[d]>bs){bs=sl[d];b=d;}if(b<0)break;
            int w=C[i]-A[i],h=D[i]-B[i];double r=(double)t/cur;
            int sh=max(1,(int)((1.0-r)*(b<2?(b==0?w:h):(b==2?w:h))));sh=min(sh,sl[b]);
            if(b==0)A[i]+=sh;else if(b==1)B[i]+=sh;else if(b==2)C[i]-=sh;else D[i]-=sh;}
    }
    initGrid();for(int i=0;i<N;i++)gridAdd(i);
    auto st=chrono::steady_clock::now();
    auto el=[&](){return chrono::duration<double>(chrono::steady_clock::now()-st).count();};
    mt19937 rng(42);
    double tl=4.5;
    while(el()<tl){
        double t=el(),f=t/tl;double T=0.05*pow(0.0001/0.05,f);
        int i=rng()%N;int oa=A[i],ob=B[i],oc=C[i],od=D[i];double os=score_i(i);
        int mt2=rng()%10;
        if(mt2<5){int d=rng()%4;int mx=max(1,(int)(500*(1.0-f*0.8)));int delta=1+rng()%mx;
            if(d==0)A[i]-=delta;else if(d==1)B[i]-=delta;else if(d==2)C[i]+=delta;else D[i]+=delta;
        }else if(mt2<8){int d=rng()%4;int sl[4]={X[i]-A[i],Y[i]-B[i],C[i]-X[i]-1,D[i]-Y[i]-1};if(sl[d]<=0)continue;
            int delta=1+rng()%sl[d];if(d==0)A[i]+=delta;else if(d==1)B[i]+=delta;else if(d==2)C[i]-=delta;else D[i]-=delta;
        }else{long long t2=R[i];int w=(int)sqrt((double)t2);w=max(w,1);int h2=(int)(t2/w);h2=max(h2,1);
            A[i]=max(0,X[i]-w/2);B[i]=max(0,Y[i]-h2/2);C[i]=min(10000,A[i]+w);D[i]=min(10000,B[i]+h2);
            if(X[i]>=C[i])C[i]=X[i]+1;if(X[i]<A[i])A[i]=X[i];if(Y[i]>=D[i])D[i]=Y[i]+1;if(Y[i]<B[i])B[i]=Y[i];}
        A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
        if(A[i]>=C[i]||B[i]>=D[i]||X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;}
        gridRemove(i);
        if(hasOverlap(i)){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;gridAdd(i);continue;}
        double ns=score_i(i),diff=ns-os;
        if(diff>=0||(double)(rng()%10000)/10000.0<exp(diff/T)){gridAdd(i);}
        else{A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;gridAdd(i);}
    }
    for(int i=0;i<N;i++)printf("%d %d %d %d\n",A[i],B[i],C[i],D[i]);
}
