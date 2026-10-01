#include <bits/stdc++.h>
using namespace std;
static const int MAXN=1001;
static const int WORDS=(MAXN+63)/64;
typedef unsigned long long u64;
u64 adj[MAXN][WORDS];
int N,M,nw;
int bestLen,bestClique[MAXN],curClique[MAXN],curLen;
chrono::steady_clock::time_point startT;
bool timeout_;
inline long long ems(){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-startT).count();}
inline void bset(u64*b,int i){b[i>>6]|=1ULL<<(i&63);}
inline void bclr(u64*b,int i){b[i>>6]&=~(1ULL<<(i&63));}
inline bool btest(u64*b,int i){return(b[i>>6]>>(i&63))&1;}
inline int bcount(u64*b){int c=0;for(int i=0;i<nw;i++)c+=__builtin_popcountll(b[i]);return c;}
inline void band(u64*d,u64*a,u64*b){for(int i=0;i<nw;i++)d[i]=a[i]&b[i];}
inline void bzro(u64*b){memset(b,0,sizeof(u64)*nw);}
u64 Pstack[200][WORDS];
int colorOrder[MAXN],colorNum[MAXN];
int colorBound(u64*P){
    static u64 cc[MAXN][WORDS];int verts[MAXN],nv=0,nc=0;
    for(int w=0;w<nw;w++){u64 b=P[w];while(b){int bit=__builtin_ctzll(b);verts[nv++]=(w<<6)|bit;b&=b-1;}}
    for(int i=0;i<nv;i++){int v=verts[i],c;
        for(c=0;c<nc;c++){bool ok=true;for(int w=0;w<nw;w++)if(adj[v][w]&cc[c][w]){ok=false;break;}if(ok)break;}
        if(c==nc){bzro(cc[c]);nc++;}bset(cc[c],v);
        colorOrder[i]=v;colorNum[i]=c+1;}
    return nc;
}
void expand(u64*P,int np,int depth){
    if(timeout_)return;
    if(np==0){if(curLen>bestLen){bestLen=curLen;memcpy(bestClique,curClique,sizeof(int)*curLen);}return;}
    int nc=colorBound(P);
    if(curLen+nc<=bestLen)return;
    for(int i=np-1;i>=0;i--){
        if(timeout_)return;
        if((i&15)==0&&ems()>1900){timeout_=true;return;}
        if(curLen+colorNum[i]<=bestLen)return;
        int v=colorOrder[i];
        band(Pstack[depth],P,adj[v]);
        int nnp=bcount(Pstack[depth]);
        curClique[curLen++]=v;
        expand(Pstack[depth],nnp,depth+1);
        curLen--;bclr(P,v);np--;
    }
}
int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    startT=chrono::steady_clock::now();timeout_=false;
    cin>>N>>M;nw=(N+64)/64;memset(adj,0,sizeof(adj));
    for(int i=0;i<M;i++){int u,v;cin>>u>>v;bset(adj[u],v);bset(adj[v],u);}
    vector<int>deg(N+1),order;vector<bool>rem(N+1,false);
    for(int i=1;i<=N;i++)deg[i]=bcount(adj[i]);
    for(int it=0;it<N;it++){int b=-1,bd=N+1;for(int i=1;i<=N;i++)if(!rem[i]&&deg[i]<bd){bd=deg[i];b=i;}rem[b]=true;order.push_back(b);for(int j=1;j<=N;j++)if(!rem[j]&&btest(adj[b],j))deg[j]--;}
    bestLen=0;curLen=0;
    u64 P[WORDS];
    for(int idx=N-1;idx>=0;idx--){
        if(timeout_)break;int v=order[idx];bzro(P);int np=0;
        for(int j=idx+1;j<N;j++)if(btest(adj[v],order[j])){bset(P,order[j]);np++;}
        if(np+1<=bestLen)continue;curLen=0;curClique[curLen++]=v;expand(P,np,0);
    }
    vector<int>inc(N+1,0);for(int i=0;i<bestLen;i++)inc[bestClique[i]]=1;
    for(int i=1;i<=N;i++)cout<<inc[i]<<"\n";
}
