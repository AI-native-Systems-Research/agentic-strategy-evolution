#include <bits/stdc++.h>
using namespace std;

int main(){
    int n, m;
    scanf("%d %d", &n, &m);
    int a[10];
    for(int i=0;i<10;i++) scanf("%d", &a[i]);

    // Use flat arrays for speed
    vector<int> adjHead(n+1,-1), adjNxt(m), adjTo(m);
    vector<int> radjHead(n+1,-1), radjNxt(m), radjTo(m);
    int eidx=0, reidx=0;
    vector<int> outdeg(n+1,0), indeg(n+1,0);

    // Also keep vector-based adj for binary search
    vector<vector<int>> adj(n+1), radj(n+1);
    for(int i=0;i<m;i++){
        int u,v; scanf("%d %d",&u,&v);
        adj[u].push_back(v);
        radj[v].push_back(u);
        outdeg[u]++; indeg[v]++;
    }

    // Sort for binary search edge lookup
    vector<vector<int>> sadj(n+1);
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

    // Preallocated arrays for greedy
    vector<int> dout(n+1);
    vector<char> used(n+1);

    // Greedy with dynamic Warnsdorff + both-end extension
    auto greedyRun=[&](int start)->int{
        for(int u=1;u<=n;u++){dout[u]=outdeg[u];used[u]=0;}
        used[start]=1;
        for(int u:radj[start]) dout[u]--;

        // Path as linked list
        static vector<int> nxt, prv;
        if((int)nxt.size()!=n+1){nxt.resize(n+1);prv.resize(n+1);}
        for(int u=1;u<=n;u++){nxt[u]=0;prv[u]=0;}
        int head=start, tail=start;

        auto mark=[&](int v){
            used[v]=1;
            for(int u:radj[v]) if(!used[u]) dout[u]--;
        };

        // Forward extend with Warnsdorff + random tie-breaking
        while(true){
            int bd=INT_MAX, cnt=0;
            int picks[16];
            for(int v:adj[tail]) if(!used[v]){
                if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;
        }

        // Backward extend
        while(true){
            int bd=INT_MAX, cnt=0;
            int picks[16];
            for(int u:radj[head]) if(!used[u]){
                if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
            }
            if(!cnt)break;
            int p=picks[rng()%cnt];
            prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;
        }

        // Insertion passes
        for(int pass=0;pass<20;pass++){
            bool ch=false;
            // Forward scan: insert v between u and w
            int u=head;
            while(u){int w=nxt[u];if(!w)break;
                for(int v:adj[u]) if(!used[v]&&hasEdge(v,w)){
                    nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;ch=true;
                }
                u=w;
            }
            // Reverse scan: insert v between p and u where p->v->u
            u=head;
            while(u){int p=prv[u];if(p){
                for(int v:radj[u]) if(!used[v]&&hasEdge(p,v)){
                    nxt[p]=v;prv[v]=p;nxt[v]=u;prv[u]=v;mark(v);ch=true;break;
                }
            }u=nxt[u];}
            if(!ch)break;
            // Re-extend
            while(true){
                int bd=INT_MAX,cnt=0;int picks[16];
                for(int v:adj[tail]) if(!used[v]){
                    if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}
                    else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}
                }
                if(!cnt)break;
                int p=picks[rng()%cnt];
                nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;
            }
            while(true){
                int bd=INT_MAX,cnt=0;int picks[16];
                for(int u:radj[head]) if(!used[u]){
                    if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}
                    else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}
                }
                if(!cnt)break;
                int p=picks[rng()%cnt];
                prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;
            }
        }

        int len=0;
        for(int u=head;u;u=nxt[u]) len++;
        if(len>bestLen){
            bestLen=len;
            bestPath.clear(); bestPath.reserve(n);
            for(int u=head;u;u=nxt[u]) bestPath.push_back(u);
        }
        return len;
    };

    // Start candidates
    vector<int> starts;
    for(int u=1;u<=n;u++) if(indeg[u]==0) starts.push_back(u);
    {
        vector<int> order(n); iota(order.begin(),order.end(),1);
        sort(order.begin(),order.end(),[&](int a,int b){
            return indeg[a]<indeg[b];
        });
        for(int i=0;i<min(n,20);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
        sort(order.begin(),order.end(),[&](int a,int b){
            return outdeg[a]-indeg[a]>outdeg[b]-indeg[b];
        });
        for(int i=0;i<min(n,10);i++){
            bool dup=false; for(int s:starts) if(s==order[i]) dup=true;
            if(!dup) starts.push_back(order[i]);
        }
    }

    // Phase 1: Smart starts
    for(int s:starts){
        if(bestLen==n||elapsed()>1.0)break;
        greedyRun(s);
    }

    // Phase 2: Random restarts
    while(bestLen<n && elapsed()<3.5){
        greedyRun((rng()%n)+1);
    }

    // Phase 3: Post-processing - try inserting remaining vertices
    if(bestLen<n && bestLen>0){
        vector<char> inP(n+1,0);
        for(int v:bestPath) inP[v]=1;

        // Build position map for O(1) lookup
        vector<int> pos(n+1,-1);
        for(int i=0;i<bestLen;i++) pos[bestPath[i]]=i;

        bool imp=true;
        while(imp && elapsed()<3.8){
            imp=false;
            for(int v=1;v<=n;v++){
                if(inP[v]) continue;
                // Try append
                if(hasEdge(bestPath.back(),v)){
                    bestPath.push_back(v);inP[v]=1;pos[v]=bestLen;bestLen++;imp=true;continue;
                }
                // Try prepend
                if(hasEdge(v,bestPath[0])){
                    bestPath.insert(bestPath.begin(),v);inP[v]=1;bestLen++;
                    for(int i=0;i<bestLen;i++) pos[bestPath[i]]=i;
                    imp=true;continue;
                }
                // Try insert between consecutive
                for(int i=0;i<bestLen-1;i++){
                    if(hasEdge(bestPath[i],v)&&hasEdge(v,bestPath[i+1])){
                        bestPath.insert(bestPath.begin()+i+1,v);inP[v]=1;bestLen++;
                        for(int j=i+1;j<bestLen;j++) pos[bestPath[j]]=j;
                        imp=true;break;
                    }
                }
            }
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
