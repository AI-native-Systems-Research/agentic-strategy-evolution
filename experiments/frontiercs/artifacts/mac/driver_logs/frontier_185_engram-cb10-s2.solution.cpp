#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 1001;
static const int WORDS = (MAXN + 63) / 64;
typedef unsigned long long u64;

u64 adj[MAXN][WORDS];
int N, M;
int bestClique[MAXN], bestLen;
int curClique[MAXN], curLen;
chrono::steady_clock::time_point startT;
bool timeout_;
int nw;

inline long long ems(){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-startT).count();}
inline void bset(u64*bs,int i){bs[i>>6]|=1ULL<<(i&63);}
inline bool btest(u64*bs,int i){return(bs[i>>6]>>(i&63))&1;}
inline void bclear(u64*bs,int i){bs[i>>6]&=~(1ULL<<(i&63));}
inline void bzero(u64*bs,int w){memset(bs,0,w*8);}
inline int bcount(u64*bs,int w){int c=0;for(int i=0;i<w;i++)c+=__builtin_popcountll(bs[i]);return c;}
inline void band(u64*r,u64*a,u64*b,int w){for(int i=0;i<w;i++)r[i]=a[i]&b[i];}

struct CV{int color;int vertex;};
CV cvbuf[MAXN];
int cvlen;

int colorBound(u64*P){
    static int verts[MAXN];
    int nv=0;
    for(int w=0;w<nw;w++){u64 bits=P[w];while(bits){int b=__builtin_ctzll(bits);verts[nv++]=(w<<6)+b;bits&=bits-1;}}
    if(!nv){cvlen=0;return 0;}
    static int subdeg[MAXN];
    for(int i=0;i<nv;i++){static u64 tmp[WORDS];band(tmp,adj[verts[i]],P,nw);subdeg[i]=bcount(tmp,nw);}
    static int idx[MAXN];
    for(int i=0;i<nv;i++)idx[i]=i;
    sort(idx,idx+nv,[](int a,int b){return subdeg[a]>subdeg[b];});
    static u64 colorSets[MAXN][WORDS];
    int nc=0;
    static int vcol[MAXN];
    for(int ii=0;ii<nv;ii++){
        int v=verts[idx[ii]];
        int c=-1;
        for(int cc=0;cc<nc;cc++){bool h=false;for(int w=0;w<nw;w++)if(adj[v][w]&colorSets[cc][w]){h=true;break;}if(!h){c=cc;break;}}
        if(c==-1){c=nc;bzero(colorSets[nc],nw);nc++;}
        vcol[ii]=c;bset(colorSets[c],v);
    }
    cvlen=nv;
    for(int ii=0;ii<nv;ii++){cvbuf[ii].color=vcol[ii]+1;cvbuf[ii].vertex=verts[idx[ii]];}
    sort(cvbuf,cvbuf+cvlen,[](const CV&a,const CV&b){return a.color<b.color;});
    return nc;
}

void expand(u64*P){
    if(timeout_)return;
    if(!bcount(P,nw)){if(curLen>bestLen){bestLen=curLen;memcpy(bestClique,curClique,curLen*sizeof(int));}return;}
    int nc=colorBound(P);
    if(curLen+nc<=bestLen)return;
    for(int i=cvlen-1;i>=0;i--){
        if(timeout_)return;
        if(ems()>1900){timeout_=true;return;}
        if(curLen+cvbuf[i].color<=bestLen)return;
        int v=cvbuf[i].vertex;
        static u64 mask[WORDS];bzero(mask,nw);
        for(int j=0;j<i;j++)bset(mask,cvbuf[j].vertex);
        static u64 newP[WORDS];
        for(int w=0;w<nw;w++)newP[w]=mask[w]&adj[v][w];
        curClique[curLen++]=v;expand(newP);curLen--;
    }
}

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    startT=chrono::steady_clock::now();timeout_=false;
    cin>>N>>M;nw=(N+64)/64;
    memset(adj,0,sizeof(adj));
    for(int i=0;i<M;i++){int u,v;cin>>u>>v;bset(adj[u],v);bset(adj[v],u);}
    vector<int>deg(N+1);for(int i=1;i<=N;i++)deg[i]=bcount(adj[i],nw);
    vector<bool>rem(N+1,false);vector<int>order;order.reserve(N);
    // Bucket-based degeneracy
    int maxd=*max_element(deg.begin()+1,deg.end());
    vector<vector<int>>bucket(maxd+2);
    for(int i=1;i<=N;i++)bucket[deg[i]].push_back(i);
    vector<int>pos(N+1);
    for(int it=0;it<N;it++){
        int d=0;while(d<=maxd&&bucket[d].empty())d++;
        int best=bucket[d].back();bucket[d].pop_back();
        rem[best]=true;order.push_back(best);
        for(int w=0;w<nw;w++){u64 bits=adj[best][w];while(bits){int b=(w<<6)+__builtin_ctzll(bits);bits&=bits-1;if(b>=1&&b<=N&&!rem[b]){bucket[deg[b]].erase(find(bucket[deg[b]].begin(),bucket[deg[b]].end(),b));deg[b]--;bucket[deg[b]].push_back(b);}}}
    }
    bestLen=0;
    for(int start=N-1;start>=max(0,N-80);start--){
        static u64 ca[WORDS];for(int w=0;w<nw;w++)ca[w]=~0ULL;
        int cl[MAXN],clen=0,sv=order[start];
        cl[clen++]=sv;band(ca,ca,adj[sv],nw);bset(ca,sv);
        for(int i=N-1;i>=0;i--){int v=order[i];if(v==sv)continue;if(btest(ca,v)){cl[clen++]=v;band(ca,ca,adj[v],nw);bset(ca,v);}}
        if(clen>bestLen){bestLen=clen;memcpy(bestClique,cl,clen*sizeof(int));}
    }
    curLen=0;
    for(int idx=N-1;idx>=0;idx--){
        if(timeout_)break;
        int v=order[idx];
        static u64 P[WORDS];bzero(P,nw);
        for(int j=idx+1;j<N;j++)if(btest(adj[v],order[j]))bset(P,order[j]);
        if(bcount(P,nw)+1<=bestLen)continue;
        curLen=0;curClique[curLen++]=v;expand(P);
    }
    vector<int>inc(N+1,0);for(int i=0;i<bestLen;i++)inc[bestClique[i]]=1;
    for(int i=1;i<=N;i++)cout<<inc[i]<<"\n";
}
