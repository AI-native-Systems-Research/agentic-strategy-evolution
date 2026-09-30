#include<bits/stdc++.h>
using namespace std;

int n;
int px[205],py[205];
long long r[205];
int a[205],b[205],c[205],d[205];

// Grid-based overlap detection
// We'll use brute force but with early termination and sorted checks
// For n<=200, we can afford O(n) per check if we do enough iterations

bool overlaps_any(int i,int na,int nb,int nc,int nd){
    for(int j=0;j<n;j++) if(j!=i){
        if(na<c[j]&&a[j]<nc&&nb<d[j]&&b[j]<nd) return true;
    }
    return false;
}

bool contains_point(int i,int na,int nb,int nc,int nd){
    return na<=px[i]&&nc>px[i]&&nb<=py[i]&&nd>py[i];
}

bool valid(int i,int na,int nb,int nc,int nd){
    if(na<0||nb<0||nc>10000||nd>10000||na>=nc||nb>=nd)return false;
    if(!contains_point(i,na,nb,nc,nd))return false;
    return !overlaps_any(i,na,nb,nc,nd);
}

double scoreI(int i){
    long long s=(long long)(c[i]-a[i])*(d[i]-b[i]);
    if(!contains_point(i,a[i],b[i],c[i],d[i]))return 0.0;
    double rat=(double)min(r[i],s)/(double)max(r[i],s);
    return 1.0-(1.0-rat)*(1.0-rat);
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    cin>>n;
    for(int i=0;i<n;i++) cin>>px[i]>>py[i]>>r[i];
    
    // Initialize: 1x1 around desired point
    for(int i=0;i<n;i++){a[i]=px[i];b[i]=py[i];c[i]=px[i]+1;d[i]=py[i]+1;}
    
    auto ts=chrono::steady_clock::now();
    auto ela=[&](){return chrono::duration<double>(chrono::steady_clock::now()-ts).count();};
    
    // Greedy expansion passes
    for(int pass=0;pass<10000&&ela()<1.5;pass++){
        vector<int>od(n);iota(od.begin(),od.end(),0);
        sort(od.begin(),od.end(),[&](int x,int y){return scoreI(x)<scoreI(y);});
        bool any=false;
        for(int i:od){
            for(int dd=0;dd<4;dd++){
                long long cu=(long long)(c[i]-a[i])*(d[i]-b[i]);
                if(cu>=r[i]*2)continue;
                int w=(dd<2)?(d[i]-b[i]):(c[i]-a[i]);
                if(w<=0)continue;
                long long target=max(r[i],cu);
                long long df=target-cu;
                int want=max(1,min(10000,(int)((df+w-1)/w)));
                int lo=0,hi=want;
                while(lo<hi){int mid=(lo+hi+1)/2;
                    int na=a[i],nb=b[i],nc=c[i],nd=d[i];
                    if(dd==0)na-=mid;else if(dd==1)nc+=mid;else if(dd==2)nb-=mid;else nd+=mid;
                    if(valid(i,na,nb,nc,nd))lo=mid;else hi=mid-1;
                }
                if(lo>0){if(dd==0)a[i]-=lo;else if(dd==1)c[i]+=lo;else if(dd==2)b[i]-=lo;else d[i]+=lo;any=true;}
            }
        }
        if(!any)break;
    }
    
    // SA phase
    mt19937 rng(42);
    double T0=0.08,T1=0.0001;
    double tl=4.85;
    int iter=0;
    while(ela()<tl){
        double t=ela()/tl;
        double T=T0*pow(T1/T0,t);
        int i=rng()%n;
        double os=scoreI(i);
        int oa=a[i],ob=b[i],oc=c[i],od2=d[i];
        int dd=rng()%4;
        int range=max(1,(int)(300*(1-t)+1));
        int delta=(int)(rng()%((unsigned)(2*range+1)))-range;
        if(!delta){iter++;continue;}
        if(dd==0)a[i]+=delta;else if(dd==1)c[i]+=delta;else if(dd==2)b[i]+=delta;else d[i]+=delta;
        if(valid(i,a[i],b[i],c[i],d[i])){
            double ns=scoreI(i);
            double diff=ns-os;
            if(diff>=0||(rng()%10000)<(int)(10000*exp(diff/T))){iter++;continue;}
        }
        a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od2;
        iter++;
    }
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
