#include <bits/stdc++.h>
using namespace std;
int N, M;
int a_thresh[10];
vector<int> adj_g[500001], radj_g[500001];
vector<int> sadj_g[500001];
int outdeg_g[500001], indeg_g[500001];
chrono::high_resolution_clock::time_point T0;
double elapsed(){return chrono::duration<double>(chrono::high_resolution_clock::now()-T0).count();}
auto hasEdge=[](int u, int v)->bool{return binary_search(sadj_g[u].begin(),sadj_g[u].end(),v);};
int globalBest=0;
vector<int> globalBestPath;

int solveRotation(mt19937& rng, int startVertex, double tl, int greedyMode=0){
    static vector<int> nxt, prv, dout;
    static vector<char> used;
    static bool inited=false;
    if(!inited){nxt.resize(N+1);prv.resize(N+1);dout.resize(N+1);used.resize(N+1);inited=true;}
    for(int u=1;u<=N;u++){dout[u]=outdeg_g[u];used[u]=0;nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;
    for(int u:radj_g[startVertex]) if(!used[u]) dout[u]--;
    int head=startVertex, tail=startVertex, pathLen=1;
    auto mark=[&](int v){used[v]=1;for(int u:radj_g[v]) if(!used[u]) dout[u]--;};
    auto extF=[&]() -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(greedyMode==0){int bd=INT_MAX;for(int v:adj_g[tail]) if(!used[v]){if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}}}
            else if(greedyMode==1){for(int v:adj_g[tail]) if(!used[v]&&cnt<16){picks[cnt++]=v;}}
            else{int bd=-1;for(int v:adj_g[tail]) if(!used[v]){if(dout[v]>bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}}}
            if(!cnt)break;
            int p=picks[rng()%cnt];nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto extB=[&]() -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(greedyMode==0){int bd=INT_MAX;for(int u:radj_g[head]) if(!used[u]){if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}}}
            else if(greedyMode==1){for(int u:radj_g[head]) if(!used[u]&&cnt<16){picks[cnt++]=u;}}
            else{int bd=-1;for(int u:radj_g[head]) if(!used[u]){if(dout[u]>bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}}}
            if(!cnt)break;
            int p=picks[rng()%cnt];prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto ins=[&]()->bool{bool ch=false;int u=head;while(u){int w=nxt[u];if(!w)break;for(int v:adj_g[u])if(!used[v]&&hasEdge(v,w)){nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;}u=w;}return ch;};
    extF();extB();
    for(int p2=0;p2<15;p2++){bool ch=ins();if(ch){extF();extB();}else break;}
    while(pathLen<N&&elapsed()<tl){
        if(extF()){extB();continue;}
        int chainLen=1000;bool chainExtended=false;
        for(int ci=0;ci<chainLen&&elapsed()<tl;ci++){
            int scCnt=0;int scBuf[64];
            for(int v:adj_g[tail]){if(used[v]&&v!=tail&&scCnt<64) scBuf[scCnt++]=v;}
            if(!scCnt) break;
            for(int i=scCnt-1;i>0;i--){int j2=rng()%(i+1);swap(scBuf[i],scBuf[j2]);}
            bool rotated=false;
            for(int si=0;si<scCnt&&!rotated;si++){
                int vi=scBuf[si];
                if(vi==head){
                    int bestCand=0,candCnt=0;int u2=head;
                    while(u2&&u2!=tail){bool hasUnvis=false;for(int w:adj_g[u2])if(!used[w]){hasUnvis=true;break;}if(hasUnvis){candCnt++;if(rng()%candCnt==0)bestCand=u2;}u2=nxt[u2];}
                    if(!bestCand)continue;
                    int newHead=nxt[bestCand];nxt[tail]=head;prv[head]=tail;nxt[bestCand]=0;prv[newHead]=0;head=newHead;tail=bestCand;rotated=true;
                } else {
                    int e=prv[vi];if(!e)continue;
                    int bestGood=0,bestAny=0;int goodCnt=0,anyCnt=0;int vj2=vi;
                    while(vj2&&nxt[vj2]){int c=nxt[vj2];if(c&&hasEdge(e,c)){bool hasUnvis=false;for(int w:adj_g[vj2])if(!used[w]){hasUnvis=true;break;}if(hasUnvis){goodCnt++;if(rng()%goodCnt==0)bestGood=vj2;}else{anyCnt++;if(rng()%anyCnt==0)bestAny=vj2;}}if(vj2==tail)break;vj2=nxt[vj2];}
                    int vj=bestGood?bestGood:bestAny;if(!vj)continue;
                    int c=nxt[vj];nxt[e]=c;prv[c]=e;nxt[tail]=vi;prv[vi]=tail;nxt[vj]=0;tail=vj;rotated=true;
                }
            }
            if(!rotated)break;
            if(extF()){extB();chainExtended=true;break;}
        }
        if(!chainExtended) break;
    }
    extB();
    for(int p3=0;p3<5&&elapsed()<tl;p3++){bool ch=ins();if(ch){extF();extB();}else break;}
    for(int iter2=0;iter2<3&&elapsed()<tl;iter2++){
        bool ch=false;
        for(int v=1;v<=N;v++){if(used[v])continue;if(hasEdge(v,head)){prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;ch=true;}else if(hasEdge(tail,v)){nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;ch=true;}}
        if(!ch)break;ins();extF();extB();
    }
    if(pathLen>globalBest){
        globalBest=pathLen;globalBestPath.clear();globalBestPath.reserve(pathLen);
        for(int u=head;u;u=nxt[u]) globalBestPath.push_back(u);
    }
    return pathLen;
}

int main(){
    T0 = chrono::high_resolution_clock::now();
    scanf("%d %d",&N,&M);
    for(int i=0;i<10;i++) scanf("%d",&a_thresh[i]);
    for(int i=0;i<M;i++){int u,v;scanf("%d%d",&u,&v);adj_g[u].push_back(v);radj_g[v].push_back(u);outdeg_g[u]++;indeg_g[v]++;}
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}
    
    vector<int> starts;
    for(int u=1;u<=N;u++) if(indeg_g[u]==0) starts.push_back(u);
    {
        vector<int> order(N);iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[](int a,int b){return indeg_g[a]<indeg_g[b];});
        for(int i=0;i<min(N,20);i++){bool dup=false;for(int s:starts)if(s==order[i])dup=true;if(!dup)starts.push_back(order[i]);}
        sort(order.begin(),order.end(),[](int a,int b){return outdeg_g[a]-indeg_g[a]>outdeg_g[b]-indeg_g[b];});
        for(int i=0;i<min(N,10);i++){bool dup=false;for(int s:starts)if(s==order[i])dup=true;if(!dup)starts.push_back(order[i]);}
    }
    
    // Debug: test each greedy mode separately
    for(int mode=0;mode<3;mode++){
        globalBest=0;globalBestPath.clear();
        T0 = chrono::high_resolution_clock::now();
        for(int attempt=0;elapsed()<3.7;attempt++){
            mt19937 rng(attempt*97+42);
            double tl=min(elapsed()+0.15,3.7);
            int s;
            if(attempt<(int)starts.size()) s=starts[attempt]; else s=(rng()%N)+1;
            solveRotation(rng,s,tl,mode);
        }
        fprintf(stderr,"Mode %d: best=%d\n",mode,globalBest);
    }
    
    // Also test mixed
    globalBest=0;globalBestPath.clear();
    T0 = chrono::high_resolution_clock::now();
    for(int attempt=0;elapsed()<3.7;attempt++){
        mt19937 rng(attempt*97+42);
        double tl=min(elapsed()+0.15,3.7);
        int mode=attempt%3;
        int s;
        if(attempt<(int)starts.size()) s=starts[attempt]; else s=(rng()%N)+1;
        solveRotation(rng,s,tl,mode);
    }
    fprintf(stderr,"Mixed: best=%d\n",globalBest);
    
    printf("%d\n",globalBest);
    for(int i=0;i<globalBest;i++){if(i)printf(" ");printf("%d",globalBestPath[i]);}
    printf("\n");
    return 0;
}
