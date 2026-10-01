#include <bits/stdc++.h>
using namespace std;

int n;
int x[1001],y[1001];
long long r[1001];
int a[1001],b[1001],c[1001],d[1001];

bool overlaps(int i, int j){
    return a[i]<c[j] && c[i]>a[j] && b[i]<d[j] && d[i]>b[j];
}

long long area(int i){ return (long long)(c[i]-a[i])*(d[i]-b[i]); }

double score(int i){
    long long s=area(i);
    if(s<=0) return 0;
    if(x[i]<a[i]||x[i]>=c[i]||y[i]<b[i]||y[i]>=d[i]) return 0;
    double mn=min((double)r[i],(double)s);
    double mx=max((double)r[i],(double)s);
    double rat=1.0-mn/mx;
    return 1.0-rat*rat;
}

// max expand for rect i in dir (0=left,1=up,2=right,3=down) without overlapping others
int maxExp(int i, int dir){
    int lim;
    if(dir==0) lim=a[i]; // can decrease a[i] by up to a[i] (to 0)
    else if(dir==1) lim=b[i];
    else if(dir==2) lim=10000-c[i];
    else lim=10000-d[i];
    
    for(int j=0;j<n;j++){
        if(j==i) continue;
        if(dir==0||dir==2){
            // need y-overlap
            if(b[i]>=d[j]||d[i]<=b[j]) continue;
            if(dir==0){
                // decreasing a[i]. Need new_a >= c[j] for j left of i, or a[j] for j overlapping x-range
                // actually need no overlap: new_a < c[j] && c[i]>a[j] would overlap (y already overlaps)
                // currently a[i]>=c[j] (no overlap condition in x if j is to left)
                // new_a = a[i]-delta. Need a[i]-delta >= c[j] => delta <= a[i]-c[j]
                if(c[j]<=a[i]) lim=min(lim, a[i]-c[j]);
                else if(a[j]<c[i]) lim=0; // already overlapping
            } else {
                if(a[j]>=c[i]) lim=min(lim, a[j]-c[i]);
                else if(c[j]>a[i]) lim=0;
            }
        } else {
            if(a[i]>=c[j]||c[i]<=a[j]) continue;
            if(dir==1){
                if(d[j]<=b[i]) lim=min(lim, b[i]-d[j]);
                else if(b[j]<d[i]) lim=0;
            } else {
                if(b[j]>=d[i]) lim=min(lim, b[j]-d[i]);
                else if(d[j]>b[i]) lim=0;
            }
        }
    }
    return max(lim,0);
}

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    scanf("%d",&n);
    for(int i=0;i<n;i++){
        scanf("%d%d%lld",&x[i],&y[i],&r[i]);
        a[i]=x[i]; b[i]=y[i]; c[i]=x[i]+1; d[i]=y[i]+1;
    }
    auto T0=chrono::steady_clock::now();
    auto ms=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-T0).count();};
    
    for(int pass=0;pass<500&&ms()<1.5;pass++){
        vector<int> ord(n); iota(ord.begin(),ord.end(),0);
        sort(ord.begin(),ord.end(),[](int i,int j){return score(i)<score(j);});
        for(int i:ord){
            for(int dir=0;dir<4;dir++){
                int mx=maxExp(i,dir);
                if(mx<=0) continue;
                long long s=area(i),t=r[i];
                int perp=(dir<2?1:0)?((dir==0||dir==2)?(d[i]-b[i]):(c[i]-a[i])):((dir==0||dir==2)?(d[i]-b[i]):(c[i]-a[i]));
                int want=s<t?(int)min((long long)mx,((t-s)+perp-1)/perp):0;
                if(s>t){ int sh=(int)min((long long)mx, ((s-t)+perp-1)/perp); want=0; (void)sh; }
                want=min(want,mx);
                if(want<=0) continue;
                if(dir==0) a[i]-=want; else if(dir==1) b[i]-=want;
                else if(dir==2) c[i]+=want; else d[i]+=want;
            }
        }
    }
    
    mt19937 rng(42);
    double tlim=4.8;
    while(ms()<tlim){
        double f=ms()/tlim;
        double T=0.1*pow(0.0001/0.1,f);
        int i=rng()%n, dir=rng()%4;
        bool expand=rng()%2;
        double os=score(i);
        int oa=a[i],ob=b[i],oc=c[i],od=d[i];
        if(expand){
            int mx=maxExp(i,dir); if(mx<=0) continue;
            int delta=1+rng()%max(1,min(mx,(int)(mx*(1-f)+1)));
            if(dir==0) a[i]-=delta; else if(dir==1) b[i]-=delta;
            else if(dir==2) c[i]+=delta; else d[i]+=delta;
        } else {
            int ms2;
            if(dir==0) ms2=x[i]-a[i]; else if(dir==1) ms2=y[i]-b[i];
            else if(dir==2) ms2=c[i]-x[i]-1; else ms2=d[i]-y[i]-1;
            if(ms2<=0) continue;
            int delta=1+rng()%max(1,min(ms2,(int)(ms2*(1-f)+1)));
            if(dir==0) a[i]+=delta; else if(dir==1) b[i]+=delta;
            else if(dir==2) c[i]-=delta; else d[i]-=delta;
        }
        if(a[i]<0||b[i]<0||c[i]>10000||d[i]>10000||a[i]>=c[i]||b[i]>=d[i]||
           x[i]<a[i]||x[i]>=c[i]||y[i]<b[i]||y[i]>=d[i]){
            a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od; continue;
        }
        bool valid=true;
        for(int j=0;j<n&&valid;j++) if(j!=i&&overlaps(i,j)) valid=false;
        if(!valid){a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;continue;}
        double ns=score(i), diff=ns-os;
        if(diff>=0||(rng()%10000)/10000.0<exp(diff/T)){} 
        else {a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od;}
    }
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a[i],b[i],c[i],d[i]);
}
