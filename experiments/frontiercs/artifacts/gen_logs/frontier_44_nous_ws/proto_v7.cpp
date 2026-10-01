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

    if(N<=2){cout<<N+1<<"\n";for(int i=0;i<=N;i++)cout<<(i<N?i:0)<<"\n";return 0;}

    isp = new bool[N]; fill(isp,isp+N,true);
    isp[0]=false; if(N>1)isp[1]=false;
    for(int i=2;(long long)i*i<N;i++) if(isp[i]) for(int j=i*i;j<N;j+=i) isp[j]=false;

    auto tick=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double,milli>(chrono::steady_clock::now()-tick).count();};

    // === Precompute spatial nearest neighbors ===
    const int K_NN = 15;

    vector<int> ysort(N);
    iota(ysort.begin(), ysort.end(), 0);
    sort(ysort.begin(), ysort.end(), [](int a, int b){
        return py[a] < py[b] || (py[a]==py[b] && px[a]<px[b]);
    });
    vector<int> yrank(N);
    for(int i=0;i<N;i++) yrank[ysort[i]] = i;

    int W_nn;
    if(N <= 500) W_nn = N-1;
    else if(N <= 5000) W_nn = 120;
    else if(N <= 20000) W_nn = 80;
    else if(N <= 80000) W_nn = 50;
    else W_nn = 35;

    vector<array<int,15>> nn(N);
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
            for(int j=0; j<(int)buf.size() && cnt<K_NN; j++){
                bool dup = false;
                for(int q=0;q<cnt;q++) if(nn[i][q]==buf[j].id){dup=true;break;}
                if(!dup) nn[i][cnt++] = buf[j].id;
            }
            for(int j=cnt;j<K_NN;j++) nn[i][j] = -1;
        }
    }

    // === Greedy NN Construction from city 0 ===
    vector<int> tour(N+1);
    vector<int> pos(N);
    {
        vector<bool> visited(N, false);
        tour[0] = 0; visited[0] = true;
        for(int step=1; step<N; step++){
            int cur = tour[step-1];
            int best = -1;
            double bestd = 1e30;
            for(int k=0;k<K_NN;k++){
                int nb = nn[cur][k];
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
    }
    for(int i=0;i<N;i++) pos[tour[i]] = i;

    // Helper for reversal
    auto rev_seg = [&](int lo, int hi){
        for(int a=lo, b=hi; a<b; a++, b--){
            swap(tour[a], tour[b]);
            pos[tour[a]]=a; pos[tour[b]]=b;
        }
        if((lo+hi)%2==0){ int m=(lo+hi)/2; pos[tour[m]]=m; }
    };

    // === NN-list 2-opt with segment length limit ===
    // Try both directions but limit reversal length to avoid expensive long reversals
    int max_rev = min(N/2, 50000); // max segment to reverse

    for(int pass=0; pass<100 && elapsed()<1800; pass++){
        int improvements = 0;
        for(int p=0; p<N-1 && elapsed()<1800; p++){
            int c = tour[p];
            for(int k=0; k<K_NN; k++){
                int nb = nn[c][k];
                if(nb<0) break;
                int q = pos[nb];

                if(q > p + 1 && q < N && (q-p-1) <= max_rev){
                    double gain = ddist(tour[p], tour[p+1]) + ddist(tour[q], tour[q+1])
                                - ddist(tour[p], tour[q]) - ddist(tour[p+1], tour[q+1]);
                    if(gain > 1e-10){
                        rev_seg(p+1, q);
                        improvements++;
                    }
                } else if(q >= 0 && q < p - 1 && (p-q-1) <= max_rev){
                    double gain = ddist(tour[q], tour[q+1]) + ddist(tour[p], tour[p+1])
                                - ddist(tour[q], tour[p]) - ddist(tour[q+1], tour[p+1]);
                    if(gain > 1e-10){
                        rev_seg(q+1, p);
                        improvements++;
                    }
                }
            }
        }
        if(improvements == 0) break;
    }

    // === Window-based 2-opt for remaining time ===
    {
        int window;
        if(N<=200) window=N;
        else if(N<=1000) window=N/2;
        else if(N<=5000) window=300;
        else if(N<=20000) window=100;
        else if(N<=50000) window=60;
        else if(N<=100000) window=40;
        else window=25;

        for(int pass=0; pass<20 && elapsed()<2150; pass++){
            bool improved=false;
            for(int i=0;i<N-1 && elapsed()<2150;i++){
                int jmax=min(i+window, N-1);
                double d_i=ddist(tour[i],tour[i+1]);
                for(int j=i+2;j<=jmax;j++){
                    double gain=d_i+ddist(tour[j],tour[j+1])
                               -ddist(tour[i],tour[j])-ddist(tour[i+1],tour[j+1]);
                    if(gain>1e-10){
                        rev_seg(i+1, j);
                        improved=true;
                        d_i=ddist(tour[i],tour[i+1]);
                    }
                }
            }
            if(!improved) break;
        }
    }

    // === Or-opt ===
    for(int pass=0; pass<5 && elapsed()<2300; pass++){
        int imp = 0;
        for(int i=1; i<N && elapsed()<2300; i++){
            int c = tour[i];
            double remove_saving = ddist(tour[i-1], c) + ddist(c, tour[i+1]) - ddist(tour[i-1], tour[i+1]);
            if(remove_saving < 1e-10) continue;
            double best_cost = 1e30;
            int best_j = -1;
            for(int k=0; k<K_NN; k++){
                int nb = nn[c][k];
                if(nb<0) break;
                int j = pos[nb];
                if(j<=0 || j>=N || j==i || j==i-1) continue;
                double ins = ddist(tour[j], c) + ddist(c, tour[j+1]) - ddist(tour[j], tour[j+1]);
                if(ins < best_cost){ best_cost=ins; best_j=j; }
                if(j-1>0 && j-1!=i && j-1!=i-1){
                    ins = ddist(tour[j-1], c) + ddist(c, tour[j]) - ddist(tour[j-1], tour[j]);
                    if(ins < best_cost){ best_cost=ins; best_j=j-1; }
                }
            }
            if(best_j >= 0 && remove_saving > best_cost + 1e-10){
                int c_val = tour[i];
                if(best_j > i){
                    for(int x=i; x<best_j; x++){tour[x]=tour[x+1];pos[tour[x]]=x;}
                    tour[best_j] = c_val; pos[c_val] = best_j;
                } else if(best_j < i-1) {
                    for(int x=i; x>best_j+1; x--){tour[x]=tour[x-1];pos[tour[x]]=x;}
                    tour[best_j+1] = c_val; pos[c_val] = best_j+1;
                }
                imp++;
            }
        }
        if(imp == 0) break;
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

    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
    return 0;
}
