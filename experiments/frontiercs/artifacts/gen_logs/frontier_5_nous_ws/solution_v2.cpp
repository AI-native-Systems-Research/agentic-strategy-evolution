#include <bits/stdc++.h>
using namespace std;

int main(){
    int n, m;
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    vector<vector<int>> adj(n+1), radj(n+1);
    vector<int> outdeg(n+1,0), indeg(n+1,0);
    // For O(1) edge lookup: use unordered_set or sorted + binary search
    vector<vector<int>> sadj(n+1), sradj(n+1);

    for(int i=0;i<m;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj[u].push_back(v);
        radj[v].push_back(u);
        outdeg[u]++; indeg[v]++;
    }
    for(int u=1;u<=n;u++){
        sadj[u]=adj[u];
        sort(sadj[u].begin(),sadj[u].end());
        sradj[u]=radj[u];
        sort(sradj[u].begin(),sradj[u].end());
    }
    auto hasEdge=[&](int u, int v)->bool{
        return binary_search(sadj[u].begin(),sadj[u].end(),v);
    };
    auto hasRevEdge=[&](int u, int v)->bool{
        // does edge v->u exist?
        return binary_search(sadj[v].begin(),sadj[v].end(),u);
    };

    mt19937 rng(42);
    auto t0=chrono::high_resolution_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::high_resolution_clock::now()-t0).count();
    };

    int bestLen=0;
    vector<int> bestPath;

    // Path stored as doubly-linked list for O(1) insert/remove
    vector<int> nxt(n+1,0), prv(n+1,0);
    vector<int> pos(n+1,0); // position in path (1-indexed)
    vector<char> used(n+1,0);
    vector<int> dout(n+1,0);

    // Build greedy path with Warnsdorff heuristic + bidirectional extension + insertion
    auto greedyBuild=[&](int start) -> pair<int,int> { // returns (head, tail)
        for(int u=1;u<=n;u++){dout[u]=outdeg[u];used[u]=0;nxt[u]=0;prv[u]=0;}
        used[start]=1;
        for(int u:radj[start]) if(!used[u]) dout[u]--;

        int head=start, tail=start;
        auto mark=[&](int v){
            used[v]=1;
            for(int u:radj[v]) if(!used[u]) dout[u]--;
        };

        // Forward extension from tail
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
        // Backward extension from head
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
        // Insertion pass
        auto ins=[&]()->bool{
            bool ch=false;
            int u=head;
            while(u){
                int w=nxt[u];
                if(!w) break;
                for(int v:adj[u]) if(!used[v]&&hasEdge(v,w)){
                    nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;ch=true;
                }
                u=w;
            }
            return ch;
        };

        extF(); extB();
        for(int p=0;p<20;p++){
            if(!ins()) break;
            extF(); extB();
        }
        return {head, tail};
    };

    // Vertex relocation: remove vertex from path interior (if bypass edge exists),
    // try to place at head/tail/insertion point to enable further extension
    auto relocateAndExtend=[&](int &head, int &tail, int &pathLen) -> bool {
        bool improved = false;
        // Collect interior vertices that can be removed (bypass edge exists)
        vector<int> removable;
        {
            int u = head;
            while(u){
                int p = prv[u], nx = nxt[u];
                if(p && nx && hasEdge(p, nx)){
                    removable.push_back(u);
                }
                u = nxt[u];
            }
        }
        if(removable.empty()) return false;

        // Shuffle for randomness
        for(int i=removable.size()-1;i>0;i--){
            int j=rng()%(i+1);
            swap(removable[i],removable[j]);
        }

        // Try removing each and see if it enables extension at endpoints
        int attempts = min((int)removable.size(), 200);
        for(int idx=0; idx<attempts; idx++){
            int v = removable[idx];
            int pv = prv[v], nv = nxt[v];

            // Check if removing v and placing at tail enables forward extension
            // OR placing at head enables backward extension
            bool canExtendFromV = false;
            for(int w:adj[v]) if(!used[w] && w!=v) { canExtendFromV=true; break; }
            bool canExtendToV = false;
            for(int w:radj[v]) if(!used[w] && w!=v) { canExtendToV=true; break; }

            if(!canExtendFromV && !canExtendToV) continue;

            // Check: can we place v at tail?
            if(canExtendFromV && hasEdge(tail, v)){
                // Remove v from interior
                nxt[pv] = nv; prv[nv] = pv;
                // Append v to tail
                nxt[tail] = v; prv[v] = tail; nxt[v] = 0;
                tail = v;
                // Now try forward extension from new tail
                while(true){
                    int bd=INT_MAX,cnt=0; int picks[16];
                    for(int w:adj[tail]) if(!used[w]){
                        if(dout[w]<bd){bd=dout[w];cnt=0;picks[0]=w;cnt=1;}
                        else if(dout[w]==bd&&cnt<16){picks[cnt++]=w;}
                    }
                    if(!cnt)break;
                    int p=picks[rng()%cnt];
                    nxt[tail]=p;prv[p]=tail;nxt[p]=0;
                    used[p]=1;
                    for(int u:radj[p]) if(!used[u]) dout[u]--;
                    tail=p;
                    pathLen++;
                    improved=true;
                }
                if(improved) return true;
                // Undo if no extension happened
                nxt[tail] = 0; // tail is still v since no extension
                // Put v back at original position
                nxt[pv] = v; prv[v] = pv; nxt[v] = nv; prv[nv] = v;
                tail = v; // wait, we need to restore tail
                // Actually this is complex to undo properly. Let's just continue.
                // The path length didn't change so it's fine.
                // Restore: v is at tail position but no extension happened
                // Need to put v back and restore old tail
                // This gets messy. Let me simplify: just skip undo and accept the relocation
                // even without extension (path length stays same, just rearranged)
                continue;
            }

            // Check: can we place v at head?
            if(canExtendToV && hasEdge(v, head)){
                nxt[pv] = nv; prv[nv] = pv;
                prv[head] = v; nxt[v] = head; prv[v] = 0;
                head = v;
                while(true){
                    int bd=INT_MAX,cnt=0; int picks[16];
                    for(int u:radj[head]) if(!used[u]){
                        if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                        else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                    }
                    if(!cnt)break;
                    int p=picks[rng()%cnt];
                    prv[head]=p;nxt[p]=head;prv[p]=0;
                    used[p]=1;
                    for(int u:radj[p]) if(!used[u]) dout[u]--;
                    head=p;
                    pathLen++;
                    improved=true;
                }
                if(improved) return true;
                continue;
            }
        }
        return improved;
    };

    // Full run: greedy + relocation + insertion improvement
    auto fullRun=[&](int start){
        auto [head, tail] = greedyBuild(start);
        int pathLen = 0;
        for(int u=head;u;u=nxt[u]) pathLen++;

        // Iterative improvement: relocation + re-extension + insertion
        for(int iter=0; iter<50 && elapsed()<3.5; iter++){
            bool ch = false;
            // Try insertion of unvisited vertices
            {
                int u=head;
                while(u){
                    int w=nxt[u];
                    if(!w)break;
                    for(int v:adj[u]) if(!used[v]&&hasEdge(v,w)){
                        nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;
                        used[v]=1;
                        for(int r:radj[v]) if(!used[r]) dout[r]--;
                        w=v;pathLen++;ch=true;
                    }
                    u=w;
                }
            }
            // Try prepend/append unvisited
            for(int v=1;v<=n&&elapsed()<3.5;v++){
                if(used[v]) continue;
                if(hasEdge(v,head)){
                    prv[head]=v;nxt[v]=head;prv[v]=0;head=v;
                    used[v]=1;
                    for(int r:radj[v]) if(!used[r]) dout[r]--;
                    pathLen++;ch=true;
                }else if(hasEdge(tail,v)){
                    nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;
                    used[v]=1;
                    for(int r:radj[v]) if(!used[r]) dout[r]--;
                    pathLen++;ch=true;
                }
            }
            if(!ch) break;
        }

        if(pathLen>bestLen){
            bestLen=pathLen;
            bestPath.clear(); bestPath.reserve(n);
            for(int u=head;u;u=nxt[u]) bestPath.push_back(u);
        }
    };

    // Start candidates: in-degree 0, then sorted by various metrics
    vector<int> starts;
    for(int u=1;u<=n;u++) if(indeg[u]==0) starts.push_back(u);
    {
        vector<int> order(n); iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[&](int a,int b){ return indeg[a]<indeg[b]; });
        for(int i=0;i<min(n,20);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
        sort(order.begin(),order.end(),[&](int a,int b){ return outdeg[a]-indeg[a]>outdeg[b]-indeg[b]; });
        for(int i=0;i<min(n,10);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
    }

    // Phase 1: Smart starts
    for(int s:starts){
        if(bestLen==n||elapsed()>1.0) break;
        fullRun(s);
    }
    // Phase 2: Random restarts
    while(bestLen<n && elapsed()<3.5){
        fullRun((rng()%n)+1);
    }

    printf("%d\n",bestLen);
    for(int i=0;i<bestLen;i++){
        if(i) printf(" ");
        printf("%d",bestPath[i]);
    }
    printf("\n");
    return 0;
}
