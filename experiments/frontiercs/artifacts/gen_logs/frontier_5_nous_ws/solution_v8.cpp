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
        for(int p2=0;p2<15;p2++){
            bool ch=ins();
            if(ch){extF();extB();}
            else break;
        }

        // Forward Pósa rotation with O(1) pointer surgery
        auto rotateForward=[&]() -> bool {
            vector<int> shortcuts;
            for(int v:adj[tail]){
                if(used[v] && v!=tail) shortcuts.push_back(v);
            }
            if(shortcuts.empty()) return false;
            for(int i=shortcuts.size()-1;i>0;i--){
                int j2=rng()%(i+1); swap(shortcuts[i],shortcuts[j2]);
            }

            for(int vi : shortcuts){
                if(vi == head){
                    // Cycle case: find vj with unvisited out-neighbor
                    vector<int> cands;
                    int u2=head;
                    while(u2 && u2!=tail){
                        for(int w:adj[u2]) if(!used[w]){cands.push_back(u2);break;}
                        u2=nxt[u2];
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
                    // Walk from vi toward tail, find break point vj
                    vector<int> goodBreaks, anyBreaks;
                    int vj2=vi;
                    while(vj2 && nxt[vj2]){
                        int c=nxt[vj2];
                        if(hasEdge(e,c)){
                            bool hasUnvis=false;
                            for(int w:adj[vj2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) goodBreaks.push_back(vj2);
                            else anyBreaks.push_back(vj2);
                        }
                        if(vj2==tail) break;
                        vj2=nxt[vj2];
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

        // Backward Pósa rotation: find vi on path such that head has edge FROM vi
        // i.e., vi → head exists, and vi is on path, vi != head
        // If vi == tail: cycle (same as forward tail→head case)
        // If vi != tail: need nxt[vi]→prv[vj] edge for break point
        //   Path: head→...→prv[vj]→vj→...→vi→nxt[vi]→...→tail
        //   Cycle portion: head→...→vi→head (using shortcut vi→head)
        //   We break at prv[vj]→vj inside cycle, need to bridge suffix nxt[vi]→...→tail
        //   New path: vj→...→vi→head→...→prv[vj]→nxt[vi]→...→tail
        //   Need: prv[vj]→nxt[vi] edge exists
        //   Pointer surgery:
        //     Let f = nxt[vi], bp = prv[vj]
        //     nxt[vi] = head; prv[head] = vi;    // close cycle (shortcut)
        //     nxt[bp] = f; prv[f] = bp;          // bridge to suffix
        //     prv[vj] = 0; head = vj;            // new head

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
                    // Tail→Head: full cycle
                    // Find vj with unvisited in-neighbor
                    vector<int> cands;
                    int u2=nxt[head]; // skip head itself
                    while(u2 && u2!=tail){
                        for(int w:radj[u2]) if(!used[w]){cands.push_back(u2);break;}
                        u2=nxt[u2];
                    }
                    // Also check tail
                    for(int w:radj[tail]) if(!used[w]){cands.push_back(tail);break;}
                    if(cands.empty()) continue;
                    int vj = cands[rng()%cands.size()];
                    // Rotate: new head=vj, new tail=prv[vj]
                    int newTail = prv[vj];
                    nxt[tail]=head; prv[head]=tail;
                    nxt[newTail]=0; prv[vj]=0;
                    head=vj; tail=newTail;
                    return true;
                } else {
                    // vi→head shortcut, vi is interior (not tail, not head)
                    int f = nxt[vi];
                    if(!f) continue;

                    // Walk from head+1 through path up to vi, find break vj
                    // where prv[vj]→f edge exists
                    vector<int> goodBreaks, anyBreaks;
                    int vj2=nxt[head]; // start from second vertex
                    while(vj2){
                        int bp=prv[vj2];
                        if(bp && hasEdge(bp, f)){
                            bool hasUnvis=false;
                            for(int w:radj[vj2]) if(!used[w]){hasUnvis=true;break;}
                            if(hasUnvis) goodBreaks.push_back(vj2);
                            else anyBreaks.push_back(vj2);
                        }
                        if(vj2==vi) break;
                        vj2=nxt[vj2];
                    }

                    int vj=0;
                    if(!goodBreaks.empty()) vj=goodBreaks[rng()%goodBreaks.size()];
                    else if(!anyBreaks.empty()) vj=anyBreaks[rng()%anyBreaks.size()];
                    if(!vj) continue;

                    int bp=prv[vj];
                    // Pointer surgery
                    nxt[vi]=head; prv[head]=vi;
                    nxt[bp]=f; prv[f]=bp;
                    prv[vj]=0; head=vj;
                    return true;
                }
            }
            return false;
        };

        // Main rotation loop
        int maxRot = min((long long)n * 100, (long long)5000000);
        int rotCount = 0;

        while(pathLen < n && rotCount < maxRot && elapsed() < tl){
            // Try extending both ends
            bool ext = extF() | extB();
            if(ext) continue;

            rotCount++;

            // Try forward rotation
            bool rotated = rotateForward();
            if(!rotated) rotated = rotateBackward();

            if(!rotated){
                // Try insertion
                if(ins()){extF();extB();continue;}
                break;
            }

            // After rotation, try extending + occasional insertion
            extF(); extB();
            if(rotCount % 100 == 0){
                ins(); extF(); extB();
            }
        }

        // Final cleanup: insertion + prepend/append
        for(int p3=0;p3<5&&elapsed()<tl;p3++){
            bool ch=ins();
            ch|=extF()|extB();
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
