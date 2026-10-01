#include <bits/stdc++.h>
using namespace std;

int n;
int X[200], Y[200];
long long R[200];
int A[200], B[200], C[200], D[200];

bool overlaps(int i, int j){
    return A[i]<C[j]&&C[i]>A[j]&&B[i]<D[j]&&D[i]>B[j];
}

double score_i(int i){
    long long si=(long long)(C[i]-A[i])*(D[i]-B[i]);
    if(si<=0) return 0;
    if(X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]) return 0;
    double mn=min((double)R[i],(double)si);
    double mx=max((double)R[i],(double)si);
    double ratio=1.0-mn/mx;
    return 1.0-ratio*ratio;
}

double totalScore(){
    double s=0;
    for(int i=0;i<n;i++) s+=score_i(i);
    return s;
}

void doPartition(vector<int>& ids, int ax, int ay, int cx, int cy, bool horiz){
    if(ids.size()==1){
        int i=ids[0];
        A[i]=ax; B[i]=ay; C[i]=cx; D[i]=cy;
        return;
    }
    if(ids.empty()) return;
    if(cx-ax<=0||cy-ay<=0){
        for(int i:ids){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
        return;
    }
    
    long long totalR=0;
    for(int i:ids) totalR+=R[i];
    
    // Try splitting
    auto trySplit=[&](bool h) -> pair<double,tuple<int,int,vector<int>,vector<int>>>{
        vector<int> sorted_ids=ids;
        if(h) sort(sorted_ids.begin(),sorted_ids.end(),[](int a,int b){return X[a]<X[b];});
        else sort(sorted_ids.begin(),sorted_ids.end(),[](int a,int b){return Y[a]<Y[b];});
        
        double bestCost=1e18;
        int bestK=-1, bestSp=-1;
        long long cumR=0;
        
        for(int k=0;k<(int)sorted_ids.size()-1;k++){
            cumR+=R[sorted_ids[k]];
            double frac=(double)cumR/totalR;
            int lo,hi,span;
            if(h){lo=ax;span=cx-ax;
                int need_lo=X[sorted_ids[k]]+1;
                int need_hi=X[sorted_ids[k+1]];
                if(need_hi<need_lo) continue;
                int sp=lo+(int)round(frac*span);
                sp=max(sp,need_lo); sp=min(sp,need_hi);
                sp=max(sp,ax+1); sp=min(sp,cx-1);
                if(sp<=ax||sp>=cx) continue;
                double af=(double)(sp-ax)/span;
                double cost=abs(af-frac);
                if(cost<bestCost){bestCost=cost;bestK=k;bestSp=sp;}
            } else {lo=ay;span=cy-ay;
                int need_lo=Y[sorted_ids[k]]+1;
                int need_hi=Y[sorted_ids[k+1]];
                if(need_hi<need_lo) continue;
                int sp=lo+(int)round(frac*span);
                sp=max(sp,need_lo); sp=min(sp,need_hi);
                sp=max(sp,ay+1); sp=min(sp,cy-1);
                if(sp<=ay||sp>=cy) continue;
                double af=(double)(sp-ay)/span;
                double cost=abs(af-frac);
                if(cost<bestCost){bestCost=cost;bestK=k;bestSp=sp;}
            }
        }
        if(bestK<0){
            bestK=(int)sorted_ids.size()/2-1;
            if(bestK<0) bestK=0;
            if(h) bestSp=(ax+cx)/2; else bestSp=(ay+cy)/2;
            // clamp
            if(h){
                int mxL=X[sorted_ids[bestK]]+1;
                int mnR=X[sorted_ids[bestK+1]];
                bestSp=max(bestSp,mxL);bestSp=min(bestSp,mnR);
                bestSp=max(bestSp,ax+1);bestSp=min(bestSp,cx-1);
            } else {
                int mxL=Y[sorted_ids[bestK]]+1;
                int mnR=Y[sorted_ids[bestK+1]];
                bestSp=max(bestSp,mxL);bestSp=min(bestSp,mnR);
                bestSp=max(bestSp,ay+1);bestSp=min(bestSp,cy-1);
            }
        }
        vector<int> left(sorted_ids.begin(),sorted_ids.begin()+bestK+1);
        vector<int> right(sorted_ids.begin()+bestK+1,sorted_ids.end());
        return {bestCost,{bestSp,h?1:0,left,right}};
    };
    
    auto [c1,r1]=trySplit(true);
    auto [c2,r2]=trySplit(false);
    
    auto& [sp,dir,left,right] = (c1<=c2)?r1:r2;
    
    if(left.empty()||right.empty()){
        // fallback
        if(horiz) sort(ids.begin(),ids.end(),[](int a,int b){return X[a]<X[b];});
        else sort(ids.begin(),ids.end(),[](int a,int b){return Y[a]<Y[b];});
        int k=ids.size()/2;
        left.assign(ids.begin(),ids.begin()+k);
        right.assign(ids.begin()+k,ids.end());
        sp=horiz?(ax+cx)/2:(ay+cy)/2;
        dir=horiz?1:0;
    }
    
    if(dir==1){
        doPartition(left,ax,ay,sp,cy,!horiz);
        doPartition(right,sp,ay,cx,cy,!horiz);
    } else {
        doPartition(left,ax,ay,cx,sp,!horiz);
        doPartition(right,ax,sp,cx,cy,!horiz);
    }
}

int main(){
    scanf("%d",&n);
    for(int i=0;i<n;i++) scanf("%d%d%lld",&X[i],&Y[i],&R[i]);
    
    vector<int> ids(n); iota(ids.begin(),ids.end(),0);
    doPartition(ids,0,0,10000,10000,true);
    
    for(int i=0;i<n;i++){
        if(A[i]>=C[i]||B[i]>=D[i]||X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i])
            {A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
    }
    for(int i=0;i<n;i++) for(int j=i+1;j<n;j++)
        if(overlaps(i,j)){A[j]=X[j];B[j]=Y[j];C[j]=X[j]+1;D[j]=Y[j]+1;}
    
    mt19937 rng(42);
    auto st=chrono::steady_clock::now();
    double tl=4.5;
    
    for(int iter=0;;iter++){
        if((iter&511)==0){
            double el=chrono::duration<double>(chrono::steady_clock::now()-st).count();
            if(el>tl) break;
        }
        int i=rng()%n;
        int dir=rng()%4;
        double oldS=score_i(i);
        int oa=A[i],ob=B[i],oc=C[i],od=D[i];
        int mag=1+rng()%100;
        int delta=(rng()&1)?mag:-mag;
        if(dir==0)A[i]+=delta;else if(dir==1)B[i]+=delta;else if(dir==2)C[i]+=delta;else D[i]+=delta;
        
        A[i]=max(A[i],0);B[i]=max(B[i],0);C[i]=min(C[i],10000);D[i]=min(D[i],10000);
        
        bool ok=A[i]<C[i]&&B[i]<D[i]&&X[i]>=A[i]&&X[i]<C[i]&&Y[i]>=B[i]&&Y[i]<D[i];
        if(ok) for(int j=0;j<n&&ok;j++) if(j!=i) ok=!overlaps(i,j);
        if(ok){
            double nS=score_i(i);
            if(nS>=oldS){/*accept*/}
            else {A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;}
        } else {A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;}
    }
    
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",A[i],B[i],C[i],D[i]);
}
