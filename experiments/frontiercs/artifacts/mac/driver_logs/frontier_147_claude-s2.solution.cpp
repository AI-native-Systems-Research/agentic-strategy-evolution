#include <bits/stdc++.h>
using namespace std;

int n;
int X[200], Y[200];
long long R[200];
int A[200], B[200], C[200], D[200];

mt19937 rng(123456789);

inline bool overlaps(int i, int j) {
    return A[i] < C[j] && A[j] < C[i] && B[i] < D[j] && B[j] < D[i];
}

inline double calcScore(int i) {
    long long si = (long long)(C[i]-A[i])*(D[i]-B[i]);
    if (si <= 0) return 0;
    if (!(A[i] <= X[i] && X[i] < C[i] && B[i] <= Y[i] && Y[i] < D[i])) return 0;
    double mn = min(R[i], si), mx = max(R[i], si);
    double ratio = 1.0 - mn/mx;
    return 1.0 - ratio*ratio;
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    cin >> n;
    for(int i=0;i<n;i++) cin >> X[i] >> Y[i] >> R[i];

    // Initialize with 1x1 at desired point
    for(int i=0;i<n;i++){
        A[i]=X[i]; B[i]=Y[i]; C[i]=X[i]+1; D[i]=Y[i]+1;
    }

    // Greedy expansion phase: try to grow each rectangle towards target area
    // Repeat multiple passes
    for(int pass=0; pass<50; pass++){
        vector<int> order(n);
        iota(order.begin(), order.end(), 0);
        shuffle(order.begin(), order.end(), rng);
        for(int i : order){
            long long si = (long long)(C[i]-A[i])*(D[i]-B[i]);
            if(si >= R[i]) continue;
            // Try expanding each side
            for(int side=0; side<4; side++){
                int na=A[i],nb=B[i],nc=C[i],nd=D[i];
                // Compute how much to expand
                long long need = R[i] - si;
                int len;
                if(side==0||side==2) len = D[i]-B[i]; else len = C[i]-A[i];
                int delta = max(1, (int)min((long long)500, need/max(1LL,(long long)len)));
                if(side==0) na -= delta;
                else if(side==1) nb -= delta;
                else if(side==2) nc += delta;
                else nd += delta;
                na=max(na,0); nb=max(nb,0); nc=min(nc,10000); nd=min(nd,10000);
                if(na>=nc||nb>=nd) continue;
                if(!(na<=X[i]&&X[i]<nc&&nb<=Y[i]&&Y[i]<nd)) continue;
                int oa=A[i],ob=B[i],oc=C[i],od=D[i];
                A[i]=na;B[i]=nb;C[i]=nc;D[i]=nd;
                bool ok=true;
                for(int j=0;j<n;j++) if(j!=i && overlaps(i,j)){
                    // shrink to not overlap
                    if(side==0) na=max(na, A[j]<C[j]?C[j]:na);
                    else if(side==1) nb=max(nb, B[j]<D[j]?D[j]:nb);
                    else if(side==2) nc=min(nc, A[j]);
                    else nd=min(nd, B[j]);
                }
                A[i]=na;B[i]=nb;C[i]=nc;D[i]=nd;
                if(na>=nc||nb>=nd||!(na<=X[i]&&X[i]<nc&&nb<=Y[i]&&Y[i]<nd)){
                    A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
                    continue;
                }
                bool ok2=true;
                for(int j=0;j<n;j++) if(j!=i && overlaps(i,j)){ok2=false;break;}
                if(!ok2){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;}
                else si=(long long)(C[i]-A[i])*(D[i]-B[i]);
            }
        }
    }

    // Simulated annealing
    auto clk = chrono::steady_clock::now;
    auto start = clk();
    double timeLimit = 4.7;

    double scores[200];
    double total=0;
    for(int i=0;i<n;i++){scores[i]=calcScore(i);total+=scores[i];}

    double T0=0.05, T1=0.0001;
    long long iter=0;
    while(true){
        if((iter&1023)==0){
            double elapsed=chrono::duration<double>(clk()-start).count();
            if(elapsed>timeLimit) break;
            double frac=elapsed/timeLimit;
            T0=0.05*(1-frac)+0.0001*frac; // current temp approximation
        }
        iter++;
        double frac = (double)(iter&0x3FF)/1024.0; // rough
        double T = T0;

        int i = rng()%n;
        int op = rng()%6; // 0-3: move one side, 4: shift, 5: resize
        int na=A[i],nb=B[i],nc=C[i],nd=D[i];
        long long si=(long long)(nc-na)*(nd-nb);
        int maxDelta = max(1, (int)(sqrt((double)R[i])*0.5));
        maxDelta = min(maxDelta, 500);
        int delta = 1 + rng()%maxDelta;
        bool expand = (si < R[i]) ? (rng()%5!=0) : (rng()%5==0);
        if(!expand) delta=-delta;

        if(op<4){
            if(op==0) na-=delta;
            else if(op==1) nb-=delta;
            else if(op==2) nc+=delta;
            else nd+=delta;
        } else if(op==4){
            int dx=(rng()%2?1:-1)*(1+rng()%max(1,maxDelta/2));
            int dy=(rng()%2?1:-1)*(1+rng()%max(1,maxDelta/2));
            na+=dx;nc+=dx;nb+=dy;nd+=dy;
        } else {
            // Try to adjust to better match target area while keeping point
            double ratio=sqrt((double)R[i]/max(1.0,(double)si));
            int w=nc-na, h=nd-nb;
            int nw=max(1,(int)(w*ratio)), nh=max(1,(int)(h*ratio));
            na=X[i]-max(0,min(nw-1,(int)((double)(X[i]-na)/w*nw)));
            nb=Y[i]-max(0,min(nh-1,(int)((double)(Y[i]-nb)/h*nh)));
            nc=na+nw; nd=nb+nh;
        }

        if(na>=nc||nb>=nd||na<0||nb<0||nc>10000||nd>10000) continue;
        if(!(na<=X[i]&&X[i]<nc&&nb<=Y[i]&&Y[i]<nd)) continue;

        int oa=A[i],ob=B[i],oc=C[i],od=D[i];
        A[i]=na;B[i]=nb;C[i]=nc;D[i]=nd;
        bool ok=true;
        for(int j=0;j<n;j++) if(j!=i&&overlaps(i,j)){ok=false;break;}
        if(!ok){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;}

        double ns=calcScore(i);
        double diff=ns-scores[i];
        if(diff>0 || (T>1e-12 && exp(diff/T) > (rng()%10000)/10000.0)){
            scores[i]=ns; total+=diff;
        } else {
            A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
        }
    }

    for(int i=0;i<n;i++) printf("%d %d %d %d\n",A[i],B[i],C[i],D[i]);
}
