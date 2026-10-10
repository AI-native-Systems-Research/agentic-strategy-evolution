#include <bits/stdc++.h>
using namespace std;

int N, M;
int a_thresh[10];
vector<int> adj_g[500001], radj_g[500001];
vector<int> sadj_g[500001];
int outdeg_g[500001], indeg_g[500001];

chrono::high_resolution_clock::time_point T0;
double elapsed(){
    return chrono::duration<double>(chrono::high_resolution_clock::now()-T0).count();
}
auto hasEdge=[](int u, int v)->bool{
    return binary_search(sadj_g[u].begin(),sadj_g[u].end(),v);
};

int globalBest=0;
vector<int> globalBestPath;

// greedyMode: 0=Warnsdorff, 1=random, 2=max-degree
int solveRotation(mt19937& rng, int startVertex, double tl, int greedyMode=0){
    static vector<int> nxt, prv, dout;
    static vector<char> used;
    static bool inited=false;
    if(!inited){
        nxt.resize(N+1); prv.resize(N+1); dout.resize(N+1); used.resize(N+1);
        inited=true;
    }

    for(int u=1;u<=N;u++){dout[u]=outdeg_g[u];used[u]=0;nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;
    for(int u:radj_g[startVertex]) if(!used[u]) dout[u]--;

    int head=startVertex, tail=startVertex, pathLen=1;
    auto mark=[&](int v){
        used[v]=1;
        for(int u:radj_g[v]) if(!used[u]) dout[u]--;
    };

    // Forward extension with configurable greedy strategy
    auto extF=[&]() -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(greedyMode == 0){
                // Warnsdorff: pick minimum remaining out-degree
                int bd=INT_MAX;
                for(int v:adj_g[tail]) if(!used[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
            } else if(greedyMode == 1){
                // Pure random: collect all unvisited neighbors
                for(int v:adj_g[tail]) if(!used[v] && cnt<16){
                    picks[cnt++]=v;
                }
            } else {
                // Max degree: pick maximum remaining out-degree
                int bd=-1;
                for(int v:adj_g[tail]) if(!used[v]){
                    if(dout[v]>bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
        }
        return ext;
    };
    auto extB=[&]() -> bool {
        bool ext=false;
        while(true){
            int cnt=0; int picks[16];
            if(greedyMode == 0){
                int bd=INT_MAX;
                for(int u:radj_g[head]) if(!used[u]){
                    if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
            } else if(greedyMode == 1){
                for(int u:radj_g[head]) if(!used[u] && cnt<16){
                    picks[cnt++]=u;
                }
            } else {
                int bd=-1;
                for(int u:radj_g[head]) if(!used[u]){
                    if(dout[u]>bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
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
            int w=nxt[u];
            if(!w) break;
            for(int v:adj_g[u]) if(!used[v]&&hasEdge(v,w)){
                nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;
            }
            u=w;
        }
        return ch;
    };

    extF(); extB();
    for(int p2=0;p2<15;p2++){
        bool ch=ins();
        if(ch){extF();extB();}
        else break;
    }

    // Directed Pósa Rotation with long chains
    while(pathLen < N && elapsed() < tl){
        if(extF()) { extB(); continue; }

        int chainLen = 1000;
        bool chainExtended = false;

        for(int ci = 0; ci < chainLen && elapsed() < tl; ci++){
            int scCnt = 0;
            int scBuf[64];
            for(int v:adj_g[tail]){
                if(used[v] && v != tail && scCnt < 64) scBuf[scCnt++] = v;
            }
            if(!scCnt) break;

            for(int i=scCnt-1;i>0;i--){
                int j2=rng()%(i+1);
                swap(scBuf[i],scBuf[j2]);
            }

            bool rotated = false;
            for(int si=0; si<scCnt && !rotated; si++){
                int vi = scBuf[si];

                if(vi == head){
                    int bestCand = 0, candCnt = 0;
                    int u2=head;
                    while(u2 && u2!=tail){
                        bool hasUnvis=false;
                        for(int w:adj_g[u2]) if(!used[w]){hasUnvis=true;break;}
                        if(hasUnvis){
                            candCnt++;
                            if(rng()%candCnt == 0) bestCand = u2;
                        }
                        u2=nxt[u2];
                    }
                    if(!bestCand) continue;

                    int newHead = nxt[bestCand];
                    nxt[tail] = head;
                    prv[head] = tail;
                    nxt[bestCand] = 0;
                    prv[newHead] = 0;
                    head = newHead;
                    tail = bestCand;
                    rotated = true;
                } else {
                    int e = prv[vi];
                    if(!e) continue;

                    int bestGood = 0, bestAny = 0;
                    int goodCnt = 0, anyCnt = 0;
                    int vj2 = vi;
                    while(vj2 && nxt[vj2]){
                        int c = nxt[vj2];
                        if(c && hasEdge(e, c)){
                            bool hasUnvis=false;
                            for(int w:adj_g[vj2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis){
                                goodCnt++;
                                if(rng()%goodCnt == 0) bestGood = vj2;
                            } else {
                                anyCnt++;
                                if(rng()%anyCnt == 0) bestAny = vj2;
                            }
                        }
                        if(vj2 == tail) break;
                        vj2 = nxt[vj2];
                    }

                    int vj = bestGood ? bestGood : bestAny;
                    if(!vj) continue;

                    int c = nxt[vj];
                    nxt[e] = c;
                    prv[c] = e;
                    nxt[tail] = vi;
                    prv[vi] = tail;
                    nxt[vj] = 0;
                    tail = vj;
                    rotated = true;
                }
            }

            if(!rotated) break;

            if(extF()){
                extB();
                chainExtended = true;
                break;
            }
        }

        if(!chainExtended) break;
    }

    extB();
    for(int p3=0;p3<5&&elapsed()<tl;p3++){
        bool ch=ins();
        if(ch){extF();extB();}
        else break;
    }

    for(int iter2=0;iter2<3&&elapsed()<tl;iter2++){
        bool ch=false;
        for(int v=1;v<=N;v++){
            if(used[v]) continue;
            if(hasEdge(v,head)){
                prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;ch=true;
            }else if(hasEdge(tail,v)){
                nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;ch=true;
            }
        }
        if(!ch) break;
        ins(); extF(); extB();
    }

    if(pathLen > globalBest){
        globalBest = pathLen;
        globalBestPath.clear(); globalBestPath.reserve(pathLen);
        for(int u=head;u;u=nxt[u]) globalBestPath.push_back(u);
    }
    return pathLen;
}

// ==================== SCC-based solver ====================
void solveDAG(){
    vector<int> scc_id(N+1, -1);
    int num_sccs = 0;
    vector<vector<int>> scc_members;
    {
        vector<bool> visited(N+1, false);
        vector<int> order;
        order.reserve(N);
        for(int start=1; start<=N; start++){
            if(visited[start]) continue;
            vector<pair<int,int>> stk;
            stk.push_back({start, 0});
            while(!stk.empty()){
                auto &[v,i] = stk.back();
                if(!visited[v]) visited[v]=true;
                if(i < (int)adj_g[v].size()){
                    int w = adj_g[v][i++];
                    if(!visited[w]) stk.push_back({w, 0});
                } else { order.push_back(v); stk.pop_back(); }
            }
        }
        fill(visited.begin(), visited.end(), false);
        for(int i=(int)order.size()-1; i>=0; i--){
            int start = order[i];
            if(visited[start]) continue;
            vector<int> comp;
            vector<int> stk2;
            stk2.push_back(start);
            while(!stk2.empty()){
                int v = stk2.back(); stk2.pop_back();
                if(visited[v]) continue;
                visited[v]=true; comp.push_back(v);
                scc_id[v] = num_sccs;
                for(int w : radj_g[v]) if(!visited[w]) stk2.push_back(w);
            }
            scc_members.push_back(comp);
            num_sccs++;
        }
    }
    if(num_sccs <= 10) return;

    vector<vector<int>> dag(num_sccs);
    vector<set<int>> dag_set(num_sccs);
    vector<int> dag_indeg(num_sccs, 0);
    vector<vector<pair<int,int>>> cross_edges(num_sccs);
    for(int u=1;u<=N;u++){
        for(int v : adj_g[u]){
            int su=scc_id[u], sv=scc_id[v];
            if(su!=sv){
                cross_edges[su].push_back({u,v});
                if(!dag_set[su].count(sv)){
                    dag_set[su].insert(sv);
                    dag[su].push_back(sv);
                    dag_indeg[sv]++;
                }
            }
        }
    }

    auto findInternalHP = [&](int scc_idx, int mustStart, int mustEnd) -> vector<int> {
        auto &mem = scc_members[scc_idx];
        int sz = mem.size();
        if(sz == 1) return mem;
        if(sz > 20) return {};
        map<int,int> toL;
        for(int i=0;i<sz;i++) toL[mem[i]]=i;
        int sL = (mustStart>=0 && toL.count(mustStart)) ? toL[mustStart] : -1;
        int eL = (mustEnd>=0 && toL.count(mustEnd)) ? toL[mustEnd] : -1;
        if(mustStart>=0 && sL<0) return {};
        if(mustEnd>=0 && eL<0) return {};
        int full=(1<<sz)-1;
        vector<vector<int>> dp(1<<sz, vector<int>(sz, -2));
        for(int i=0;i<sz;i++){
            if(sL>=0 && i!=sL) continue;
            dp[1<<i][i]=-1;
        }
        vector<vector<int>> localAdj(sz);
        for(int i=0;i<sz;i++)
            for(int j=0;j<sz;j++)
                if(i!=j && hasEdge(mem[i],mem[j]))
                    localAdj[i].push_back(j);
        for(int mask=1;mask<=full;mask++){
            for(int v=0;v<sz;v++){
                if(dp[mask][v]==-2) continue;
                for(int w:localAdj[v]){
                    if(mask&(1<<w)) continue;
                    int nm=mask|(1<<w);
                    if(dp[nm][w]==-2) dp[nm][w]=v;
                }
            }
        }
        int endV=-1;
        if(eL>=0 && dp[full][eL]!=-2) endV=eL;
        else if(eL<0){
            for(int v=0;v<sz;v++) if(dp[full][v]!=-2){endV=v;break;}
        }
        if(endV<0) return {};
        vector<int> res;
        int mask=full, v=endV;
        while(v>=0){ res.push_back(mem[v]); int pv=dp[mask][v]; mask^=(1<<v); v=pv; }
        reverse(res.begin(),res.end());
        return res;
    };

    vector<int> dagPath;
    vector<bool> dagVisited(num_sccs, false);
    vector<int> curDagIndeg(dag_indeg.begin(), dag_indeg.end());
    function<bool(int)> dfsDAG = [&](int cur) -> bool {
        dagPath.push_back(cur); dagVisited[cur] = true;
        for(int nxt : dag[cur]) curDagIndeg[nxt]--;
        if((int)dagPath.size() == num_sccs) return true;
        vector<int> cands;
        for(int nxt : dag[cur])
            if(!dagVisited[nxt] && curDagIndeg[nxt]==0) cands.push_back(nxt);
        sort(cands.begin(), cands.end(), [&](int a, int b){ return dag[a].size() < dag[b].size(); });
        for(int nxt : cands){
            if(elapsed() > 1.0) break;
            if(dfsDAG(nxt)) return true;
        }
        dagPath.pop_back(); dagVisited[cur] = false;
        for(int nxt : dag[cur]) curDagIndeg[nxt]++;
        return false;
    };

    vector<int> sources;
    for(int i=0;i<num_sccs;i++) if(dag_indeg[i]==0) sources.push_back(i);
    bool foundDagHP = false;
    for(int s : sources){
        if(elapsed() > 1.0) break;
        dagPath.clear();
        fill(dagVisited.begin(), dagVisited.end(), false);
        copy(dag_indeg.begin(), dag_indeg.end(), curDagIndeg.begin());
        if(dfsDAG(s)){ foundDagHP = true; break; }
    }
    if(!foundDagHP || (int)dagPath.size() < num_sccs) return;

    vector<int> vertexPath;
    for(int di=0; di<(int)dagPath.size(); di++){
        int si = dagPath[di];
        auto &mem = scc_members[si];
        if(mem.size() == 1){
            int v = mem[0];
            if(!vertexPath.empty() && !hasEdge(vertexPath.back(), v)) continue;
            vertexPath.push_back(v); continue;
        }
        int mustStart = -1;
        if(!vertexPath.empty()){
            for(int v : mem) if(hasEdge(vertexPath.back(), v)){ mustStart = v; break; }
            if(mustStart < 0) continue;
        }
        int mustEnd = -1;
        if(di < (int)dagPath.size()-1){
            int sj = dagPath[di+1];
            vector<int> possibleExits;
            for(auto &[u,v] : cross_edges[si])
                if(scc_id[v] == sj) possibleExits.push_back(u);
            sort(possibleExits.begin(), possibleExits.end());
            possibleExits.erase(unique(possibleExits.begin(), possibleExits.end()), possibleExits.end());
            for(int exitV : possibleExits){
                auto hp = findInternalHP(si, mustStart, exitV);
                if((int)hp.size() == (int)mem.size()){
                    if(!vertexPath.empty() && !hasEdge(vertexPath.back(), hp[0])) continue;
                    for(int x : hp) vertexPath.push_back(x);
                    mustEnd = exitV; break;
                }
            }
        }
        if(mustEnd < 0){
            auto hp = findInternalHP(si, mustStart, -1);
            if(!hp.empty()){
                if(!vertexPath.empty() && !hasEdge(vertexPath.back(), hp[0])) continue;
                for(int x : hp) vertexPath.push_back(x);
            }
        }
    }

    bool valid=true;
    set<int> seen;
    for(int i=0;i<(int)vertexPath.size();i++){
        if(seen.count(vertexPath[i])){valid=false;break;}
        seen.insert(vertexPath[i]);
        if(i>0 && !hasEdge(vertexPath[i-1],vertexPath[i])){valid=false;break;}
    }
    if(valid && (int)vertexPath.size()>globalBest){
        globalBest=vertexPath.size();
        globalBestPath=vertexPath;
    }
}

int main(){
    T0 = chrono::high_resolution_clock::now();
    scanf("%d %d", &N, &M);
    for(int i=0;i<10;i++) scanf("%d", &a_thresh[i]);
    for(int i=0;i<M;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj_g[u].push_back(v);
        radj_g[v].push_back(u);
        outdeg_g[u]++; indeg_g[v]++;
    }
    for(int u=1;u<=N;u++){
        sadj_g[u]=adj_g[u];
        sort(sadj_g[u].begin(),sadj_g[u].end());
    }

    if(N <= 2000) solveDAG();

    // Build diverse start candidates
    vector<int> starts;
    for(int u=1;u<=N;u++) if(indeg_g[u]==0) starts.push_back(u);
    {
        vector<int> order(N); iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[](int a2,int b2){return indeg_g[a2]<indeg_g[b2];});
        for(int i=0;i<min(N,20);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
        sort(order.begin(),order.end(),[](int a2,int b2){return outdeg_g[a2]-indeg_g[a2]>outdeg_g[b2]-indeg_g[b2];});
        for(int i=0;i<min(N,10);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
        sort(order.begin(),order.end(),[](int a2,int b2){
            return (outdeg_g[a2]+indeg_g[a2]) > (outdeg_g[b2]+indeg_g[b2]);
        });
        for(int i=0;i<min(N,10);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
    }

    // Multi-restart with diverse greedy strategies
    double TIME_LIMIT = 3.7;

    for(int attempt=0; globalBest<N && elapsed()<TIME_LIMIT; attempt++){
        mt19937 rng(attempt * 97 + 42);

        // Time allocation per attempt: adaptive
        // For small N: give first attempt most time
        // For large N: short attempts with diversity
        double perAttempt;
        if(N <= 4000 && attempt == 0) perAttempt = 3.0;
        else if(N <= 5000) perAttempt = 0.3;
        else if(N <= 20000) perAttempt = 0.15;
        else perAttempt = 0.05;

        double tl = min(elapsed() + perAttempt, TIME_LIMIT);

        // Cycle through greedy modes: Warnsdorff(0), random(1), max-deg(2)
        int greedyMode = attempt % 3;

        int s;
        if(attempt < (int)starts.size()){
            s = starts[attempt];
        } else {
            s = (rng()%N)+1;
        }

        solveRotation(rng, s, tl, greedyMode);
    }

    printf("%d\n",globalBest);
    for(int i=0;i<globalBest;i++){
        if(i) printf(" ");
        printf("%d",globalBestPath[i]);
    }
    printf("\n");
    return 0;
}
