#include<bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    int n;cin>>n;
    vector<int>x(n),y(n);vector<long long>r(n);
    for(int i=0;i<n;i++)cin>>x[i]>>y[i]>>r[i];
    vector<int>a(n),b(n),c(n),d(n);
    // Initialize with 1x1 around desired point
    for(int i=0;i<n;i++){a[i]=x[i];b[i]=y[i];c[i]=x[i]+1;d[i]=y[i]+1;}
    const int GS=50,GN=200;
    vector<vector<int>>grid(GN*GN);
    auto addG=[&](int i){for(int gy=b[i]/GS,gye=min(GN-1,(d[i]-1)/GS);gy<=gye;gy++)for(int gx=a[i]/GS,gxe=min(GN-1,(c[i]-1)/GS);gx<=gxe;gx++)grid[gy*GN+gx].push_back(i);};
    auto remG=[&](int i){for(int gy=b[i]/GS,gye=min(GN-1,(d[i]-1)/GS);gy<=gye;gy++)for(int gx=a[i]/GS,gxe=min(GN-1,(c[i]-1)/GS);gx<=gxe;gx++){auto&v=grid[gy*GN+gx];for(int k=0;k<(int)v.size();k++)if(v[k]==i){v[k]=v.back();v.pop_back();break;}}};
    auto overlaps=[&](int i)->bool{for(int gy=b[i]/GS,gye=min(GN-1,(d[i]-1)/GS);gy<=gye;gy++)for(int gx=a[i]/GS,gxe=min(GN-1,(c[i]-1)/GS);gx<=gxe;gx++)for(int j:grid[gy*GN+gx])if(j!=i&&a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j])return true;return false;};
    auto valid=[&](int i)->bool{return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&a[i]<=x[i]&&c[i]>x[i]&&b[i]<=y[i]&&d[i]>y[i];};
    auto area=[&](int i)->long long{return(long long)(c[i]-a[i])*(d[i]-b[i]);};
    auto sc=[&](int i)->double{long long s=area(i);double rt=(double)min(r[i],s)/(double)max(r[i],s);double t=1.0-rt;return 1.0-t*t;};
    for(int i=0;i<n;i++)addG(i);
    for(int pass=0;pass<3000&&elapsed()<2.5;pass++){
        vector<int>ord(n);iota(ord.begin(),ord.end(),0);
        mt19937 rng(pass*7+13);shuffle(ord.begin(),ord.end(),rng);
        if(pass%3!=2)sort(ord.begin(),ord.end(),[&](int u,int v){return sc(u)<sc(v);});
        for(int i:ord)for(int s=0;s<4;s++){
            if(area(i)>=r[i]*2&&(s<2?true:true)&&area(i)>r[i])continue;
            remG(i);int oa=a[i],ob=b[i],oc=c[i],od=d[i];
            int hi=(s==0?a[i]:s==1?b[i]:s==2?10000-c[i]:10000-d[i]),lo=0;
            while(lo<hi){int mid=(lo+hi+1)/2;a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;if(s==0)a[i]-=mid;else if(s==1)b[i]-=mid;else if(s==2)c[i]+=mid;else d[i]+=mid;if(valid(i)&&!overlaps(i))lo=mid;else hi=mid-1;}
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;if(lo>0){if(s==0)a[i]-=lo;else if(s==1)b[i]-=lo;else if(s==2)c[i]+=lo;else d[i]+=lo;if(sc(i)<sc(i)-1e-12){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}}
            addG(i);
        }
    }
    mt19937 rng(54321);
    while(elapsed()<4.5){
        double frac=elapsed()/4.6;double T=0.03*(1.0-frac)+1e-10;
        int i=rng()%n;int side=rng()%4;
        int maxd=max(1,(int)(500*(1.0-frac)));
        int delta=(int)(rng()%(2*maxd+1))-maxd;if(!delta)continue;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];double os=sc(i);
        remG(i);
        if(side==0)a[i]+=delta;else if(side==1)b[i]+=delta;else if(side==2)c[i]+=delta;else d[i]+=delta;
        if(!valid(i)||overlaps(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);continue;}
        double ns=sc(i);double diff=ns-os;
        if(diff>=0||((double)(rng()%1000000)/1000000.0)<exp(diff/T)){addG(i);}
        else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);}
    }
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
