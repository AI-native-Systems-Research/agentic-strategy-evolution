#include<bits/stdc++.h>
using namespace std;
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto t0=chrono::steady_clock::now();
    auto ms=[&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    int n;cin>>n;
    vector<int>x(n),y(n),r(n);
    for(int i=0;i<n;i++)cin>>x[i]>>y[i]>>r[i];
    vector<int>a(n),b(n),c(n),d(n);
    for(int i=0;i<n;i++){a[i]=x[i];b[i]=y[i];c[i]=x[i]+1;d[i]=y[i]+1;}
    
    // Check overlap between rect i (with proposed coords) and all others
    auto overlapsAny=[&](int i,int na,int nb,int nc,int nd)->bool{
        for(int j=0;j<n;j++)if(j!=i)
            if(na<c[j]&&nc>a[j]&&nb<d[j]&&nd>b[j])return true;
        return false;
    };
    
    mt19937 rng(12345);
    int maxIter=200*n;
    double score_sum=0;
    for(int iter=0;;iter++){
        if(ms()>4700)break;
        // Pick random company
        int i=rng()%n;
        long long cur=(long long)(c[i]-a[i])*(d[i]-b[i]);
        long long target=r[i];
        // Pick random direction: 0=left,1=up,2=right,3=down
        int dir=rng()%4;
        // Binary search for max expansion
        int lo=1,hi=300,best=0;
        while(lo<=hi){
            int mid=(lo+hi)/2;
            int na=a[i],nb=b[i],nc=c[i],nd=d[i];
            if(dir==0)na-=mid;else if(dir==1)nb-=mid;else if(dir==2)nc+=mid;else nd+=mid;
            if(na<0||nb<0||nc>10000||nd>10000){hi=mid-1;continue;}
            if(!overlapsAny(i,na,nb,nc,nd)){best=mid;lo=mid+1;}else hi=mid-1;
        }
        if(best<=0){
            // Try shrinking if oversized
            if(cur>target){
                int na=a[i],nb=b[i],nc=c[i],nd=d[i];
                if(dir==0&&nc-na>1&&na+1<=x[i])a[i]++;
                else if(dir==1&&nd-nb>1&&nb+1<=y[i])b[i]++;
                else if(dir==2&&nc-na>1&&nc-1>x[i])c[i]--;
                else if(dir==3&&nd-nb>1&&nd-1>y[i])d[i]--;
            }
            continue;
        }
        int side=(dir==0||dir==2)?(d[i]-b[i]):(c[i]-a[i]);
        long long need=target-cur;
        if(need<=0)continue;
        int want=(int)min((long long)best,max(1LL,side>0?(need+side-1)/side:1LL));
        if(want<1)want=1;
        if(want>best)want=best;
        long long newArea;
        if(dir==0||dir==2)newArea=(long long)(c[i]-a[i]+want)*(d[i]-b[i]);
        else newArea=(long long)(c[i]-a[i])*(d[i]-b[i]+want);
        if(newArea>2*target&&cur>=target)continue;
        if(dir==0)a[i]-=want;else if(dir==1)b[i]-=want;else if(dir==2)c[i]+=want;else d[i]+=want;
    }
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
