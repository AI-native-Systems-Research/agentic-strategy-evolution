#include <bits/stdc++.h>
using namespace std;
int N,M;
vector<int> adj_g[500001], radj_g[500001], sadj_g[500001];
int outdeg_g[500001], indeg_g[500001];
chrono::high_resolution_clock::time_point T0;
double elapsed(){return chrono::duration<double>(chrono::high_resolution_clock::now()-T0).count();}
auto hasEdge=[](int u, int v)->bool{return binary_search(sadj_g[u].begin(),sadj_g[u].end(),v);};
int globalBest=0;
vector<int> globalBestPath;
int solveRotation(mt19937& rng, int startVertex, double tl){
    static vector<int> nxt,prv,dout;static vector<char> used;static bool inited=false;
    if(!inited){nxt.resize(N+1);prv.resize(N+1);dout.resize(N+1);used.resize(N+1);inited=true;}
    for(int u=1;u<=N;u++){dout[u]=outdeg_g[u];used[u]=0;nxt[u]=0;prv[u]=0;}
    used[startVertex]=1;for(int u:radj_g[startVertex])if(!used[u])dout[u]--;
    int head=startVertex,tail=startVertex,pathLen=1;
    auto mark=[&](int v){used[v]=1;for(int u:radj_g[v])if(!used[u])dout[u]--;};
    auto extF=[&]()->bool{bool ext=false;while(true){int bd=INT_MAX,cnt=0;int picks[16];for(int v:adj_g[tail])if(!used[v]){if(dout[v]<bd){bd=dout[v];cnt=0;picks[0]=v;cnt=1;}else if(dout[v]==bd&&cnt<16){picks[cnt++]=v;}}if(!cnt)break;int p=picks[rng()%cnt];nxt[tail]=p;prv[p]=tail;nxt[p]=0;mark(p);tail=p;pathLen++;ext=true;}return ext;};
    auto extB=[&]()->bool{bool ext=false;while(true){int bd=INT_MAX,cnt=0;int picks[16];for(int u:radj_g[head])if(!used[u]){if(dout[u]<bd){bd=dout[u];cnt=0;picks[0]=u;cnt=1;}else if(dout[u]==bd&&cnt<16){picks[cnt++]=u;}}if(!cnt)break;int p=picks[rng()%cnt];prv[head]=p;nxt[p]=head;prv[p]=0;mark(p);head=p;pathLen++;ext=true;}return ext;};
    auto ins=[&]()->bool{bool ch=false;int u=head;while(u){int w=nxt[u];if(!w)break;for(int v:adj_g[u])if(!used[v]&&hasEdge(v,w)){nxt[u]=v;prv[v]=u;nxt[v]=w;prv[w]=v;mark(v);w=v;pathLen++;ch=true;}u=w;}return ch;};
    extF();extB();for(int p2=0;p2<15;p2++){bool ch=ins();if(ch){extF();extB();}else break;}
    int maxRot=min(N*50,2000000);int rotCount=0;
    while(pathLen<N&&rotCount<maxRot&&elapsed()<tl){
        if(extF())continue;rotCount++;
        vector<int> shortcuts;for(int v:adj_g[tail])if(used[v]&&v!=tail)shortcuts.push_back(v);
        if(shortcuts.empty())break;
        for(int i=shortcuts.size()-1;i>0;i--){int j2=rng()%(i+1);swap(shortcuts[i],shortcuts[j2]);}
        bool rotated=false;
        for(int vi:shortcuts){
            if(rotated)break;
            if(vi==head){
                vector<int> candidates;int u2=head;while(u2&&u2!=tail){bool h=false;for(int w:adj_g[u2])if(!used[w]){h=true;break;}if(h)candidates.push_back(u2);u2=nxt[u2];}
                if(candidates.empty())continue;
                int vj=candidates[rng()%candidates.size()];int newHead=nxt[vj];nxt[tail]=head;prv[head]=tail;nxt[vj]=0;prv[newHead]=0;head=newHead;tail=vj;rotated=true;
            } else {
                int e=prv[vi];if(!e)continue;
                vector<int> goodBreaks,anyBreaks;int vj2=vi;
                while(vj2&&nxt[vj2]){int c=nxt[vj2];if(c&&hasEdge(e,c)){bool h=false;for(int w:adj_g[vj2])if(!used[w]){h=true;break;}if(h)goodBreaks.push_back(vj2);else anyBreaks.push_back(vj2);}if(vj2==tail)break;vj2=nxt[vj2];}
                int vj=0;if(!goodBreaks.empty())vj=goodBreaks[rng()%goodBreaks.size()];else if(!anyBreaks.empty())vj=anyBreaks[rng()%anyBreaks.size()];if(!vj)continue;
                int c=nxt[vj];nxt[e]=c;prv[c]=e;nxt[tail]=vi;prv[vi]=tail;nxt[vj]=0;tail=vj;rotated=true;
            }
        }
        if(!rotated)break;extF();
    }
    extB();for(int p3=0;p3<5&&elapsed()<tl;p3++){bool ch=ins();if(ch){extF();extB();}else break;}
    for(int iter2=0;iter2<3&&elapsed()<tl;iter2++){bool ch=false;for(int v=1;v<=N;v++){if(used[v])continue;if(hasEdge(v,head)){prv[head]=v;nxt[v]=head;prv[v]=0;head=v;mark(v);pathLen++;ch=true;}else if(hasEdge(tail,v)){nxt[tail]=v;prv[v]=tail;nxt[v]=0;tail=v;mark(v);pathLen++;ch=true;}}if(!ch)break;ins();extF();extB();}
    if(pathLen>globalBest){globalBest=pathLen;globalBestPath.clear();globalBestPath.reserve(pathLen);for(int u=head;u;u=nxt[u])globalBestPath.push_back(u);}
    return pathLen;
}

int main(){
    T0=chrono::high_resolution_clock::now();
    scanf("%d%d",&N,&M);int a[10];for(int i=0;i<10;i++)scanf("%d",&a[i]);
    for(int i=0;i<M;i++){int u,v;scanf("%d%d",&u,&v);adj_g[u].push_back(v);radj_g[v].push_back(u);outdeg_g[u]++;indeg_g[v]++;}
    for(int u=1;u<=N;u++){sadj_g[u]=adj_g[u];sort(sadj_g[u].begin(),sadj_g[u].end());}
    
    vector<int> starts;
    for(int u=1;u<=N;u++) if(indeg_g[u]==0) starts.push_back(u);
    {vector<int> order(N);iota(order.begin(),order.end(),1);sort(order.begin(),order.end(),[](int a,int b){return indeg_g[a]<indeg_g[b];});for(int i=0;i<min(N,20);i++){bool dup=false;for(int s:starts)if(s==order[i])dup=true;if(!dup)starts.push_back(order[i]);}}
    
    mt19937 rng0(42);
    for(int s:starts){
        if(globalBest==N||elapsed()>1.5)break;
        solveRotation(rng0,s,1.5);
    }
    while(globalBest<N&&elapsed()<3.5){
        int s=(rng0()%N)+1;
        int before=globalBest;
        solveRotation(rng0,s,3.5);
        if(globalBest==N){
            fprintf(stderr,"Solved at t=%.3f best=%d\n",elapsed(),globalBest);
            break;
        }
    }
    fprintf(stderr,"After Warnsdorff: best=%d at t=%.3f\n",globalBest,elapsed());
    printf("%d\n",globalBest);
    for(int i=0;i<globalBest;i++){if(i)printf(" ");printf("%d",globalBestPath[i]);}printf("\n");
    return 0;
}
