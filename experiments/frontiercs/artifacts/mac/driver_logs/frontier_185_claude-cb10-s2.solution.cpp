#include <bits/stdc++.h>
using namespace std;

const int MAXN = 1002;
bitset<MAXN> adj[MAXN];
int N, M;
vector<int> bestClique;
int bestSize = 0;
mt19937 rng(42);
chrono::steady_clock::time_point startTime;

inline int elapsed_ms() {
    return (int)chrono::duration_cast<chrono::milliseconds>(
        chrono::steady_clock::now() - startTime).count();
}

int timeLimitMs = 1900;
bool timeUp = false;

void expand(vector<int>& clique, vector<int>& cands) {
    if (timeUp) return;
    if (elapsed_ms() > timeLimitMs) { timeUp = true; return; }
    
    if (cands.empty()) {
        if ((int)clique.size() > bestSize) {
            bestSize = clique.size();
            bestClique = clique;
        }
        return;
    }
    
    int nc = cands.size();
    if ((int)clique.size() + nc <= bestSize) return;
    
    // Greedy coloring
    vector<int> color(nc, 0);
    int maxColor = 0;
    vector<bitset<MAXN>> colorSet; // vertices in each color class by bitset on cands indices... use small approach
    
    // Use array-based coloring
    vector<int> usedArr(nc + 2, 0);
    int stamp = 0;
    
    for (int i = 0; i < nc; i++) {
        stamp++;
        for (int j = 0; j < i; j++) {
            if (adj[cands[i]].test(cands[j]) && color[j] > 0) {
                usedArr[color[j]] = stamp;
            }
        }
        int c = 1;
        while (usedArr[c] == stamp) c++;
        color[i] = c;
        if (c > maxColor) maxColor = c;
    }
    
    if ((int)clique.size() + maxColor <= bestSize) return;
    
    // Sort by color
    vector<int> idx(nc);
    iota(idx.begin(), idx.end(), 0);
    sort(idx.begin(), idx.end(), [&](int a, int b){ return color[a] < color[b]; });
    
    vector<int> sortedCands(nc), sortedColor(nc);
    for (int i = 0; i < nc; i++) {
        sortedCands[i] = cands[idx[i]];
        sortedColor[i] = color[idx[i]];
    }
    
    for (int i = nc - 1; i >= 0; i--) {
        if (timeUp) return;
        if ((int)clique.size() + sortedColor[i] <= bestSize) return;
        
        int v = sortedCands[i];
        clique.push_back(v);
        
        vector<int> newCands;
        newCands.reserve(i);
        for (int j = 0; j < i; j++) {
            if (adj[v].test(sortedCands[j])) {
                newCands.push_back(sortedCands[j]);
            }
        }
        
        expand(clique, newCands);
        clique.pop_back();
    }
}

void localSearch(int maxMs) {
    while (elapsed_ms() < maxMs) {
        vector<int> perm(N);
        iota(perm.begin(), perm.end(), 1);
        shuffle(perm.begin(), perm.end(), rng);
        
        vector<int> clique;
        bitset<MAXN> cBS, cn;
        cn.set();
        for (int v : perm) {
            if (cn.test(v)) {
                clique.push_back(v);
                cBS.set(v);
                cn &= adj[v];
            }
        }
        if ((int)clique.size() > bestSize) { bestSize=clique.size(); bestClique=clique; }
        
        vector<int> tight(N+1,0);
        for (int v=1;v<=N;v++) tight[v]=(int)(adj[v]&cBS).count();
        int cs=clique.size();
        set<int> cSet(clique.begin(),clique.end());
        vector<int> tabu(N+1,0);
        
        for (int iter=0;iter<200000&&elapsed_ms()<maxMs;iter++){
            int bestV=-1,bestDeg=-1;
            for(int v=1;v<=N;v++){
                if(!cSet.count(v)&&tight[v]==cs){
                    if(tabu[v]>iter&&cs+1<=bestSize)continue;
                    int d=(int)adj[v].count();
                    if(d>bestDeg){bestDeg=d;bestV=v;}
                }
            }
            if(bestV!=-1){
                clique.push_back(bestV);cSet.insert(bestV);cBS.set(bestV);
                for(int w=1;w<=N;w++)if(adj[bestV].test(w))tight[w]++;
                cs++;
                if(cs>bestSize){bestSize=cs;bestClique=clique;}
                continue;
            }
            vector<int>cp(clique);shuffle(cp.begin(),cp.end(),rng);
            bool did=false;
            for(int u:cp){
                if(elapsed_ms()>maxMs)break;
                vector<int>addC;
                for(int v=1;v<=N;v++){
                    if(!cSet.count(v)&&tight[v]==cs-1&&!adj[v].test(u)){
                        if(tabu[v]<=iter||cs>bestSize)addC.push_back(v);
                    }
                }
                if(addC.empty())continue;
                int v=addC[rng()%addC.size()];
                cSet.erase(u);cBS.reset(u);
                for(int w=1;w<=N;w++)if(adj[u].test(w))tight[w]--;
                clique.erase(find(clique.begin(),clique.end(),u));
                clique.push_back(v);cSet.insert(v);cBS.set(v);
                for(int w=1;w<=N;w++)if(adj[v].test(w))tight[w]++;
                tabu[u]=iter+cs+rng()%10+2;cs=clique.size();did=true;break;
            }
            if(!did&&!clique.empty()){
                int i2=rng()%clique.size();int u=clique[i2];
                cSet.erase(u);cBS.reset(u);
                for(int w=1;w<=N;w++)if(adj[u].test(w))tight[w]--;
                clique.erase(clique.begin()+i2);
                tabu[u]=iter+cs+rng()%5+3;cs=clique.size();
            }
        }
    }
}

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    startTime=chrono::steady_clock::now();
    cin>>N>>M;
    for(int i=0;i<M;i++){int u,v;cin>>u>>v;adj[u].set(v);adj[v].set(u);}
    
    vector<int>deg(N+1);
    for(int i=1;i<=N;i++)deg[i]=(int)adj[i].count();
    vector<bool>removed(N+1,false);
    vector<int>degen;
    for(int i=0;i<N;i++){
        int mv=0,md=N+1;
        for(int v=1;v<=N;v++)if(!removed[v]&&deg[v]<md){md=deg[v];mv=v;}
        degen.push_back(mv);removed[mv]=true;
        for(int v=1;v<=N;v++)if(!removed[v]&&adj[mv].test(v))deg[v]--;
    }
    
    localSearch(600);
    
    timeUp=false;
    for(int idx=N-1;idx>=0&&!timeUp&&elapsed_ms()<timeLimitMs;idx--){
        int v=degen[idx];
        vector<int>cands;
        for(int j=idx+1;j<N;j++)if(adj[v].test(degen[j]))cands.push_back(degen[j]);
        if((int)cands.size()+1<=bestSize)continue;
        vector<int>cl={v};
        expand(cl,cands);
    }
    
    timeUp=false;
    localSearch(timeLimitMs);
    
    vector<bool>inC(N+1,false);
    for(int v:bestClique)inC[v]=true;
    for(int i=1;i<=N;i++)cout<<(inC[i]?1:0)<<"\n";
}
