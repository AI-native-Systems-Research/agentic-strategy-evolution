#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>
#include <cstring>
#include <chrono>
#include <random>

using namespace std;

static int N;
static double *cx, *cy;
static bool *is_prime;
static int *tour; // length N+1

inline double ddist(int a, int b) {
    double dx = cx[a] - cx[b], dy = cy[a] - cy[b];
    return sqrt(dx*dx + dy*dy);
}

inline double stepCost(int t, int from, int to) {
    double d = ddist(from, to);
    if (t % 10 == 0 && !is_prime[from]) d *= 1.1;
    return d;
}

// Cost of steps from position i to j (1-indexed steps: step t moves from tour[t-1] to tour[t])
// So step t uses tour[t-1]->tour[t]. We sum steps from lo to hi inclusive.
inline double segCost(int lo, int hi) {
    double s = 0;
    for (int t = lo; t <= hi; t++)
        s += stepCost(t, tour[t-1], tour[t]);
    return s;
}

double totalCost() {
    double s = 0;
    for (int t = 1; t <= N; t++)
        s += stepCost(t, tour[t-1], tour[t]);
    return s;
}

void sieve(int maxn) {
    is_prime = new bool[maxn+1];
    memset(is_prime, true, (maxn+1)*sizeof(bool));
    is_prime[0] = is_prime[1] = false;
    for (int i = 2; (long long)i*i <= maxn; i++)
        if (is_prime[i])
            for (int j = i*i; j <= maxn; j += i)
                is_prime[j] = false;
}

int main() {
    auto t0 = chrono::steady_clock::now();
    
    scanf("%d", &N);
    cx = new double[N]; cy = new double[N];
    for (int i = 0; i < N; i++) {
        double x, y; scanf("%lf%lf", &x, &y);
        cx[i] = x; cy[i] = y;
    }
    sieve(N);
    
    tour = new int[N+1];
    
    // Nearest neighbor from city 0
    vector<bool> visited(N, false);
    tour[0] = 0; visited[0] = true;
    for (int i = 1; i < N; i++) {
        int prev = tour[i-1];
        int best = -1; double bestd = 1e30;
        for (int j = 0; j < N; j++) {
            if (!visited[j]) {
                double d = ddist(prev, j);
                if (d < bestd) { bestd = d; best = j; }
            }
        }
        tour[i] = best; visited[best] = true;
    }
    tour[N] = 0;
    
    double curCost = totalCost();
    mt19937 rng(42);
    
    auto elapsed = [&]() -> double {
        auto now = chrono::steady_clock::now();
        return chrono::duration<double>(now - t0).count();
    };
    
    // 2-opt with delta evaluation over affected segment
    int maxSeg = min(N-1, 500);
    
    while (elapsed() < 1.75) {
        for (int iter = 0; iter < 2000 && elapsed() < 1.75; iter++) {
            int i = 1 + rng() % (N-1);
            int len = 2 + rng() % min(maxSeg, N-i);
            int j = i + len - 1;
            if (j >= N) continue;
            
            // Steps affected: i to j+1 (step i: tour[i-1]->tour[i], ..., step j+1: tour[j]->tour[j+1])
            // But step j+1 might be beyond N
            int slo = i, shi = min(j+1, N);
            double oldC = segCost(slo, shi);
            
            // Reverse tour[i..j]
            reverse(tour + i, tour + j + 1);
            double newC = segCost(slo, shi);
            
            if (newC < oldC - 1e-10) {
                curCost += (newC - oldC);
            } else {
                reverse(tour + i, tour + j + 1);
            }
        }
        
        // Or-opt: relocate single city
        for (int iter = 0; iter < 2000 && elapsed() < 1.75; iter++) {
            int i = 1 + rng() % (N-1);
            int j = 1 + rng() % (N-1);
            if (i == j) continue;
            
            // Compute old cost of affected region
            // Removing city at position i affects steps i and i+1
            // Inserting at position j affects steps around j
            // Too complex for partial delta; use full recompute for small N, else skip
            // Actually let's just do it with full cost for small N
            if (N > 5000) continue;
            
            int city = tour[i];
            memmove(tour + i, tour + i + 1, (N - i) * sizeof(int));
            int jj = (j > i) ? j - 1 : j;
            if (jj >= N) jj = N - 1;
            memmove(tour + jj + 1, tour + jj, (N - jj) * sizeof(int));
            tour[jj] = city;
            double newCost = totalCost();
            if (newCost < curCost - 1e-10) {
                curCost = newCost;
            } else {
                // undo
                memmove(tour + jj, tour + jj + 1, (N - jj) * sizeof(int));
                memmove(tour + i + 1, tour + i, (N - i) * sizeof(int));
                tour[i] = city;
            }
        }
    }
    
    printf("%d\n", N+1);
    for (int i = 0; i <= N; i++) printf("%d\n", tour[i]);
    
    delete[] cx; delete[] cy; delete[] is_prime; delete[] tour;
    return 0;
}