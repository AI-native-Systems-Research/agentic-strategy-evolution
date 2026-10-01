#include<bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    int n;cin>>n;
    vector<int>X(n),Y(n);vector<long long>R(n);
    for(int i=0;i<n;i++)cin>>X[i]>>Y[i]>>R[i];
    vector<int>a(n),b(n),c(n),d(n);
    // Initial: 1x1 at desired point
    for(int i=0;i<n;i++){a[i]=X[i];b[i]=Y[i];c[i]=X[i]+1;d[i]=Y[i]+1;}
    const int GS=10,GN=10000/GS;
    vector<vector<int>>grid(GN*GN);
    auto addG=[&](int i){int gxs=a[i]/GS,gxe=min(GN-1,(c[i]-1)/GS),gys=b[i]/GS,gye=min(GN-1,(d[i]-1)/GS);for(int gy=gys;gy<=gye;gy++)for(int gx=gxs;gx<=gxe;gx++)grid[gy*GN+gx].push_back(i);};
    auto remG=[&](int i){int gxs=a[i]/GS,gxe=min(GN-1,(c[i]-1)/GS),gys=b[i]/GS,gye=min(GN-1,(d[i]-1)/GS);for(int gy=gys;gy<=gye;gy++)for(int gx=gxs;gx<=gxe;gx++){auto&v=grid[gy*GN+gx];for(int k=(int)v.size()-1;k>=0;k--)if(v[k]==i){v[k]=v.back();v.pop_back();break;}}};
    auto overlapsI=[&](int i)->bool{int gxs=a[i]/GS,gxe=min(GN-1,(c[i]-1)/GS),gys=b[i]/GS,gye=min(GN-1,(d[i]-1)/GS);for(int gy=gys;gy<=gye;gy++)for(int gx=gxs;gx<=gxe;gx++)for(int j:grid[gy*GN+gx])if(j!=i&&a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j])return true;return false;};
    auto valid=[&](int i)->bool{return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i];};
    auto area=[&](int i)->long long{return(long long)(c[i]-a[i])*(d[i]-b[i]);};
    auto sc=[&](int i)->double{long long s=area(i);double rt=(double)min(R[i],s)/(double)max(R[i],s);double t=1.0-rt;return 1.0-t*t;};
    for(int i=0;i<n;i++)addG(i);
    mt19937 rng(42);
    // Greedy expansion
    for(int pass=0;pass<5000&&elapsed()<2.0;pass++){vector<int>ord(n);iota(ord.begin(),ord.end(),0);shuffle(ord.begin(),ord.end(),rng);for(int i:ord){remG(i);for(int it=0;it<20;it++){int bs=-1,bd=0;double bi=-1e18;for(int s=0;s<4;s++){int mx;if(s==0)mx=a[i];else if(s==1)mx=b[i];else if(s==2)mx=10000-c[i];else mx=10000-d[i];if(mx<=0)continue;long long ca=area(i);int w=c[i]-a[i],h=d[i]-b[i];long long need=R[i]-ca;int td=1;if(need>0){if(s<2)td=min(mx,(int)min((long long)mx,s==0?(need+h-1)/h:(need+w-1)/w));else td=min(mx,(int)min((long long)mx,s==2?(need+h-1)/h:(need+w-1)/w));}td=max(1,min(td,mx));int oa=a[i],ob=b[i],oc=c[i],od=d[i];if(s==0)a[i]-=td;else if(s==1)b[i]-=td;else if(s==2)c[i]+=td;else d[i]+=td;double ns=valid(i)&&!overlapsI(i)?sc(i):-1e18;double cs=sc(i);a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;double imp=ns-sc(i);if(imp>bi){bi=imp;bs=s;bd=td;}}if(bs<0||bi<1e-12)break;if(bs==0)a[i]-=bd;else if(bs==1)b[i]-=bd;else if(bs==2)c[i]+=bd;else d[i]+=bd;}addG(i);}}
    // SA
    while(elapsed()<4.7){double frac=min(1.0,elapsed()/4.7);double T=0.05*(1.0-frac)+1e-8;int i=rng()%n;int side=rng()%4;long long ca=area(i);int maxd=max(1,(int)(300*(1.0-frac))+1);int delta;bool big=ca>R[i];if(big&&(rng()%4)<3){if(side==0){int mx=X[i]-a[i];if(mx<1)continue;delta=1+(rng()%min(maxd,mx));}else if(side==1){int mx=Y[i]-b[i];if(mx<1)continue;delta=1+(rng()%min(maxd,mx));}else if(side==2){int mx=c[i]-X[i]-1;if(mx<1)continue;delta=-(1+(int)(rng()%min(maxd,mx)));}else{int mx=d[i]-Y[i]-1;if(mx<1)continue;delta=-(1+(int)(rng()%min(maxd,mx)));}}else{delta=(int)(rng()%(2*maxd+1))-maxd;}if(!delta)continue;int oa=a[i],ob=b[i],oc=c[i],od=d[i];double os=sc(i);remG(i);if(side==0)a[i]+=delta;else if(side==1)b[i]+=delta;else if(side==2)c[i]+=delta;else d[i]+=delta;if(!valid(i)||overlapsI(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);continue;}double ns=sc(i),diff=ns-os;if(diff>=0||(exp(diff/T)>(rng()%1000000)/1e6)){addG(i);}else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);}}
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
