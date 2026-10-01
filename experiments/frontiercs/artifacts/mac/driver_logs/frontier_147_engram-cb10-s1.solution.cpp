#include <bits/stdc++.h>
using namespace std;

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int n; cin>>n;
    vector<int> x(n),y(n); vector<long long> r(n);
    for(int i=0;i<n;i++) cin>>x[i]>>y[i]>>r[i];
    
    const int W=10000, G=200;
    double cellW=(double)W/G;
    vector<int> a(n),b(n),c(n),d(n);
    vector<vector<vector<int>>> grid(G+1,vector<vector<int>>(G+1));
    
    auto gc=[&](int v)->int{int g=(int)(v/cellW);return max(0,min(G,g));};
    auto addG=[&](int i){int x0=gc(a[i]),y0=gc(b[i]),x1=gc(c[i]-1),y1=gc(d[i]-1);for(int gx=x0;gx<=x1;gx++)for(int gy=y0;gy<=y1;gy++)grid[gx][gy].push_back(i);};
    auto remG=[&](int i){int x0=gc(a[i]),y0=gc(b[i]),x1=gc(c[i]-1),y1=gc(d[i]-1);for(int gx=x0;gx<=x1;gx++)for(int gy=y0;gy<=y1;gy++){auto&v=grid[gx][gy];for(int k=0;k<(int)v.size();k++)if(v[k]==i){v[k]=v.back();v.pop_back();break;}}};
    auto overlaps=[&](int i,int na,int nb,int nc,int nd)->bool{if(na<0||nb<0||nc>W||nd>W||na>=nc||nb>=nd)return true;int x0=gc(na),y0=gc(nb),x1=gc(nc-1),y1=gc(nd-1);for(int gx=x0;gx<=x1;gx++)for(int gy=y0;gy<=y1;gy++)for(int j:grid[gx][gy])if(j!=i&&na<c[j]&&a[j]<nc&&nb<d[j]&&b[j]<nd)return true;return false;};
    auto maxE=[&](int i,int dir,int mx)->int{int lo=1,hi=mx,best=0;while(lo<=hi){int mid=(lo+hi)/2;int na=a[i],nb=b[i],nc=c[i],nd=d[i];if(dir==0)na-=mid;else if(dir==1)nc+=mid;else if(dir==2)nb-=mid;else nd+=mid;if(!overlaps(i,na,nb,nc,nd)){best=mid;lo=mid+1;}else hi=mid-1;}return best;};
    auto sat=[&](int i)->double{double s=(double)(c[i]-a[i])*(d[i]-b[i]),ri=r[i];if(s<=0)return 0;double rat=min(ri,s)/max(ri,s);return 1-(1-rat)*(1-rat);};
    
    mt19937 rng(42);
    vector<int> ba(n),bb(n),bc(n),bd(n);double bs=-1;
    auto t0=chrono::steady_clock::now();
    auto el=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    for(int att=0;el()<4.5;att++){
        for(int i=0;i<=G;i++)for(int j=0;j<=G;j++)grid[i][j].clear();
        for(int i=0;i<n;i++){a[i]=x[i];b[i]=y[i];c[i]=x[i]+1;d[i]=y[i]+1;addG(i);}
        for(int rnd=0;rnd<500&&el()<4.4;rnd++){
            vector<int> ord(n);iota(ord.begin(),ord.end(),0);
            sort(ord.begin(),ord.end(),[&](int u,int v){return sat(u)<sat(v);});
            bool ch=false;
            for(int i:ord){
                long long area=(long long)(c[i]-a[i])*(d[i]-b[i]);
                if(area>0){double rat=min((double)r[i],(double)area)/max((double)r[i],(double)area);if(rat>0.995)continue;}
                remG(i);
                if(area<r[i]){int dirs[]={0,1,2,3};shuffle(dirs,dirs+4,rng);for(int dir:dirs){area=(long long)(c[i]-a[i])*(d[i]-b[i]);if(area>=r[i])break;long long need=r[i]-area;int side=(dir<2)?(d[i]-b[i]):(c[i]-a[i]);if(!side)continue;int mx=min((long long)W,(need+side-1)/side);int e=maxE(i,dir,mx);if(e>0){if(dir==0)a[i]-=e;else if(dir==1)c[i]+=e;else if(dir==2)b[i]-=e;else d[i]+=e;ch=true;}}}
                area=(long long)(c[i]-a[i])*(d[i]-b[i]);
                if(area>r[i]){for(int dir=0;dir<4;dir++){area=(long long)(c[i]-a[i])*(d[i]-b[i]);if(area<=r[i])break;double rat=(double)area/r[i];int s=0;if(dir==0){s=min((int)((rat-1)*(c[i]-a[i])/2),x[i]-a[i]);if(s>0){a[i]+=s;ch=true;}}else if(dir==1){s=min((int)((rat-1)*(c[i]-a[i])/2),c[i]-x[i]-1);if(s>0){c[i]-=s;ch=true;}}else if(dir==2){s=min((int)((rat-1)*(d[i]-b[i])/2),y[i]-b[i]);if(s>0){b[i]+=s;ch=true;}}else{s=min((int)((rat-1)*(d[i]-b[i])/2),d[i]-y[i]-1);if(s>0){d[i]-=s;ch=true;}}}}
                addG(i);
            }
            if(!ch)break;
        }
        double sc=0;for(int i=0;i<n;i++)sc+=sat(i);
        if(sc>bs){bs=sc;ba=a;bb=b;bc=c;bd=d;}
    }
    for(int i=0;i<n;i++)cout<<ba[i]<<" "<<bb[i]<<" "<<bc[i]<<" "<<bd[i]<<"\n";
}
