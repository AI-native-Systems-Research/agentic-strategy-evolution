#include <bits/stdc++.h>
using namespace std;

int n;
int X[205], Y[205];
long long R[205];
int A[205], B[205], C[205], D[205];

bool overlaps(int i, int j) {
    return A[i] < C[j] && C[i] > A[j] && B[i] < D[j] && D[i] > B[j];
}

bool anyOverlap(int i) {
    for (int j = 0; j < n; j++) {
        if (j == i) continue;
        if (overlaps(i, j)) return true;
    }
    return false;
}

double score_i(int i) {
    long long s = (long long)(C[i]-A[i])*(D[i]-B[i]);
    if (s <= 0) return 0;
    if (!(A[i] <= X[i] && X[i] < C[i] && B[i] <= Y[i] && Y[i] < D[i])) return 0;
    double mn = min((double)R[i], (double)s);
    double mx = max((double)R[i], (double)s);
    double ratio = mn / mx;
    return 1.0 - (1.0 - ratio) * (1.0 - ratio);
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    auto start = chrono::steady_clock::now();
    auto elapsed = [&](){ return chrono::duration<double>(chrono::steady_clock::now()-start).count(); };

    cin >> n;
    for (int i = 0; i < n; i++) {
        cin >> X[i] >> Y[i] >> R[i];
        A[i] = X[i]; B[i] = Y[i]; C[i] = X[i]+1; D[i] = Y[i]+1;
    }

    mt19937 rng(42);

    // Greedy expansion
    for (int iter = 0; iter < 2000 && elapsed() < 2.0; iter++) {
        for (int i = 0; i < n; i++) {
            long long s = (long long)(C[i]-A[i])*(D[i]-B[i]);
            if (s >= R[i] * 2) continue;
            int dirs[] = {0,1,2,3};
            shuffle(dirs, dirs+4, rng);
            for (int k = 0; k < 4; k++) {
                int d = dirs[k];
                int oa=A[i],ob=B[i],oc=C[i],od=D[i];
                if (d==0) { if(A[i]<=0) continue; A[i]--; }
                else if (d==1) { if(C[i]>=10000) continue; C[i]++; }
                else if (d==2) { if(B[i]<=0) continue; B[i]--; }
                else { if(D[i]>=10000) continue; D[i]++; }
                if (anyOverlap(i)) { A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od; }
            }
        }
    }

    // SA
    uniform_int_distribution<int> distN(0, n-1);
    uniform_int_distribution<int> distD(0, 3);
    uniform_real_distribution<double> distR(0.0, 1.0);
    double temp = 0.05;

    while (elapsed() < 4.7) {
        int i = distN(rng);
        int d = distD(rng);
        bool grow = distR(rng) < 0.6;
        int oa=A[i],ob=B[i],oc=C[i],od=D[i];
        double oldS = score_i(i);

        if (grow) {
            if (d==0) { if(A[i]<=0) continue; A[i]--; }
            else if (d==1) { if(C[i]>=10000) continue; C[i]++; }
            else if (d==2) { if(B[i]<=0) continue; B[i]--; }
            else { if(D[i]>=10000) continue; D[i]++; }
        } else {
            if (d==0) { if(A[i]+1>=C[i]||A[i]+1>X[i]) continue; A[i]++; }
            else if (d==1) { if(C[i]-1<=A[i]||C[i]-1<=X[i]) continue; C[i]--; }
            else if (d==2) { if(B[i]+1>=D[i]||B[i]+1>Y[i]) continue; B[i]++; }
            else { if(D[i]-1<=B[i]||D[i]-1<=Y[i]) continue; D[i]--; }
        }

        if (anyOverlap(i)) { A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od; continue; }
        double newS = score_i(i);
        double delta = newS - oldS;
        if (delta < 0 && distR(rng) > exp(delta/temp)) {
            A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
        }
        temp *= 0.9999995;
        if (temp < 1e-6) temp = 1e-6;
    }

    for (int i = 0; i < n; i++)
        cout << A[i] << " " << B[i] << " " << C[i] << " " << D[i] << "\n";
}
