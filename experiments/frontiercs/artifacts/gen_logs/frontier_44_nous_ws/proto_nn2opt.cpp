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

    if(N<=2){cout<<N+1<<"\n";for(int i=0;i<=N;i++)cout<<(i<N?i:0)<<"\n";return 0;}

    isp = new bool[N]; fill(isp,isp+N,true);
    isp[0]=false; if(N>1)isp[1]=false;
    for(int i=2;(long long)i*i<N;i++) if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;

    auto tick=chrono::steady_clock::now();
    auto ms=[&](){return chrono::duration<double,milli>(chrono::steady_clock::now()-tick).count();};

    // --- Spatial grid for nearest-neighbor lookup ---
    double xlo=px[0],xhi=px[0],ylo=py[0],yhi=py[0];
    for(int i=1;i<N;i++){xlo=min(xlo,px[i]);xhi=max(xhi,px[i]);ylo=min(ylo,py[i]);yhi=max(yhi,py[i]);}

    // Grid cell size: aim for ~10-20 cities per cell on average
    double area = max(1.0,(xhi-xlo))*max(1.0,(yhi-ylo));
    double cellsz = sqrt(area / N) * 2.0; // ~4 cities per cell
    if(cellsz < 1.0) cellsz = 1.0;

    int gw = (int)((xhi-xlo)/cellsz) + 1;
    int gh = (int)((yhi-ylo)/cellsz) + 1;
    gw = max(1, min(gw, 5000));
    gh = max(1, min(gh, 5000));
    double actual_cw = (xhi-xlo+1.0)/gw;
    double actual_ch = (yhi-ylo+1.0)/gh;

    // Build grid
    vector<vector<int>> grid(gw*gh);
    auto cell = [&](int c) -> int {
        int cx = min((int)((px[c]-xlo)/actual_cw), gw-1);
        int cy = min((int)((py[c]-ylo)/actual_ch), gh-1);
        return cy*gw+cx;
    };
    for(int i=0;i<N;i++) grid[cell(i)].push_back(i);

    // Precompute k nearest neighbors for each city
    const int K_NN = 12;
    vector<array<int,12>> nn(N);
    for(int i=0;i<N;i++){
        int cx = min((int)((px[i]-xlo)/actual_cw), gw-1);
        int cy = min((int)((py[i]-ylo)/actual_ch), gh-1);
        // Search expanding rings of cells
        vector<pair<double,int>> cands;
        for(int r=0; r<=max(gw,gh) && (int)cands.size()<K_NN*3; r++){
            for(int dx=-r;dx<=r;dx++){
                for(int dy=-r;dy<=r;dy++){
                    if(abs(dx)!=r && abs(dy)!=r) continue; // only border of ring
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

    // --- Nearest-neighbor construction from city 0 ---
    vector<bool> visited(N, false);
    vector<int> tour(N+1);
    tour[0] = 0;
    visited[0] = true;

    for(int step=1; step<N; step++){
        int cur = tour[step-1];
        int best = -1;
        double bestd = 1e30;
        // First check NN list
        for(int j=0;j<K_NN;j++){
            int nb = nn[cur][j];
            if(nb<0) break;
            if(!visited[nb]){
                double d = ddist(cur, nb);
                if(d<bestd){ bestd=d; best=nb; }
            }
        }
        // If no unvisited in NN list, search grid
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

    // --- Position lookup ---
    vector<int> pos(N);
    for(int i=0;i<=N;i++) if(i<N) pos[tour[i]] = i;
    // pos tracks first occurrence for cities in tour[0..N-1]

    // --- NN-list 2-opt ---
    // For each city c at tour position p, and for each NN nb of c,
    // try the 2-opt swap that removes edge (c, tour[p+1]) and (nb, tour[pos[nb]+1])
    // and adds (c, nb) and (tour[p+1], tour[pos[nb]+1])
    // = reversal of segment tour[p+1..pos[nb]] or tour[pos[nb]+1..p]

    auto two_opt_pass = [&]() -> int {
        int improvements = 0;
        for(int i=0; i<N && ms()<2000; i++){
            int c = tour[i];
            double d_ci = ddist(c, tour[i+1]);
            for(int k=0; k<K_NN; k++){
                int nb = nn[c][k];
                if(nb<0) break;
                if(ddist(c, nb) >= d_ci * 1.5) break; // prune: if NN is further than current edge * factor, skip
                int j = pos[nb];
                if(j <= i) continue; // only consider j > i to avoid double-counting
                if(j == i+1) continue; // adjacent, skip
                // Consider reversing segment tour[i+1..j]
                // Old edges: (tour[i], tour[i+1]) + (tour[j], tour[j+1])
                // New edges: (tour[i], tour[j]) + (tour[i+1], tour[j+1])
                double gain = d_ci + ddist(tour[j], tour[j+1])
                            - ddist(c, tour[j]) - ddist(tour[i+1], tour[j+1]);
                if(gain > 1e-10){
                    // Reverse segment [i+1..j]
                    int lo=i+1, hi=j;
                    while(lo<hi){
                        swap(tour[lo], tour[hi]);
                        pos[tour[lo]]=lo;
                        pos[tour[hi]]=hi;
                        lo++; hi--;
                    }
                    if(lo==hi) pos[tour[lo]]=lo;
                    improvements++;
                    d_ci = ddist(c, tour[i+1]); // update for next iteration
                }
            }
        }
        return improvements;
    };

    // Also try the NN of tour[i+1] in same fashion
    auto two_opt_pass_reverse = [&]() -> int {
        int improvements = 0;
        for(int i=N-1; i>=0 && ms()<2000; i--){
            int c = tour[i];
            double d_ci = ddist(c, tour[i+1]);
            for(int k=0; k<K_NN; k++){
                int nb = nn[tour[i+1]][k];
                if(nb<0) break;
                int j = pos[nb];
                if(j <= i+1) continue;
                if(j == i+1) continue;
                // Reverse segment [i+1..j]
                double gain = d_ci + ddist(tour[j], tour[j+1])
                            - ddist(c, tour[j]) - ddist(tour[i+1], tour[j+1]);
                if(gain > 1e-10){
                    int lo=i+1, hi=j;
                    while(lo<hi){
                        swap(tour[lo], tour[hi]);
                        pos[tour[lo]]=lo;
                        pos[tour[hi]]=hi;
                        lo++; hi--;
                    }
                    if(lo==hi) pos[tour[lo]]=lo;
                    improvements++;
                    d_ci = ddist(c, tour[i+1]);
                }
            }
        }
        return improvements;
    };

    // Run multiple passes of NN 2-opt
    for(int pass=0; pass<50 && ms()<2000; pass++){
        int imp1 = two_opt_pass();
        int imp2 = two_opt_pass_reverse();
        if(imp1+imp2 == 0) break;
    }

    // --- Or-opt: single city relocation ---
    auto or_opt_pass = [&]() -> int {
        int improvements = 0;
        for(int i=1; i<N && ms()<2200; i++){
            int c = tour[i];
            // Cost of removing c from position i
            double remove_cost = ddist(tour[i-1], c) + ddist(c, tour[i+1]) - ddist(tour[i-1], tour[i+1]);
            if(remove_cost < 1e-10) continue; // no savings from removing

            double best_insert_cost = 1e30;
            int best_j = -1;

            for(int k=0; k<K_NN; k++){
                int nb = nn[c][k];
                if(nb<0) break;
                int j = pos[nb];
                // Try inserting c after position j (between tour[j] and tour[j+1])
                if(j==i || j==i-1) continue; // would create same or adjacent arrangement
                double insert_cost = ddist(tour[j], c) + ddist(c, tour[j+1]) - ddist(tour[j], tour[j+1]);
                if(insert_cost < best_insert_cost){
                    best_insert_cost = insert_cost;
                    best_j = j;
                }
                // Also try inserting before j (between tour[j-1] and tour[j])
                if(j>0 && j-1!=i && j-1!=i-1){
                    insert_cost = ddist(tour[j-1], c) + ddist(c, tour[j]) - ddist(tour[j-1], tour[j]);
                    if(insert_cost < best_insert_cost){
                        best_insert_cost = insert_cost;
                        best_j = j-1;
                    }
                }
            }

            if(best_j >= 0 && remove_cost - best_insert_cost > 1e-10){
                // Remove c from position i and insert after best_j
                // This is complex with array, do it carefully
                int c_val = tour[i];
                if(best_j > i){
                    // Shift left: tour[i+1..best_j] shifts to tour[i..best_j-1], insert at best_j
                    for(int x=i; x<best_j; x++){
                        tour[x] = tour[x+1];
                        pos[tour[x]] = x;
                    }
                    tour[best_j] = c_val;
                    pos[c_val] = best_j;
                } else {
                    // best_j < i-1 (since we excluded i-1)
                    // Shift right: tour[best_j+1..i-1] shifts to tour[best_j+2..i], insert at best_j+1
                    for(int x=i; x>best_j+1; x--){
                        tour[x] = tour[x-1];
                        pos[tour[x]] = x;
                    }
                    tour[best_j+1] = c_val;
                    pos[c_val] = best_j+1;
                }
                improvements++;
            }
        }
        return improvements;
    };

    for(int pass=0; pass<10 && ms()<2200; pass++){
        int imp = or_opt_pass();
        if(imp == 0) break;
    }

    // --- Carrot optimization ---
    for(int p=9;p<N;p+=10){
        if(isp[tour[p]]) continue;
        double pen_edge=ddist(tour[p],tour[p+1]);
        double savings=0.1*pen_edge;
        int best=-1; double best_net=0;
        int sr=min(500,N/2);
        for(int delta=1;delta<=sr;delta++){
            for(int d:{-delta,delta}){
                int j=p+d;
                if(j<=0||j>=N) continue;
                if(!isp[tour[j]]) continue;
                if(j>=9&&j<N&&(j%10==9)) continue;
                double old_c,new_c;
                int u=tour[p],v=tour[j];
                if(abs(p-j)>1){
                    old_c=ddist(tour[p-1],u)+ddist(u,tour[p+1])+ddist(tour[j-1],v)+ddist(v,tour[j+1]);
                    new_c=ddist(tour[p-1],v)+ddist(v,tour[p+1])+ddist(tour[j-1],u)+ddist(u,tour[j+1]);
                } else if(j==p+1){
                    old_c=ddist(tour[p-1],u)+ddist(u,v)+ddist(v,tour[j+1]);
                    new_c=ddist(tour[p-1],v)+ddist(v,u)+ddist(u,tour[j+1]);
                } else {
                    old_c=ddist(tour[j-1],v)+ddist(v,u)+ddist(u,tour[p+1]);
                    new_c=ddist(tour[j-1],u)+ddist(u,v)+ddist(v,tour[p+1]);
                }
                double net=savings-(new_c-old_c);
                if(net>best_net){best_net=net;best=j;}
            }
        }
        if(best>=0) swap(tour[p],tour[best]);
    }

    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
    return 0;
}
