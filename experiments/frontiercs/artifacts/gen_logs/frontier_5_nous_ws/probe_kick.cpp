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

// Full solver with kick-restart: build path, then repeatedly kick tail and re-extend
void solveWithKick(mt19937& rng, int startVertex, double tl){
    vector<int> nxt(N+1), prv(N+1), dout(N+1);
    vector<char> used(N+1,0);

    // Rebuild dout from scratch (not static - we'll modify it during kicks)
    auto rebuildDout = [&](){
        for(int u=1;u<=N;u++){
            dout[u]=0;
            for(int v:adj_g[u]) if(!used[v]) dout[u]++;
        }
    };

    for(int u=1;u<=N;u++){nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;
    int head=startVertex, tail=startVertex, pathLen=1;
    
    rebuildDout();
    
    auto mark=[&](int v){ 
        used[v]=1; 
        for(int u:radj_g[v]) if(!used[u]) dout[u]--; 
    };
    auto unmark=[&](int v){
        used[v]=0;
        for(int u:radj_g[v]) if(!used[u]) dout[u]++;
    };

    auto extF=[&]() -> bool {
        bool ext=false;
        while(true){
            int bd=-1,cnt=0; int picks[16]; // max-degree
            for(int v:adj_g[tail]) if(!used[v]){
                if(dout[v]>bd){bd=dout[v];cnt=1;picks[0]=v;}
                else if(dout[v]==bd&&cnt<16)picks[cnt++]=v;
            }
            if(!cnt)break;
            int p=picks[rng()%cnt]; nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto extB=[&]() -> bool {
        bool ext=false;
        while(true){
            int bd=-1,cnt=0; int picks[16];
            for(int u:radj_g[head]) if(!used[u]){
                if(dout[u]>bd){bd=dout[u];cnt=1;picks[0]=u;}
                else if(dout[u]==bd&&cnt<16)picks[cnt++]=u;
            }
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

    // Initial construction
    extF(); extB();
    for(int p2=0;p2<15;p2++){bool ch=ins();if(ch){extF();extB();}else break;}
    
    // Rotation phase (limited)
    int rotLimit = min(N * 10, 500000);
    int rotCount = 0;
    while(pathLen<N && rotCount<rotLimit && elapsed()<min(tl, elapsed()+0.5)){
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
    
    // Save best so far
    if(pathLen > globalBest){
        globalBest=pathLen;
        globalBestPath.clear();
        for(int u=head;u;u=nxt[u]) globalBestPath.push_back(u);
    }
    
    // Kick-and-rebuild loop
    int kickSize = max(50, pathLen / 10);
    for(int kick=0; pathLen<N && elapsed()<tl; kick++){
        int before = pathLen;
        
        // Remove kickSize vertices from the tail
        int toRemove = min(kickSize, pathLen - 1);
        for(int i=0;i<toRemove && tail!=head;i++){
            int p=prv[tail];
            unmark(tail);
            nxt[p]=0;
            prv[tail]=0;
            tail=p;
            pathLen--;
        }
        
        // Also remove some random vertices from the middle (puncture)
        int punctures = min(20, pathLen/10);
        for(int i=0;i<punctures;i++){
            // Walk to a random position
            int pos = rng() % max(1, pathLen-2) + 1; // avoid head and tail
            int u=head;
            for(int j=0;j<pos && nxt[u];j++) u=nxt[u];
            if(u==head||u==tail) continue;
            int p=prv[u], n=nxt[u];
            if(p && n && hasEdge(p,n)){
                nxt[p]=n; prv[n]=p;
                unmark(u); nxt[u]=0; prv[u]=0;
                pathLen--;
            }
        }
        
        // Re-extend
        extF(); extB();
        for(int p2=0;p2<10;p2++){bool ch=ins();if(ch){extF();extB();}else break;}
        
        // Vertex scan
        for(int v=1;v<=N;v++){
            if(used[v]) continue;
            if(hasEdge(v,head)){prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;}
            else if(hasEdge(tail,v)){nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;}
        }
        ins(); extF(); extB();
        
        if(pathLen > globalBest){
            globalBest=pathLen;
            globalBestPath.clear();
            for(int u=head;u;u=nxt[u]) globalBestPath.push_back(u);
        }
        
        // Vary kick size
        if(pathLen <= before) kickSize = min(kickSize * 2, pathLen / 2);
        else kickSize = max(50, pathLen / 10);
    }
}

int main(){
    T0=chrono::high_resolution_clock::now();
    scanf("%d %d",&N,&M);
    int a[10]; for(int i=0;i<10;i++) scanf("%d",&a[i]);
    for(int i=0;i<M;i++){int u,v;scanf("%d %d",&u,&v);adj_g[u].push_back(v);radj_g[v].push_back(u);outdeg_g[u]++;indeg_g[v]++;}
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}

    // Best-of-K kick restarts
    for(int attempt=0; elapsed()<3.5; attempt++){
        mt19937 rng(attempt*137+7919);
        int s;
        if(attempt==0) s=1; // arbitrary start
        else s=(rng()%N)+1;
        solveWithKick(rng, s, min(elapsed()+0.5, 3.5));
    }

    fprintf(stderr, "n=%d best=%d (%.1f%%) time=%.2fs\n", N, globalBest, 100.0*globalBest/N, elapsed());
    
    printf("%d\n",globalBest);
    for(int i=0;i<globalBest;i++){if(i)printf(" ");printf("%d",globalBestPath[i]);}
    printf("\n");
    return 0;
}
