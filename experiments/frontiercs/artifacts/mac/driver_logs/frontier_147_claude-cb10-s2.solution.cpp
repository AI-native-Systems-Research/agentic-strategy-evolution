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
    for(int i=0;i<n;i++){a[i]=X[i];b[i]=Y[i];c[i]=X[i]+1;d[i]=Y[i]+1;}
    auto area=[&](int i)->long long{return(long long)(c[i]-a[i])*(d[i]-b[i]);};
    auto sat=[&](int i)->double{
        if(!(a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i]))return 0.0;
        long long s=area(i);double rat=(double)min(R[i],s)/(double)max(R[i],s);double t=1.0-rat;return 1.0-t*t;
    };
    const int GS=50,GN=(10000+GS-1)/GS;
    vector<vector<int>>grid(GN*GN);
    auto gx1=[](int v){return v/GS;};
    auto gx2=[](int v){return min(GN-1,(v-1)/GS);};
    auto addG=[&](int i){int x1=gx1(a[i]),x2=gx2(c[i]),y1=gx1(b[i]),y2=gx2(d[i]);for(int gy=y1;gy<=y2;gy++)for(int gx=x1;gx<=x2;gx++)grid[gy*GN+gx].push_back(i);};
    auto remG=[&](int i){int x1=gx1(a[i]),x2=gx2(c[i]),y1=gx1(b[i]),y2=gx2(d[i]);for(int gy=y1;gy<=y2;gy++)for(int gx=x1;gx<=x2;gx++){auto&v=grid[gy*GN+gx];for(int k=(int)v.size()-1;k>=0;k--)if(v[k]==i){v[k]=v.back();v.pop_back();break;}}};
    auto overlaps=[&](int i)->bool{int x1=gx1(a[i]),x2=gx2(c[i]),y1=gx1(b[i]),y2=gx2(d[i]);for(int gy=y1;gy<=y2;gy++)for(int gx=x1;gx<=x2;gx++)for(int j:grid[gy*GN+gx])if(j!=i&&a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j])return true;return false;};
    auto valid=[&](int i)->bool{return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i];};
    for(int i=0;i<n;i++)addG(i);
    // Greedy expansion
    for(int pass=0;pass<200&&elapsed()<1.0;pass++){for(int i=0;i<n;i++){remG(i);for(int s=0;s<4;s++){int oa=a[i],ob=b[i],oc=c[i],od=d[i];long long ca=area(i);if(ca>=R[i])continue;int w=c[i]-a[i],h=d[i]-b[i];int td=max(1,(int)((R[i]-ca)/(s<2?h:w)));if(s==0)a[i]=max(0,a[i]-td);else if(s==1)b[i]=max(0,b[i]-td);else if(s==2)c[i]=min(10000,c[i]+td);else d[i]=min(10000,d[i]+td);if(!valid(i)||overlaps(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}}addG(i);}}
    mt19937 rng(42);
    while(elapsed()<4.7){double frac=min(1.0,elapsed()/4.7);double T=0.05*pow(0.0001,frac);int i=rng()%n;int side=rng()%4;int maxd=max(1,(int)(300*(1.0-frac))+1);int delta=(int)(rng()%(2*maxd+1))-maxd;if(!delta)continue;int oa=a[i],ob=b[i],oc=c[i],od=d[i];double os=sat(i);remG(i);if(side==0)a[i]+=delta;else if(side==1)b[i]+=delta;else if(side==2)c[i]+=delta;else d[i]+=delta;if(!valid(i)||overlaps(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);continue;}double ns=sat(i),diff=ns-os;if(diff>=0||(double)(rng()%1000000)/1e6<exp(diff/T)){addG(i);}else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);}}
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
