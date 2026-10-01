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
    auto valid=[&](int i)->bool{return a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&a[i]<=X[i]&&c[i]>X[i]&&b[i]<=Y[i]&&d[i]>Y[i];};
    // Use interval tree or just brute force for n<=200
    auto overlapsAny=[&](int i)->bool{
        for(int j=0;j<n;j++)if(j!=i&&a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j])return true;return false;
    };
    // Sort by area descending for greedy
    vector<int>order(n);iota(order.begin(),order.end(),0);
    // Greedy expansion
    for(int pass=0;pass<800&&elapsed()<1.5;pass++){
        for(int idx=0;idx<n;idx++){
            int i=idx;
            for(int s=0;s<4;s++){
                int ss=(s+pass)%4;
                if(area(i)>=R[i]*2)continue;
                int oa=a[i],ob=b[i],oc=c[i],od=d[i];
                int lo=0,hi;
                if(ss==0)hi=a[i];else if(ss==1)hi=b[i];else if(ss==2)hi=10000-c[i];else hi=10000-d[i];
                while(lo<hi){int mid=(lo+hi+1)/2;int ta=oa,tb=ob,tc=oc,td=od;if(ss==0)ta=oa-mid;else if(ss==1)tb=ob-mid;else if(ss==2)tc=oc+mid;else td=od+mid;a[i]=ta;b[i]=tb;c[i]=tc;d[i]=td;if(valid(i)&&!overlapsAny(i))lo=mid;else hi=mid-1;a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}
                if(lo>0){if(ss==0)a[i]-=lo;else if(ss==1)b[i]-=lo;else if(ss==2)c[i]+=lo;else d[i]+=lo;}
            }
        }
    }
    mt19937 rng(42);
    double curScore=0;for(int i=0;i<n;i++)curScore+=sat(i);
    vector<int>ba=a,bb=b,bc=c,bd=d;double bestScore=curScore;
    while(elapsed()<4.7){
        double frac=elapsed()/4.7;double T=0.05*pow(0.0005,frac);
        int i=rng()%n;int op=rng()%6;
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];double os=sat(i);
        int maxd=max(1,(int)(300*(1.0-frac))+1);int delta=(int)(rng()%(2*maxd+1))-maxd;
        if(!delta)continue;
        if(op<4){if(op==0)a[i]+=delta;else if(op==1)b[i]+=delta;else if(op==2)c[i]+=delta;else d[i]+=delta;}
        else if(op==4){a[i]+=delta;c[i]+=delta;}else{b[i]+=delta;d[i]+=delta;}
        if(!valid(i)||overlapsAny(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;continue;}
        double ns=sat(i),diff=ns-os;
        if(diff>=0||(double)(rng()%1000000)/1e6<exp(diff/T)){
            curScore+=diff;
            if(curScore>bestScore){bestScore=curScore;ba=a;bb=b;bc=c;bd=d;}
        }else{a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}
    }
    for(int i=0;i<n;i++)cout<<ba[i]<<" "<<bb[i]<<" "<<bc[i]<<" "<<bd[i]<<"\n";
}
