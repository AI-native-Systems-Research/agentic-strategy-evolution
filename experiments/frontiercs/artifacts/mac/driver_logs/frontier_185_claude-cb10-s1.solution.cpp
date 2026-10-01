#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1001;
bitset<MAXN> adj[MAXN];
int N, M;
int best_size = 0;
vector<int> best_clique;
chrono::steady_clock::time_point start_time;
bool timeout_flag;
mt19937 rng(42);

inline int elapsed_ms() {
    return (int)chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - start_time).count();
}

void update_best(const vector<int>& c) {
    if ((int)c.size() > best_size) {
        // verify
        for (int i = 0; i < (int)c.size(); i++)
            for (int j = i+1; j < (int)c.size(); j++)
                if (!adj[c[i]][c[j]]) return;
        best_size = c.size();
        best_clique = c;
    }
}

void bnb(bitset<MAXN>& P, vector<int>& cur, int depth, int time_limit) {
    if (timeout_flag) return;
    if ((depth & 7) == 0 && elapsed_ms() > time_limit) { timeout_flag = true; return; }
    
    if (P.none()) { 
        if ((int)cur.size() > best_size) {
            best_size = cur.size();
            best_clique = cur;
        }
        return; 
    }
    
    int cnt = (int)P.count();
    if ((int)cur.size() + cnt <= best_size) return;
    
    vector<int> verts;
    verts.reserve(cnt);
    for (int v = P._Find_first(); v <= N; v = P._Find_next(v)) verts.push_back(v);
    
    // Sort by degree in subgraph ascending for greedy coloring
    sort(verts.begin(), verts.end(), [&](int a, int b) {
        return (adj[a] & P).count() < (adj[b] & P).count();
    });
    
    // Greedy coloring
    int ncolors = 0;
    vector<bitset<MAXN>> color_class;
    vector<int> vcol(cnt);
    
    for (int i = 0; i < cnt; i++) {
        int v = verts[i];
        int c;
        for (c = 0; c < ncolors; c++) {
            if ((adj[v] & color_class[c]).none()) break;
        }
        if (c == ncolors) { color_class.emplace_back(); ncolors++; }
        color_class[c].set(v);
        vcol[i] = c + 1;
    }
    
    if ((int)cur.size() + ncolors <= best_size) return;
    
    // 2-swap recoloring
    int need = best_size - (int)cur.size();
    for (int i = cnt - 1; i >= 0; i--) {
        int v = verts[i];
        if (vcol[i] <= need) break;
        int cur_c = vcol[i] - 1;
        bool improved = false;
        
        for (int c = 0; c < cur_c && !improved; c++) {
            if ((adj[v] & color_class[c]).none()) {
                color_class[cur_c].reset(v);
                color_class[c].set(v);
                vcol[i] = c + 1;
                improved = true;
            }
        }
        if (improved) continue;
        
        for (int c1 = 0; c1 < cur_c && !improved; c1++) {
            bitset<MAXN> conflicts = adj[v] & color_class[c1];
            if ((int)conflicts.count() == 1) {
                int w = conflicts._Find_first();
                for (int c2 = 0; c2 < ncolors; c2++) {
                    if (c2 == c1 || c2 == cur_c) continue;
                    if ((adj[w] & color_class[c2]).none()) {
                        color_class[cur_c].reset(v);
                        color_class[c1].reset(w);
                        color_class[c1].set(v);
                        color_class[c2].set(w);
                        vcol[i] = c1 + 1;
                        for (int j = 0; j < cnt; j++)
                            if (verts[j] == w) { vcol[j] = c2 + 1; break; }
                        improved = true;
                        break;
                    }
                }
            }
        }
    }
    
    int max_col = 0;
    for (int i = 0; i < cnt; i++) max_col = max(max_col, vcol[i]);
    ncolors = max_col;
    if ((int)cur.size() + ncolors <= best_size) return;
    
    vector<pair<int,int>> colored(cnt);
    for (int i = 0; i < cnt; i++) colored[i] = {vcol[i], verts[i]};
    sort(colored.begin(), colored.end(), [](auto& a, auto& b){ return a.first > b.first; });
    
    for (auto& [col, v] : colored) {
        if (timeout_flag) return;
        if ((int)cur.size() + col <= best_size) return;
        P.reset(v);
        bitset<MAXN> newP = P & adj[v];
        cur.push_back(v);
        bnb(newP, cur, depth + 1, time_limit);
        cur.pop_back();
    }
}

void local_search(int time_limit_ms) {
    auto run_search = [&](vector<int> clique, int end_ms) {
        bitset<MAXN> inClique;
        for (int v : clique) inClique.set(v);
        vector<int> tight(N+1,0);
        for (int v : clique)
            for (int u = adj[v]._Find_first(); u <= N; u = adj[v]._Find_next(u)) tight[u]++;
        int csize = (int)clique.size();
        vector<int> tabu(N+1,0);
        int iter=0, no_improve=0;
        while (elapsed_ms() < end_ms) {
            iter++; no_improve++;
            int best_add=-1, best_add_deg=-1;
            for (int v=1;v<=N;v++) if (!inClique[v]&&tight[v]==csize) {
                int d=(int)(adj[v]&~inClique).count();
                if (d>best_add_deg||(d==best_add_deg&&(rng()&1))){best_add=v;best_add_deg=d;}
            }
            if (best_add!=-1) {
                inClique.set(best_add);clique.push_back(best_add);csize++;
                for(int u=adj[best_add]._Find_first();u<=N;u=adj[best_add]._Find_next(u))tight[u]++;
                tabu[best_add]=iter+csize+(rng()%5);
                if(csize>best_size){best_size=csize;best_clique=clique;no_improve=0;}
                continue;
            }
            int bs=-1,bss=-1;
            for(int v=1;v<=N;v++) if(!inClique[v]&&tight[v]==csize-1&&tabu[v]<=iter){
                int d=(int)adj[v].count();if(d>bss||(d==bss&&(rng()&1))){bs=v;bss=d;}}
            if(bs!=-1){int drop=-1;for(int u:clique)if(!adj[bs][u]){drop=u;break;}
                if(drop!=-1){inClique.reset(drop);clique.erase(find(clique.begin(),clique.end(),drop));csize--;
                for(int u=adj[drop]._Find_first();u<=N;u=adj[drop]._Find_next(u))tight[u]--;
                tabu[drop]=iter+csize+3+(rng()%10);inClique.set(bs);clique.push_back(bs);csize++;
                for(int u=adj[bs]._Find_first();u<=N;u=adj[bs]._Find_next(u))tight[u]++;
                tabu[bs]=iter+csize+(rng()%5);}continue;}
            if(csize>1){int nd=(no_improve>15)?min(csize-1,1+(int)(rng()%max(1,csize/3))):1;
                for(int d=0;d<nd&&csize>1;d++){int idx=rng()%csize;int drop=clique[idx];
                inClique.reset(drop);clique[idx]=clique.back();clique.pop_back();csize--;
                for(int u=adj[drop]._Find_first();u<=N;u=adj[drop]._Find_next(u))tight[u]--;
                tabu[drop]=iter+csize+5+(rng()%15);}if(no_improve>15)no_improve=0;}
        }
    };
    while(elapsed_ms()<time_limit_ms){
        vector<int> init;int r=rng()%5;
        if(r<2&&!best_clique.empty()){init=best_clique;}
        else{int sv=rng()%N+1;init={sv};bitset<MAXN> common=adj[sv];
        while(common.any()){vector<int>c;for(int v=common._Find_first();v<=N;v=common._Find_next(v))c.push_back(v);
        sort(c.begin(),c.end(),[&](int a,int b){return(adj[a]&common).count()>(adj[b]&common).count();});
        int top=max(1,(int)c.size()/3);int pick=c[rng()%top];init.push_back(pick);common&=adj[pick];}
        update_best(init);}
        int rem=time_limit_ms-elapsed_ms();if(rem<5)break;
        run_search(init,min(time_limit_ms,elapsed_ms()+max(50,rem/4)));
    }
}

int main(){
    ios::sync_with_stdio(false);cin.tie(NULL);
    start_time=chrono::steady_clock::now();
    cin>>N>>M;
    for(int i=0;i<M;i++){int u,v;cin>>u>>v;adj[u].set(v);adj[v].set(u);}
    vector<int>deg(N+1);for(int i=1;i<=N;i++)deg[i]=(int)adj[i].count();
    vector<int>order;vector<bool>removed(N+1,false);
    for(int it=0;it<N;it++){int mv=-1,md=N+1;
    for(int i=1;i<=N;i++)if(!removed[i]&&deg[i]<md){md=deg[i];mv=i;}
    order.push_back(mv);removed[mv]=true;
    for(int j=1;j<=N;j++)if(!removed[j]&&adj[mv][j])deg[j]--;}
    timeout_flag=false;
    for(int idx=N-1;idx>=0&&!timeout_flag;idx--){
        int v=order[idx];bitset<MAXN>P;
        for(int j=idx+1;j<N;j++){int u=order[j];if(adj[v][u])P.set(u);}
        vector<int>cur={v};
        if((int)cur.size()+(int)P.count()<=best_size)continue;
        bnb(P,cur,0,1400);
    }
    local_search(1940);
    vector<int>inC(N+1,0);for(int v:best_clique)inC[v]=1;
    for(int i=1;i<=N;i++)cout<<inC[i]<<"\n";
}
