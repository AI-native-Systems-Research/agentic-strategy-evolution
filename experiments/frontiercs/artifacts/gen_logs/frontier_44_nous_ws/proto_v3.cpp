#include <bits/stdc++.h>
using namespace std;

int N;
long long *px, *py;
bool* isp;

inline double ddist(int a, int b) {
    double dx = (double)(px[a]-px[b]), dy = (double)(py[a]-py[b]);
    return sqrt(dx*dx+dy*dy);
}
inline double ddist2(int a, int b) {
    double dx = (double)(px[a]-px[b]), dy = (double)(py[a]-py[b]);
    return dx*dx+dy*dy;
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
    auto ms=[&](){return chrono::duration<double,milli>(chrono::steady_clock::now()-tick).count();};

    // --- Precompute spatial nearest neighbors ---
    // Use x-sorted + y-sorted dual lookup with squared distances
    const int K_NN = 10;

    // Y-sorted index
    vector<int> ysort(N);
    iota(ysort.begin(), ysort.end(), 0);
    sort(ysort.begin(), ysort.end(), [](int a, int b){
        return py[a] < py[b] || (py[a]==py[b] && px[a]<px[b]);
    });
    vector<int> yrank(N);
    for(int i=0;i<N;i++) yrank[ysort[i]] = i;

    // NN computation: for each city, merge x-window and y-window candidates
    int W_x, W_y;
    if(N <= 1000) { W_x = N/2; W_y = N/2; }
    else if(N <= 10000) { W_x = 100; W_y = 100; }
    else if(N <= 50000) { W_x = 60; W_y = 60; }
    else { W_x = 40; W_y = 40; }

    struct NNEntry { double d2; int id; };
    vector<array<int,10>> nn(N);

    {
        vector<NNEntry> buf;
        buf.reserve(2*(W_x+W_y)+10);

        for(int i=0;i<N;i++){
            buf.clear();
            // x-window
            int xlo = max(0, i-W_x), xhi = min(N-1, i+W_x);
            for(int j=xlo;j<=xhi;j++){
                if(j==i) continue;
                buf.push_back({ddist2(i,j), j});
            }
            // y-window
            int yr = yrank[i];
            int ylo = max(0, yr-W_y), yhi = min(N-1, yr+W_y);
            for(int k=ylo;k<=yhi;k++){
                int j = ysort[k];
                if(j==i) continue;
                buf.push_back({ddist2(i,j), j});
            }

            // Partial sort for top K_NN (by squared dist)
            int need = min((int)buf.size(), K_NN);
            partial_sort(buf.begin(), buf.begin()+need, buf.end(),
                        [](const NNEntry& a, const NNEntry& b){return a.d2<b.d2;});

            // Fill nn (may have dups from x/y overlap, that's OK for now)
            int cnt = 0;
            for(int j=0; j<(int)buf.size() && cnt<K_NN; j++){
                bool dup = false;
                for(int k=0;k<cnt;k++) if(nn[i][k]==buf[j].id){dup=true;break;}
                if(!dup) nn[i][cnt++] = buf[j].id;
            }
            for(int j=cnt;j<K_NN;j++) nn[i][j] = -1;
        }
    }
    fprintf(stderr, "NN precompute: %.1fms\n", ms());

    // --- Strip-based serpentine construction ---
    vector<int> cit(N-1); iota(cit.begin(),cit.end(),1);
    sort(cit.begin(),cit.end(),[](int a,int b){return py[a]<py[b]||(py[a]==py[b]&&px[a]<px[b]);});

    double xlo_d=(double)px[0],xhi_d=(double)px[0],ylo_d=(double)py[0],yhi_d=(double)py[0];
    for(int i=1;i<N;i++){xlo_d=min(xlo_d,(double)px[i]);xhi_d=max(xhi_d,(double)px[i]);ylo_d=min(ylo_d,(double)py[i]);yhi_d=max(yhi_d,(double)py[i]);}
    double WW=max(1.0,xhi_d-xlo_d), H=max(1.0,yhi_d-ylo_d);
    int ns=max(1,(int)round(sqrt((double)(N-1)*H/WW)));
    ns=max(1,min(ns,N-1));

    vector<vector<int>> strips(ns);
    int M2=N-1;
    for(int i=0;i<M2;i++){int s=min((int)((long long)i*ns/M2),ns-1);strips[s].push_back(cit[i]);}
    for(int s=0;s<ns;s++){
        sort(strips[s].begin(),strips[s].end(),[](int a,int b){return px[a]<px[b]||(px[a]==px[b]&&py[a]<py[b]);});
        if(s%2==1)reverse(strips[s].begin(),strips[s].end());
    }

    int* tour = new int[N+2];
    int ti=0;
    tour[ti++]=0;
    for(int s=0;s<ns;s++) for(int c:strips[s]) tour[ti++]=c;
    tour[ti++]=0;

    fprintf(stderr, "Construction: %.1fms\n", ms());

    // --- Position lookup ---
    int* pos = new int[N];
    for(int i=0;i<N;i++) pos[tour[i]] = i;

    // --- NN-list 2-opt ---
    int total_imp = 0;
    for(int pass=0; pass<100 && ms()<1600; pass++){
        int improvements = 0;
        for(int i=0; i<N && ms()<1600; i++){
            int c = tour[i];
            double d_ci = ddist(c, tour[i+1]);
            // Check NN of c
            for(int k=0; k<K_NN; k++){
                int nb = nn[c][k];
                if(nb<0) break;
                int j = pos[nb];
                if(j <= i+1 || j >= N) continue;
                double gain = d_ci + ddist(tour[j], tour[j+1])
                            - ddist(c, nb) - ddist(tour[i+1], tour[j+1]);
                if(gain > 1e-10){
                    int lo=i+1, hi=j;
                    while(lo<hi){swap(tour[lo],tour[hi]);pos[tour[lo]]=lo;pos[tour[hi]]=hi;lo++;hi--;}
                    if(lo==hi) pos[tour[lo]]=lo;
                    improvements++;
                    d_ci = ddist(c, tour[i+1]);
                }
            }
            // Check NN of tour[i+1]
            int ci1 = tour[i+1];
            for(int k=0; k<K_NN; k++){
                int nb = nn[ci1][k];
                if(nb<0) break;
                int j = pos[nb];
                if(j <= i+1 || j >= N) continue;
                double gain = ddist(tour[i], tour[i+1]) + ddist(tour[j], tour[j+1])
                            - ddist(tour[i], tour[j]) - ddist(tour[i+1], tour[j+1]);
                if(gain > 1e-10){
                    int lo=i+1, hi=j;
                    while(lo<hi){swap(tour[lo],tour[hi]);pos[tour[lo]]=lo;pos[tour[hi]]=hi;lo++;hi--;}
                    if(lo==hi) pos[tour[lo]]=lo;
                    improvements++;
                }
            }
        }
        total_imp += improvements;
        if(improvements == 0) break;
    }
    fprintf(stderr, "NN 2-opt: %.1fms  imp=%d\n", ms(), total_imp);

    // --- Window-based 2-opt for remaining time ---
    {
        int window;
        if(N<=200) window=N;
        else if(N<=1000) window=N/2;
        else if(N<=5000) window=300;
        else if(N<=20000) window=100;
        else if(N<=50000) window=60;
        else if(N<=100000) window=40;
        else window=25;

        for(int pass=0; pass<20 && ms()<2100; pass++){
            bool improved=false;
            for(int i=0;i<N && ms()<2100;i++){
                int jmax=min(i+window,N);
                double d_i=ddist(tour[i],tour[i+1]);
                for(int j=i+2;j<=jmax;j++){
                    double gain=d_i+ddist(tour[j],tour[j+1])
                               -ddist(tour[i],tour[j])-ddist(tour[i+1],tour[j+1]);
                    if(gain>1e-10){
                        int lo=i+1,hi=j;
                        while(lo<hi){swap(tour[lo],tour[hi]);pos[tour[lo]]=lo;pos[tour[hi]]=hi;lo++;hi--;}
                        if(lo==hi) pos[tour[lo]]=lo;
                        improved=true;
                        d_i=ddist(tour[i],tour[i+1]);
                    }
                }
            }
            if(!improved) break;
        }
    }
    fprintf(stderr, "Window 2-opt: %.1fms\n", ms());

    // --- Or-opt: single city relocation ---
    for(int pass=0; pass<5 && ms()<2250; pass++){
        int imp = 0;
        for(int i=1; i<N && ms()<2250; i++){
            int c = tour[i];
            double remove_saving = ddist(tour[i-1], c) + ddist(c, tour[i+1]) - ddist(tour[i-1], tour[i+1]);
            if(remove_saving < 1e-10) continue;

            double best_cost = 1e30;
            int best_j = -1;

            for(int k=0; k<K_NN; k++){
                int nb = nn[c][k];
                if(nb<0) break;
                int j = pos[nb];
                if(j==i || j==i-1 || j<=0) continue;
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
    fprintf(stderr, "Or-opt: %.1fms\n", ms());

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
        if(best>=0){swap(tour[p],tour[best]);pos[tour[p]]=p;pos[tour[best]]=best;}
    }
    fprintf(stderr, "Carrot: %.1fms\n", ms());

    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++) cout<<tour[i]<<"\n";
    return 0;
}
