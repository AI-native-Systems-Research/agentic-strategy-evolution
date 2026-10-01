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
        long long s=area(i);double rat=(double)min(R[i],s)/(double)max(R[i],s);double t=1.0-rat;return 1.0-t*t;
    };
    auto valid=[&](int i)->bool{
        return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i];
    };
    auto overlaps=[&](int i,int j)->bool{
        return a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j];
    };
    
    // Grid-based spatial index
    const int G=50;
    const int CELL=10000/G;
    vector<vector<int>>grid(G*G);
    auto cellIdx=[&](int gx,int gy)->int{return gy*G+gx;};
    
    auto addToGrid=[&](int i){
        int gx0=a[i]/CELL, gy0=b[i]/CELL;
        int gx1=min(G-1,(c[i]-1)/CELL), gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)
            for(int gx=gx0;gx<=gx1;gx++)
                grid[cellIdx(gx,gy)].push_back(i);
    };
    auto removeFromGrid=[&](int i){
        int gx0=a[i]/CELL, gy0=b[i]/CELL;
        int gx1=min(G-1,(c[i]-1)/CELL), gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)
            for(int gx=gx0;gx<=gx1;gx++){
                auto &v=grid[cellIdx(gx,gy)];
                v.erase(find(v.begin(),v.end(),i));
            }
    };
    
    auto overlapsAnyGrid=[&](int i)->bool{
        int gx0=a[i]/CELL, gy0=b[i]/CELL;
        int gx1=min(G-1,(c[i]-1)/CELL), gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)
            for(int gx=gx0;gx<=gx1;gx++)
                for(int j:grid[cellIdx(gx,gy)])
                    if(j!=i&&overlaps(i,j))return true;
        return false;
    };
    
    auto getOverlappingGrid=[&](int i)->vector<int>{
        vector<int>res;
        int gx0=a[i]/CELL, gy0=b[i]/CELL;
        int gx1=min(G-1,(c[i]-1)/CELL), gy1=min(G-1,(d[i]-1)/CELL);
        for(int gy=gy0;gy<=gy1;gy++)
            for(int gx=gx0;gx<=gx1;gx++)
                for(int j:grid[cellIdx(gx,gy)])
                    if(j!=i&&overlaps(i,j))res.push_back(j);
        sort(res.begin(),res.end());
        res.erase(unique(res.begin(),res.end()),res.end());
        return res;
    };
    
    for(int i=0;i<n;i++) addToGrid(i);
    
    auto tryExpand=[&](int i, int dir, long long maxArea=-1){
        int lo=0,hi;
        if(dir==0)hi=a[i];else if(dir==1)hi=b[i];else if(dir==2)hi=10000-c[i];else hi=10000-d[i];
        if(hi<=0)return;
        if(maxArea>0){
            long long cur=area(i);
            if(cur>=maxArea)return;
            long long rem=maxArea-cur;
            int side=(dir<2)?(dir==0?(d[i]-b[i]):(c[i]-a[i])):(dir==2?(d[i]-b[i]):(c[i]-a[i]));
            if(side<=0)return;
            int maxExp=(int)(rem/side)+1;
            hi=min(hi,maxExp);
        }
        if(hi<=0)return;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        removeFromGrid(i);
        while(lo<hi){
            int mid=(lo+hi+1)/2;
            if(dir==0)a[i]=oa-mid;else if(dir==1)b[i]=ob-mid;else if(dir==2)c[i]=oc+mid;else d[i]=od+mid;
            if(valid(i)&&!overlapsAnyGrid(i))lo=mid;else hi=mid-1;
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
        }
        if(lo>0){if(dir==0)a[i]-=lo;else if(dir==1)b[i]-=lo;else if(dir==2)c[i]+=lo;else d[i]+=lo;}
        addToGrid(i);
    };
    
    mt19937 rng(42);
    vector<int>order(n);
    iota(order.begin(),order.end(),0);
    
    // Sort by R (smaller first) for initial expansion
    sort(order.begin(),order.end(),[&](int a,int b){return R[a]<R[b];});
    
    // Phase 1: Greedy expansion with area limit
    for(int pass=0;pass<300&&elapsed()<0.8;pass++){
        if(pass>5)shuffle(order.begin(),order.end(),rng);
        for(int idx=0;idx<n;idx++){
            int i=order[idx];
            int dirs[]={0,1,2,3};
            for(int k=3;k>0;k--){int j=rng()%(k+1);swap(dirs[k],dirs[j]);}
            for(int s=0;s<4;s++){
                long long maxA=(long long)(R[i]*1.2)+1;
                tryExpand(i,dirs[s],maxA);
            }
        }
    }
    
    // Phase 2: Expand underfilled
    for(int pass=0;pass<300&&elapsed()<1.5;pass++){
        shuffle(order.begin(),order.end(),rng);
        for(int idx=0;idx<n;idx++){
            int i=order[idx];
            if(area(i)>=R[i])continue;
            int dirs[]={0,1,2,3};
            for(int k=3;k>0;k--){int j=rng()%(k+1);swap(dirs[k],dirs[j]);}
            for(int s=0;s<4;s++) tryExpand(i,dirs[s]);
        }
    }
    
    // Shrink overfilled
    for(int i=0;i<n;i++){
        if(area(i)<=R[i])continue;
        double curS=sat(i);
        for(int dir=0;dir<4;dir++){
            int hi;
            if(dir==0)hi=X[i]-a[i];else if(dir==1)hi=Y[i]-b[i];else if(dir==2)hi=c[i]-(X[i]+1);else hi=d[i]-(Y[i]+1);
            int oa=a[i],ob=b[i],oc=c[i],od=d[i];
            removeFromGrid(i);
            int best=0;double bs=curS;
            for(int amt=1;amt<=hi;amt++){
                if(dir==0)a[i]=oa+amt;else if(dir==1)b[i]=ob+amt;else if(dir==2)c[i]=oc-amt;else d[i]=od-amt;
                double ns=sat(i);if(ns>bs){bs=ns;best=amt;}
                if(area(i)<=R[i])break;
            }
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            if(best>0){if(dir==0)a[i]+=best;else if(dir==1)b[i]+=best;else if(dir==2)c[i]-=best;else d[i]-=best;curS=bs;}
            addToGrid(i);
        }
    }
    
    double curScore=0;for(int i=0;i<n;i++)curScore+=sat(i);
    auto ba=a,bb=b,bc=c,bd=d;double bestScore=curScore;
    
    // SA phase
    while(elapsed()<4.7){
        double frac=elapsed()/4.7;
        double T=0.05*(1.0-frac)+0.0001;
        int i=rng()%n;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        double os=sat(i);
        removeFromGrid(i);
        
        int op=rng()%10;
        int maxd_=max(1,(int)(300*(1.0-frac))+1);
        int delta=((int)(rng()%(2*maxd_))+1)-maxd_;
        if(!delta)delta=1;
        
        if(op<4){if(op==0)a[i]+=delta;else if(op==1)b[i]+=delta;else if(op==2)c[i]+=delta;else d[i]+=delta;}
        else if(op<6){if(op==4){a[i]+=delta;c[i]+=delta;}else{b[i]+=delta;d[i]+=delta;}}
        else{
            long long cur=area(i);
            int dir2=rng()%4;
            int side=(dir2<2)?(dir2==0?(d[i]-b[i]):(c[i]-a[i])):(dir2==2?(d[i]-b[i]):(c[i]-a[i]));
            if(side>0){
                int adj=(int)((cur-(long long)R[i])/side);
                if(adj==0)adj=(cur>R[i])?1:-1;
                if(dir2==0)a[i]+=adj;else if(dir2==1)b[i]+=adj;else if(dir2==2)c[i]-=adj;else d[i]-=adj;
            }
        }
        
        if(!valid(i)||overlapsAnyGrid(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addToGrid(i);continue;}
        double ns=sat(i),diff=ns-os;
        if(diff>=0||(rng()%1000000)<(int)(1000000*exp(diff/T))){
            addToGrid(i);
            curScore+=diff;
            if(curScore>bestScore){bestScore=curScore;ba=a;bb=b;bc=c;bd=d;}
        }else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addToGrid(i);}
    }
    
    for(int i=0;i<n;i++)cout<<ba[i]<<" "<<bb[i]<<" "<<bc[i]<<" "<<bd[i]<<"\n";
}
