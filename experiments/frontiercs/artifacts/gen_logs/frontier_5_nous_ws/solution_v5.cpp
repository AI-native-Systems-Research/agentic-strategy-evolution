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

    // Greedy + Posa rotation approach
    auto solve=[&](int start, double tl) -> int {
        // Build path as array with position tracking
        vector<int> path;
        path.reserve(n);
        vector<int> pos(n+1, -1);
        vector<char> inPath(n+1, 0);
        vector<int> dout(n+1);
        for(int u=1;u<=n;u++) dout[u]=outdeg[u];

        auto markUsed=[&](int v){
            inPath[v]=1;
            pos[v]=path.size()-1; // set after push_back
            for(int u:radj[v]) if(!inPath[u]) dout[u]--;
        };

        // Initialize with start vertex
        path.push_back(start);
        pos[start]=0;
        inPath[start]=1;
        for(int u:radj[start]) dout[u]--;

        // Forward extension with Warnsdorff
        auto extendForward=[&]() -> bool {
            bool extended=false;
            while(true){
                int tail=path.back();
                int bd=INT_MAX,cnt=0; int picks[16];
                for(int v:adj[tail]) if(!inPath[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
                if(!cnt) break;
                int p=picks[rng()%cnt];
                path.push_back(p);
                pos[p]=path.size()-1;
                inPath[p]=1;
                for(int u:radj[p]) if(!inPath[u]) dout[u]--;
                extended=true;
            }
            return extended;
        };

        extendForward();

        // Insertion pass: insert unvisited vertices between consecutive path vertices
        auto insertionPass=[&]() -> bool {
            bool ch=false;
            // For efficiency, scan path and try insertions
            int pathLen=path.size();
            for(int idx=0;idx<pathLen-1 && elapsed()<tl;idx++){
                int u=path[idx], w=path[idx+1];
                for(int v:adj[u]) if(!inPath[v]&&hasEdge(v,w)){
                    // Insert v between idx and idx+1
                    path.insert(path.begin()+idx+1, v);
                    pathLen++;
                    inPath[v]=1;
                    for(int r:radj[v]) if(!inPath[r]) dout[r]--;
                    // Update positions from idx+1 onward
                    for(int k=idx+1;k<pathLen;k++) pos[path[k]]=k;
                    ch=true;
                    // Don't advance idx, check new pair (u, v)
                    break; // move to next pair
                }
            }
            return ch;
        };

        // Prepend/append unvisited vertices
        auto prependAppend=[&]() -> bool {
            bool ch=false;
            for(int v=1;v<=n;v++){
                if(inPath[v]) continue;
                if(hasEdge(v, path[0])){
                    path.insert(path.begin(), v);
                    inPath[v]=1;
                    for(int r:radj[v]) if(!inPath[r]) dout[r]--;
                    for(int k=0;k<(int)path.size();k++) pos[path[k]]=k;
                    ch=true;
                } else if(hasEdge(path.back(), v)){
                    path.push_back(v);
                    pos[v]=path.size()-1;
                    inPath[v]=1;
                    for(int r:radj[v]) if(!inPath[r]) dout[r]--;
                    ch=true;
                }
            }
            return ch;
        };

        // Do initial insertion + prepend/append
        for(int p2=0;p2<10&&elapsed()<tl;p2++){
            bool ch=insertionPass();
            ch|=prependAppend();
            extendForward();
            if(!ch) break;
        }

        // === Directed Pósa Rotation ===
        // When can't extend tail:
        // 1. Find shortcut: tail → path[i] (i < pathLen-1)
        // 2. If i == 0: cycle formed, break at j where path[j] has unvisited out-neighbor
        //    New path: path[j+1..k-1] + path[0..j], tail = path[j]
        // 3. If i > 0: need edge path[i-1] → path[j+1] for some j ∈ [i, k-2]
        //    New path: path[0..i-1] + path[j+1..k-1] + path[i..j], tail = path[j]
        // 4. Try extending from new tail

        int rotations = 0;
        int maxRotations = min(n * 20, 1000000);

        while((int)path.size() < n && rotations < maxRotations && elapsed() < tl){
            int pathLen = path.size();
            int tail = path[pathLen-1];

            // Try to extend first
            {
                bool ext=false;
                int bd=INT_MAX,cnt=0; int picks[16];
                for(int v:adj[tail]) if(!inPath[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
                if(cnt>0){
                    int p=picks[rng()%cnt];
                    path.push_back(p);
                    pos[p]=path.size()-1;
                    inPath[p]=1;
                    for(int u:radj[p]) if(!inPath[u]) dout[u]--;
                    continue; // keep extending
                }
            }

            // Can't extend. Try Pósa rotation.
            rotations++;

            // Collect shortcuts from tail to path interior
            // Shuffle adj for randomness
            vector<int>& tAdj = adj[tail];
            bool rotated = false;

            // Randomly pick from tail's neighbors that are on the path
            vector<int> shortcuts;
            for(int v:tAdj){
                if(inPath[v] && pos[v] < pathLen-1){
                    shortcuts.push_back(pos[v]);
                }
            }
            if(shortcuts.empty()) break; // no shortcuts, give up on this path

            // Shuffle shortcuts
            for(int ii=shortcuts.size()-1;ii>0;ii--){
                int jj=rng()%(ii+1);
                swap(shortcuts[ii],shortcuts[jj]);
            }

            for(int i : shortcuts){
                if(rotated) break;

                if(i == 0){
                    // Tail → Head: forms a full cycle
                    // Find j where path[j] has an unvisited out-neighbor
                    // Try random positions
                    vector<int> candidates;
                    for(int j=0; j<pathLen-1; j++){
                        for(int w:adj[path[j]]) if(!inPath[w]){
                            candidates.push_back(j);
                            break;
                        }
                    }
                    if(candidates.empty()) continue;
                    int j = candidates[rng()%candidates.size()];

                    // Rotate: new path = path[j+1..k-1] + path[0..j]
                    vector<int> newPath;
                    newPath.reserve(pathLen);
                    for(int k2=j+1;k2<pathLen;k2++) newPath.push_back(path[k2]);
                    for(int k2=0;k2<=j;k2++) newPath.push_back(path[k2]);
                    path = newPath;
                    for(int k2=0;k2<pathLen;k2++) pos[path[k2]]=k2;
                    rotated = true;
                } else {
                    // Tail → path[i], i > 0
                    // Need edge path[i-1] → path[j+1] for j in [i, k-2]
                    // AND path[j] should ideally have unvisited out-neighbor

                    int pi_1 = path[i-1];
                    vector<int> validBreaks;
                    for(int j=i; j<pathLen-1; j++){
                        int jp1 = path[j+1];
                        if(hasEdge(pi_1, jp1)){
                            // Check if new tail (path[j]) has unvisited out-neighbor
                            bool hasUnvis = false;
                            for(int w:adj[path[j]]) if(!inPath[w]){hasUnvis=true;break;}
                            if(hasUnvis) validBreaks.push_back(j);
                        }
                    }
                    if(validBreaks.empty()){
                        // Try without the "has unvisited" requirement (just rotate for diversity)
                        for(int j=i; j<pathLen-1; j++){
                            if(hasEdge(pi_1, path[j+1])){
                                validBreaks.push_back(j);
                            }
                        }
                    }
                    if(validBreaks.empty()) continue;

                    int j = validBreaks[rng()%validBreaks.size()];

                    // New path: path[0..i-1] + path[j+1..k-1] + path[i..j]
                    vector<int> newPath;
                    newPath.reserve(pathLen);
                    for(int k2=0;k2<=i-1;k2++) newPath.push_back(path[k2]);
                    for(int k2=j+1;k2<pathLen;k2++) newPath.push_back(path[k2]);
                    for(int k2=i;k2<=j;k2++) newPath.push_back(path[k2]);
                    path = newPath;
                    for(int k2=0;k2<pathLen;k2++) pos[path[k2]]=k2;
                    rotated = true;
                }
            }

            if(!rotated) break; // no valid rotation found

            // After rotation, try to extend from new tail
            extendForward();
            // Also try insertion once
            insertionPass();
        }

        // Final insertion + prepend/append pass
        for(int p3=0;p3<5&&elapsed()<tl;p3++){
            bool ch=insertionPass();
            ch|=prependAppend();
            if(!ch) break;
        }

        int pathLen = path.size();
        if(pathLen > bestLen){
            bestLen = pathLen;
            bestPath = path;
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

    // Phase 2: Random restarts with full pipeline
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
