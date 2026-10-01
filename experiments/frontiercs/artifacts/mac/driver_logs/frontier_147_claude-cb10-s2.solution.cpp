#include<bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n; cin>>n;
    vector<int>x(n),y(n); vector<long long>r(n);
    for(int i=0;i<n;i++) cin>>x[i]>>y[i]>>r[i];
    vector<int>a(n),b(n),c(n),d(n);
    for(int i=0;i<n;i++){a[i]=x[i];b[i]=y[i];c[i]=x[i]+1;d[i]=y[i]+1;}
    
    const int GS=50,GN=200;
    vector<vector<int>>grid(GN*GN);
    auto gx0=[&](int i){return a[i]/GS;};
    auto gy0=[&](int i){return b[i]/GS;};
    auto gx1=[&](int i){return min(GN-1,(c[i]-1)/GS);};
    auto gy1=[&](int i){return min(GN-1,(d[i]-1)/GS);};
    auto addG=[&](int i){int x0=gx0(i),y0=gy0(i),x1=gx1(i),y1=gy1(i);for(int gy=y0;gy<=y1;gy++)for(int gx=x0;gx<=x1;gx++)grid[gy*GN+gx].push_back(i);};
    auto remG=[&](int i){int x0=gx0(i),y0=gy0(i),x1=gx1(i),y1=gy1(i);for(int gy=y0;gy<=y1;gy++)for(int gx=x0;gx<=x1;gx++){auto&v=grid[gy*GN+gx];for(int k=0;k<(int)v.size();k++)if(v[k]==i){v[k]=v.back();v.pop_back();break;}}};
    auto overlapsI=[&](int i)->bool{int x0=gx0(i),y0=gy0(i),x1=gx1(i),y1=gy1(i);for(int gy=y0;gy<=y1;gy++)for(int gx=x0;gx<=x1;gx++)for(int j:grid[gy*GN+gx])if(j!=i&&a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j])return true;return false;};
    auto valid=[&](int i)->bool{return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&a[i]<=x[i]&&c[i]>x[i]&&b[i]<=y[i]&&d[i]>y[i];};
    auto area=[&](int i)->long long{return(long long)(c[i]-a[i])*(d[i]-b[i]);};
    auto sc=[&](int i)->double{long long s=area(i);double rt=(double)min(r[i],s)/(double)max(r[i],s);double t=1.0-rt;return 1.0-t*t;};
    for(int i=0;i<n;i++) addG(i);
    
    for(int pass=0;pass<1200;pass++){
        vector<int>ord(n);iota(ord.begin(),ord.end(),0);
        mt19937 rng(pass*7+13);shuffle(ord.begin(),ord.end(),rng);
        if(pass%3!=2)sort(ord.begin(),ord.end(),[&](int u,int v){return sc(u)<sc(v);});
        for(int i:ord)for(int s=0;s<4;s++){
            double cursc=sc(i);if(cursc>0.9999)continue;
            remG(i);int oa=a[i],ob=b[i],oc=c[i],od=d[i];
            int hi=(s==0?a[i]:s==1?b[i]:s==2?10000-c[i]:10000-d[i]),lo=0;
            while(lo<hi){int mid=(lo+hi+1)/2;a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;if(s==0)a[i]-=mid;else if(s==1)b[i]-=mid;else if(s==2)c[i]+=mid;else d[i]+=mid;if(valid(i)&&!overlapsI(i))lo=mid;else hi=mid-1;}
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;
            if(lo>0){if(s==0)a[i]-=lo;else if(s==1)b[i]-=lo;else if(s==2)c[i]+=lo;else d[i]+=lo;if(sc(i)<cursc-1e-12){int tlo=0,thi=lo;while(tlo<thi){int mid=(tlo+thi+1)/2;a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;if(s==0)a[i]-=mid;else if(s==1)b[i]-=mid;else if(s==2)c[i]+=mid;else d[i]+=mid;if(sc(i)>=cursc-1e-12)tlo=mid;else thi=mid-1;}a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;if(tlo>0){if(s==0)a[i]-=tlo;else if(s==1)b[i]-=tlo;else if(s==2)c[i]+=tlo;else d[i]+=tlo;}}}
            addG(i);
        }
    }
    mt19937 rng(12345);
    auto st=chrono::steady_clock::now();
    for(int it=0;;it++){
        if((it&4095)==0&&chrono::duration<double>(chrono::steady_clock::now()-st).count()>4.3)break;
        double el=chrono::duration<double>(chrono::steady_clock::now()-st).count();double frac=el/4.5;
        double T=0.015*(1.0-frac)+1e-10;
        int i=rng()%n;int side=rng()%4;
        int maxd=max(1,(int)(200*(1.0-frac)));
        int delta=(int)(rng()%(2*maxd+1))-maxd;if(!delta)continue;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];double os=sc(i);
        remG(i);
        if(side==0)a[i]+=delta;else if(side==1)b[i]+=delta;else if(side==2)c[i]+=delta;else d[i]+=delta;
        if(!valid(i)||overlapsI(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);continue;}
        double ns=sc(i);double diff=ns-os;
        if(diff>=0||((double)(rng()%1000000)/1000000.0)<exp(diff/T)){addG(i);}
        else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;addG(i);}
    }
    for(int i=0;i<n;i++) cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
