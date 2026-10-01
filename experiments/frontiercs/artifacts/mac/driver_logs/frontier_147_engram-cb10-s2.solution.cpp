#include <bits/stdc++.h>
using namespace std;

static int N;
static int X[5001], Y[5001];
static long long R[5001];
static int A[5001], B[5001], C[5001], D[5001];

// Grid-based overlap detection
static const int G = 100; // grid cells per axis, each cell = 100x100
static vector<int> grid[G][G];

void gridClear(){
    for(int i=0;i<G;i++) for(int j=0;j<G;j++) grid[i][j].clear();
}

void gridAdd(int id){
    int gx1=A[id]/100, gy1=B[id]/100, gx2=(C[id]-1)/100, gy2=(D[id]-1)/100;
    gx1=max(0,min(G-1,gx1)); gy1=max(0,min(G-1,gy1));
    gx2=max(0,min(G-1,gx2)); gy2=max(0,min(G-1,gy2));
    for(int i=gx1;i<=gx2;i++) for(int j=gy1;j<=gy2;j++) grid[i][j].push_back(id);
}

void gridRemove(int id){
    int gx1=A[id]/100, gy1=B[id]/100, gx2=(C[id]-1)/100, gy2=(D[id]-1)/100;
    gx1=max(0,min(G-1,gx1)); gy1=max(0,min(G-1,gy1));
    gx2=max(0,min(G-1,gx2)); gy2=max(0,min(G-1,gy2));
    for(int i=gx1;i<=gx2;i++) for(int j=gy1;j<=gy2;j++){
        auto &v=grid[i][j];
        v.erase(remove(v.begin(),v.end(),id),v.end());
    }
}

bool overlaps(int i, int j){
    return A[i]<C[j]&&C[i]>A[j]&&B[i]<D[j]&&D[i]>B[j];
}

bool checkOverlap(int id){
    int gx1=A[id]/100, gy1=B[id]/100, gx2=(C[id]-1)/100, gy2=(D[id]-1)/100;
    gx1=max(0,min(G-1,gx1)); gy1=max(0,min(G-1,gy1));
    gx2=max(0,min(G-1,gx2)); gy2=max(0,min(G-1,gy2));
    for(int i=gx1;i<=gx2;i++) for(int j=gy1;j<=gy2;j++){
        for(int o:grid[i][j]) if(o!=id && overlaps(id,o)) return true;
    }
    return false;
}

long long area_i(int i){ return (long long)(C[i]-A[i])*(D[i]-B[i]); }

double score_i(int i){
    long long si=area_i(i);
    if(si<=0) return 0;
    double mn=min((double)R[i],(double)si);
    double mx=max((double)R[i],(double)si);
    double ratio=1.0-mn/mx;
    return 1.0-ratio*ratio;
}

struct Rect{int x1,y1,x2,y2;};

void partition(vector<int>&ids, Rect bound){
    if(ids.size()==1){
        int i=ids[0];
        A[i]=bound.x1;B[i]=bound.y1;C[i]=bound.x2;D[i]=bound.y2;
        return;
    }
    if(ids.empty()) return;
    
    int W=bound.x2-bound.x1, H=bound.y2-bound.y1;
    long long totalR=0;
    for(int i:ids) totalR+=R[i];
    
    double bestCost=1e18;
    int bestSplit=-1; bool bestHoriz=false;
    vector<int> bestLeft, bestRight;
    
    for(int horiz=0;horiz<2;horiz++){
        vector<int> si=ids;
        if(horiz) sort(si.begin(),si.end(),[](int a,int b){return Y[a]<Y[b];});
        else sort(si.begin(),si.end(),[](int a,int b){return X[a]<X[b];});
        
        long long cumR=0;
        for(int k=0;k<(int)si.size()-1;k++){
            cumR+=R[si[k]];
            double frac=(double)cumR/totalR;
            int lo,hi,splitPos;
            if(horiz){
                lo=Y[si[k]]+1; hi=Y[si[k+1]];
                if(lo>hi) continue;
                splitPos=bound.y1+(int)round(frac*H);
                splitPos=max(splitPos,lo); splitPos=min(splitPos,hi);
                if(splitPos<=bound.y1||splitPos>=bound.y2) continue;
            } else {
                lo=X[si[k]]+1; hi=X[si[k+1]];
                if(lo>hi) continue;
                splitPos=bound.x1+(int)round(frac*W);
                splitPos=max(splitPos,lo); splitPos=min(splitPos,hi);
                if(splitPos<=bound.x1||splitPos>=bound.x2) continue;
            }
            double actualFrac=horiz?(double)(splitPos-bound.y1)/H:(double)(splitPos-bound.x1)/W;
            double cost=(actualFrac-frac)*(actualFrac-frac);
            if(cost<bestCost){
                bestCost=cost; bestSplit=splitPos; bestHoriz=horiz;
                bestLeft.assign(si.begin(),si.begin()+k+1);
                bestRight.assign(si.begin()+k+1,si.end());
            }
        }
    }
    
    if(bestSplit<0){
        for(int i:ids){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
        return;
    }
    
    if(bestHoriz){
        partition(bestLeft,{bound.x1,bound.y1,bound.x2,bestSplit});
        partition(bestRight,{bound.x1,bestSplit,bound.x2,bound.y2});
    } else {
        partition(bestLeft,{bound.x1,bound.y1,bestSplit,bound.y2});
        partition(bestRight,{bestSplit,bound.y1,bound.x2,bound.y2});
    }
}

int main(){
    scanf("%d",&N);
    for(int i=0;i<N;i++) scanf("%d%d%lld",&X[i],&Y[i],&R[i]);
    
    vector<int> all(N); iota(all.begin(),all.end(),0);
    partition(all,{0,0,10000,10000});
    for(int i=0;i<N;i++) if(X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
    
    gridClear();
    for(int i=0;i<N;i++) gridAdd(i);
    
    auto start=chrono::steady_clock::now();
    auto el=[&](){return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    
    mt19937 rng(42);
    double T0=0.05,Tend=0.0001,tl=4.7;
    
    while(el()<tl){
        double f=el()/tl;
        double T=T0*pow(Tend/T0,f);
        int i=rng()%N;
        int dir=rng()%4;
        int oa=A[i],ob=B[i],oc=C[i],od=D[i];
        double oldS=score_i(i);
        
        bool expand=(rng()%2==0);
        if(expand){
            int maxD=max(1,(int)(200*(1.0-f*0.95)));
            int delta=1+rng()%maxD;
            if(dir==0) A[i]-=delta; else if(dir==1) B[i]-=delta;
            else if(dir==2) C[i]+=delta; else D[i]+=delta;
        } else {
            int maxShrink;
            if(dir==0) maxShrink=X[i]-A[i]; else if(dir==1) maxShrink=Y[i]-B[i];
            else if(dir==2) maxShrink=C[i]-X[i]-1; else maxShrink=D[i]-Y[i]-1;
            if(maxShrink<=0){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;}
            int maxD=max(1,(int)(maxShrink*(1.0-f*0.9)));
            int delta=1+rng()%maxD;
            if(dir==0) A[i]+=delta; else if(dir==1) B[i]+=delta;
            else if(dir==2) C[i]-=delta; else D[i]-=delta;
        }
        
        if(A[i]<0||B[i]<0||C[i]>10000||D[i]>10000||A[i]>=C[i]||B[i]>=D[i]||
           X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){
            A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;
        }
        
        if(expand && checkOverlap(i)){
            A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;
        }
        
        double newS=score_i(i);
        double diff=newS-oldS;
        if(diff>=0||(double)(rng()%10000)/10000.0<exp(diff/T)){
            if(expand){gridRemove(i);gridAdd(i);}
            else{gridRemove(i);gridAdd(i);}
        } else {
            A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
        }
    }
    
    for(int i=0;i<N;i++) printf("%d %d %d %d\n",A[i],B[i],C[i],D[i]);
}
