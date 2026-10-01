#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int N;
    cin >> N;
    vector<double> X(N), Y(N);
    for(int i=0;i<N;i++) cin >> X[i] >> Y[i];
    
    vector<bool> is_prime(max(N,2), false);
    {
        vector<bool> sieve(max(N,2), true);
        sieve[0]=false; if(N>1) sieve[1]=false;
        for(int i=2;(long long)i*i<max(N,2);i++)
            if(sieve[i]) for(int j=i*i;j<max(N,2);j+=i) sieve[j]=false;
        for(int i=0;i<N;i++) is_prime[i]=sieve[i];
    }
    
    auto dist=[&](int a,int b)->double{
        double dx=X[a]-X[b], dy=Y[a]-Y[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // tour[0..N], tour[0]=tour[N]=0
    // Steps are 1-indexed: step t moves from tour[t-1] to tour[t]
    // Penalty: step t, if t%10==0 and tour[t-1] is not prime, multiplier=1.1
    
    vector<int> tour(N+1);
    // Start with identity tour: 0,1,2,...,N-1,0
    for(int i=0;i<N;i++) tour[i]=i;
    tour[N]=0;
    
    // pos[city] = index in tour where city appears (for cities 1..N-1, index 1..N-1)
    vector<int> pos(N);
    for(int i=0;i<=N;i++) if(i<N) pos[tour[i]]=i;
    
    auto mult=[&](int step, int city)->double{
        return (step%10==0 && !is_prime[city]) ? 1.1 : 1.0;
    };
    
    // Cost of edge at index i: step i+1, from tour[i] to tour[i+1]
    // multiplier depends on step (i+1) and tour[i]
    auto edgeCost=[&](int i)->double{
        int step = i+1;
        return mult(step, tour[i]) * dist(tour[i], tour[i+1]);
    };
    
    auto totalCost=[&]()->double{
        double s=0;
        for(int i=0;i<N;i++) s+=edgeCost(i);
        return s;
    };
    
    double bestCost = totalCost();
    
    auto start_time = chrono::steady_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-start_time).count();
    };
    
    // For large N, we can't do O(N^2) 2-opt naively.
    // Strategy: or-opt (relocate single cities) + prime placement optimization
    
    mt19937 rng(42);
    
    // Or-opt: remove city at position i, insert at position j
    // This changes steps around positions i-1,i,i+1 and j,j+1
    
    auto tryRelocate=[&](int from_pos) -> bool {
        if(from_pos<=0 || from_pos>=N) return false;
        int city = tour[from_pos];
        int prev = tour[from_pos-1];
        int next = tour[from_pos+1];
        
        // Cost of removing city from current position
        double oldRemove = edgeCost(from_pos-1) + edgeCost(from_pos);
        // Cost of connecting prev to next after removal
        // But step numbers change when we remove and reinsert...
        // This makes exact delta computation hard because step numbers shift.
        // For efficiency, we'll just do the move and check total cost.
        // But that's O(N) per move...
        
        // For moderate N, let's try a faster approach:
        // We'll test a few candidate insertion positions near the city's coordinates.
        return false;
    };
    
    // Since exact delta with step-number changes is complex, let's use a different strategy:
    // Simulated annealing with random 2-opt moves, evaluating full cost only on affected segments
    
    // For the penalty structure, a key observation: only every 10th step matters.
    // Let's focus on: 
    // 1) Good underlying TSP tour
    // 2) Swap cities to place primes at penalty positions
    
    // Phase 1: Improve tour with 2-opt (ignoring penalties for speed, or using approximate deltas)
    // For large N, use random 2-opt with neighbor lists
    
    // Actually, let's try a segmented approach since cities are x-sorted:
    // The identity tour is already decent. Try random swaps of nearby cities.
    
    // Phase 1: Random segment reversals (2-opt) - fast version
    // For a segment reversal [i+1..j], step numbers don't change, but cities at those positions change.
    // The edges affected are: (tour[i], tour[i+1]) and (tour[j], tour[j+1]), plus all edges within
    // the reversed segment have their step penalties potentially changed.
    // For short reversals, we can compute exact delta.
    
    int maxSegLen = min(N, 50); // Only try short reversals
    
    double temperature = bestCost / N * 0.1;
    double coolingRate = 0.99999;
    int iterations = 0;
    
    while(elapsed() < 1.5) {
        // Random 2-opt with short segments
        int i = rng() % N;
        int len = 2 + rng() % (maxSegLen - 1);
        int j = i + len;
        if(j >= N) { iterations++; continue; }
        if(i == 0 && j == N-1) { iterations++; continue; }
        
        // Compute old cost for affected range [i..j]
        double oldC = 0;
        for(int k=i; k<=j; k++) oldC += edgeCost(k);
        
        // Reverse segment [i+1..j]
        reverse(tour.begin()+i+1, tour.begin()+j+1);
        
        double newC = 0;
        for(int k=i; k<=j; k++) newC += edgeCost(k);
        
        double delta = newC - oldC;
        
        if(delta < 0 || (temperature > 1e-12 && exp(-delta/temperature) > (rng()%10000)/10000.0)) {
            bestCost += delta;
        } else {
            reverse(tour.begin()+i+1, tour.begin()+j+1);
        }
        
        temperature *= coolingRate;
        iterations++;
    }
    
    // Phase 2: Prime placement - swap to put primes at every 10th step position
    for(int step=10; step<=N; step+=10) {
        int idx = step-1; // tour[idx] is the source city for step `step`
        if(is_prime[tour[idx]]) continue;
        // Find a nearby prime city not at a penalty position, and swap
        double bestDelta = 0;
        int bestSwap = -1;
        for(int tries=0; tries<min(N,500); tries++){
            int other = 1 + rng()%(N-1);
            int opos = -1;
            for(int k=1;k<N;k++) if(tour[k]==other){opos=k;break;}
            if(opos<0 || opos==idx) continue;
            if(!is_prime[other]) continue;
            int ostep = opos+1;
            if(ostep%10==0) continue; // don't rob another penalty position
            // Try swap
            swap(tour[idx], tour[opos]);
            double newLocal=0, oldLocal=0;
            for(int k=max(0,idx-1);k<=min(N-1,idx+1);k++) newLocal+=edgeCost(k);
            for(int k=max(0,opos-1);k<=min(N-1,opos+1);k++) if(k<max(0,idx-1)||k>min(N-1,idx+1)) newLocal+=edgeCost(k);
            swap(tour[idx], tour[opos]);
            for(int k=max(0,idx-1);k<=min(N-1,idx+1);k++) oldLocal+=edgeCost(k);
            for(int k=max(0,opos-1);k<=min(N-1,opos+1);k++) if(k<max(0,idx-1)||k>min(N-1,idx+1)) oldLocal+=edgeCost(k);
            double d=newLocal-oldLocal;
            if(d<bestDelta){bestDelta=d;bestSwap=opos;}
        }
        if(bestSwap>=0){
            swap(tour[idx],tour[bestSwap]);
            bestCost+=bestDelta;
        }
    }
    
    cout << N+1 << "\n";
    for(int i=0;i<=N;i++) cout << tour[i] << "\n";
}
