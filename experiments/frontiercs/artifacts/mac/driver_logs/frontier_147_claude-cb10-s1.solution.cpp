#include<bits/stdc++.h>
using namespace std;

int n;
int px[205],py[205];
long long r[205];
int a[205],b[205],c[205],d[205];

// Grid-based spatial index for fast overlap detection
// Each cell stores which rectangles overlap it
static const int G=100;
static const int GS=100; // 10000/100
vector<int> grid[G][G];

void grid_add(int i){
    int gx0=a[i]/GS, gx1=(c[i]-1)/GS, gy0=b[i]/GS, gy1=(d[i]-1)/GS;
    gx0=max(0,min(G-1,gx0)); gx1=max(0,min(G-1,gx1));
    gy0=max(0,min(G-1,gy0)); gy1=max(0,min(G-1,gy1));
    for(int x=gx0;x<=gx1;x++) for(int y=gy0;y<=gy1;y++) grid[x][y].push_back(i);
}
void grid_remove(int i){
    int gx0=a[i]/GS, gx1=(c[i]-1)/GS, gy0=b[i]/GS, gy1=(d[i]-1)/GS;
    gx0=max(0,min(G-1,gx0)); gx1=max(0,min(G-1,gx1));
    gy0=max(0,min(G-1,gy0)); gy1=max(0,min(G-1,gy1));
    for(int x=gx0;x<=gx1;x++) for(int y=gy0;y<=gy1;y++){
        auto &v=grid[x][y];
        v.erase(find(v.begin(),v.end(),i));
    }
}

bool overlaps_fast(int i,int na,int nb,int nc,int nd){
    int gx0=na/GS, gx1=(nc-1)/GS, gy0=nb/GS, gy1=(nd-1)/GS;
    gx0=max(0,min(G-1,gx0)); gx1=max(0,min(G-1,gx1));
    gy0=max(0,min(G-1,gy0)); gy1=max(0,min(G-1,gy1));
    static bool seen[205];
    static int seenlist[205];
    int scnt=0;
    bool res=false;
    for(int x=gx0;x<=gx1&&!res;x++) for(int y=gy0;y<=gy1&&!res;y++){
        for(int j:grid[x][y]){
            if(j==i||seen[j])continue;
            seen[j]=true; seenlist[scnt++]=j;
            if(na<c[j]&&a[j]<nc&&nb<d[j]&&b[j]<nd){res=true;break;}
        }
    }
    for(int k=0;k<scnt;k++) seen[seenlist[k]]=false;
    return res;
}

bool contains_point(int i,int na,int nb,int nc,int nd){
    return na<=px[i]&&nc>px[i]&&nb<=py[i]&&nd>py[i];
}
bool valid(int i,int na,int nb,int nc,int nd){
    if(na<0||nb<0||nc>10000||nd>10000||na>=nc||nb>=nd)return false;
    if(!contains_point(i,na,nb,nc,nd))return false;
    return !overlaps_fast(i,na,nb,nc,nd);
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
    // Init: 1x1 at desired point
    for(int i=0;i<n;i++){a[i]=px[i];b[i]=py[i];c[i]=px[i]+1;d[i]=py[i]+1;}
    // Build grid
    for(int i=0;i<n;i++) grid_add(i);
    
    auto ts=chrono::steady_clock::now();
    auto ela=[&](){return chrono::duration<double>(chrono::steady_clock::now()-ts).count();};
    
    // Greedy expansion passes
    for(int pass=0;pass<50000&&ela()<1.5;pass++){
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
                while(lo<hi){
                    int mid=(lo+hi+1)/2;
                    int na=a[i],nb=b[i],nc=c[i],nd=d[i];
                    if(dd==0)na-=mid;else if(dd==1)nc+=mid;else if(dd==2)nb-=mid;else nd+=mid;
                    if(valid(i,na,nb,nc,nd))lo=mid;else hi=mid-1;
                }
                if(lo>0){
                    grid_remove(i);
                    if(dd==0)a[i]-=lo;else if(dd==1)c[i]+=lo;else if(dd==2)b[i]-=lo;else d[i]+=lo;
                    grid_add(i);
                    any=true;
                }
            }
        }
        if(!any)break;
    }
    
    mt19937 rng(42);
    double tl=4.85;
    double bestTotal=0;
    for(int i=0;i<n;i++) bestTotal+=scoreI(i);
    int ba[205],bb[205],bc[205],bd[205];
    memcpy(ba,a,sizeof(a));memcpy(bb,b,sizeof(b));memcpy(bc,c,sizeof(c));memcpy(bd,d,sizeof(d));
    
    while(ela()<tl){
        double t=ela()/tl;
        double T=0.05*pow(0.00001/0.05,t);
        int i=rng()%n;
        double os=scoreI(i);
        int oa=a[i],ob=b[i],oc=c[i],od2=d[i];
        int mv=rng()%5;
        int range=max(1,(int)(300*(1-t)+1));
        if(mv<4){
            int delta=(int)(rng()%((unsigned)(2*range+1)))-range;
            if(!delta)continue;
            grid_remove(i);
            if(mv==0)a[i]+=delta;else if(mv==1)c[i]+=delta;else if(mv==2)b[i]+=delta;else d[i]+=delta;
        } else {
            // Shrink one side, expand another
            grid_remove(i);
            int s1=rng()%4, s2=rng()%4;
            int d1=(int)(rng()%((unsigned)(range)))+1;
            int d2=(int)(rng()%((unsigned)(range)))+1;
            if(s1==0)a[i]+=d1;else if(s1==1)c[i]-=d1;else if(s1==2)b[i]+=d1;else d[i]-=d1;
            if(s2==0)a[i]-=d2;else if(s2==1)c[i]+=d2;else if(s2==2)b[i]-=d2;else d[i]+=d2;
        }
        if(valid(i,a[i],b[i],c[i],d[i])){
            double ns=scoreI(i);
            double diff=ns-os;
            if(diff>=0||(rng()%1000000)/1000000.0<exp(diff/T)){
                grid_add(i);
                double curTotal=bestTotal-os+ns;
                if(curTotal>bestTotal){
                    bestTotal=curTotal;
                    memcpy(ba,a,sizeof(a));memcpy(bb,b,sizeof(b));memcpy(bc,c,sizeof(c));memcpy(bd,d,sizeof(d));
                }
                continue;
            }
        }
        a[i]=oa;b[i]=ob;c[i]=oc;d[i]=od2;
        grid_add(i);
    }
    memcpy(a,ba,sizeof(a));memcpy(b,bb,sizeof(b));memcpy(c,bc,sizeof(c));memcpy(d,bd,sizeof(d));
    for(int i=0;i<n;i++)cout<<a[i]<<" "<<b[i]<<" "<<c[i]<<" "<<d[i]<<"\n";
}
