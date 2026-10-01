#include <bits/stdc++.h>
using namespace std;

int n;
int px[200],py[200];
long long pr[200];
int a[200],b[200],c[200],d[200];

long long area(int i){return (long long)(c[i]-a[i])*(d[i]-b[i]);}

double scorei(int i){
    long long s=area(i);
    if(s<=0)return 0;
    if(px[i]<a[i]||px[i]>=c[i]||py[i]<b[i]||py[i]>=d[i])return 0;
    double mn=min((double)pr[i],(double)s);
    double mx=max((double)pr[i],(double)s);
    double rat=1.0-mn/mx;
    return 1.0-rat*rat;
}

bool overlaps(int i,int j){
    return a[i]<c[j]&&c[i]>a[j]&&b[i]<d[j]&&d[i]>b[j];
}

bool anyOverlap(int i){
    for(int j=0;j<n;j++) if(j!=i&&overlaps(i,j)) return true;
    return false;
}

int maxExp(int i,int dir){
    int hi;
    if(dir==0)hi=a[i]; else if(dir==1)hi=b[i];
    else if(dir==2)hi=10000-c[i]; else hi=10000-d[i];
    if(hi<=0)return 0;
    for(int j=0;j<n;j++){
        if(j==i)continue;
        if(dir==0||dir==2){
            if(b[i]>=d[j]||d[i]<=b[j])continue;
            if(dir==0){if(c[j]<=a[i])hi=min(hi,a[i]-c[j]);}
            else{if(a[j]>=c[i])hi=min(hi,a[j]-c[i]);}
        }else{
            if(a[i]>=c[j]||c[i]<=a[j])continue;
            if(dir==1){if(d[j]<=b[i])hi=min(hi,b[i]-d[j]);}
            else{if(b[j]>=d[i])hi=min(hi,b[j]-d[i]);}
        }
    }
    return max(hi,0);
}

void expand(int i,int dir,int delta){
    if(dir==0)a[i]-=delta;else if(dir==1)b[i]-=delta;
    else if(dir==2)c[i]+=delta;else d[i]+=delta;
}

void shrink(int i,int dir,int delta){
    if(dir==0)a[i]+=delta;else if(dir==1)b[i]+=delta;
    else if(dir==2)c[i]-=delta;else d[i]-=delta;
}

int maxShrink(int i,int dir){
    if(dir==0)return px[i]-a[i];
    if(dir==1)return py[i]-b[i];
    if(dir==2)return c[i]-px[i]-1;
    return d[i]-py[i]-1;
}

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    cin>>n;
    for(int i=0;i<n;i++)cin>>px[i]>>py[i]>>pr[i];
    for(int i=0;i<n;i++){a[i]=px[i];b[i]=py[i];c[i]=px[i]+1;d[i]=py[i]+1;}

    auto clk=[]{return chrono::steady_clock::now();};
    auto st=clk();
    auto ela=[&]{return chrono::duration<double>(clk()-st).count();};

    // Greedy expansion
    for(int pass=0;pass<2000&&ela()<2.0;pass++){
        vector<int>ord(n);iota(ord.begin(),ord.end(),0);
        sort(ord.begin(),ord.end(),[](int i,int j){return scorei(i)<scorei(j);});
        for(int i:ord){
            int dirs[]={0,1,2,3};
            for(int dir:dirs){
                if(area(i)>=pr[i]*1.5)break;
                int mx=maxExp(i,dir);if(mx<=0)continue;
                int perp=(dir<2)?(d[i]-b[i]):(c[i]-a[i]);
                if(dir>=2)perp=(dir==2)?(d[i]-b[i]):(c[i]-a[i]);
                long long need=pr[i]-area(i);
                int w;
                if(need>0)w=min((long long)mx,(need+perp-1)/max(1LL,(long long)perp));
                else w=0;
                w=max(0,min(w,mx));
                if(w>0)expand(i,dir,w);
            }
        }
    }

    // SA
    mt19937 rng(42);
    double T0=0.02,Te=0.0001,tl=4.8;
    while(ela()<tl){
        double f=min(1.0,(ela()-2.0)/(tl-2.0));if(f<0)f=0;
        double T=T0*pow(Te/T0,f);
        int i=rng()%n;
        int dir=rng()%4;
        double os=scorei(i);
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        bool exp=(rng()%3!=0);
        if(exp){
            int mx=maxExp(i,dir);if(mx<=0)continue;
            int delta=1+rng()%max(1,min(mx,(int)(mx*(1.0-f*0.8))));
            expand(i,dir,delta);
        }else{
            int ms=maxShrink(i,dir);if(ms<=0)continue;
            int delta=1+rng()%max(1,min(ms,(int)(ms*(1.0-f*0.8))));
            shrink(i,dir,delta);
        }
        if(a[i]<0||b[i]<0||c[i]>10000||d[i]>10000||a[i]>=c[i]||b[i]>=d[i]||
           px[i]<a[i]||px[i]>=c[i]||py[i]<b[i]||py[i]>=d[i]){
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;continue;
        }
        if(exp&&anyOverlap(i)){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;continue;}
        double ns=scorei(i);
        double diff=ns-os;
        if(diff<0){
            double p=exp(diff/T);
            if((rng()%10000)/10000.0>=p){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}
        }
    }

    for(int i=0;i<n;i++)printf("%d %d %d %d\n",a[i],b[i],c[i],d[i]);
}
