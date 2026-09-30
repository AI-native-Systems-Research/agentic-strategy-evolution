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

struct Path {
    vector<int> nxt, prv, dout;
    vector<char> used;
    int head, tail, pathLen;
    
    void init(int n){
        nxt.assign(n+1,0);prv.assign(n+1,0);dout.resize(n+1);used.assign(n+1,0);
        for(int u=1;u<=n;u++) dout[u]=outdeg_g[u];
        head=tail=0;pathLen=0;
    }
    void mark(int v){
        used[v]=1;
        for(int u:radj_g[v]) if(!used[u]) dout[u]--;
    }
    void unmark(int v){
        used[v]=0;
        for(int u:radj_g[v]) if(!used[u]) dout[u]++;
    }
    void startAt(int v){
        head=tail=v; pathLen=1; mark(v);
    }
    bool extF(mt19937& rng){
        bool ext=false;
        while(true){
            int bd=-1,cnt=0;int picks[16];
            for(int v:adj_g[tail])if(!used[v]){if(dout[v]>bd){bd=dout[v];cnt=1;picks[0]=v;}else if(dout[v]==bd&&cnt<16)picks[cnt++]=v;}
            if(!cnt)break;
            int p=picks[rng()%cnt];nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
        }
        return ext;
    }
    bool extB(mt19937& rng){
        bool ext=false;
        while(true){
            int bd=-1,cnt=0;int picks[16];
            for(int u:radj_g[head])if(!used[u]){if(dout[u]>bd){bd=dout[u];cnt=1;picks[0]=u;}else if(dout[u]==bd&&cnt<16)picks[cnt++]=u;}
            if(!cnt)break;
            int p=picks[rng()%cnt];prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;
        }
        return ext;
    }
    bool ins(){
        bool ch=false;int u=head;
        while(u){int w=nxt[u];if(!w)break;
            for(int v:adj_g[u])if(!used[v]&&hasEdge(v,w)){nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;}
            u=w;
        }
        return ch;
    }
    bool rotate(mt19937& rng){
        vector<int>sc;for(int v:adj_g[tail])if(used[v]&&v!=tail)sc.push_back(v);if(sc.empty())return false;
        for(int i=sc.size()-1;i>0;i--){int j2=rng()%(i+1);swap(sc[i],sc[j2]);}
        for(int vi:sc){
            if(vi==head){
                vector<int>cd;int u2=head;while(u2&&u2!=tail){bool h=false;for(int w:adj_g[u2])if(!used[w]){h=true;break;}if(h)cd.push_back(u2);u2=nxt[u2];}
                if(cd.empty())continue;int vj=cd[rng()%cd.size()];int nH=nxt[vj];nxt[tail]=head;prv[head]=tail;nxt[vj]=0;prv[nH]=0;head=nH;tail=vj;return true;
            } else {
                int e=prv[vi];if(!e)continue;
                vector<int>gB,aB;int vj2=vi;while(vj2&&nxt[vj2]){int c=nxt[vj2];if(c&&hasEdge(e,c)){bool h=false;for(int w:adj_g[vj2])if(!used[w]){h=true;break;}if(h)gB.push_back(vj2);else aB.push_back(vj2);}if(vj2==tail)break;vj2=nxt[vj2];}
                int vj=0;if(!gB.empty())vj=gB[rng()%gB.size()];else if(!aB.empty())vj=aB[rng()%aB.size()];if(!vj)continue;
                int c=nxt[vj];nxt[e]=c;prv[c]=e;nxt[tail]=vi;prv[vi]=tail;nxt[vj]=0;tail=vj;return true;
            }
        }
        return false;
    }
    void saveBest(){
        if(pathLen>globalBest){
            globalBest=pathLen;
            globalBestPath.clear();
            for(int u=head;u;u=nxt[u]) globalBestPath.push_back(u);
        }
    }
    // Truncate: remove last k vertices from path, return them
    vector<int> truncateTail(int k){
        vector<int> removed;
        for(int i=0;i<k&&tail!=head;i++){
            int p=prv[tail];
            unmark(tail);
            nxt[p]=0;prv[tail]=0;
            removed.push_back(tail);
            tail=p;
            pathLen--;
        }
        return removed;
    }
    // Find escape vertices near the tail
    // Returns list of (position_from_tail, vertex, unvisited_neighbor) 
    vector<tuple<int,int,int>> findTailEscapes(int maxDist){
        vector<tuple<int,int,int>> result;
        int u=tail;
        for(int d=0;d<maxDist&&u;d++){
            for(int v:adj_g[u]) if(!used[v]){
                result.push_back({d,u,v});
                break; // one per escape vertex
            }
            u=prv[u];
        }
        return result;
    }
};

int main(){
    T0=chrono::high_resolution_clock::now();
    scanf("%d %d",&N,&M);int a[10];for(int i=0;i<10;i++)scanf("%d",&a[i]);
    for(int i=0;i<M;i++){int u,v;scanf("%d %d",&u,&v);adj_g[u].push_back(v);radj_g[v].push_back(u);outdeg_g[u]++;indeg_g[v]++;}
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}

    // Multi-restart with break-and-extend
    for(int attempt=0; elapsed()<3.5; attempt++){
        mt19937 rng(attempt*137+7919);
        Path P;
        P.init(N);
        int s=(rng()%N)+1;
        P.startAt(s);
        P.extF(rng); P.extB(rng);
        for(int p2=0;p2<15;p2++){if(!P.ins())break;P.extF(rng);P.extB(rng);}
        
        // Rotation phase (limited)
        for(int rot=0;rot<min(N*10,500000)&&P.pathLen<N&&elapsed()<min(elapsed()+0.3,3.5);rot++){
            if(P.extF(rng))continue;
            if(!P.rotate(rng))break;
            P.extF(rng);
        }
        P.extB(rng);
        for(int p3=0;p3<5;p3++){if(!P.ins())break;P.extF(rng);P.extB(rng);}
        for(int i2=0;i2<3;i2++){
            bool ch=false;
            for(int v=1;v<=N;v++){if(P.used[v])continue;if(hasEdge(v,P.head)){P.prv[P.head]=v;P.nxt[v]=P.head;P.prv[v]=0;P.head=v;P.mark(v);P.pathLen++;ch=true;}else if(hasEdge(P.tail,v)){P.nxt[P.tail]=v;P.prv[v]=P.tail;P.nxt[v]=0;P.tail=v;P.mark(v);P.pathLen++;ch=true;}}
            if(!ch)break;P.ins();P.extF(rng);P.extB(rng);
        }
        
        P.saveBest();
        
        // Break-and-extend loop: repeatedly truncate near escape and re-extend
        double breakTl = min(elapsed() + 0.2, 3.5);
        for(int brk=0; P.pathLen<N && elapsed()<breakTl; brk++){
            auto escapes = P.findTailEscapes(min(100, P.pathLen/2));
            if(escapes.empty()) break;
            
            // Try the nearest escape first (least loss)
            auto [dist, escV, unvisV] = escapes[0];
            int beforeLen = P.pathLen;
            
            // Truncate to escape vertex + redirect
            auto removed = P.truncateTail(dist);
            // Now tail should be escV (or close). Redirect tail→unvisV
            if(P.tail == escV || hasEdge(P.tail, unvisV)){
                // Extend through unvisV
                if(!P.used[unvisV]){
                    P.nxt[P.tail]=unvisV;P.prv[unvisV]=P.tail;P.nxt[unvisV]=0;P.mark(unvisV);P.tail=unvisV;P.pathLen++;
                }
                P.extF(rng); P.extB(rng);
                for(int p2=0;p2<5;p2++){if(!P.ins())break;P.extF(rng);P.extB(rng);}
                // Try to pick up removed vertices
                for(int v:removed){
                    if(P.used[v])continue;
                    if(hasEdge(v,P.head)){P.prv[P.head]=v;P.nxt[v]=P.head;P.prv[v]=0;P.head=v;P.mark(v);P.pathLen++;}
                    else if(hasEdge(P.tail,v)){P.nxt[P.tail]=v;P.prv[v]=P.tail;P.nxt[v]=0;P.tail=v;P.mark(v);P.pathLen++;}
                }
                P.ins(); P.extF(rng); P.extB(rng);
            }
            
            P.saveBest();
            
            if(P.pathLen <= beforeLen - dist) break; // Not improving
        }
        
        P.saveBest();
    }

    fprintf(stderr,"best=%d (%.1f%%)\n",globalBest,100.0*globalBest/N);
    printf("%d\n",globalBest);for(int i=0;i<globalBest;i++){if(i)printf(" ");printf("%d",globalBestPath[i]);}printf("\n");
    return 0;
}
