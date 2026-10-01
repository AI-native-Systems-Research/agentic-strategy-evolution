#include<bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    
    int n; cin>>n;
    vector<int>x(n),y(n); vector<long long>r(n);
    for(int i=0;i<n;i++) cin>>x[i]>>y[i]>>r[i];
    
    vector<int>a(n),b(n),c(n),d(n);
    for(int i=0;i<n;i++){a[i]=x[i];b[i]=y[i];c[i]=x[i]+1;d[i]=y[i]+1;}
    
    const int GS=50, GN=10000/GS;
    vector<vector<int>>grid(GN*GN);
    
    auto addG=[&](int i){
        int gxs=a[i]/GS, gxe=min(GN-1,(c[i]-1)/GS);
        int gys=b[i]/GS, gye=min(GN-1,(d[i]-1)/GS);
        for(int gy=gys;gy<=gye;gy++)for(int gx=gxs;gx<=gxe;gx++)
            grid[gy*GN+gx].push_back(i);
    };
    auto remG=[&](int i){
        int gxs=a[i]/GS, gxe=min(GN-1,(c[i]-1)/GS);
        int gys=b[i]/GS, gye=min(GN-1,(d[i]-1)/GS);
        for(int gy=gys;gy<=gye;gy++)for(int gx=gxs;gx<=gxe;gx++){
            auto&v=grid[gy*GN+gx];
            for(int k=0;k<(int)v.size();k++) if(v[k]==i){v[k]=v.back();v.pop_back();break;}
        }
    };
    auto overlapsAny=[&](int i)->bool{
        int gxs=a[i]/GS, gxe=min(GN-1,(c[i]-1)/GS);
        int gys=b[i]/GS, gye=min(GN-1,(d[i]-1)/GS);
        for(int gy=gys;gy<=gye;gy++)for(int gx=gxs;gx<=gxe;gx++)
            for(int j:grid[gy*GN+gx])
                if(j!=i && a[i]<c[j] && c[i]>a[j] && b[i]<d[j] && d[i]>b[j]) return true;
        return false;
    };
    
    auto valid=[&](int i)->bool{
        return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]
            &&a[i]<=x[i]&&c[i]>x[i]&&b[i]<=y[i]&&d[i]>y[i];
    };
    auto area=[&](int i)->long long{return(long long)(c[i]-a[i])*(d[i]-b[i]);};
    auto sc=[&](int i)->double{
        long long s=area(i);
        if(!(a[i]<=x[i]&&c[i]>x[i]&&b[i]<=y[i]&&d[i]>y[i])) return 0.0;
        double rt=(double)min(r[i],s)/(double)max(r[i],s);
        double t=1.0-rt; return 1.0-t*t;
    };
    
    auto maxExpand=[&](int i, int side)->int{
        int lo=0, hi;
        if(side==0) hi=a[i]; else if(side==1) hi=b[i]; else if(side==2) hi=10000-c[i]; else hi=10000-d[i];
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        while(lo<hi){
            int mid=(lo+hi+1)/2;
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            if(side==0) a[i]=oa-mid; else if(side==1) b[i]=ob-mid; else if(side==2) c[i]=oc+mid; else d[i]=od+mid;
            if(a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&!overlapsAny(i)) lo=mid; else hi=mid-1;
        }
        a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
        return lo;
    };
    
    for(int i=0;i<n;i++) addG(i);
    
    // Greedy expansion
    for(int pass=0;pass<3000&&elapsed()<1.5;pass++){
        vector<int>ord(n); iota(ord.begin(),ord.end(),0);
        mt19937 rng2(pass*7+13);
        shuffle(ord.begin(),ord.end(),rng2);
        if(pass%3!=2) sort(ord.begin(),ord.end(),[&](int u,int v){return sc(u)<sc(v);});
        for(int i:ord){
            if(area(i)>=r[i]*2) continue;
            remG(i);
            for(int iter=0;iter<4;iter++){
                int bestS=-1,bestD=0; double bestI=-1e18;
                for(int s=0;s<4;s++){
                    int mx=maxExpand(i,s); if(mx<=0) continue;
                    long long curA=area(i),need=r[i]-curA; if(need<=0) continue;
                    int td;
                    if(s==0||s==2) td=min(mx,max(1,(int)((need+(d[i]-b[i])-1)/(d[i]-b[i]))));
                    else td=min(mx,max(1,(int)((need+(c[i]-a[i])-1)/(c[i]-a[i]))));
                    int oa=a[i],ob=b[i],oc=c[i],od=d[i]; double os=sc(i);
                    if(s==0)a[i]-=td;else if(s==1)b[i]-=td;else if(s==2)c[i]+=td;else d[i]+=td;
                    double ns=sc(i),imp=ns-os;
                    if(imp>bestI){bestI=imp;bestS=s;bestD=td;}
                    a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
                }
                if(bestS<0||bestI<1e-12) break;
                if(bestS==0)a[i]-=bestD;else if(bestS==1)b[i]-=bestD;else if(bestS==2)c[i]+=bestD;else d[i]+=bestD;
            }
            addG(i);
        }
    }
    
    // SA
    mt19937 rng(54321);
    double totScore=0; for(int i=0;i<n;i++) totScore+=sc(i);
    
    while(elapsed()<4.7){
        double frac=min(1.0,elapsed()/4.7);
        double T=0.08*(1.0-frac)+1e-9;
        int i=rng()%n;
        int side=rng()%4;
        int maxd_val=max(1,(int)(200*(1.0-frac))+1);
        int delta=(int)(rng()%(2*maxd_val+1))-maxd_val;
        if(!delta) continue;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        double os=sc(i);
        remG(i);
        if(side==0)a[i]+=delta;else if(side==1)b[i]+=delta;else if(side==2)c[i]+=delta;else d[i]+=delta;
        if(!valid(i)||overlapsAny(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);continue;}
        double ns=sc(i), diff=ns-os;
        double rr=(rng()%1000000)/1000000.0;
        if(diff>=0||rr<exp(diff/T)){
            addG(i);
            totScore+=diff;
        } else {
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);
        }
    }
    
    for(int i=0;i<n;i++) cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
