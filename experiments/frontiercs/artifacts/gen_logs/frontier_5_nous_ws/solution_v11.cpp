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

    // Linked list representation
    vector<int> nxt(n+1,0), prv(n+1,0);
    vector<int> dout(n+1);
    vector<char> used(n+1);

    auto solve=[&](int start, double tl) -> int {
        for(int u=1;u<=n;u++){dout[u]=outdeg[u];used[u]=0;nxt[u]=0;prv[u]=0;}
        used[start]=1;
        for(int u:radj[start]) if(!used[u]) dout[u]--;

        int head=start, tail=start, pathLen=1;
        auto mark=[&](int v){
            used[v]=1;
            for(int u:radj[v]) if(!used[u]) dout[u]--;
        };

        // Forward extension from tail with Warnsdorff
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
                nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;
            }
            return ext;
        };
        // Backward extension from head
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
                prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;
            }
            return ext;
        };
        // Insertion pass using linked list
        auto ins=[&]()->bool{
            bool ch=false;
            int u=head;
            while(u){
                int w=nxt[u];
                if(!w) break;
                for(int v:adj[u]) if(!used[v]&&hasEdge(v,w)){
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

        // === Directed Pósa Rotation (O(1) per rotation using linked list) ===
        // When tail is stuck:
        // Find shortcut: tail → vi (vi on path, vi != tail)
        // Case 1: vi == head → cycle → break at vj where vj has unvisited out-neighbor
        //   Reconnect: head becomes nxt[vj], tail becomes vj (cycle broken)
        // Case 2: vi != head → need prv[vi] → nxt[vj] edge (break point)
        //   Original: ...→prv[vi]→vi→...→vj→nxt[vj]→...→tail
        //   New:      ...→prv[vi]→nxt[vj]→...→tail→vi→...→vj (new tail)
        //   O(1) pointer surgery:
        //     let e=prv[vi], c=nxt[vj]
        //     nxt[e]=c; prv[c]=e;     // connect prefix to segment B
        //     nxt[tail]=vi; prv[vi]=tail;  // connect tail (end of B) to start of A
        //     nxt[vj]=0; tail=vj;     // vj is new tail

        int maxRot = min(n * 50, 2000000);
        int rotCount = 0;

        while(pathLen < n && rotCount < maxRot && elapsed() < tl){
            // Try extending first
            if(extF()) continue;

            rotCount++;

            // Collect shortcuts: tail → vi where vi is on path and vi != tail
            // Shuffle for diversity
            vector<int> shortcuts;
            for(int v:adj[tail]){
                if(used[v] && v != tail) shortcuts.push_back(v);
            }
            if(shortcuts.empty()) break;

            // Shuffle
            for(int i=shortcuts.size()-1;i>0;i--){
                int j2=rng()%(i+1);
                swap(shortcuts[i],shortcuts[j2]);
            }

            bool rotated = false;
            for(int vi : shortcuts){
                if(rotated) break;

                if(vi == head){
                    // Case 1: tail → head, forms cycle
                    // Find vj on path where vj has unvisited out-neighbor
                    // Walk the cycle to find candidates
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

                    // Rotate: break at vj
                    // New path: nxt[vj] → ... → tail → head → ... → vj
                    int newHead = nxt[vj];
                    // Pointer surgery:
                    nxt[tail] = head;    // close cycle
                    prv[head] = tail;
                    nxt[vj] = 0;         // break cycle at vj
                    prv[newHead] = 0;
                    head = newHead;
                    tail = vj;
                    rotated = true;
                } else {
                    // Case 2: tail → vi, vi != head
                    // Need edge prv[vi] → nxt[vj] for some vj between vi and tail (inclusive vi, exclusive tail)
                    int e = prv[vi]; // e = prv[vi]
                    if(!e) continue; // vi is head, already handled above

                    // Walk from vi to tail-1, looking for vj where hasEdge(e, nxt[vj])
                    // and preferably vj has unvisited out-neighbor
                    vector<int> goodBreaks, anyBreaks;
                    int vj2 = vi;
                    while(vj2 && nxt[vj2]){
                        int c = nxt[vj2];
                        if(c && hasEdge(e, c)){
                            bool hasUnvis=false;
                            for(int w:adj[vj2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) goodBreaks.push_back(vj2);
                            else anyBreaks.push_back(vj2);
                        }
                        if(vj2 == tail) break;
                        vj2 = nxt[vj2];
                    }

                    int vj = 0;
                    if(!goodBreaks.empty()) vj = goodBreaks[rng()%goodBreaks.size()];
                    else if(!anyBreaks.empty()) vj = anyBreaks[rng()%anyBreaks.size()];
                    if(!vj) continue;

                    int c = nxt[vj];
                    // Pointer surgery:
                    // Original: ...→e→vi→...→vj→c→...→tail
                    // New:      ...→e→c→...→tail→vi→...→vj (new tail)
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

            // After rotation, try to extend + insert
            extF();
        }

        // Also try backward extension + insertion at end
        extB();
        for(int p3=0;p3<5&&elapsed()<tl;p3++){
            bool ch=ins();
            if(ch){extF();extB();}
            else break;
        }

        // Final: try prepend/append individual vertices
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
            // Try insertion after adding
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

    // Phase 1: Smart starts — give each one enough rotation time
    for(int s:starts){
        if(bestLen==n||elapsed()>2.0) break;
        solve(s, min(elapsed()+0.5, 2.0));
    }
    // Phase 2: Random restarts — each gets up to 0.3s of rotation time
    while(bestLen<n && elapsed()<3.5){
        int s=(rng()%n)+1;
        solve(s, min(elapsed()+0.3, 3.5));
    }

    printf("%d\n",bestLen);
    for(int i=0;i<bestLen;i++){
        if(i) printf(" ");
        printf("%d",bestPath[i]);
    }
    printf("\n");
    return 0;
}
