#include <bits/stdc++.h>
using namespace std;

int main(){
    int n, m;
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    vector<vector<int>> adj(n+1), radj(n+1);
    vector<vector<int>> sadj(n+1);
    vector<int> outdeg(n+1,0), indeg(n+1,0);
    for(int i=0;i<m;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj[u].push_back(v);
        radj[v].push_back(u);
        outdeg[u]++; indeg[v]++;
    }
    for(int u=1;u<=n;u++){
        sadj[u]=adj[u];
        sort(sadj[u].begin(),sadj[u].end());
    }
    auto hasEdge=[&](int u, int v)->bool{
        return binary_search(sadj[u].begin(),sadj[u].end(),v);
    };

    mt19937 rng(42);
    auto t0=chrono::high_resolution_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::high_resolution_clock::now()-t0).count();
    };

    int bestLen=0;
    vector<int> bestPath;

    // Arrays for greedy construction
    vector<int> dout(n+1);
    vector<char> used(n+1);
    vector<int> nxt(n+1), prv(n+1);

    // Greedy with Warnsdorff + bidirectional + insertion
    // Returns path as vector
    auto greedyBuild=[&](int start) -> vector<int> {
        for(int u=1;u<=n;u++){dout[u]=outdeg[u];used[u]=0;nxt[u]=0;prv[u]=0;}
        used[start]=1;
        for(int u:radj[start]) if(!used[u]) dout[u]--;

        int head=start, tail=start;
        auto mark=[&](int v){
            used[v]=1;
            for(int u:radj[v]) if(!used[u]) dout[u]--;
        };

        auto extF=[&]{
            while(true){
                int bd=INT_MAX,cnt=0; int picks[16];
                for(int v:adj[tail]) if(!used[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
                if(!cnt)break;
                int p=picks[rng()%cnt];
                nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;
            }
        };
        auto extB=[&]{
            while(true){
                int bd=INT_MAX,cnt=0; int picks[16];
                for(int u:radj[head]) if(!used[u]){
                    if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
                if(!cnt)break;
                int p=picks[rng()%cnt];
                prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;
            }
        };
        auto ins=[&]()->bool{
            bool ch=false;
            int u=head;
            while(u){int w=nxt[u];if(!w)break;
                for(int v:adj[u]) if(!used[v]&&hasEdge(v,w)){
                    nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;ch=true;
                }
                u=w;
            }
            u=head;
            while(u){int p2=prv[u];if(p2){
                for(int v:radj[u]) if(!used[v]&&hasEdge(p2,v)){
                    nxt[p2]=v;prv[v]=p2;nxt[v]=u;prv[u]=v;mark(v);ch=true;break;
                }
            }u=nxt[u];}
            return ch;
        };

        extF(); extB();
        for(int p=0;p<20;p++){
            if(!ins()) break;
            extF(); extB();
        }

        // Post-process: insert remaining
        for(int iter2=0;iter2<5;iter2++){
            bool ch=false;
            for(int v=1;v<=n;v++){
                if(used[v]) continue;
                if(hasEdge(v,head)){
                    prv[head]=v;nxt[v]=head;prv[v]=0;head=v;
                    used[v]=1; for(int r:radj[v]) if(!used[r]) dout[r]--;
                    ch=true;continue;
                }
                if(hasEdge(tail,v)){
                    nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;
                    used[v]=1; for(int r:radj[v]) if(!used[r]) dout[r]--;
                    ch=true;continue;
                }
                int u2=head;
                while(u2){
                    int w=nxt[u2]; if(!w)break;
                    if(hasEdge(u2,v)&&hasEdge(v,w)){
                        nxt[u2]=v;prv[v]=u2;nxt[v]=w;prv[w]=v;
                        used[v]=1; for(int r:radj[v]) if(!used[r]) dout[r]--;
                        ch=true;break;
                    }
                    u2=nxt[u2];
                }
            }
            if(!ch)break;
        }

        // Collect path
        vector<int> path;
        for(int u=head;u;u=nxt[u]) path.push_back(u);
        return path;
    };

    // Ruin-and-recreate improvement on a path (stored as vector)
    auto ruinAndRecreate=[&](vector<int>& path, double tl) -> bool {
        int pathLen = path.size();
        if(pathLen == n) return false;

        // Build position map
        vector<int> pos(n+1, -1);
        for(int i=0;i<pathLen;i++) pos[path[i]]=i;

        // Mark path vertices
        vector<char> inPath(n+1, 0);
        for(int v:path) inPath[v]=1;

        bool improved = false;
        int attempts = 0;
        int maxAttempts = min(pathLen * 2, 5000);

        while(attempts < maxAttempts && elapsed() < tl){
            attempts++;

            // Pick random position on path
            int idx = rng() % pathLen;
            int u = path[idx];

            // Find shortcuts from u to later path vertices (skip immediate next)
            vector<int> shortcuts;
            for(int v:adj[u]){
                if(pos[v] > idx + 1){
                    shortcuts.push_back(pos[v]);
                }
            }
            if(shortcuts.empty()) continue;

            // Pick a random shortcut target
            int target_pos = shortcuts[rng() % shortcuts.size()];

            // Ruin: free vertices path[idx+1..target_pos-1]
            int ruin_size = target_pos - idx - 1;
            if(ruin_size < 1 || ruin_size > pathLen/3) continue;

            vector<int> freed;
            for(int k=idx+1; k<target_pos; k++){
                freed.push_back(path[k]);
            }

            // Collect all unvisited vertices + freed vertices
            vector<int> pool = freed;
            for(int v=1;v<=n;v++){
                if(!inPath[v]) pool.push_back(v);
            }

            // Build a sub-path through pool vertices, starting from path[idx]'s successors
            // We need: path[idx] → [sub-path through pool] → path[target_pos]
            // Using greedy

            // Mark pool vertices
            vector<char> poolSet(n+1, 0);
            for(int v:pool) poolSet[v]=1;

            // Greedy extension from path[idx] through pool
            vector<int> subPath;
            vector<char> subUsed(n+1, 0);
            int cur = path[idx];

            while(true){
                int best=-1, bestDeg=INT_MAX;
                int cnt2=0;
                int picks[16];
                for(int v:adj[cur]){
                    if(!poolSet[v] || subUsed[v]) continue;
                    // Count future neighbors in pool
                    int deg=0;
                    for(int w:adj[v]) if(poolSet[w]&&!subUsed[w]) deg++;
                    if(deg<bestDeg){bestDeg=deg;cnt2=0;picks[0]=v;cnt2=1;}
                    else if(deg==bestDeg&&cnt2<16){picks[cnt2++]=v;}
                }
                if(!cnt2) break;
                int p=picks[rng()%cnt2];
                subPath.push_back(p);
                subUsed[p]=1;
                cur=p;
            }

            // Check if subPath ends at a vertex that connects to path[target_pos]
            if(!subPath.empty() && hasEdge(subPath.back(), path[target_pos])){
                // Great! Sub-path bridges from path[idx] to path[target_pos]
                int newLen = idx + 1 + subPath.size() + (pathLen - target_pos);
                if(newLen > pathLen){
                    // Build new path
                    vector<int> newPath;
                    newPath.reserve(newLen);
                    for(int k=0;k<=idx;k++) newPath.push_back(path[k]);
                    for(int v:subPath) newPath.push_back(v);
                    for(int k=target_pos;k<pathLen;k++) newPath.push_back(path[k]);

                    path = newPath;
                    pathLen = path.size();
                    // Update pos and inPath
                    for(int v=1;v<=n;v++){pos[v]=-1;inPath[v]=0;}
                    for(int i2=0;i2<pathLen;i2++){pos[path[i2]]=i2;inPath[path[i2]]=1;}
                    improved = true;
                }
            }
            // Also try: just extending subPath (even if it doesn't connect to path[target_pos])
            // Append subPath vertices to end of path instead
            else if(!subPath.empty()){
                // Check if path's tail connects to head of subPath
                // Or if subPath can be appended/prepended
                // For simplicity, try connecting via tail
                if(hasEdge(path[pathLen-1], subPath[0])){
                    // Remove freed vertices from path, add subPath at end
                    // But this breaks the shortcut... skip for now
                }
            }
        }
        return improved;
    };

    // Chain merging: build secondary paths among unvisited vertices and stitch
    auto chainStitch=[&](vector<int>& path, double tl) -> bool {
        int pathLen = path.size();
        if(pathLen == n) return false;

        vector<char> inPath(n+1, 0);
        for(int v:path) inPath[v]=1;

        bool improved = false;

        // Collect unvisited vertices
        vector<int> unvis;
        for(int v=1;v<=n;v++) if(!inPath[v]) unvis.push_back(v);
        if(unvis.empty()) return false;

        // Shuffle unvisited
        for(int i=unvis.size()-1;i>0;i--){
            int j=rng()%(i+1);
            swap(unvis[i],unvis[j]);
        }

        // Build secondary paths among unvisited vertices
        vector<vector<int>> chains;
        vector<char> chainUsed(n+1, 0);

        for(int sv:unvis){
            if(chainUsed[sv]) continue;
            if(elapsed()>tl) break;

            // Build a chain starting from sv using greedy among unvisited+not-in-chain
            vector<int> chain;
            chain.push_back(sv);
            chainUsed[sv]=1;
            int cur=sv;
            while(true){
                int best=-1, bestDeg=INT_MAX;
                int cnt2=0; int picks[8];
                for(int v:adj[cur]){
                    if(inPath[v]||chainUsed[v]) continue;
                    int deg=0;
                    for(int w:adj[v]) if(!inPath[w]&&!chainUsed[w]) deg++;
                    if(deg<bestDeg){bestDeg=deg;cnt2=0;picks[0]=v;cnt2=1;}
                    else if(deg==bestDeg&&cnt2<8){picks[cnt2++]=v;}
                }
                if(!cnt2) break;
                int p=picks[rng()%cnt2];
                chain.push_back(p);
                chainUsed[p]=1;
                cur=p;
            }
            if(chain.size()>=1) chains.push_back(chain);
        }

        // Try to stitch each chain into the main path
        for(auto& chain:chains){
            if(elapsed()>tl) break;
            int chead=chain.front(), ctail=chain.back();
            int clen=chain.size();

            // Try append: path_tail → chain_head
            if(hasEdge(path.back(), chead)){
                for(int v:chain) path.push_back(v);
                for(int v:chain) inPath[v]=1;
                improved=true;
                continue;
            }
            // Try prepend: chain_tail → path_head
            if(hasEdge(ctail, path[0])){
                vector<int> newPath;
                newPath.reserve(path.size()+clen);
                for(int v:chain) newPath.push_back(v);
                for(int v:path) newPath.push_back(v);
                path=newPath;
                for(int v:chain) inPath[v]=1;
                improved=true;
                continue;
            }
            // Try internal stitch: find i where path[i]→chead AND ctail→path[i+1]
            for(int i=0;i<(int)path.size()-1;i++){
                if(hasEdge(path[i],chead)&&hasEdge(ctail,path[i+1])){
                    vector<int> newPath;
                    newPath.reserve(path.size()+clen);
                    for(int k=0;k<=i;k++) newPath.push_back(path[k]);
                    for(int v:chain) newPath.push_back(v);
                    for(int k=i+1;k<(int)path.size();k++) newPath.push_back(path[k]);
                    path=newPath;
                    for(int v:chain) inPath[v]=1;
                    improved=true;
                    break;
                }
            }
        }
        return improved;
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

    // Phase 1: Build initial paths with smart starts
    for(int s:starts){
        if(bestLen==n||elapsed()>1.0) break;
        auto path = greedyBuild(s);
        if((int)path.size()>bestLen){
            bestLen=path.size();
            bestPath=path;
        }
    }

    // Phase 2: Improve best path with ruin-and-recreate + chain stitching
    if(bestLen < n && bestLen > 0){
        // Alternate between ruin-and-recreate and chain stitching
        for(int round=0; round<20 && elapsed()<2.5; round++){
            bool ch1 = ruinAndRecreate(bestPath, 2.5);
            bool ch2 = chainStitch(bestPath, 2.5);
            bestLen = bestPath.size();
            if(!ch1 && !ch2) break;
        }
    }

    // Phase 3: More random restarts with full pipeline
    while(bestLen<n && elapsed()<3.5){
        int s = (rng()%n)+1;
        auto path = greedyBuild(s);
        // Quick ruin-and-recreate on this path
        for(int r=0;r<5&&elapsed()<3.5;r++){
            bool ch1 = ruinAndRecreate(path, 3.5);
            bool ch2 = chainStitch(path, 3.5);
            if(!ch1&&!ch2) break;
        }
        if((int)path.size()>bestLen){
            bestLen=path.size();
            bestPath=path;
        }
    }

    printf("%d\n",bestLen);
    for(int i=0;i<bestLen;i++){
        if(i) printf(" ");
        printf("%d",bestPath[i]);
    }
    printf("\n");
    return 0;
}
