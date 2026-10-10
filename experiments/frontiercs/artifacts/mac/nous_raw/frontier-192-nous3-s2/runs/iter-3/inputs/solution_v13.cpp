#include <bits/stdc++.h>
using namespace std;

static int n, m;
static int pos[1002];
static int adj_arr[40001];
static int side_arr[1001];
static int gain_arr[1001];
static int best_side_arr[1001];
static int global_best_side[1001];
static int cut_val;

inline void flip_vertex(int v) {
    side_arr[v] ^= 1;
    cut_val += gain_arr[v];
    gain_arr[v] = -gain_arr[v];
    const int end = pos[v];
    for(int i = pos[v-1]; i < end; i++){
        int w = adj_arr[i];
        if(side_arr[v] == side_arr[w]) gain_arr[w] += 2;
        else gain_arr[w] -= 2;
    }
}

inline void calc_state() {
    memset(gain_arr + 1, 0, n * sizeof(int));
    cut_val = 0;
    for(int u = 1; u <= n; u++){
        const int end = pos[u];
        for(int i = pos[u-1]; i < end; i++){
            int w = adj_arr[i];
            if(side_arr[u] == side_arr[w]) gain_arr[u]++;
            else { gain_arr[u]--; cut_val++; }
        }
    }
    cut_val /= 2;
}

inline void greedy_improve() {
    bool improved = true;
    while(improved){
        improved = false;
        for(int v = 1; v <= n; v++){
            if(gain_arr[v] > 0){
                flip_vertex(v);
                improved = true;
            }
        }
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    cin >> n >> m;

    int deg[1001] = {};
    int eu[20001], ev[20001];
    for(int i = 0; i < m; i++){
        cin >> eu[i] >> ev[i];
        deg[eu[i]]++; deg[ev[i]]++;
    }
    pos[0] = 0;
    for(int i = 1; i <= n; i++) pos[i] = pos[i-1] + deg[i];
    int cur[1001];
    for(int i = 1; i <= n; i++) cur[i] = pos[i-1];
    for(int i = 0; i < m; i++){
        adj_arr[cur[eu[i]]++] = ev[i];
        adj_arr[cur[ev[i]]++] = eu[i];
    }

    if(m == 0){
        for(int i = 1; i <= n; i++){
            if(i > 1) putchar(' ');
            putchar('0');
        }
        putchar('\n');
        return 0;
    }

    mt19937 rng(31415);
    uniform_real_distribution<double> unif(0.0, 1.0);

    int global_best_cut = -1;

    // Use 1.2M budget for SA restarts, save ~300k iterations for final refinement
    int sa_budget = 1200000;

    int num_restarts;
    int sa_iters_per;
    if(n <= 100) {
        num_restarts = 18;
        sa_iters_per = sa_budget / num_restarts;
    } else if(n <= 300) {
        num_restarts = 10;
        sa_iters_per = sa_budget / num_restarts;
    } else if(n <= 600) {
        num_restarts = 7;
        sa_iters_per = sa_budget / num_restarts;
    } else {
        num_restarts = 4;
        sa_iters_per = sa_budget / num_restarts;
    }

    for(int restart = 0; restart < num_restarts; restart++){
        if(restart < num_restarts / 2) {
            int order[1000];
            for(int i = 0; i < n; i++) order[i] = i + 1;
            for(int i = n - 1; i > 0; i--){
                int j = rng() % (i + 1);
                int tmp = order[i]; order[i] = order[j]; order[j] = tmp;
            }
            for(int i = 1; i <= n; i++) side_arr[i] = 0;
            for(int idx = 0; idx < n; idx++){
                int v = order[idx];
                int in0 = 0, in1 = 0;
                const int end = pos[v];
                for(int i = pos[v-1]; i < end; i++){
                    int w = adj_arr[i];
                    if(side_arr[w] == 0) in0++;
                    else in1++;
                }
                side_arr[v] = (in0 >= in1) ? 1 : 0;
            }
        } else {
            for(int i = 1; i <= n; i++) side_arr[i] = rng() % 2;
        }

        calc_state();
        greedy_improve();
        int best_cut = cut_val;
        memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));

        // SA
        double T_start = 3.0, T_end = 0.001;
        double ratio = pow(T_end / T_start, 1.0 / sa_iters_per);
        double T = T_start;
        for(int it = 0; it < sa_iters_per; it++){
            int v = (rng() % n) + 1;
            int g = gain_arr[v];
            if(g > 0 || unif(rng) < exp((double)g / T)){
                flip_vertex(v);
                if(cut_val > best_cut){
                    best_cut = cut_val;
                    memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));
                }
            }
            T *= ratio;
        }

        memcpy(side_arr + 1, best_side_arr + 1, n * sizeof(int));
        calc_state();
        greedy_improve();
        if(cut_val > best_cut){
            best_cut = cut_val;
            memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));
        }

        // Quick ILS per restart
        for(int p = 0; p < 15; p++){
            memcpy(side_arr + 1, best_side_arr + 1, n * sizeof(int));
            calc_state();
            int k = max(1, n / (15 + p));
            for(int j = 0; j < k; j++){
                int v = (rng() % n) + 1;
                flip_vertex(v);
            }
            greedy_improve();
            if(cut_val > best_cut){
                best_cut = cut_val;
                memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));
            }
        }

        if(best_cut > global_best_cut){
            global_best_cut = best_cut;
            memcpy(global_best_side + 1, best_side_arr + 1, n * sizeof(int));
        }
    }

    // Phase 2: Final refinement of global best with SA + ILS
    // Use remaining budget for a focused SA on the best solution found
    int refine_iters = 300000;
    memcpy(side_arr + 1, global_best_side + 1, n * sizeof(int));
    calc_state();
    int best_cut = cut_val;
    memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));

    // Low-temperature SA for fine-tuning
    double T = 1.0, T_end = 0.0001;
    double ratio = pow(T_end / T, 1.0 / refine_iters);
    for(int it = 0; it < refine_iters; it++){
        int v = (rng() % n) + 1;
        int g = gain_arr[v];
        if(g > 0 || unif(rng) < exp((double)g / T)){
            flip_vertex(v);
            if(cut_val > best_cut){
                best_cut = cut_val;
                memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));
            }
        }
        T *= ratio;
    }

    memcpy(side_arr + 1, best_side_arr + 1, n * sizeof(int));
    calc_state();
    greedy_improve();
    if(cut_val > best_cut){
        best_cut = cut_val;
        memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));
    }

    // Final ILS on refined best
    for(int p = 0; p < 40; p++){
        memcpy(side_arr + 1, best_side_arr + 1, n * sizeof(int));
        calc_state();
        int k = max(1, n / (12 + p));
        for(int j = 0; j < k; j++){
            int v = (rng() % n) + 1;
            flip_vertex(v);
        }
        greedy_improve();
        if(cut_val > best_cut){
            best_cut = cut_val;
            memcpy(best_side_arr + 1, side_arr + 1, n * sizeof(int));
        }
    }

    if(best_cut > global_best_cut){
        memcpy(global_best_side + 1, best_side_arr + 1, n * sizeof(int));
    }

    for(int i = 1; i <= n; i++){
        if(i > 1) putchar(' ');
        putchar('0' + global_best_side[i]);
    }
    putchar('\n');

    return 0;
}
