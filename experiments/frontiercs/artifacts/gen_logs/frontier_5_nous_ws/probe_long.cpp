#include <bits/stdc++.h>
using namespace std;
int N, M;
vector<int> adj_g[500001], radj_g[500001];
vector<int> sadj_g[500001];
int outdeg_g[500001], indeg_g[500001];
chrono::high_resolution_clock::time_point T0;
double elapsed(){ return chrono::duration<double>(chrono::high_resolution_clock::now()-T0).count(); }
auto hasEdge=[](int u, int v)->bool{ return binary_search(sadj_g[u].begin(),sadj_g[u].end(),v); };
int globalBest=0;
vector<int> globalBestPath;

int solveRotation(mt19937& rng, int startVertex, double tl, int greedyMode){
    static vector<int> nxt, prv, dout; static vector<char> used; static bool inited=false;
    if(!inited){nxt.resize(N+1);prv.resize(N+1);dout.resize(N+1);used.resize(N+1);inited=true;}
    for(int u=1;u<=N;u++){dout[u]=outdeg_g[u];used[u]=0;nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;for(int u:radj_g[startVertex])if(!used[u])dout[u]--;
    int head=startVertex,tail=startVertex,pathLen=1;
    auto mark=[&](int v){used[v]=1;for(int u:radj_g[v])if(!used[u])dout[u]--;};
    auto extF=[&]()->bool{bool ext=false;while(true){int cnt=0;int picks[16];
        if(greedyMode==2){int bd=-1;for(int v:adj_g[tail])if(!used[v]){if(dout[v]>bd){bd=dout[v];cnt=1;picks[0]=v;}else if(dout[v]==bd&&cnt<16)picks[cnt++]=v;}}
        else if(greedyMode==0){int bd=INT_MAX;for(int v:adj_g[tail])if(!used[v]){if(dout[v]<bd){bd=dout[v];cnt=1;picks[0]=v;}else if(dout[v]==bd&&cnt<16)picks[cnt++]=v;}}
        else{for(int v:adj_g[tail])if(!used[v]&&cnt<16)picks[cnt++]=v;}
        if(!cnt)break;int p=picks[rng()%cnt];nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;}return ext;};
    auto extB=[&]()->bool{bool ext=false;while(true){int cnt=0;int picks[16];
        if(greedyMode==2){int bd=-1;for(int u:radj_g[head])if(!used[u]){if(dout[u]>bd){bd=dout[u];cnt=1;picks[0]=u;}else if(dout[u]==bd&&cnt<16)picks[cnt++]=u;}}
        else if(greedyMode==0){int bd=INT_MAX;for(int u:radj_g[head])if(!used[u]){if(dout[u]<bd){bd=dout[u];cnt=1;picks[0]=u;}else if(dout[u]==bd&&cnt<16)picks[cnt++]=u;}}
        else{for(int u:radj_g[head])if(!used[u]&&cnt<16)picks[cnt++]=u;}
        if(!cnt)break;int p=picks[rng()%cnt];prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;}return ext;};
    auto ins=[&]()->bool{bool ch=false;int u=head;while(u){int w=nxt[u];if(!w)break;for(int v:adj_g[u])if(!used[v]&&hasEdge(v,w)){nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;}u=w;}return ch;};
    extF();extB();for(int p2=0;p2<15;p2++){if(!ins())break;extF();extB();}
    // Long rotation with extB in the loop too
    while(pathLen<N && elapsed()<tl){
        bool anyProgress=false;
        if(extF()){anyProgress=true;continue;}
        if(extB()){anyProgress=true;extF();continue;}
        // Rotation
        vector<int> sc;for(int v:adj_g[tail])if(used[v]&&v!=tail)sc.push_back(v);if(sc.empty())break;
        for(int i=sc.size()-1;i>0;i--){int j2=rng()%(i+1);swap(sc[i],sc[j2]);}
        bool rotated=false;
        for(int vi:sc){if(rotated)break;
            if(vi==head){vector<int>cd;int u2=head;while(u2&&u2!=tail){bool h=false;for(int w:adj_g[u2])if(!used[w]){h=true;break;}if(h)cd.push_back(u2);u2=nxt[u2];}if(cd.empty())continue;int vj=cd[rng()%cd.size()];int nH=nxt[vj];nxt[tail]=head;prv[head]=tail;nxt[vj]=0;prv[nH]=0;head=nH;tail=vj;rotated=true;}
            else{int e=prv[vi];if(!e)continue;vector<int>gB,aB;int vj2=vi;while(vj2&&nxt[vj2]){int c=nxt[vj2];if(c&&hasEdge(e,c)){bool h=false;for(int w:adj_g[vj2])if(!used[w]){h=true;break;}if(h)gB.push_back(vj2);else aB.push_back(vj2);}if(vj2==tail)break;vj2=nxt[vj2];}int vj=0;if(!gB.empty())vj=gB[rng()%gB.size()];else if(!aB.empty())vj=aB[rng()%aB.size()];if(!vj)continue;int c=nxt[vj];nxt[e]=c;prv[c]=e;nxt[tail]=vi;prv[vi]=tail;nxt[vj]=0;tail=vj;rotated=true;}
        }
        if(!rotated)break;
        extF();extB();
    }
    for(int p3=0;p3<10&&elapsed()<tl;p3++){if(!ins())break;extF();extB();}
    for(int i2=0;i2<3&&elapsed()<tl;i2++){bool ch=false;for(int v=1;v<=N;v++){if(used[v])continue;if(hasEdge(v,head)){prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;ch=true;}else if(hasEdge(tail,v)){nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;ch=true;}}if(!ch)break;ins();extF();extB();}
    if(pathLen>globalBest){globalBest=pathLen;globalBestPath.clear();for(int u=head;u;u=nxt[u])globalBestPath.push_back(u);}
    return pathLen;
}
int main(){
    T0=chrono::high_resolution_clock::now();
    scanf("%d %d",&N,&M);int a[10];for(int i=0;i<10;i++)scanf("%d",&a[i]);
    for(int i=0;i<M;i++){int u,v;scanf("%d %d",&u,&v);adj_g[u].push_back(v);radj_g[v].push_back(u);outdeg_g[u]++;indeg_g[v]++;}
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}
    // Try: longer budgets per attempt
    int attempts=0;
    for(int a=0;elapsed()<3.5;a++){
        mt19937 rng(a*137+7919);
        int s=(rng()%N)+1;
        solveRotation(rng,s,min(elapsed()+0.5,3.5),2);
        attempts++;
    }
    fprintf(stderr,"attempts=%d best=%d (%.1f%%)\n",attempts,globalBest,100.0*globalBest/N);
    printf("%d\n",globalBest);for(int i=0;i<globalBest;i++){if(i)printf(" ");printf("%d",globalBestPath[i]);}printf("\n");
    return 0;
}
