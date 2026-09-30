#include<bits/stdc++.h>
using namespace std;

int n;
int px[205],py[205];
long long r[205];
int a[205],b[205],c[205],d[205];

static const int G=100, GS=100;
vector<int> grid[G][G];

void grid_add(int i){
    int gx0=max(0,a[i]/GS), gx1=min(G-1,(c[i]-1)/GS);
    int gy0=max(0,b[i]/GS), gy1=min(G-1,(d[i]-1)/GS);
    for(int x=gx0;x<=gx1;x++) for(int y=gy0;y<=gy1;y++) grid[x][y].push_back(i);
}
void grid_remove(int i){
    int gx0=max(0,a[i]/GS), gx1=min(G-1,(c[i]-1)/GS);
    int gy0=max(0,b[i]/GS), gy1=min(G-1,(d[i]-1)/GS);
    for(int x=gx0;x<=gx1;x++) for(int y=gy0;y<=gy1;y++){
        auto &v=grid[x][y];
        v.erase(find(v.begin(),v.end(),i));
    }
}

bool overlaps_any(int i,int na,int nb,int nc,int nd){
    int gx0=max(0,na/GS), gx1=min(G-1,(nc-1)/GS);
    int gy0=max(0,nb/GS), gy1=min(G-1,(nd-1)/GS);
    static bool seen[205]; static int sl[205]; int sc=0;
    bool res=false;
    for(int x=gx0;x<=gx1&&!res;x++) for(int y=gy0;y<=gy1&&!res;y++){
        for(int j:grid[x][y]){
            if(j==i||seen[j])continue;
            seen[j]=true; sl[sc++]=j;
            if(na<c[j]&&a[j]<nc&&nb<d[j]&&b[j]<nd){res=true;break;}
        }
    }
    for(int k=0;k<sc;k++) seen[sl[k]]=false;
    return res;
}

bool cp(int i,int na,int nb,int nc,int nd){return na<=px[i]&&nc>px[i]&&nb<=py[i]&&nd>py[i];}
bool valid(int i,int na,int nb,int nc,int nd){
    return na>=0&&nb>=0&&nc<=10000&&nd<=10000&&na<nc&&nb<nd&&cp(i,na,nb,nc,nd)&&!overlaps_any(i,na,nb,nc,nd);
}
double scoreI(int i){
    long long s=(long long)(c[i]-a[i])*(d[i]-b[i]);
    if(!cp(i,a[i],b[i],c[i],d[i]))return 0;
    double rat=(double)min(r[i],s)/(double)max(r[i],s);
    return 1.0-(1.0-rat)*(1.0-rat);
}

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    cin>>n;
    for(int i=0;i<n;i++) cin>>px[i]>>py[i]>>r[i];
    for(int i=0;i<n;i++){a[i]=px[i];b[i]=py[i];c[i]=px[i]+1;d[i]=py[i]+1;}
    for(int i=0;i<n;i++) grid_add(i);
    auto ts=chrono::steady_clock::now();
    auto ela=[&](){return chrono::duration<double>(chrono::steady_clock::now()-ts).count();};
    // Greedy expansion
    for(int pass=0;pass<100000&&ela()<2.0;pass++){
        vector<int>od(n);iota(od.begin(),od.end(),0);
        sort(od.begin(),od.end(),[](int x,int y){return x<y;});
        // shuffle based on score
        sort(od.begin(),od.end(),[&](int x,int y){return scoreI(x)<scoreI(y);});
        bool any=false;
        for(int i:od){
            for(int dd=0;dd<4;dd++){
                long long cu=(long long)(c[i]-a[i])*(d[i]-b[i]);
                if(cu>=r[i]*3)continue;
                int w=(dd<2)?(d[i]-b[i]):(c[i]-a[i]);
                if(w<=0)continue;
                long long need=max(r[i]-cu,(long long)0);
                int want=max(1,min(10000,(int)((need+w-1)/w)));
                want=min(want,5000);
                int lo=0,hi=want;
                while(lo<hi){int mid=(lo+hi+1)/2;int na=a[i],nb=b[i],nc=c[i],nd=d[i];
                    if(dd==0)na-=mid;else if(dd==1)nc+=mid;else if(dd==2)nb-=mid;else nd+=mid;
                    if(valid(i,na,nb,nc,nd))lo=mid;else hi=mid-1;}
                if(lo>0){grid_remove(i);if(dd==0)a[i]-=lo;else if(dd==1)c[i]+=lo;else if(dd==2)b[i]-=lo;else d[i]+=lo;grid_add(i);any=true;}
            }
        }
        if(!any)break;
    }
    mt19937 rng(42);
    double curTotal=0;for(int i=0;i<n;i++)curTotal+=scoreI(i);
    double bestTotal=curTotal;
    int ba[205],bb[205],bc[205],bd[205];
    memcpy(ba,a,sizeof(a));memcpy(bb,b,sizeof(b));memcpy(bc,c,sizeof(c));memcpy(bd,d,sizeof(d));
    double tl=4.85;
    while(ela()<tl){
        double t=ela()/tl;
        double T=0.03*(1-t)+0.0001;
        int i=rng()%n;
        double os=scoreI(i);
        int oa=a[i],ob=b[i],oc=c[i],od2=d[i];
        int range=max(1,(int)(200*(1-t)+1));
        grid_remove(i);
        int mv=rng()%6;
        if(mv<4){int delta=(int)(rng()%(2*range+1))-range;if(!delta){grid_add(i);continue;}
            if(mv==0)a[i]+=delta;else if(mv==1)c[i]+=delta;else if(mv==2)b[i]+=delta;else d[i]+=delta;
        } else if(mv==4){int dx=(int)(rng()%(2*range+1))-range;a[i]+=dx;c[i]+=dx;}
        else{int dy=(int)(rng()%(2*range+1))-range;b[i]+=dy;d[i]+=dy;}
        if(a[i]>=0&&b[i]>=0&&c[i]<=10000&&d[i]<=10000&&a[i]<c[i]&&b[i]<d[i]&&cp(i,a[i],b[i],c[i],d[i])&&!overlaps_any(i,a[i],b[i],c[i],d[i])){
            double ns=scoreI(i);
            double diff=ns-os;
            if(diff>=0||((rng()%1000000)/1000000.0)<exp(diff/T)){
                grid_add(i);curTotal+=diff;
                if(curTotal>bestTotal){bestTotal=curTotal;memcpy(ba,a,sizeof(a));memcpy(bb,b,sizeof(b));memcpy(bc,c,sizeof(c));memcpy(bd,d,sizeof(d));}
                continue;
            }
        }
        a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od2;grid_add(i);
    }
    memcpy(a,ba,sizeof(a));memcpy(b,bb,sizeof(b));memcpy(c,bc,sizeof(c));memcpy(d,bd,sizeof(d));
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
