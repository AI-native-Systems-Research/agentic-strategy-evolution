#include <bits/stdc++.h>
using namespace std;

int main(){
    int n, m;
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    vector<vector<int>> adj(n+1), radj(n+1);
    vector<vector<int>> sadj(n+1), sradj(n+1);
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
        sradj[u]=radj[u];
        sort(sradj[u].begin(),sradj[u].end());
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
        for(int p2=0;p2<10;p2++){
            bool ch=ins();
            if(ch){extF();extB();}
            else break;
        }

        // === Directed Pósa Rotation — Forward (rotate tail) ===
        auto rotateForward=[&]() -> bool {
            // Collect shortcuts: tail → vi where vi is on path, vi != tail
            vector<int> shortcuts;
            for(int v:adj[tail]){
                if(used[v] && v!=tail) shortcuts.push_back(v);
            }
            if(shortcuts.empty()) return false;
            // Shuffle
            for(int i=shortcuts.size()-1;i>0;i--){
                int j2=rng()%(i+1); swap(shortcuts[i],shortcuts[j2]);
            }

            for(int vi : shortcuts){
                if(vi == head){
                    // Tail→Head: cycle
                    // Walk cycle to find vj with unvisited out-neighbor
                    // Limit walk for large paths
                    int walkLimit = min(pathLen, 500);
                    vector<int> cands;
                    int u2=head; int steps=0;
                    while(u2 && u2!=tail && steps<walkLimit){
                        for(int w:adj[u2]) if(!used[w]){cands.push_back(u2);break;}
                        u2=nxt[u2]; steps++;
                    }
                    if(cands.empty()) continue;
                    int vj = cands[rng()%cands.size()];
                    int newHead = nxt[vj];
                    nxt[tail]=head; prv[head]=tail;
                    nxt[vj]=0; prv[newHead]=0;
                    head=newHead; tail=vj;
                    return true;
                } else {
                    int e = prv[vi];
                    if(!e) continue;
                    // Walk from vi toward tail, find break point vj where hasEdge(e, nxt[vj])
                    int walkLimit = min(pathLen, 500);
                    vector<int> goodBreaks, anyBreaks;
                    int vj2=vi; int steps=0;
                    while(vj2 && nxt[vj2] && steps<walkLimit){
                        int c=nxt[vj2];
                        if(hasEdge(e,c)){
                            bool hasUnvis=false;
                            for(int w:adj[vj2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) goodBreaks.push_back(vj2);
                            else anyBreaks.push_back(vj2);
                        }
                        vj2=nxt[vj2]; steps++;
                    }
                    int vj=0;
                    if(!goodBreaks.empty()) vj=goodBreaks[rng()%goodBreaks.size()];
                    else if(!anyBreaks.empty()) vj=anyBreaks[rng()%anyBreaks.size()];
                    if(!vj) continue;

                    int c=nxt[vj];
                    nxt[e]=c; prv[c]=e;
                    nxt[tail]=vi; prv[vi]=tail;
                    nxt[vj]=0; tail=vj;
                    return true;
                }
            }
            return false;
        };

        // === Directed Pósa Rotation — Backward (rotate head) ===
        // Symmetric: find shortcut vi → head where vi is on path
        // Case 1: vi == tail → cycle → break at vj where vj has unvisited in-neighbor
        //   Reorder: tail becomes prv[vj], head becomes vj
        // Case 2: vi != tail → need edge prv[vj] → nxt[vi] (break point)
        //   Original: head→...→vi→nxt[vi]→...→prv[vj]→vj→...→tail
        //   New: head→...→vi→(tail→...→vj)→(nxt[vi]→...→prv[vj])
        //   Wait, let me think more carefully.
        //
        //   Shortcut: vi → head. Path: head→...→vi→...→tail
        //   Cycle: head→...→vi→head
        //   Break at edge prv[vj]→vj for vj between head and vi:
        //     Need nxt[vi]→vj edge to exist
        //     New path: vj→...→vi→head→...→prv[vj]  (new head=vj, new tail=prv[vj])
        //
        //   No wait, let me re-derive.
        //
        //   Path: head→A→...→B→vi→C→...→tail
        //   Shortcut: vi→head
        //   Cycle: head→A→...→B→vi→head  (only vertices head..vi)
        //   Break at edge prv[vj]→vj in the cycle portion (vj between head and vi inclusive):
        //     New segment from cycle: vj→...→vi→head→...→prv[vj]
        //     Then append the rest: →C→...→tail
        //     But we need prv[vj]→C edge? No...
        //
        //     Actually the rest (C→...→tail) was nxt[vi]→...→tail in original
        //     After rotation: new path should include everyone
        //
        //     Hmm, this is the mirror of forward rotation.
        //     Forward: tail→vi shortcut → cycle vi...tail → break → move segment
        //     Backward: vi→head shortcut → cycle head...vi → break → move segment
        //
        //   Let me just do the mirror:
        //   Cycle: head→...→vi→head (using shortcut vi→head and path head→...→vi)
        //   Suffix (not in cycle): nxt[vi]→...→tail
        //   Break at edge prv[vj]→vj where prv[vj] and vj are in cycle:
        //     Need edge nxt[vi]→prv[vj] to stitch suffix to the break point
        //     New path: vj→...→vi→head→...→prv[vj]→nxt[vi]→...→tail
        //     Wait, that's not right either. Let me think step by step.
        //
        //   Original path: [head → ... → vi] → [nxt[vi] → ... → tail]
        //                   ^^^^^ cycle part      ^^^^^ suffix
        //   Cycle: head → ... → vi → head
        //   Break at prv[vj] → vj:
        //     Cycle path from break: vj → ... → vi → head → ... → prv[vj]
        //     Need to connect suffix: prv[vj] → nxt[vi] → ... → tail
        //     So need edge prv[vj] → nxt[vi]? No, prv[vj] is new tail of cycle segment
        //
        //   Full new path: vj → ... → vi → head → ... → prv[vj]  then  nxt[vi] → ... → tail
        //   We need prv[vj] → nxt[vi] edge to connect them.
        //
        //   So: new head = vj, new path = vj→...→vi→head→...→prv[vj]→nxt[vi]→...→tail
        //
        //   Wait, I keep getting confused. Let me use concrete variables.
        //
        //   Let f = nxt[vi] (first of suffix)
        //   Cycle portion: head → a1 → ... → ak → vi → head
        //   Break at edge bp → vj (bp = prv[vj]):
        //     Cycle from vj: vj → ... → vi → head → ... → bp
        //     New path: vj → ... → vi → head → ... → bp → f → ... → tail
        //     Need: bp → f edge exists (edge from bp to first of suffix)
        //     New head = vj, tail stays same
        //
        //   Pointer surgery:
        //     nxt[bp] was vj → set nxt[bp] = f; prv[f] = bp;  // connect to suffix
        //     nxt[vi] = head;  // already existed, but set: prv[head] = vi
        //     Actually: vi→head is the shortcut, but in the original path, nxt[vi]=f
        //     So we need: nxt[vi] = head (use shortcut); prv[head] = vi
        //     prv[vj] = 0 (new head)
        //     head = vj
        //     nxt[bp] = f; prv[f] = bp;

        auto rotateBackward=[&]() -> bool {
            vector<int> shortcuts;
            for(int v:radj[head]){
                if(used[v] && v!=head) shortcuts.push_back(v);
            }
            if(shortcuts.empty()) return false;
            for(int i=shortcuts.size()-1;i>0;i--){
                int j2=rng()%(i+1); swap(shortcuts[i],shortcuts[j2]);
            }

            for(int vi : shortcuts){
                if(vi == tail){
                    // Tail→Head: same as forward cycle case
                    // Find vj on path with unvisited in-neighbor (for backward extension)
                    int walkLimit = min(pathLen, 500);
                    vector<int> cands;
                    int u2=tail; int steps=0;
                    while(u2 && u2!=head && steps<walkLimit){
                        for(int w:radj[u2]) if(!used[w]){cands.push_back(u2);break;}
                        u2=prv[u2]; steps++;
                    }
                    if(cands.empty()) continue;
                    int vj = cands[rng()%cands.size()];
                    int newTail = prv[vj];
                    nxt[tail]=head; prv[head]=tail;
                    prv[vj]=0; nxt[newTail]=0;
                    head=vj; tail=newTail;
                    return true;
                } else {
                    // vi→head shortcut, vi is interior (not tail)
                    int f = nxt[vi];
                    if(!f) continue; // vi is tail, handled above

                    // Walk from head toward vi, find break point
                    // Need: prv[vj]→f edge exists  (bp=prv[vj], need bp→f)
                    int walkLimit = min(pathLen, 500);
                    vector<int> goodBreaks, anyBreaks;
                    int vj2=head; int steps=0;
                    while(vj2 && steps<walkLimit){
                        int bp=prv[vj2];
                        if(bp && hasEdge(bp, f)){
                            bool hasUnvis=false;
                            for(int w:radj[vj2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) goodBreaks.push_back(vj2);
                            else anyBreaks.push_back(vj2);
                        }
                        if(vj2==vi) break;
                        vj2=nxt[vj2]; steps++;
                    }

                    int vj=0;
                    if(!goodBreaks.empty()) vj=goodBreaks[rng()%goodBreaks.size()];
                    else if(!anyBreaks.empty()) vj=anyBreaks[rng()%anyBreaks.size()];
                    if(!vj) continue;

                    int bp=prv[vj];
                    // Pointer surgery:
                    // vj becomes new head
                    // vi→head closes cycle, bp→f bridges to suffix
                    nxt[vi]=head; prv[head]=vi;
                    nxt[bp]=f; prv[f]=bp;
                    prv[vj]=0;
                    head=vj;
                    return true;
                }
            }
            return false;
        };

        // Rotation loop: alternate forward and backward
        int maxRot = min(n * 100, 5000000);
        int rotCount = 0;
        int stuckCount = 0;

        while(pathLen < n && rotCount < maxRot && elapsed() < tl){
            // Try extending both ends
            bool ext = extF();
            ext |= extB();
            if(ext){ stuckCount=0; continue; }

            rotCount++;
            stuckCount++;

            // Alternate between forward and backward rotation
            bool rotated = false;
            if(stuckCount % 2 == 1){
                rotated = rotateForward();
                if(!rotated) rotated = rotateBackward();
            } else {
                rotated = rotateBackward();
                if(!rotated) rotated = rotateForward();
            }

            if(!rotated){
                // Try insertion as last resort
                if(ins()){extF();extB();stuckCount=0;continue;}
                break;
            }

            // After rotation, try extending
            extF(); extB();

            // Periodically do insertion
            if(rotCount % 50 == 0) ins();
        }

        // Final cleanup
        for(int p3=0;p3<5&&elapsed()<tl;p3++){
            bool ch=ins();
            ch|=extF();
            ch|=extB();
            // Try prepend/append
            for(int v=1;v<=n;v++){
                if(used[v]) continue;
                if(hasEdge(v,head)){
                    prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;ch=true;
                }else if(hasEdge(tail,v)){
                    nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;ch=true;
                }
            }
            if(!ch) break;
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
