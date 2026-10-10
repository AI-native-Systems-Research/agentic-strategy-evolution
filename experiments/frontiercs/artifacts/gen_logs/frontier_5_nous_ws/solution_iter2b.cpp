#include <bits/stdc++.h>
using namespace std;

int main(){
    int n, m;
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    vector<vector<int>> adj(n+1), radj(n+1);
    vector<int> outdeg(n+1,0), indeg(n+1,0);

    // Edge storage for O(1) lookup
    vector<unordered_set<int>> adj_set(n+1);

    for(int i=0;i<m;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj[u].push_back(v);
        radj[v].push_back(u);
        adj_set[u].insert(v);
        outdeg[u]++; indeg[v]++;
    }

    auto hasEdge=[&](int u, int v)->bool{
        return adj_set[u].count(v);
    };

    mt19937 rng(42);
    auto t0=chrono::high_resolution_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::high_resolution_clock::now()-t0).count();
    };

    int bestLen=0;
    vector<int> bestPath;

    // ——— SCC computation (iterative Kosaraju) ———
    vector<int> scc_id(n+1, -1);
    int num_sccs = 0;
    vector<vector<int>> scc_members;
    {
        vector<bool> visited(n+1, false);
        vector<int> order;
        order.reserve(n);
        for(int start=1; start<=n; start++){
            if(visited[start]) continue;
            vector<pair<int,int>> stk;
            stk.push_back({start, 0});
            while(!stk.empty()){
                auto &[v,i] = stk.back();
                if(!visited[v]) visited[v]=true;
                if(i < (int)adj[v].size()){
                    int w = adj[v][i++];
                    if(!visited[w]) stk.push_back({w, 0});
                } else {
                    order.push_back(v);
                    stk.pop_back();
                }
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
                visited[v]=true;
                comp.push_back(v);
                scc_id[v] = num_sccs;
                for(int w : radj[v]) if(!visited[w]) stk2.push_back(w);
            }
            scc_members.push_back(comp);
            num_sccs++;
        }
    }

    // ——— DAG-based solver for fragmented graphs ———
    if(num_sccs > 10){
        // Build condensation DAG
        vector<vector<int>> dag(num_sccs);
        vector<set<int>> dag_set(num_sccs);
        vector<int> dag_indeg(num_sccs, 0);
        for(int u=1;u<=n;u++){
            for(int v : adj[u]){
                int su=scc_id[u], sv=scc_id[v];
                if(su!=sv && !dag_set[su].count(sv)){
                    dag_set[su].insert(sv);
                    dag[su].push_back(sv);
                    dag_indeg[sv]++;
                }
            }
        }

        // Topological sort + greedy HP in DAG
        auto tryDAGPath = [&](int startSCC) -> vector<int> {
            vector<bool> vis(num_sccs, false);
            vector<int> dp;
            dp.push_back(startSCC);
            vis[startSCC]=true;
            while((int)dp.size() < num_sccs){
                int cur = dp.back();
                int best=-1, bestScore=-1;
                for(int nxt : dag[cur]){
                    if(!vis[nxt]){
                        int score=0;
                        for(int nn : dag[nxt]) if(!vis[nn]) score++;
                        if(best==-1 || score>bestScore){
                            bestScore=score; best=nxt;
                        }
                    }
                }
                if(best==-1) break;
                dp.push_back(best);
                vis[best]=true;
            }
            return dp;
        };

        vector<int> bestDP;
        for(int i=0;i<num_sccs;i++){
            if(dag_indeg[i]==0){
                auto p=tryDAGPath(i);
                if((int)p.size()>(int)bestDP.size()) bestDP=p;
            }
        }
        for(int tries=0; tries<200 && elapsed()<0.3; tries++){
            int s=rng()%num_sccs;
            auto p=tryDAGPath(s);
            if((int)p.size()>(int)bestDP.size()) bestDP=p;
            if((int)p.size()==num_sccs) break;
        }

        // Build vertex path through DAG path
        // For each SCC, use bitmask DP to find internal HP
        function<vector<int>(vector<int>&, int, int)> findHP_SCC = [&](vector<int>& members, int mustStart, int mustEnd) -> vector<int> {
            int sz=members.size();
            if(sz==1) return {members[0]};
            if(sz>20){
                // Too large, just return in order
                return members;
            }
            map<int,int> toL;
            for(int i=0;i<sz;i++) toL[members[i]]=i;
            int sL = (mustStart>=0) ? toL[mustStart] : -1;
            int eL = (mustEnd>=0) ? toL[mustEnd] : -1;
            int full=(1<<sz)-1;
            // dp[mask][v] = prev vertex (-2 = invalid, -1 = start)
            vector<vector<int>> dp(1<<sz, vector<int>(sz, -2));
            for(int i=0;i<sz;i++){
                if(sL>=0 && i!=sL) continue;
                dp[1<<i][i]=-1;
            }
            vector<vector<int>> localAdj(sz);
            for(int i=0;i<sz;i++)
                for(int j=0;j<sz;j++)
                    if(i!=j && hasEdge(members[i],members[j]))
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
            if(endV<0){
                // No full HP with constraints, try without constraints
                if(mustStart>=0 || mustEnd>=0){
                    return findHP_SCC(members, -1, -1);
                }
                return {members[0]};
            }
            vector<int> res;
            int mask=full, v=endV;
            while(v>=0){
                res.push_back(members[v]);
                int pv=dp[mask][v];
                mask^=(1<<v);
                v=pv;
            }
            reverse(res.begin(),res.end());
            return res;
        };

        // Assemble path
        int dagLen=bestDP.size();
        vector<int> fullPath;
        for(int i=0;i<dagLen;i++){
            int si=bestDP[i];
            auto &mem=scc_members[si];

            if(mem.size()==1){
                if(!fullPath.empty() && !hasEdge(fullPath.back(), mem[0])) continue;
                fullPath.push_back(mem[0]);
                continue;
            }

            // Find entry: must be reachable from previous exit
            int mustStart=-1;
            if(!fullPath.empty()){
                for(int v:mem) if(hasEdge(fullPath.back(),v)){mustStart=v;break;}
                if(mustStart<0) continue; // can't connect
            }

            // Find exit: must reach next SCC
            int mustEnd=-1;
            if(i<dagLen-1){
                int sj=bestDP[i+1];
                auto &nextMem=scc_members[sj];
                // Try each (exit, entry) pair
                for(int u:mem){
                    for(int v:nextMem){
                        if(hasEdge(u,v)){
                            // Try HP from mustStart to u
                            auto hp=findHP_SCC(mem, mustStart, u);
                            if((int)hp.size()==(int)mem.size()){
                                if(!fullPath.empty() && !hasEdge(fullPath.back(), hp[0])){
                                    continue;
                                }
                                for(int x:hp) fullPath.push_back(x);
                                mustEnd=u;
                                goto nextSCC;
                            }
                        }
                    }
                }
            }

            {
                // No constrained HP found, try unconstrained
                auto hp=findHP_SCC(mem, mustStart, -1);
                if(!fullPath.empty() && !hp.empty() && !hasEdge(fullPath.back(), hp[0])){
                    continue;
                }
                for(int x:hp) fullPath.push_back(x);
            }
            nextSCC:;
        }

        // Validate
        bool valid=true;
        set<int> seen;
        for(int i=0;i<(int)fullPath.size();i++){
            if(seen.count(fullPath[i])){valid=false;break;}
            seen.insert(fullPath[i]);
            if(i>0 && !hasEdge(fullPath[i-1],fullPath[i])){valid=false;break;}
        }
        if(valid && (int)fullPath.size()>bestLen){
            bestLen=fullPath.size();
            bestPath=fullPath;
        }
    }

    // ——— Linked-list rotation solver (works for all graph types) ———
    vector<int> nxt(n+1,0), prv(n+1,0);
    vector<int> dout(n+1);
    vector<char> used(n+1);
    // Position array for fast break-point search
    vector<int> pos(n+1, -1);

    auto solve=[&](int start, double tl) -> int {
        for(int u=1;u<=n;u++){dout[u]=outdeg[u];used[u]=0;nxt[u]=0;prv[u]=0;pos[u]=-1;}
        used[start]=1;
        for(int u:radj[start]) if(!used[u]) dout[u]--;

        int head=start, tail=start, pathLen=1;
        pos[start]=0;

        auto mark=[&](int v){
            used[v]=1;
            for(int u:radj[v]) if(!used[u]) dout[u]--;
        };

        auto extF=[&]() -> bool {
            bool ext=false;
            while(true){
                int bd=INT_MAX,cnt=0; int picks[16];
                for(int v:adj[tail]) if(!used[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
                if(!cnt)break;
                int p=picks[rng()%cnt];
                nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);
                pos[p]=pathLen;
                tail=p;pathLen++;ext=true;
            }
            return ext;
        };

        auto extB=[&]() -> bool {
            bool ext=false;
            while(true){
                int bd=INT_MAX,cnt=0; int picks[16];
                for(int u:radj[head]) if(!used[u]){
                    if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
                if(!cnt)break;
                int p=picks[rng()%cnt];
                prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;
                // Shift all positions by 1
                // This is O(pathLen) - only do if pathLen is small
                // For large paths, skip position update (will recompute later)
                pathLen++;ext=true;
            }
            if(ext){
                // Recompute positions
                int idx=0;
                for(int u=head;u;u=nxt[u]) pos[u]=idx++;
            }
            return ext;
        };

        auto ins=[&]()->bool{
            bool ch=false;
            int u=head;
            while(u){
                int w=nxt[u];
                if(!w) break;
                for(int v:adj[u]) if(!used[v]&&hasEdge(v,w)){
                    nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);
                    // Update positions from v onwards
                    pos[v]=pos[u]+1;
                    // Shift all after v
                    for(int x=w;x;x=nxt[x]) pos[x]=pos[prv[x]]+1;
                    w=v;pathLen++;ch=true;
                }
                u=w;
            }
            return ch;
        };

        // Recompute all positions
        auto recomputePos=[&](){
            int idx=0;
            for(int u=head;u;u=nxt[u]) pos[u]=idx++;
        };

        extF(); extB();
        for(int p2=0;p2<15;p2++){
            bool ch=ins();
            if(ch){extF();extB();}
            else break;
        }
        recomputePos();

        // === Directed Pósa Rotation with adjacency-based break-point search ===
        while(pathLen < n && elapsed() < tl){
            if(extF()){
                // pos for new vertices already set in extF
                continue;
            }

            // Forward rotation: tail → vi (on path)
            bool rotated = false;

            vector<int> shortcuts;
            for(int v:adj[tail]){
                if(used[v] && v != tail && pos[v]>=0) shortcuts.push_back(v);
            }
            if(!shortcuts.empty()){
                for(int i=shortcuts.size()-1;i>0;i--){
                    int j2=rng()%(i+1);
                    swap(shortcuts[i],shortcuts[j2]);
                }

                for(int vi : shortcuts){
                    if(rotated) break;

                    if(vi == head){
                        // Case 1: tail → head, forms cycle
                        vector<int> candidates;
                        int u2=head;
                        while(u2 && u2!=tail){
                            bool hasUnvis=false;
                            for(int w:adj[u2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) candidates.push_back(u2);
                            u2=nxt[u2];
                        }
                        if(candidates.empty()) continue;
                        int vj = candidates[rng()%candidates.size()];

                        int newHead = nxt[vj];
                        nxt[tail] = head;
                        prv[head] = tail;
                        nxt[vj] = 0;
                        prv[newHead] = 0;
                        head = newHead;
                        tail = vj;
                        recomputePos();
                        rotated = true;
                    } else {
                        // Case 2: tail → vi, vi != head
                        int e = prv[vi];
                        if(!e) continue;
                        int pvi = pos[vi];

                        // Adjacency-based break-point search:
                        // For each c in adj[e], if c is on path and pos[c] > pvi,
                        // then vj = prv[c] is a valid break point
                        vector<int> goodBreaks, anyBreaks;
                        for(int c : adj[e]){
                            if(!used[c] || pos[c] < 0) continue;
                            if(pos[c] <= pvi) continue; // c must be after vi
                            int vj = prv[c];
                            if(!vj || vj==tail) {
                                // vj is tail: this means c doesn't exist after vj
                                // Actually if vj==tail, that means c=0 which we already checked
                                // vj can be any vertex between vi and tail
                                // Check: if c is right after vj, and vj is between vi and tail
                                if(pos[vj] < pvi) continue;
                            }
                            bool hasUnvis=false;
                            for(int w:adj[vj]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) goodBreaks.push_back(vj);
                            else anyBreaks.push_back(vj);
                        }

                        int vj = 0;
                        if(!goodBreaks.empty()) vj = goodBreaks[rng()%goodBreaks.size()];
                        else if(!anyBreaks.empty()) vj = anyBreaks[rng()%anyBreaks.size()];
                        if(!vj) continue;

                        int c = nxt[vj];
                        // Pointer surgery (same as v6):
                        nxt[e] = c;
                        prv[c] = e;
                        nxt[tail] = vi;
                        prv[vi] = tail;
                        nxt[vj] = 0;
                        tail = vj;
                        recomputePos();
                        rotated = true;
                    }
                }
            }

            if(!rotated) break;
            extF();
        }

        extB();
        for(int p3=0;p3<5&&elapsed()<tl;p3++){
            bool ch=ins();
            if(ch){extF();extB();}
            else break;
        }
        recomputePos();

        for(int iter2=0;iter2<3&&elapsed()<tl;iter2++){
            bool ch=false;
            for(int v=1;v<=n;v++){
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

        if(pathLen > bestLen){
            bestLen = pathLen;
            bestPath.clear(); bestPath.reserve(pathLen);
            for(int u=head;u;u=nxt[u]) bestPath.push_back(u);
        }
        return pathLen;
    };

    // Start candidates
    vector<int> starts;
    for(int u=1;u<=n;u++) if(indeg[u]==0) starts.push_back(u);
    {
        vector<int> order(n); iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[&](int a2,int b2){return indeg[a2]<indeg[b2];});
        for(int i=0;i<min(n,20);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
        sort(order.begin(),order.end(),[&](int a2,int b2){return outdeg[a2]-indeg[a2]>outdeg[b2]-indeg[b2];});
        for(int i=0;i<min(n,10);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
    }

    // Phase 1: Smart starts
    for(int s:starts){
        if(bestLen==n||elapsed()>1.5) break;
        solve(s, 1.5);
    }
    // Phase 2: Random restarts
    while(bestLen<n && elapsed()<3.6){
        int s=(rng()%n)+1;
        solve(s, 3.6);
    }

    printf("%d\n",bestLen);
    for(int i=0;i<bestLen;i++){
        if(i) printf(" ");
        printf("%d",bestPath[i]);
    }
    printf("\n");
    return 0;
}
