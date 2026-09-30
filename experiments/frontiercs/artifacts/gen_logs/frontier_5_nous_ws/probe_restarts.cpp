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

// Simple greedy construction (no rotation) - as fast as possible
int solveGreedy(mt19937& rng, int startVertex, int greedyMode){
    static vector<int> nxt, prv, dout;
    static vector<char> used;
    static bool inited=false;
    if(!inited){ nxt.resize(N+1); prv.resize(N+1); dout.resize(N+1); used.resize(N+1); inited=true; }

    for(int u=1;u<=N;u++){dout[u]=outdeg_g[u];used[u]=0;nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;
    for(int u:radj_g[startVertex]) if(!used[u]) dout[u]--;

    int head=startVertex, tail=startVertex, pathLen=1;
    auto mark=[&](int v){ used[v]=1; for(int u:radj_g[v]) if(!used[u]) dout[u]--; };

    auto extF=[&](int mode) -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(mode == 0){ // Warnsdorff
                int bd=INT_MAX;
                for(int v:adj_g[tail]) if(!used[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
            } else if(mode == 2){ // max-degree
                int bd=-1;
                for(int v:adj_g[tail]) if(!used[v]){
                    if(dout[v]>bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
            } else { // random
                for(int v:adj_g[tail]) if(!used[v] && cnt<16){picks[cnt++]=v;}
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto extB=[&](int mode) -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(mode == 0){
                int bd=INT_MAX;
                for(int u:radj_g[head]) if(!used[u]){
                    if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
            } else if(mode == 2){
                int bd=-1;
                for(int u:radj_g[head]) if(!used[u]){
                    if(dout[u]>bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
            } else {
                for(int u:radj_g[head]) if(!used[u] && cnt<16){picks[cnt++]=u;}
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto ins=[&]()->bool{
        bool ch=false;
        int u=head;
        while(u){
            int w=nxt[u]; if(!w)break;
            for(int v:adj_g[u]) if(!used[v]&&hasEdge(v,w)){
                nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;
            }
            u=w;
        }
        return ch;
    };

    extF(greedyMode); extB(greedyMode);
    for(int p2=0;p2<15;p2++){
        bool ch=ins();
        if(ch){extF(greedyMode);extB(greedyMode);}
        else break;
    }
    // Try scanning for loose vertices
    for(int v=1;v<=N;v++){
        if(used[v]) continue;
        if(hasEdge(v,head)){prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;}
        else if(hasEdge(tail,v)){nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;}
    }
    for(int p2=0;p2<5;p2++){
        bool ch=ins();
        if(ch){extF(greedyMode);extB(greedyMode);}
        else break;
    }

    if(pathLen > globalBest) globalBest = pathLen;
    return pathLen;
}

int main(){
    T0 = chrono::high_resolution_clock::now();
    scanf("%d %d", &N, &M);
    int a[10]; for(int i=0;i<10;i++) scanf("%d", &a[i]);
    for(int i=0;i<M;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj_g[u].push_back(v); radj_g[v].push_back(u);
        outdeg_g[u]++; indeg_g[v]++;
    }
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}

    fprintf(stderr, "n=%d m=%d avg_deg=%.2f\n", N, M, (double)M/N);
    
    int bestByMode[4] = {};  // warnsdorff, random, maxdeg
    int totalAttempts = 0;
    
    for(int attempt=0; elapsed() < 3.5; attempt++){
        int mode = attempt % 3; // 0=warnsdorff, 1=random, 2=maxdeg
        mt19937 rng(attempt * 137 + 7919);
        int s = (rng()%N)+1;
        int k = solveGreedy(rng, s, mode);
        if(k > bestByMode[mode]) bestByMode[mode] = k;
        totalAttempts++;
    }
    
    fprintf(stderr, "Attempts=%d best=%d  warnsdorff=%d random=%d maxdeg=%d  time=%.2fs\n",
        totalAttempts, globalBest, bestByMode[0], bestByMode[1], bestByMode[2], elapsed());
    
    printf("%d\n1\n", globalBest);
    return 0;
}
