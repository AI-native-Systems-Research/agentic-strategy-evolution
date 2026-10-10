#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    int N;
    cin >> N;
    vector<double> cx(N), cy(N);
    for(int i=0;i<N;i++) cin >> cx[i] >> cy[i];
    
    vector<bool> is_prime(N, false);
    if(N>2){
        vector<bool> sieve(N, true);
        sieve[0]=false;
        if(N>1) sieve[1]=false;
        for(int i=2;(long long)i*i<N;i++)
            if(sieve[i])
                for(int j=i*i;j<N;j+=i) sieve[j]=false;
        for(int i=0;i<N;i++) is_prime[i]=sieve[i];
    }
    
    // Precompute distances for small N
    vector<vector<float>> dist;
    bool useDist = (N <= 5000);
    if(useDist){
        dist.assign(N, vector<float>(N,0));
        for(int i=0;i<N;i++)
            for(int j=i+1;j<N;j++){
                float d = sqrtf((float)(cx[i]-cx[j])*(cx[i]-cx[j])+(float)(cy[i]-cy[j])*(cy[i]-cy[j]));
                dist[i][j]=dist[j][i]=d;
            }
    }
    
    auto ddist = [&](int a, int b) -> double {
        if(useDist) return dist[a][b];
        double dx=cx[a]-cx[b], dy=cy[a]-cy[b];
        return sqrt(dx*dx+dy*dy);
    };
    
    // step s is 1-indexed; tour[s-1] is source city at step s
    // penalty: if s%10==0 and source city is NOT prime, multiply by 1.1
    auto getmult = [&](int s, int src) -> double {
        return (s%10==0 && !is_prime[src]) ? 1.1 : 1.0;
    };
    
    auto tourCost = [&](const vector<int>& t) -> double {
        double cost=0;
        for(int s=1;s<=N;s++){
            cost += ddist(t[s-1],t[s]) * getmult(s, t[s-1]);
        }
        return cost;
    };
    
    // Nearest neighbor from start city
    auto buildNN = [&](int start) -> vector<int> {
        vector<int> t(N+1);
        vector<bool> visited(N, false);
        t[0]=start;
        visited[start]=true;
        for(int step=1;step<N;step++){
            int last=t[step-1];
            int best=-1; double bestD=1e30;
            for(int j=0;j<N;j++){
                if(!visited[j]){
                    double d=ddist(last,j);
                    if(d<bestD){bestD=d;best=j;}
                }
            }
            t[step]=best;
            visited[best]=true;
        }
        t[N]=start;
        return t;
    };
    
    // Grid-based NN for large N
    vector<int> bestTour;
    double bestCost = 1e30;
    
    if(N <= 3000){
        // Try multiple starts
        vector<int> starts = {0};
        if(N <= 1500){
            for(int i=1;i<min(N,20);i++) starts.push_back(rand()%N);
        }
        for(int s : starts){
            if(elapsed()>0.3) break;
            auto t = buildNN(s);
            // Rotate so city 0 is at position 0
            int zp=-1;
            for(int i=0;i<N;i++) if(t[i]==0){zp=i;break;}
            vector<int> rt(N+1);
            for(int i=0;i<N;i++) rt[i]=t[(zp+i)%N];
            rt[N]=0;
            double c = tourCost(rt);
            if(c<bestCost){bestCost=c;bestTour=rt;}
        }
    } else {
        // Grid-based NN
        double minx=*min_element(cx.begin(),cx.end());
        double maxx=*max_element(cx.begin(),cx.end());
        double miny=*min_element(cy.begin(),cy.end());
        double maxy=*max_element(cy.begin(),cy.end());
        
        int gridSize = max(1, (int)sqrt((double)N / 4.0));
        double cellW = (maxx-minx)/gridSize + 1e-9;
        double cellH = (maxy-miny)/gridSize + 1e-9;
        if(cellW < 1e-12) cellW = 1.0;
        if(cellH < 1e-12) cellH = 1.0;
        
        vector<vector<int>> grid(gridSize*gridSize);
        auto getCellXY = [&](double x, double y) -> pair<int,int> {
            int gx = min(gridSize-1, max(0,(int)((x-minx)/cellW)));
            int gy = min(gridSize-1, max(0,(int)((y-miny)/cellH)));
            return {gx, gy};
        };
        auto getCell = [&](int id) -> int {
            auto [gx,gy] = getCellXY(cx[id], cy[id]);
            return gy*gridSize+gx;
        };
        
        vector<bool> visited(N, false);
        for(int i=0;i<N;i++) grid[getCell(i)].push_back(i);
        
        bestTour.resize(N+1);
        bestTour[0]=0;
        visited[0]=true;
        {
            int c=getCell(0);
            auto &v=grid[c];
            v.erase(find(v.begin(),v.end(),0));
        }
        
        for(int step=1;step<N;step++){
            int last=bestTour[step-1];
            auto [gx0,gy0] = getCellXY(cx[last], cy[last]);
            
            int best=-1; double bestD=1e30;
            for(int rad=0;rad<gridSize*2;rad++){
                if(best!=-1){
                    double minPossible = max(0.0, (double)(rad-1)) * min(cellW, cellH);
                    if(minPossible > bestD*1.5) break;
                }
                for(int dx=-rad;dx<=rad;dx++){
                    for(int dy=-rad;dy<=rad;dy++){
                        if(abs(dx)!=rad && abs(dy)!=rad) continue;
                        int gx=gx0+dx, gy=gy0+dy;
                        if(gx<0||gx>=gridSize||gy<0||gy>=gridSize) continue;
                        auto &v=grid[gy*gridSize+gx];
                        for(int id : v){
                            if(!visited[id]){
                                double d=ddist(last,id);
                                if(d<bestD){bestD=d;best=id;}
                            }
                        }
                    }
                }
                if(best!=-1 && rad>0) break;
            }
            bestTour[step]=best;
            visited[best]=true;
            {
                int c=getCell(best);
                auto &v=grid[c];
                v.erase(find(v.begin(),v.end(),best));
            }
        }
        bestTour[N]=0;
        bestCost = tourCost(bestTour);
    }
    
    vector<int> tour = bestTour;
    double curCost = bestCost;
    
    // Compute segment cost from step lo to step hi inclusive
    auto segCost = [&](const vector<int>& t, int lo, int hi) -> double {
        double c=0;
        for(int s=max(1,lo);s<=min(N,hi);s++)
            c += ddist(t[s-1],t[s]) * getmult(s, t[s-1]);
        return c;
    };
    
    // Or-opt: remove city at tour position i (1<=i<N), try reinserting at position j
    // This shifts step assignments for everything between i and j
    auto orOptDelta = [&](int i, int j) -> double {
        // i: position to remove, j: position to insert before removal gap
        // After removal, the tour without city at i: ... tour[i-1], tour[i+1] ...
        // Then insert between positions
        // This is complex with penalty shifts. Let's just compute cost difference
        // by building the modified segment.
        
        if(i==j || i==0 || i>=N) return 0;
        if(j==0 || j>=N) return 0;
        
        int city = tour[i];
        
        // Build new tour segment
        // Affected range: min(i,j)-1 to max(i,j)+1
        int lo = min(i,j);
        int hi = max(i,j);
        
        double oldC = segCost(tour, lo, hi+1);
        
        // Create temporary segment
        vector<int> seg;
        for(int k=lo-1;k<=hi+1 && k<=N;k++){
            if(k==i) continue;
            if(j<i && k==j-1){
                seg.push_back(tour[k]);
                seg.push_back(city);
            } else if(j>i && k==j){
                seg.push_back(city);
                seg.push_back(tour[k]);
            } else {
                seg.push_back(tour[k]);
            }
        }
        // Hmm, this is getting complicated. Let me just do it directly.
        return 1e30; // placeholder
    };
    
    // Simple but effective: 2-opt and swap-based local search
    
    vector<int> pos(N);
    auto buildPos = [&](){
        for(int i=0;i<N;i++) pos[tour[i]]=i;
    };
    buildPos();
    
    // Or-opt: remove city at position i, insert at position j
    // Directly recompute affected cost
    auto tryOrOpt = [&](int i) -> pair<double,int> {
        if(i<=0||i>=N) return {0,-1};
        int city = tour[i];
        // Cost of removing: edges (i-1,i) and (i,i+1) become (i-1,i+1)
        // Steps i and i+1 change
        // But reinsertion shifts steps... 
        // For simplicity, just try and compute full delta
        
        // old edges at i: step i (tour[i-1]->tour[i]) and step i+1 (tour[i]->tour[i+1])
        // new edge: step becomes (tour[i-1]->tour[i+1]) but step numbering shifts
        
        // This is too complex for O(1). Let's just try removing and reinserting
        // and compute the actual cost change over the affected region.
        
        double bestDelta = 0;
        int bestJ = -1;
        
        // Try nearby positions
        int range = min(50, N-1);
        for(int j=max(1,i-range); j<=min(N-1,i+range); j++){
            if(j==i||j==i-1) continue; // no change or equivalent
            
            // Build modified tour for the affected range
            int lo = min(i,j);
            int hi = max(i,j);
            if(j>i) hi = j; else lo = j;
            
            // Old cost for steps lo..hi+1
            double oldC = 0;
            for(int s=lo;s<=min(hi+1,N);s++)
                oldC += ddist(tour[s-1],tour[s]) * getmult(s, tour[s-1]);
            
            // Build new segment
            vector<int> seg;
            if(j>i){
                // Remove from i, insert after j
                // positions lo-1=i-1, then i+1..j, city, j+1..hi+1
                seg.push_back(tour[i-1]);
                for(int k=i+1;k<=j;k++) seg.push_back(tour[k]);
                seg.push_back(city);
                if(j+1<=N) seg.push_back(tour[j+1<=N?j+1:0]);
                // steps lo to hi+1
                // seg has: tour[i-1], tour[i+1],...,tour[j], city, tour[j+1]
                // edges: (tour[i-1],tour[i+1]) at step lo=i
                //        ...
                //        (tour[j], city) at step j
                //        (city, tour[j+1]) at step j+1
            } else {
                // j < i: insert before j, remove from i
                seg.push_back(tour[j-1]);
                seg.push_back(city);
                for(int k=j;k<i;k++) seg.push_back(tour[k]);
                if(i+1<=N) seg.push_back(tour[i+1<=N?i+1:0]);
            }
            
            double newC = 0;
            for(int k=1;k<(int)seg.size();k++){
                int step = lo + k - 1;
                if(step>=1 && step<=N)
                    newC += ddist(seg[k-1],seg[k]) * getmult(step, seg[k-1]);
            }
            
            double delta = newC - oldC;
            if(delta < bestDelta - 1e-10){
                bestDelta = delta;
                bestJ = j;
            }
        }
        return {bestDelta, bestJ};
    };
    
    auto applyOrOpt = [&](int i, int j){
        int city = tour[i];
        if(j > i){
            // shift left
            for(int k=i;k<j;k++) tour[k]=tour[k+1];
            tour[j]=city;
        } else {
            // shift right
            for(int k=i;k>j;k--) tour[k]=tour[k-1];
            tour[j]=city;
        }
        buildPos();
    };
    
    // Main optimization loop
    mt19937 rng(42);
    
    int iter = 0;
    while(elapsed() < 1.9){
        bool improved = false;
        iter++;
        
        // Or-opt pass
        for(int i=1;i<N && elapsed()<1.85;i++){
            auto [delta,j] = tryOrOpt(i);
            if(delta < -1e-10){
                applyOrOpt(i,j);
                curCost += delta;
                improved = true;
            }
        }
        
        // 2-opt pass
        for(int i=1;i<N-1&&elapsed()<1.85;i++){
            for(int j=i+1;j<min(i+40,N);j++){
                int lo=i, hi=j+1;
                double oldSeg=0;
                for(int s=lo;s<=min(hi,N);s++) oldSeg+=ddist(tour[s-1],tour[s])*getmult(s,tour[s-1]);
                reverse(tour.begin()+i,tour.begin()+j+1);
                double newSeg=0;
                for(int s=lo;s<=min(hi,N);s++) newSeg+=ddist(tour[s-1],tour[s])*getmult(s,tour[s-1]);
                if(newSeg<oldSeg-1e-10){
                    curCost+=newSeg-oldSeg;
                    buildPos();
                    improved=true;
                } else {
                    reverse(tour.begin()+i,tour.begin()+j+1);
                }
            }
        }
        
        if(!improved) break;
    }
    
    cout << N+1 << "\n";
    for(int i=0;i<=N;i++) cout << tour[i] << "\n";
}
