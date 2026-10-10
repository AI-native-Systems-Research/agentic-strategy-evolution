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

int solveRotation(mt19937& rng, int startVertex, double tl, int greedyMode, int maxRotLimit){
    static vector<int> nxt, prv, dout;
    static vector<char> used;
    static bool inited=false;
    if(!inited){ nxt.resize(N+1); prv.resize(N+1); dout.resize(N+1); used.resize(N+1); inited=true; }
    for(int u=1;u<=N;u++){dout[u]=outdeg_g[u];used[u]=0;nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;
    for(int u:radj_g[startVertex]) if(!used[u]) dout[u]--;
    int head=startVertex, tail=startVertex, pathLen=1;
    auto mark=[&](int v){ used[v]=1; for(int u:radj_g[v]) if(!used[u]) dout[u]--; };
    auto extF=[&]() -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(greedyMode==0){int bd=INT_MAX;for(int v:adj_g[tail])if(!used[v]){if(dout[v]<bd){bd=dout[v];cnt=1;picks[0]=v;}else if(dout[v]==bd&&cnt<16)picks[cnt++]=v;}}
            else if(greedyMode==2){int bd=-1;for(int v:adj_g[tail])if(!used[v]){if(dout[v]>bd){bd=dout[v];cnt=1;picks[0]=v;}else if(dout[v]==bd&&cnt<16)picks[cnt++]=v;}}
            else{for(int v:adj_g[tail])if(!used[v]&&cnt<16)picks[cnt++]=v;}
            if(!cnt)break;
            int p=picks[rng()%cnt]; nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto extB=[&]() -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(greedyMode==0){int bd=INT_MAX;for(int u:radj_g[head])if(!used[u]){if(dout[u]<bd){bd=dout[u];cnt=1;picks[0]=u;}else if(dout[u]==bd&&cnt<16)picks[cnt++]=u;}}
            else if(greedyMode==2){int bd=-1;for(int u:radj_g[head])if(!used[u]){if(dout[u]>bd){bd=dout[u];cnt=1;picks[0]=u;}else if(dout[u]==bd&&cnt<16)picks[cnt++]=u;}}
            else{for(int u:radj_g[head])if(!used[u]&&cnt<16)picks[cnt++]=u;}
            if(!cnt)break;
            int p=picks[rng()%cnt]; prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto ins=[&]()->bool{
        bool ch=false; int u=head;
        while(u){ int w=nxt[u]; if(!w)break;
            for(int v:adj_g[u]) if(!used[v]&&hasEdge(v,w)){nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;}
            u=w;
        }
        return ch;
    };
    // Two-vertex insertion: check if u→x→y→w exists for unused x,y
    auto ins2=[&]()->bool{
        bool ch=false; int u=head;
        while(u){ int w=nxt[u]; if(!w)break;
            for(int x:adj_g[u]) if(!used[x]){
                for(int y:adj_g[x]) if(!used[y]&&y!=x&&hasEdge(y,w)){
                    nxt[u]=x;prv[x]=u;nxt[x]=y;prv[y]=x;nxt[y]=w;prv[w]=y;
                    mark(x);mark(y);pathLen+=2;ch=true;
                    w=y; break;
                }
                if(ch) break;
            }
            u=nxt[u]; if(u==w) u=nxt[u]; // skip if we just inserted
        }
        return ch;
    };
    
    extF(); extB();
    for(int p2=0;p2<15;p2++){bool ch=ins();if(ch){extF();extB();}else break;}
    // Try 2-vertex insertion
    for(int p2=0;p2<5;p2++){bool ch=ins2();if(ch){extF();extB();ins();}else break;}
    
    int rotCount=0;
    while(pathLen<N && rotCount<maxRotLimit && elapsed()<tl){
        if(extF()) continue;
        rotCount++;
        vector<int> shortcuts;
        for(int v:adj_g[tail]) if(used[v]&&v!=tail) shortcuts.push_back(v);
        if(shortcuts.empty()) break;
        for(int i=shortcuts.size()-1;i>0;i--){int j2=rng()%(i+1);swap(shortcuts[i],shortcuts[j2]);}
        bool rotated=false;
        for(int vi:shortcuts){
            if(rotated)break;
            if(vi==head){
                vector<int> cands; int u2=head;
                while(u2&&u2!=tail){bool h=false;for(int w:adj_g[u2])if(!used[w]){h=true;break;}if(h)cands.push_back(u2);u2=nxt[u2];}
                if(cands.empty())continue;
                int vj=cands[rng()%cands.size()];
                int newHead=nxt[vj]; nxt[tail]=head;prv[head]=tail;nxt[vj]=0;prv[newHead]=0;head=newHead;tail=vj;rotated=true;
            } else {
                int e=prv[vi];if(!e)continue;
                vector<int> goodB,anyB; int vj2=vi;
                while(vj2&&nxt[vj2]){int c=nxt[vj2];if(c&&hasEdge(e,c)){bool h=false;for(int w:adj_g[vj2])if(!used[w]){h=true;break;}if(h)goodB.push_back(vj2);else anyB.push_back(vj2);}if(vj2==tail)break;vj2=nxt[vj2];}
                int vj=0;if(!goodB.empty())vj=goodB[rng()%goodB.size()];else if(!anyB.empty())vj=anyB[rng()%anyB.size()];if(!vj)continue;
                int c=nxt[vj];nxt[e]=c;prv[c]=e;nxt[tail]=vi;prv[vi]=tail;nxt[vj]=0;tail=vj;rotated=true;
            }
        }
        if(!rotated)break;
        extF();
    }
    extB();
    for(int p3=0;p3<5;p3++){bool ch=ins();if(ch){extF();extB();}else break;}
    for(int p3=0;p3<3;p3++){bool ch=ins2();if(ch){extF();extB();ins();}else break;}
    for(int i2=0;i2<3&&elapsed()<tl;i2++){
        bool ch=false;
        for(int v=1;v<=N;v++){if(used[v])continue;if(hasEdge(v,head)){prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;ch=true;}else if(hasEdge(tail,v)){nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;ch=true;}}
        if(!ch)break; ins();ins2();extF();extB();
    }
    if(pathLen>globalBest){
        globalBest=pathLen;
        globalBestPath.clear();
        for(int u=head;u;u=nxt[u]) globalBestPath.push_back(u);
    }
    return pathLen;
}

int main(){
    T0=chrono::high_resolution_clock::now();
    scanf("%d %d",&N,&M);
    int a[10]; for(int i=0;i<10;i++) scanf("%d",&a[i]);
    for(int i=0;i<M;i++){int u,v;scanf("%d %d",&u,&v);adj_g[u].push_back(v);radj_g[v].push_back(u);outdeg_g[u]++;indeg_g[v]++;}
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}

    double avgDeg=(double)M/N;
    
    vector<int> starts;
    for(int u=1;u<=N;u++) if(indeg_g[u]==0) starts.push_back(u);
    {
        vector<int> order(N); iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[](int a,int b){return outdeg_g[a]-indeg_g[a]>outdeg_g[b]-indeg_g[b];});
        for(int i=0;i<min(N,20);i++){bool dup=false;for(int s:starts)if(s==order[i])dup=true;if(!dup)starts.push_back(order[i]);}
    }

    // Phase 1: Warnsdorff seed 42 (short budget for sparse graphs)
    double phase1_limit;
    {
        mt19937 rng0(42);
        for(int s:starts){
            if(globalBest==N||elapsed()>1.5) break;
            solveRotation(rng0, s, 1.5, 0, min(N*50, 2000000));
        }
        // Check coverage after starters
        double coverage = (double)globalBest / N;
        if(coverage >= 0.8){
            // Continue Phase 1 — graph is solvable by seed 42
            phase1_limit = 3.0;
            while(globalBest<N && elapsed()<phase1_limit){
                int s=(rng0()%N)+1;
                solveRotation(rng0, s, phase1_limit, 0, min(N*50, 2000000));
            }
        } else {
            phase1_limit = elapsed(); // Phase 1 done, switch to Phase 2
        }
    }
    
    fprintf(stderr, "Phase1 done: coverage=%.1f%% time=%.2fs\n", 100.0*globalBest/N, elapsed());

    // Phase 2: Multi-restart max-degree with adaptive parameters
    {
        int rotLimit;
        double perAttempt;
        if(avgDeg <= 4) { rotLimit = 1000; perAttempt = 0.04; }
        else if(avgDeg <= 7) { rotLimit = 5000; perAttempt = 0.12; }
        else { rotLimit = min(N*50, 2000000); perAttempt = 0.3; }
        
        int attempts=0;
        for(int attempt=0; elapsed()<3.5; attempt++){
            mt19937 rng(attempt*137+7919);
            double tl = min(elapsed()+perAttempt, 3.5);
            
            int s;
            if(attempt < (int)starts.size()) s = starts[attempt];
            else s = (rng()%N)+1;
            
            // Mix modes: 70% max-deg, 20% warnsdorff, 10% random
            int mode;
            if(attempt % 10 < 7) mode = 2; // max-deg
            else if(attempt % 10 < 9) mode = 0; // warnsdorff
            else mode = 1; // random
            
            solveRotation(rng, s, tl, mode, rotLimit);
            attempts++;
        }
        
        fprintf(stderr, "Phase2 done: attempts=%d best=%d (%.1f%%) time=%.2fs\n",
            attempts, globalBest, 100.0*globalBest/N, elapsed());
    }

    printf("%d\n",globalBest);
    for(int i=0;i<globalBest;i++){if(i)printf(" ");printf("%d",globalBestPath[i]);}
    printf("\n");
    return 0;
}
