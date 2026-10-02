#include <bits/stdc++.h>
using namespace std;

struct Timer {
    chrono::high_resolution_clock::time_point start;
    Timer() : start(chrono::high_resolution_clock::now()) {}
    double elapsed() const {
        return chrono::duration<double>(chrono::high_resolution_clock::now() - start).count();
    }
};

const int GRID = 10000;
int N;
int x[205], y[205], r[205];
int a[205], b[205], c[205], d[205];
int best_a[205], best_b[205], best_c[205], best_d[205];
double best_score;

unsigned long long xorstate = 88172645463325252ULL;
inline unsigned long long xorshift() {
    xorstate ^= xorstate << 13;
    xorstate ^= xorstate >> 7;
    xorstate ^= xorstate << 17;
    return xorstate;
}

inline long long area(int i) {
    return (long long)(c[i] - a[i]) * (d[i] - b[i]);
}

inline double satisfaction(int i) {
    if (!(a[i] <= x[i] && x[i] < c[i] && b[i] <= y[i] && y[i] < d[i])) return 0.0;
    long long s = area(i);
    if (s <= 0) return 0.0;
    double mn = min((double)s, (double)r[i]);
    double mx = max((double)s, (double)r[i]);
    double diff = 1.0 - mn / mx;
    return 1.0 - diff * diff;
}

inline int max_expand_left(int i) {
    int lim = 0;
    for (int j = 0; j < N; j++) {
        if (j == i) continue;
        if (b[i] < d[j] && b[j] < d[i] && c[j] <= a[i])
            lim = max(lim, c[j]);
    }
    return lim;
}
inline int max_expand_right(int i) {
    int lim = GRID;
    for (int j = 0; j < N; j++) {
        if (j == i) continue;
        if (b[i] < d[j] && b[j] < d[i] && a[j] >= c[i])
            lim = min(lim, a[j]);
    }
    return lim;
}
inline int max_expand_down(int i) {
    int lim = 0;
    for (int j = 0; j < N; j++) {
        if (j == i) continue;
        if (a[i] < c[j] && a[j] < c[i] && d[j] <= b[i])
            lim = max(lim, d[j]);
    }
    return lim;
}
inline int max_expand_up(int i) {
    int lim = GRID;
    for (int j = 0; j < N; j++) {
        if (j == i) continue;
        if (a[i] < c[j] && a[j] < c[i] && b[j] >= d[i])
            lim = min(lim, b[j]);
    }
    return lim;
}

Timer gtimer;

void greedy_init() {
    for (int i = 0; i < N; i++) {
        a[i] = x[i]; b[i] = y[i]; c[i] = x[i] + 1; d[i] = y[i] + 1;
    }
    int pass = 0;
    while (gtimer.elapsed() < 0.12 && pass < 200) {
        pass++;
        bool any = false;
        for (int i = 0; i < N; i++) {
            if (area(i) >= (long long)r[i]) continue;
            int w = c[i]-a[i], h = d[i]-b[i], step, lim, nv;
            lim = max_expand_left(i); step = max(1,w/2); nv = max(lim,a[i]-step);
            if (nv<a[i]) { a[i]=nv; any=true; }
            lim = max_expand_right(i); step = max(1,w/2); nv = min(lim,c[i]+step);
            if (nv>c[i]) { c[i]=nv; any=true; }
            lim = max_expand_down(i); step = max(1,h/2); nv = max(lim,b[i]-step);
            if (nv<b[i]) { b[i]=nv; any=true; }
            lim = max_expand_up(i); step = max(1,h/2); nv = min(lim,d[i]+step);
            if (nv>d[i]) { d[i]=nv; any=true; }
        }
        if (!any) break;
    }
}

double total_score() {
    double s = 0;
    for (int i = 0; i < N; i++) s += satisfaction(i);
    return s;
}

void simulated_annealing() {
    double T0 = 0.08, T1 = 0.0005;
    double sa_start = gtimer.elapsed();
    double total_time = 4.8;
    double sa_budget = total_time - sa_start;

    best_score = total_score();
    for (int i = 0; i < N; i++) { best_a[i]=a[i]; best_b[i]=b[i]; best_c[i]=c[i]; best_d[i]=d[i]; }

    // Two-phase cooling: linear from T0 to Tmid in first 60%, then exponential from Tmid to T1
    double phase1_frac = 0.6;
    double T_mid = 0.01;

    double progress = 0, T = T0;
    int iter = 0;

    while (true) {
        if ((iter & 0x3FF) == 0) {
            double elapsed = gtimer.elapsed();
            if (elapsed > total_time) break;
            progress = (elapsed - sa_start) / sa_budget;
            if (progress > 1.0) break;

            // Two-phase cooling schedule
            if (progress < phase1_frac) {
                // Phase 1: linear cooling T0 -> T_mid
                double p1 = progress / phase1_frac;
                T = T0 + (T_mid - T0) * p1;
            } else {
                // Phase 2: exponential cooling T_mid -> T1
                double p2 = (progress - phase1_frac) / (1.0 - phase1_frac);
                T = T_mid * pow(T1 / T_mid, p2);
            }

            // Check and save best periodically
            if ((iter & 0x7FFF) == 0) {
                double sc = total_score();
                if (sc > best_score) {
                    best_score = sc;
                    for (int j = 0; j < N; j++) { best_a[j]=a[j]; best_b[j]=b[j]; best_c[j]=c[j]; best_d[j]=d[j]; }
                }
            }
        }
        iter++;

        int i = xorshift() % N;
        int edge = xorshift() % 4;

        double old_si = satisfaction(i);
        int oa=a[i], ob=b[i], oc=c[i], od=d[i];

        int lo, hi, newval;
        switch(edge) {
            case 0: {
                lo = max_expand_left(i); hi = c[i]-1;
                if (lo >= hi) continue;
                int range = hi-lo; newval = lo + xorshift()%range;
                if (newval > x[i]) newval = x[i];
                a[i] = newval;
            } break;
            case 1: {
                lo = a[i]+1; hi = max_expand_right(i);
                if (lo >= hi) continue;
                int range = hi-lo; newval = lo + xorshift()%range + 1;
                if (newval < x[i]+1) newval = x[i]+1;
                if (newval > hi) newval = hi;
                c[i] = newval;
            } break;
            case 2: {
                lo = max_expand_down(i); hi = d[i]-1;
                if (lo >= hi) continue;
                int range = hi-lo; newval = lo + xorshift()%range;
                if (newval > y[i]) newval = y[i];
                b[i] = newval;
            } break;
            case 3: {
                lo = b[i]+1; hi = max_expand_up(i);
                if (lo >= hi) continue;
                int range = hi-lo; newval = lo + xorshift()%range + 1;
                if (newval < y[i]+1) newval = y[i]+1;
                if (newval > hi) newval = hi;
                d[i] = newval;
            } break;
        }

        double new_si = satisfaction(i);
        double delta = new_si - old_si;

        if (delta >= 0 || (xorshift() % 10000) < (unsigned long long)(exp(delta / T) * 10000)) {
            // accept
        } else {
            a[i]=oa; b[i]=ob; c[i]=oc; d[i]=od;
        }
    }

    // Final best check and restore
    double sc = total_score();
    if (sc > best_score) {
        best_score = sc;
        for (int j = 0; j < N; j++) { best_a[j]=a[j]; best_b[j]=b[j]; best_c[j]=c[j]; best_d[j]=d[j]; }
    }
    for (int i = 0; i < N; i++) { a[i]=best_a[i]; b[i]=best_b[i]; c[i]=best_c[i]; d[i]=best_d[i]; }
}

int main() {
    scanf("%d", &N);
    for (int i = 0; i < N; i++) scanf("%d %d %d", &x[i], &y[i], &r[i]);
    greedy_init();
    simulated_annealing();
    for (int i = 0; i < N; i++) printf("%d %d %d %d\n", a[i], b[i], c[i], d[i]);
    return 0;
}
