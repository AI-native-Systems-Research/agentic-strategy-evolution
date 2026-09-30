#include <bits/stdc++.h>
using namespace std;
const long long MW=20000000LL,MV=25000000LL;
struct Item{string name;int q;long long v,m,l;};
int n;
Item items[12];
long long bestVal;
int bestSol[12],curSol[12];
int sortOrder[12];
chrono::steady_clock::time_point T0;
inline int ms(){return(int)chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-T0).count();}

double lpBound(int idx,long long rw,long long rv,long long val){
    double ub=(double)val;
    double drw=(double)rw, drv=(double)rv;
    for(int i=idx;i<n;i++){
        int si=sortOrder[i];
        if(drw<=0&&drv<=0)break;
        double maxByW=drw/items[si].m;
        double maxByV=drv/items[si].l;
        double f=min({(double)items[si].q, maxByW, maxByV});
        if(f<=0)continue;
        if(f>=(double)items[si].q){
            ub+=(double)items[si].q*items[si].v;
            drw-=(double)items[si].q*items[si].m;
            drv-=(double)items[si].q*items[si].l;
        } else {
            ub+=f*items[si].v;
            break;
        }
    }
    return ub;
}

void solve(int idx,long long rw,long long rv,long long val){
    if(val>bestVal){bestVal=val;memcpy(bestSol,curSol,sizeof(curSol));}
    if(idx==n||ms()>850)return;
    int si=sortOrder[idx];
    int maxK=(int)min({(long long)items[si].q,rw/items[si].m,rv/items[si].l});
    for(int k=maxK;k>=0;k--){
        if(ms()>850)return;
        long long nw=rw-(long long)k*items[si].m;
        long long nv=rv-(long long)k*items[si].l;
        long long nval=val+(long long)k*items[si].v;
        if(lpBound(idx+1,nw,nv,nval)<=(double)bestVal+0.5)continue;
        curSol[si]=k;
        solve(idx+1,nw,nv,nval);
    }
    curSol[si]=0;
}

int main(){
    T0=chrono::steady_clock::now();
    string input((istreambuf_iterator<char>(cin)),{});
    vector<pair<string,tuple<int,long long,long long,long long>>>data;
    regex r("\"([^\"]+)\"\\s*:\\s*\\[\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)\\s*\\]");
    for(sregex_iterator it(input.begin(),input.end(),r),end;it!=end;++it)
        data.push_back({(*it)[1],{stoi((*it)[2]),stoll((*it)[3]),stoll((*it)[4]),stoll((*it)[5])}});
    n=(int)data.size();
    for(int i=0;i<n;i++){auto&[nm,t]=data[i];auto&[q,v,m,l]=t;items[i]={nm,q,v,m,l};}
    bestVal=-1;memset(bestSol,0,sizeof(bestSol));memset(curSol,0,sizeof(curSol));
    auto tryOrder=[&](vector<int>ord){
        for(int i=0;i<n;i++)sortOrder[i]=ord[i];
        memset(curSol,0,sizeof(curSol));
        solve(0,MW,MV,0);
    };
    auto makeOrder=[&](auto cmp)->vector<int>{
        vector<int>o(n);iota(o.begin(),o.end(),0);
        sort(o.begin(),o.end(),cmp);return o;
    };
    tryOrder(makeOrder([](int a,int b){return(double)items[a].v/max(items[a].m,items[a].l)>(double)items[b].v/max(items[b].m,items[b].l);}));
    if(ms()<750)tryOrder(makeOrder([](int a,int b){return(double)items[a].v/(items[a].m+items[a].l)>(double)items[b].v/(items[b].m+items[b].l);}));
    if(ms()<750)tryOrder(makeOrder([](int a,int b){return(double)items[a].v/items[a].m>(double)items[b].v/items[b].m;}));
    if(ms()<750)tryOrder(makeOrder([](int a,int b){return(double)items[a].v/items[a].l>(double)items[b].v/items[b].l;}));
    if(ms()<750)tryOrder(makeOrder([](int a,int b){return items[a].v>items[b].v;}));
    // Local search
    auto eval=[&](int*sol,long long&tw,long long&tv)->long long{
        tw=0;tv=0;long long val=0;
        for(int i=0;i<n;i++){tw+=(long long)sol[i]*items[i].m;tv+=(long long)sol[i]*items[i].l;val+=(long long)sol[i]*items[i].v;}
        return val;
    };
    int lsSol[12];memcpy(lsSol,bestSol,sizeof(bestSol));
    long long tw,tv;long long lsVal=eval(lsSol,tw,tv);
    mt19937 rng(42);
    while(ms()<950){
        int i=rng()%n,j=rng()%n;
        if(i==j)continue;
        int di=(rng()%3)-1, dj=(rng()%3)-1;
        if(di==0&&dj==0)continue;
        int ni=lsSol[i]+di, nj=lsSol[j]+dj;
        if(ni<0||ni>items[i].q||nj<0||nj>items[j].q)continue;
        long long nw=tw+(long long)di*items[i].m+(long long)dj*items[j].m;
        long long nv=tv+(long long)di*items[i].l+(long long)dj*items[j].l;
        if(nw>MW||nv>MV||nw<0||nv<0)continue;
        long long nval=lsVal+(long long)di*items[i].v+(long long)dj*items[j].v;
        if(nval>lsVal){lsSol[i]=ni;lsSol[j]=nj;tw=nw;tv=nv;lsVal=nval;
            if(lsVal>bestVal){bestVal=lsVal;memcpy(bestSol,lsSol,sizeof(lsSol));}
        }
    }
    cout<<"{\n";int c=0;
    for(auto&[nm,t]:data){if(c++)cout<<",\n";int idx=-1;for(int i=0;i<n;i++)if(items[i].name==nm)idx=i;cout<<" \""<<nm<<"\": "<<bestSol[idx];}
    cout<<"\n}\n";
}
