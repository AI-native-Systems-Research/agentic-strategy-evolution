#include <bits/stdc++.h>
using namespace std;
int N;
double *px, *py;
bool* isp;
inline double ddist(int a, int b) {
    double dx = px[a]-px[b], dy = py[a]-py[b];
    return sqrt(dx*dx+dy*dy);
}
int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    cin >> N;
    px = new double[N]; py = new double[N];
    for(int i=0;i<N;i++){long long a,b;cin>>a>>b;px[i]=a;py[i]=b;}
    if(N<=2){return 0;}
    isp = new bool[N]; fill(isp,isp+N,true);
    isp[0]=false; if(N>1)isp[1]=false;
    for(int i=2;(long long)i*i<N;i++) if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;
    auto tick=chrono::steady_clock::now();
    auto ms=[&](){return chrono::duration<double,milli>(chrono::steady_clock::now()-tick).count();};
    
    // Grid
    double xlo=px[0],xhi=px[0],ylo=py[0],yhi=py[0];
    for(int i=1;i<N;i++){xlo=min(xlo,px[i]);xhi=max(xhi,px[i]);ylo=min(ylo,py[i]);yhi=max(yhi,py[i]);}
    double area = max(1.0,(xhi-xlo))*max(1.0,(yhi-ylo));
    double cellsz = sqrt(area / N) * 3.0;
    if(cellsz < 1.0) cellsz = 1.0;
    int gw = (int)((xhi-xlo)/cellsz) + 1;
    int gh = (int)((yhi-ylo)/cellsz) + 1;
    gw = max(1, min(gw, 3000));
    gh = max(1, min(gh, 3000));
    double actual_cw = (xhi-xlo+1.0)/gw;
    double actual_ch = (yhi-ylo+1.0)/gh;
    
    vector<vector<int>> grid(gw*gh);
    for(int i=0;i<N;i++){
        int cx = min((int)((px[i]-xlo)/actual_cw), gw-1);
        int cy = min((int)((py[i]-ylo)/actual_ch), gh-1);
        grid[cy*gw+cx].push_back(i);
    }
    fprintf(stderr, "Grid built: %.1fms  gw=%d gh=%d\n", ms(), gw, gh);
    
    // NN precompute
    const int K_NN = 10;
    vector<array<int,10>> nn(N);
    for(int i=0;i<N;i++){
        int cx = min((int)((px[i]-xlo)/actual_cw), gw-1);
        int cy = min((int)((py[i]-ylo)/actual_ch), gh-1);
        vector<pair<double,int>> cands;
        for(int r=0; r<=max(gw,gh) && (int)cands.size()<K_NN*3; r++){
            for(int dx=-r;dx<=r;dx++){
                for(int dy=-r;dy<=r;dy++){
                    if(abs(dx)!=r && abs(dy)!=r) continue;
                    int nx=cx+dx, ny=cy+dy;
                    if(nx<0||nx>=gw||ny<0||ny>=gh) continue;
                    for(int c : grid[ny*gw+nx]){
                        if(c==i) continue;
                        cands.push_back({ddist(i,c), c});
                    }
                }
            }
            if(r>0 && (int)cands.size()>=K_NN*3) break;
        }
        sort(cands.begin(), cands.end());
        int cnt = min((int)cands.size(), K_NN);
        for(int j=0;j<cnt;j++) nn[i][j] = cands[j].second;
        for(int j=cnt;j<K_NN;j++) nn[i][j] = -1;
    }
    fprintf(stderr, "NN precompute: %.1fms\n", ms());
    
    // NN construction
    vector<bool> visited(N, false);
    vector<int> tour(N+1);
    tour[0] = 0; visited[0] = true;
    for(int step=1; step<N; step++){
        int cur = tour[step-1];
        int best = -1; double bestd = 1e30;
        for(int j=0;j<K_NN;j++){
            int nb = nn[cur][j];
            if(nb<0) break;
            if(!visited[nb]){
                double d = ddist(cur, nb);
                if(d<bestd){ bestd=d; best=nb; }
            }
        }
        if(best<0){
            int cx = min((int)((px[cur]-xlo)/actual_cw), gw-1);
            int cy = min((int)((py[cur]-ylo)/actual_ch), gh-1);
            for(int r=0; r<=max(gw,gh); r++){
                for(int dx=-r;dx<=r;dx++){
                    for(int dy=-r;dy<=r;dy++){
                        if(abs(dx)!=r && abs(dy)!=r) continue;
                        int nx=cx+dx, ny=cy+dy;
                        if(nx<0||nx>=gw||ny<0||ny>=gh) continue;
                        for(int c : grid[ny*gw+nx]){
                            if(!visited[c]){
                                double d = ddist(cur,c);
                                if(d<bestd){ bestd=d; best=c; }
                            }
                        }
                    }
                }
                if(best>=0) break;
            }
        }
        tour[step] = best;
        visited[best] = true;
    }
    tour[N] = 0;
    fprintf(stderr, "NN construction: %.1fms\n", ms());
    
    return 0;
}
