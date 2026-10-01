#include<bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    
    int n; cin>>n;
    vector<int>X(n),Y(n); vector<long long>R(n);
    for(int i=0;i<n;i++) cin>>X[i]>>Y[i]>>R[i];
    
    vector<int>a(n),b(n),c(n),d(n);
    for(int i=0;i<n;i++){a[i]=X[i];b[i]=Y[i];c[i]=X[i]+1;d[i]=Y[i]+1;}
    
    auto area=[&](int i)->long long{return(long long)(c[i]-a[i])*(d[i]-b[i]);};
    auto sat=[&](int i)->double{
        if(!(a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i]))return 0.0;
        long long s=area(i);
        double rat=(double)min(R[i],s)/(double)max(R[i],s);
        double t=1.0-rat; return 1.0-t*t;
    };
    auto valid=[&](int i)->bool{
        return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]
               &&a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i];
    };
    auto ov=[&](int i,int j)->bool{
        return a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j];
    };
    
    const int G=50,CELL=200;
    vector<vector<int>>grid(G*G);
    auto ci=[&](int gx,int gy)->int{return gy*G+gx;};
    auto addG=[&](int i){
        int gx0=max(0,a[i]/CELL),gy0=max(0,b[i]/CELL);
        int gx1=min(G-1,(c[i]-1)/CELL),gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)for(int gx=gx0;gx<=gx1;gx++)grid[ci(gx,gy)].push_back(i);
    };
    auto rmG=[&](int i){
        int gx0=max(0,a[i]/CELL),gy0=max(0,b[i]/CELL);
        int gx1=min(G-1,(c[i]-1)/CELL),gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)for(int gx=gx0;gx<=gx1;gx++){
            auto&v=grid[ci(gx,gy)];
            auto it=find(v.begin(),v.end(),i);if(it!=v.end()){swap(*it,v.back());v.pop_back();}
        }
    };
    auto ovAny=[&](int i)->bool{
        int gx0=max(0,a[i]/CELL),gy0=max(0,b[i]/CELL);
        int gx1=min(G-1,(c[i]-1)/CELL),gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)for(int gx=gx0;gx<=gx1;gx++)
            for(int j:grid[ci(gx,gy)])if(j!=i&&ov(i,j))return true;
        return false;
    };
    
    // Find max expansion in a direction without overlap
    auto maxExp=[&](int i,int dir)->int{
        int hi;
        if(dir==0)hi=a[i];else if(dir==1)hi=b[i];else if(dir==2)hi=10000-c[i];else hi=10000-d[i];
        if(hi<=0)return 0;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        int lo=0;
        while(lo<hi){
            int mid=(lo+hi+1)/2;
            if(dir==0)a[i]=oa-mid;else if(dir==1)b[i]=ob-mid;else if(dir==2)c[i]=oc+mid;else d[i]=od+mid;
            if(valid(i)&&!ovAny(i))lo=mid;else hi=mid-1;
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
        }
        return lo;
    };
    
    auto tryExp=[&](int i,int dir,long long maxA=-1){
        int hi;
        if(dir==0)hi=a[i];else if(dir==1)hi=b[i];else if(dir==2)hi=10000-c[i];else hi=10000-d[i];
        if(hi<=0)return;
        if(maxA>0){
            long long cu=area(i);if(cu>=maxA)return;
            int sd=(dir%2==0)?(d[i]-b[i]):(c[i]-a[i]);
            if(sd<=0)return;
            hi=min(hi,(int)((maxA-cu+sd-1)/sd));
        }
        if(hi<=0)return;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        rmG(i);int lo=0;
        while(lo<hi){
            int mid=(lo+hi+1)/2;
            if(dir==0)a[i]=oa-mid;else if(dir==1)b[i]=ob-mid;else if(dir==2)c[i]=oc+mid;else d[i]=od+mid;
            if(valid(i)&&!ovAny(i))lo=mid;else hi=mid-1;
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
        }
        if(lo>0){if(dir==0)a[i]-=lo;else if(dir==1)b[i]-=lo;else if(dir==2)c[i]+=lo;else d[i]+=lo;}
        addG(i);
    };
    
    // Try to expand to target area, balancing directions
    auto expandBalanced=[&](int i,long long target){
        for(int iter=0;iter<8;iter++){
            long long cur=area(i);
            if(cur>=target)break;
            // Try all 4 dirs, pick the one that gets closest to target without exceeding
            int bestDir=-1; double bestSat=-1;
            int oa=a[i],ob=b[i],oc=c[i],od=d[i];
            rmG(i);
            for(int dir=0;dir<4;dir++){
                int mx=maxExp(i,dir);
                if(mx<=0)continue;
                // compute how much we need
                int sd=(dir%2==0)?(d[i]-b[i]):(c[i]-a[i]);
                if(sd<=0)continue;
                long long need=target-cur;
                int want=min(mx,(int)((need+sd-1)/sd));
                if(want<=0)continue;
                if(dir==0)a[i]=oa-want;else if(dir==1)b[i]=ob-want;else if(dir==2)c[i]=oc+want;else d[i]=od+want;
                double s=sat(i);
                if(s>bestSat){bestSat=s;bestDir=dir;}
                a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            }
            addG(i);
            if(bestDir>=0){
                long long cur2=area(i);
                int sd=(bestDir%2==0)?(d[i]-b[i]):(c[i]-a[i]);
                long long need=target-cur2;
                if(sd>0&&need>0){
                    int want=(int)((need+sd-1)/sd);
                    tryExp(i,bestDir,(long long)(target*1.05)+1);
                }
            }
        }
    };
    
    mt19937 rng(42);
    for(int i=0;i<n;i++)addG(i);
    vector<int>ord(n);iota(ord.begin(),ord.end(),0);
    
    // Phase 1: expand with cap, sorted by area (small first)
    sort(ord.begin(),ord.end(),[&](int a,int b){return R[a]<R[b];});
    for(int pass=0;pass<200&&elapsed()<0.5;pass++){
        if(pass>0)shuffle(ord.begin(),ord.end(),rng);
        for(int i:ord){
            long long cap=(long long)(R[i]*1.05)+1;
            int ds[]={0,1,2,3};for(int k=3;k>0;k--){int j=rng()%(k+1);swap(ds[k],ds[j]);}
            for(int s=0;s<4;s++)tryExp(i,ds[s],cap);
        }
    }
    
    // Phase 2: expand undersized without cap
    for(int pass=0;pass<400&&elapsed()<1.2;pass++){
        shuffle(ord.begin(),ord.end(),rng);
        bool any=false;
        for(int i:ord){
            if(area(i)>=R[i])continue;
            any=true;
            int ds[]={0,1,2,3};for(int k=3;k>0;k--){int j=rng()%(k+1);swap(ds[k],ds[j]);}
            for(int s=0;s<4;s++)tryExp(i,ds[s]);
        }
        if(!any)break;
    }
    
    // Phase 3: shrink oversized, then re-expand undersized
    for(int iter=0;iter<30&&elapsed()<3.5;iter++){
        // Shrink oversized rectangles
        for(int i=0;i<n;i++){
            long long cur=area(i);
            if(cur<=R[i])continue;
            // Try shrinking each side
            for(int dir=0;dir<4;dir++){
                int hi;
                if(dir==0)hi=X[i]-a[i];
                else if(dir==1)hi=Y[i]-b[i];
                else if(dir==2)hi=c[i]-(X[i]+1);
                else hi=d[i]-(Y[i]+1);
                if(hi<=0)continue;
                
                rmG(i);
                double bs=sat(i);int best=0;
                int oa=a[i],ob=b[i],oc=c[i],od=d[i];
                for(int amt=1;amt<=hi;amt++){
                    if(dir==0)a[i]=oa+amt;else if(dir==1)b[i]=ob+amt;
                    else if(dir==2)c[i]=oc-amt;else d[i]=od-amt;
                    double ns2=sat(i);
                    if(ns2>=bs-1e-9){bs=ns2;best=amt;}
                    if(area(i)<=R[i])break;
                }
                a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                if(best>0){
                    if(dir==0)a[i]+=best;else if(dir==1)b[i]+=best;
                    else if(dir==2)c[i]-=best;else d[i]-=best;
                }
                addG(i);
            }
        }
        // Re-expand undersized
        for(int pass=0;pass<200&&elapsed()<3.5;pass++){
            shuffle(ord.begin(),ord.end(),rng);
            bool any=false;
            for(int i:ord){
                if(area(i)>=R[i])continue;
                any=true;
                int ds[]={0,1,2,3};for(int k=3;k>0;k--){int j=rng()%(k+1);swap(ds[k],ds[j]);}
                for(int s=0;s<4;s++)tryExp(i,ds[s]);
            }
            if(!any)break;
        }
    }
    
    auto ba=a,bb=b,bc=c,bd=d;
    double bestScore=0;for(int i=0;i<n;i++)bestScore+=sat(i);
    double curScore=bestScore;
    
    // SA phase
    while(elapsed()<4.85){
        double frac=min(1.0,(elapsed()-3.5)/1.35);
        if(frac<0)frac=0;
        double T=0.05*(1.0-frac)+0.0001;
        int i=rng()%n;int oa=a[i],ob=b[i],oc=c[i],od=d[i];double os=sat(i);
        rmG(i);
        int maxd_=max(1,(int)(200*(1.0-frac))+1);
        int delta=((int)(rng()%(2*maxd_+1)))-maxd_;if(!delta)delta=1;
        int op=rng()%8;
        if(op<4){if(op==0)a[i]+=delta;else if(op==1)b[i]+=delta;else if(op==2)c[i]+=delta;else d[i]+=delta;}
        else if(op<6){if(op==4){a[i]+=delta;c[i]+=delta;}else{b[i]+=delta;d[i]+=delta;}}
        else{if(op==6){a[i]-=delta;c[i]+=delta;}else{b[i]-=delta;d[i]+=delta;}}
        if(!valid(i)||ovAny(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);continue;}
        double ns=sat(i),diff=ns-os;
        if(diff>=0||((double)(rng()%1000000)/1000000.0)<exp(diff/T)){
            addG(i);curScore+=diff;
            if(curScore>bestScore){bestScore=curScore;ba=a;bb=b;bc=c;bd=d;}
        }else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);}
    }
    for(int i=0;i<n;i++)
        cout<<ba[i]<<" "<<bb[i]<<" "<<bc[i]<<" "<<bd[i]<<"\n";
}
