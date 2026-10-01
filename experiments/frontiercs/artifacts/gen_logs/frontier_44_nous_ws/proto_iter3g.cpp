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
    const int K_NN = 20;

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

    auto rawCost = [&]() -> double {
        double t = 0;
        for(int i=0;i<N;i++) t += ddist(tour[i], tour[i+1]);
        return t;
    };

    // === NN-list 2-opt with cycling detection ===
    double prev_cost = rawCost();
    int prev_imp_count = -1;
    for(int pass=0; pass<200 && elapsed()<2000; pass++){
        int improvements = 0;
        for(int i=0; i<N-1 && elapsed()<2000; i++){
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

        // Cycling detection: if same number of improvements as previous pass
        // and cost isn't decreasing, we're cycling
        if(pass >= 5){
            if(improvements == prev_imp_count){
                double cur_cost = rawCost();
                if(cur_cost >= prev_cost * 0.99999) break;
                prev_cost = cur_cost;
            } else if(pass % 5 == 0){
                double cur_cost = rawCost();
                if(cur_cost >= prev_cost * 0.99999) break;
                prev_cost = cur_cost;
            }
        }
        prev_imp_count = improvements;
    }

    double after_2opt_ms = elapsed();

    // === Window-based 2-opt ===
    {
        int window;
        if(N<=200) window=N;
        else if(N<=1000) window=N/2;
        else if(N<=5000) window=300;
        else if(N<=20000) window=100;
        else if(N<=50000) window=60;
        else if(N<=100000) window=40;
        else window=25;

        for(int pass=0; pass<10 && elapsed()<2200; pass++){
            bool improved=false;
            for(int i=0;i<N-1 && elapsed()<2200;i++){
                int jmax=min(i+window, N-1);
                double d_i=ddist(tour[i],tour[i+1]);
                for(int j=i+2;j<=jmax;j++){
                    double gain=d_i+ddist(tour[j],tour[j+1])
                               -ddist(tour[i],tour[j])-ddist(tour[i+1],tour[j+1]);
                    if(gain>1e-10){
                        for(int a=i+1,b=j;a<b;a++,b--){swap(tour[a],tour[b]);pos[tour[a]]=a;pos[tour[b]]=b;}
                        if((i+1+j)%2==0){int m=(i+1+j)/2;pos[tour[m]]=m;}
                        improved=true;
                        d_i=ddist(tour[i],tour[i+1]);
                    }
                }
            }
            if(!improved) break;
        }
    }

    // === ILS: Double-bridge perturbation + re-2opt ===
    // Only for small/medium N where 2-opt converges fast
    if(after_2opt_ms < 1000 && N >= 8 && N <= 50000 && elapsed() < 1500) {
        int* best_tour = new int[N+1];
        memcpy(best_tour, tour, (N+1)*sizeof(int));
        double best_cost = rawCost();

        mt19937 rng(42);
        double end_time = min(2200.0, after_2opt_ms + 2000.0); // give ILS up to 2s

        while(elapsed() < end_time) {
            // Double-bridge perturbation on best tour
            memcpy(tour, best_tour, (N+1)*sizeof(int));
            for(int i=0;i<N;i++) pos[tour[i]] = i;

            // Pick 3 random positions 1 <= a < b < c < N
            vector<int> cuts;
            while((int)cuts.size() < 3){
                int r = 1 + rng() % (N-1);
                bool ok = true;
                for(int c : cuts) if(abs(c-r) < 2) { ok=false; break; }
                if(ok) cuts.push_back(r);
            }
            sort(cuts.begin(), cuts.end());
            int a=cuts[0], b=cuts[1], c=cuts[2];

            // Reconnect: [0..a-1] + [b..c-1] + [a..b-1] + [c..N]
            int* nt = new int[N+1];
            int idx = 0;
            for(int i=0;i<a;i++) nt[idx++]=tour[i];
            for(int i=b;i<c;i++) nt[idx++]=tour[i];
            for(int i=a;i<b;i++) nt[idx++]=tour[i];
            for(int i=c;i<=N;i++) nt[idx++]=tour[i];
            memcpy(tour, nt, (N+1)*sizeof(int));
            delete[] nt;
            for(int i=0;i<N;i++) pos[tour[i]] = i;

            // Re-optimize: limited 2-opt
            double reopt_end = min(elapsed() + max(100.0, (end_time - elapsed()) * 0.3), end_time);
            double rc = rawCost();
            for(int pass=0; pass<100 && elapsed()<reopt_end; pass++){
                int improvements = 0;
                for(int i=0; i<N-1 && elapsed()<reopt_end; i++){
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
                // Cycling detection for re-opt
                if(pass >= 3){
                    double nc = rawCost();
                    if(nc >= rc * 0.99999) break;
                    rc = nc;
                }
            }

            double cur_cost = rawCost();
            if(cur_cost < best_cost - 1e-6){
                best_cost = cur_cost;
                memcpy(best_tour, tour, (N+1)*sizeof(int));
            }
        }

        memcpy(tour, best_tour, (N+1)*sizeof(int));
        for(int i=0;i<N;i++) pos[tour[i]] = i;
        delete[] best_tour;
    }

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
    return 0;
}
