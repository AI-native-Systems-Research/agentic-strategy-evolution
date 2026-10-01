#include <bits/stdc++.h>
using namespace std;

int N;
long long *px, *py;
bool* isp;

inline double ddist(int a, int b) {
    double dx = (double)(px[a]-px[b]), dy = (double)(py[a]-py[b]);
    return sqrt(dx*dx+dy*dy);
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    cin >> N;
    px = new long long[N]; py = new long long[N];
    for(int i=0;i<N;i++) cin>>px[i]>>py[i];

    if(N<=2){printf("%d\n",N+1);for(int i=0;i<=N;i++)printf("%d\n",i<N?i:0);return 0;}

    isp = new bool[N]; fill(isp,isp+N,true);
    isp[0]=false; if(N>1)isp[1]=false;
    for(int i=2;(long long)i*i<N;i++) if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;

    auto tick=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double,milli>(chrono::steady_clock::now()-tick).count();};

    // === Precompute nearest neighbors ===
    const int K_NN = 25;

    int* ysort = new int[N];
    iota(ysort, ysort+N, 0);
    sort(ysort, ysort+N, [](int a, int b){
        return py[a] < py[b] || (py[a]==py[b] && px[a]<px[b]);
    });
    int* yrank = new int[N];
    for(int i=0;i<N;i++) yrank[ysort[i]] = i;

    int W_nn;
    if(N <= 500) W_nn = N-1;
    else if(N <= 5000) W_nn = 150;
    else if(N <= 20000) W_nn = 100;
    else if(N <= 80000) W_nn = 60;
    else W_nn = 45;

    int* nn = new int[N * K_NN];
    {
        struct E { double d2; int id; };
        vector<E> buf;
        buf.reserve(4*W_nn+10);
        for(int i=0;i<N;i++){
            buf.clear();
            int xlo = max(0, i-W_nn), xhi = min(N-1, i+W_nn);
            for(int j=xlo;j<=xhi;j++){
                if(j==i) continue;
                double dx=(double)(px[i]-px[j]), dy=(double)(py[i]-py[j]);
                buf.push_back({dx*dx+dy*dy, j});
            }
            int yr = yrank[i];
            int ylo = max(0, yr-W_nn), yhi = min(N-1, yr+W_nn);
            for(int k=ylo;k<=yhi;k++){
                int j = ysort[k];
                if(j==i) continue;
                double dx=(double)(px[i]-px[j]), dy=(double)(py[i]-py[j]);
                buf.push_back({dx*dx+dy*dy, j});
            }
            int need = min((int)buf.size(), K_NN);
            partial_sort(buf.begin(), buf.begin()+need, buf.end(),
                        [](const E& a, const E& b){return a.d2<b.d2;});
            int cnt = 0;
            int* nnp = nn + i*K_NN;
            for(int j=0; j<(int)buf.size() && cnt<K_NN; j++){
                bool dup = false;
                for(int q=0;q<cnt;q++) if(nnp[q]==buf[j].id){dup=true;break;}
                if(!dup) nnp[cnt++] = buf[j].id;
            }
            for(int j=cnt;j<K_NN;j++) nnp[j] = -1;
        }
    }
    delete[] ysort; delete[] yrank;

    // === Greedy NN Construction from city 0 ===
    int* tour = new int[N+1];
    int* pos = new int[N];
    {
        bool* visited = new bool[N]();
        tour[0] = 0; visited[0] = true;
        for(int step=1; step<N; step++){
            int cur = tour[step-1];
            int best = -1;
            double bestd = 1e30;
            int* nnp = nn + cur*K_NN;
            for(int k=0;k<K_NN;k++){
                int nb = nnp[k];
                if(nb<0) break;
                if(!visited[nb]){
                    double d = ddist(cur, nb);
                    if(d<bestd){ bestd=d; best=nb; }
                }
            }
            if(best<0){
                for(int r=1;r<N;r++){
                    for(int d : {-r, r}){
                        int nb = cur + d;
                        if(nb>=0 && nb<N && !visited[nb]){
                            double dd = ddist(cur, nb);
                            if(dd<bestd){ bestd=dd; best=nb; }
                        }
                    }
                    if(best>=0 && r>W_nn) break;
                }
            }
            tour[step] = best;
            visited[best] = true;
        }
        tour[N] = 0;
        delete[] visited;
    }
    for(int i=0;i<N;i++) pos[tour[i]] = i;

    // === Helper: compute penalized tour cost ===
    auto tourCost = [&]() -> double {
        double total = 0.0;
        for(int t=1;t<=N;t++){
            int a = tour[t-1], b = tour[t];
            double m = 1.0;
            if(t%10==0 && !isp[a]) m = 1.1;
            total += m * ddist(a, b);
        }
        return total;
    };

    // === Phase 1: NN-list 2-opt until convergence ===
    double tl_2opt = min(2000.0, N <= 5000 ? 1500.0 : 1800.0);

    for(int pass=0; pass<200 && elapsed()<tl_2opt; pass++){
        int improvements = 0;
        for(int i=0; i<N-1 && elapsed()<tl_2opt; i++){
            int c = tour[i];
            double d_ci = ddist(c, tour[i+1]);
            int* nnp = nn + c*K_NN;
            for(int k=0; k<K_NN; k++){
                int nb = nnp[k];
                if(nb<0) break;
                int j = pos[nb];
                if(j <= i+1 || j >= N) continue;
                double gain = d_ci + ddist(tour[j], tour[j+1])
                            - ddist(c, nb) - ddist(tour[i+1], tour[j+1]);
                if(gain > 1e-10){
                    for(int a=i+1, b=j; a<b; a++, b--){
                        swap(tour[a], tour[b]);
                        pos[tour[a]]=a; pos[tour[b]]=b;
                    }
                    if((i+1+j)%2==0){int m=(i+1+j)/2;pos[tour[m]]=m;}
                    improvements++;
                    d_ci = ddist(c, tour[i+1]);
                }
            }
            // Also check NN of tour[i+1]
            int ci1 = tour[i+1];
            nnp = nn + ci1*K_NN;
            for(int k=0; k<K_NN; k++){
                int nb = nnp[k];
                if(nb<0) break;
                int j = pos[nb];
                if(j <= i+1 || j >= N) continue;
                double gain = ddist(tour[i], tour[i+1]) + ddist(tour[j], tour[j+1])
                            - ddist(tour[i], tour[j]) - ddist(tour[i+1], tour[j+1]);
                if(gain > 1e-10){
                    for(int a=i+1, b=j; a<b; a++, b--){
                        swap(tour[a], tour[b]);
                        pos[tour[a]]=a; pos[tour[b]]=b;
                    }
                    if((i+1+j)%2==0){int m=(i+1+j)/2;pos[tour[m]]=m;}
                    improvements++;
                }
            }
        }
        if(improvements == 0) break;
    }

    // === Phase 2: Or-opt (single city relocation) with NN-list ===
    double tl_oropt = min(2200.0, N <= 5000 ? 2000.0 : 2100.0);

    for(int pass=0; pass<10 && elapsed()<tl_oropt; pass++){
        int imp = 0;
        for(int i=1; i<N && elapsed()<tl_oropt; i++){
            int c = tour[i];
            // Cost of removing city c from position i
            double remove_saving = ddist(tour[i-1], c) + ddist(c, tour[i+1])
                                  - ddist(tour[i-1], tour[i+1]);
            if(remove_saving < 1e-10) continue;

            // Find best insertion position using NN of c
            double best_insert_cost = 1e30;
            int best_j = -1;
            int* nnp = nn + c*K_NN;
            for(int k=0; k<K_NN; k++){
                int nb = nnp[k];
                if(nb<0) break;
                int j = pos[nb];
                // Try inserting c after position j
                if(j>=0 && j<N && j!=i && j!=i-1){
                    int nxt = tour[j+1];
                    double ins = ddist(tour[j], c) + ddist(c, nxt) - ddist(tour[j], nxt);
                    if(ins < best_insert_cost){ best_insert_cost=ins; best_j=j; }
                }
                // Try inserting c before position j
                if(j>0 && j-1!=i && j-1!=i-1 && j!=i){
                    int prev = tour[j-1];
                    double ins = ddist(prev, c) + ddist(c, tour[j]) - ddist(prev, tour[j]);
                    if(ins < best_insert_cost){ best_insert_cost=ins; best_j=j-1; }
                }
            }

            if(best_j >= 0 && remove_saving > best_insert_cost + 1e-10){
                int c_val = tour[i];
                if(best_j > i){
                    // Shift left: remove from i, insert after best_j
                    for(int x=i; x<best_j; x++){
                        tour[x]=tour[x+1]; pos[tour[x]]=x;
                    }
                    tour[best_j] = c_val; pos[c_val] = best_j;
                } else if(best_j < i-1) {
                    // Shift right: remove from i, insert after best_j
                    for(int x=i; x>best_j+1; x--){
                        tour[x]=tour[x-1]; pos[tour[x]]=x;
                    }
                    tour[best_j+1] = c_val; pos[c_val] = best_j+1;
                }
                imp++;
            }
        }
        if(imp == 0) break;

        // After or-opt, do one more 2-opt pass to clean up
        for(int twopass=0; twopass<3 && elapsed()<tl_oropt; twopass++){
            int improvements = 0;
            for(int i=0; i<N-1 && elapsed()<tl_oropt; i++){
                int c = tour[i];
                double d_ci = ddist(c, tour[i+1]);
                int* nnp = nn + c*K_NN;
                for(int k=0; k<K_NN; k++){
                    int nb = nnp[k];
                    if(nb<0) break;
                    int j = pos[nb];
                    if(j <= i+1 || j >= N) continue;
                    double gain = d_ci + ddist(tour[j], tour[j+1])
                                - ddist(c, nb) - ddist(tour[i+1], tour[j+1]);
                    if(gain > 1e-10){
                        for(int a=i+1, b=j; a<b; a++, b--){
                            swap(tour[a], tour[b]);
                            pos[tour[a]]=a; pos[tour[b]]=b;
                        }
                        if((i+1+j)%2==0){int m=(i+1+j)/2;pos[tour[m]]=m;}
                        improvements++;
                        d_ci = ddist(c, tour[i+1]);
                    }
                }
            }
            if(improvements == 0) break;
        }
    }

    // === Phase 3: Double-bridge + ILS (if time remains) ===
    // Save best tour
    int* best_tour = new int[N+1];
    memcpy(best_tour, tour, (N+1)*sizeof(int));
    double best_cost = tourCost();

    mt19937 rng(42);

    while(elapsed() < 2300) {
        // Double-bridge perturbation
        // Select 3 random cut points 1 <= a < b < c < N
        int a = 1 + rng() % (N-3);
        int b = a + 1 + rng() % (N-2-a);
        int c = b + 1 + rng() % (N-1-b);

        // Reconnect: [0..a-1] + [b..c-1] + [a..b-1] + [c..N]
        int* newtour = new int[N+1];
        int idx = 0;
        for(int i=0;i<a;i++) newtour[idx++] = tour[i];
        for(int i=b;i<c;i++) newtour[idx++] = tour[i];
        for(int i=a;i<b;i++) newtour[idx++] = tour[i];
        for(int i=c;i<=N;i++) newtour[idx++] = tour[i];

        memcpy(tour, newtour, (N+1)*sizeof(int));
        delete[] newtour;
        for(int i=0;i<N;i++) pos[tour[i]] = i;

        // Quick NN-list 2-opt
        double tl_ils = min(elapsed() + 300.0, 2300.0);
        for(int pass=0; pass<20 && elapsed()<tl_ils; pass++){
            int improvements = 0;
            for(int i=0; i<N-1 && elapsed()<tl_ils; i++){
                int cv = tour[i];
                double d_ci = ddist(cv, tour[i+1]);
                int* nnp = nn + cv*K_NN;
                for(int k=0; k<K_NN; k++){
                    int nb = nnp[k];
                    if(nb<0) break;
                    int j = pos[nb];
                    if(j <= i+1 || j >= N) continue;
                    double gain = d_ci + ddist(tour[j], tour[j+1])
                                - ddist(cv, nb) - ddist(tour[i+1], tour[j+1]);
                    if(gain > 1e-10){
                        for(int aa=i+1, bb=j; aa<bb; aa++, bb--){
                            swap(tour[aa], tour[bb]);
                            pos[tour[aa]]=aa; pos[tour[bb]]=bb;
                        }
                        if((i+1+j)%2==0){int m=(i+1+j)/2;pos[tour[m]]=m;}
                        improvements++;
                        d_ci = ddist(cv, tour[i+1]);
                    }
                }
            }
            if(improvements == 0) break;
        }

        double cost = tourCost();
        if(cost < best_cost){
            best_cost = cost;
            memcpy(best_tour, tour, (N+1)*sizeof(int));
        } else {
            // Revert to best
            memcpy(tour, best_tour, (N+1)*sizeof(int));
            for(int i=0;i<N;i++) pos[tour[i]] = i;
        }
    }

    // Use best tour found
    memcpy(tour, best_tour, (N+1)*sizeof(int));
    for(int i=0;i<N;i++) pos[tour[i]] = i;

    // === Carrot optimization ===
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
        if(best>=0){
            pos[tour[p]]=best; pos[tour[best]]=p;
            swap(tour[p],tour[best]);
        }
    }

    printf("%d\n",N+1);
    for(int i=0;i<=N;i++) printf("%d\n",tour[i]);

    delete[] best_tour;
    delete[] nn;
    delete[] tour;
    delete[] pos;
    delete[] isp;
    delete[] px;
    delete[] py;
    return 0;
}
