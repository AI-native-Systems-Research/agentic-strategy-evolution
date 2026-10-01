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

    // === Phase 1: NN-list 2-opt ===
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

    // === Phase 2: Window-based 2-opt ===
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

    // === Phase 3: Or-opt using linked-list for O(1) moves ===
    // Build linked list from current tour
    int* nxt = new int[N]; // next city in tour (by city ID)
    int* prv = new int[N]; // prev city in tour (by city ID)
    for(int i=0; i<N; i++){
        nxt[tour[i]] = tour[(i+1) % (N+1) == N+1 ? 0 : i+1];
        prv[tour[i]] = tour[i > 0 ? i-1 : N];
    }
    // Special: tour goes 0 -> ... -> 0. So nxt[tour[N-1]] = 0, prv[0] = tour[N-1]
    // Actually tour[N] = 0 = tour[0], so the tour is a cycle through positions 0..N-1
    // nxt[tour[i]] = tour[i+1] for i < N; nxt[tour[N-1]] = tour[N] = 0
    // prv[tour[0]] = prv[0] ... but 0 appears at positions 0 and N
    // We need to handle the depot (city 0) carefully.
    // Let's use a virtual node for the depot end. Actually, easier: linearize.
    // The tour visits cities: tour[0]=0, tour[1], ..., tour[N-1], back to 0.
    // We treat it as a linear path with a closing edge from tour[N-1] to 0.
    // For or-opt, don't relocate city 0.

    // Re-do: for i=0..N-1, city tour[i] has:
    //   nxt = tour[i+1] if i < N-1, else 0 (closing)
    //   prv = tour[i-1] if i > 0, else 0 (but city 0 IS tour[0], so prv[0]=tour[N-1])
    // This is circular with city 0 being the start/end.

    // Rebuild properly:
    for(int i=0; i<N; i++){
        int city = tour[i];
        nxt[city] = (i < N-1) ? tour[i+1] : tour[0]; // circular: last -> first (which is 0)
        prv[city] = (i > 0) ? tour[i-1] : tour[N-1]; // circular: first -> last
    }

    for(int pass=0; pass<20 && elapsed()<2350; pass++){
        int imp = 0;
        // Iterate through tour in order (use array for iteration order)
        for(int i=1; i<N && elapsed()<2350; i++){
            int c = tour[i]; // Don't move city 0
            if(c == 0) continue;

            int pc = prv[c], nc = nxt[c];
            double remove_saving = ddist(pc, c) + ddist(c, nc) - ddist(pc, nc);
            if(remove_saving < 1e-10) continue;

            // Find best insertion using NN of c
            double best_gain = 1e-10;
            int best_after = -1;
            int* nnp = nn + c*K_NN;
            for(int k=0; k<K_NN; k++){
                int nb = nnp[k];
                if(nb<0) break;
                if(nb == pc || nb == nc || nb == c) continue;

                // Try inserting c after nb
                int nb_nxt = nxt[nb];
                double insert_cost = ddist(nb, c) + ddist(c, nb_nxt) - ddist(nb, nb_nxt);
                double gain = remove_saving - insert_cost;
                if(gain > best_gain){ best_gain=gain; best_after=nb; }

                // Try inserting c before nb
                int nb_prv = prv[nb];
                if(nb_prv != pc && nb_prv != nc && nb_prv != c){
                    insert_cost = ddist(nb_prv, c) + ddist(c, nb) - ddist(nb_prv, nb);
                    gain = remove_saving - insert_cost;
                    if(gain > best_gain){ best_gain=gain; best_after=nb_prv; }
                }
            }

            if(best_after >= 0){
                // Splice out c
                nxt[pc] = nc;
                prv[nc] = pc;
                // Insert c after best_after
                int ba_nxt = nxt[best_after];
                nxt[best_after] = c;
                prv[c] = best_after;
                nxt[c] = ba_nxt;
                prv[ba_nxt] = c;
                imp++;
            }
        }
        if(imp == 0) break;

        // Rebuild tour array from linked list for next pass iteration
        tour[0] = 0;
        for(int i=1; i<=N; i++){
            tour[i] = nxt[tour[i-1]];
        }
        // Verify tour[N] == 0
        for(int i=0;i<N;i++) pos[tour[i]] = i;
    }

    // Rebuild tour from linked list
    tour[0] = 0;
    for(int i=1; i<N; i++){
        tour[i] = nxt[tour[i-1]];
    }
    tour[N] = 0;
    for(int i=0;i<N;i++) pos[tour[i]] = i;

    // === Phase 4: Another round of NN-list 2-opt after or-opt ===
    for(int pass=0; pass<50 && elapsed()<2380; pass++){
        int improvements = 0;
        for(int i=0; i<N-1 && elapsed()<2380; i++){
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

    delete[] nxt; delete[] prv;
    delete[] nn; delete[] tour; delete[] pos;
    delete[] isp; delete[] px; delete[] py;
    return 0;
}
