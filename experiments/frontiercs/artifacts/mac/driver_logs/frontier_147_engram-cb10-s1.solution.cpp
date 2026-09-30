#include <bits/stdc++.h>
using namespace std;

int n;
vector<int> px, py;
vector<long long> rr;
vector<int> ra, rb, rc, rd;

double scoreOf(int i) {
    long long s = (long long)(rc[i]-ra[i])*(long long)(rd[i]-rb[i]);
    if(s <= 0) return 0.0;
    if(!(ra[i] <= px[i] && px[i] < rc[i] && rb[i] <= py[i] && py[i] < rd[i])) return 0.0;
    double ratio = (double)min(rr[i], s) / (double)max(rr[i], s);
    return 1.0 - (1.0 - ratio) * (1.0 - ratio);
}

double totalScore() {
    double s = 0;
    for(int i=0;i<n;i++) s += scoreOf(i);
    return s;
}

void bspSolve(vector<int>& ids, int lx, int ly, int ux, int uy, bool splitX, mt19937& rng, bool randomize) {
    if(ids.size() == 1) {
        int i = ids[0];
        ra[i] = lx; rb[i] = ly; rc[i] = ux; rd[i] = uy;
        return;
    }
    if(ids.empty()) return;
    
    int sz = ids.size();
    
    // Try both directions if not randomizing
    vector<bool> tryDirs;
    if(randomize && sz > 2) {
        // Occasionally flip direction
        bool flip = (rng() % 100) < 20;
        tryDirs.push_back(flip ? !splitX : splitX);
    } else {
        tryDirs.push_back(splitX);
        tryDirs.push_back(!splitX);
    }
    
    double bestCost = 1e18;
    int bestK = -1;
    int bestSplit = -1;
    bool bestDir = splitX;
    
    for(bool trySplitX : tryDirs) {
        if(trySplitX) {
            sort(ids.begin(), ids.end(), [](int a, int b){ return px[a] < px[b]; });
        } else {
            sort(ids.begin(), ids.end(), [](int a, int b){ return py[a] < py[b]; });
        }
        
        long long totalR = 0;
        for(int i : ids) totalR += rr[i];
        
        long long cumR = 0;
        for(int k = 1; k < sz; k++) {
            cumR += rr[ids[k-1]];
            double frac = (double)cumR / totalR;
            
            int splitPos;
            if(trySplitX) {
                splitPos = lx + (int)round(frac * (ux - lx));
                int maxLeft = px[ids[k-1]];
                int minRight = px[ids[k]];
                splitPos = max(splitPos, maxLeft + 1);
                splitPos = min(splitPos, minRight + 1);
                if(splitPos <= lx || splitPos >= ux) continue;
            } else {
                splitPos = ly + (int)round(frac * (uy - ly));
                int maxLeft = py[ids[k-1]];
                int minRight = py[ids[k]];
                splitPos = max(splitPos, maxLeft + 1);
                splitPos = min(splitPos, minRight + 1);
                if(splitPos <= ly || splitPos >= uy) continue;
            }
            
            double actualFrac;
            if(trySplitX) actualFrac = (double)(splitPos - lx) / (ux - lx);
            else actualFrac = (double)(splitPos - ly) / (uy - ly);
            
            double cost = (frac - actualFrac) * (frac - actualFrac);
            
            if(randomize) {
                // Add small random perturbation to encourage diversity
                cost += (double)(rng() % 1000) * 1e-9;
            }
            
            if(cost < bestCost) {
                bestCost = cost;
                bestK = k;
                bestSplit = splitPos;
                bestDir = trySplitX;
            }
        }
    }
    
    if(bestSplit < 0) {
        // Last resort: assign 1x1 rectangles
        for(int idx : ids) {
            ra[idx] = px[idx]; rb[idx] = py[idx]; rc[idx] = px[idx]+1; rd[idx] = py[idx]+1;
        }
        return;
    }
    
    // Re-sort by best direction
    if(bestDir) {
        sort(ids.begin(), ids.end(), [](int a, int b){ return px[a] < px[b]; });
    } else {
        sort(ids.begin(), ids.end(), [](int a, int b){ return py[a] < py[b]; });
    }
    
    vector<int> left(ids.begin(), ids.begin()+bestK);
    vector<int> right(ids.begin()+bestK, ids.end());
    
    bool nextDir = !bestDir;
    
    if(bestDir) {
        bspSolve(left, lx, ly, bestSplit, uy, nextDir, rng, randomize);
        bspSolve(right, bestSplit, ly, ux, uy, nextDir, rng, randomize);
    } else {
        bspSolve(left, lx, ly, ux, bestSplit, nextDir, rng, randomize);
        bspSolve(right, lx, bestSplit, ux, uy, nextDir, rng, randomize);
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    cin >> n;
    px.resize(n); py.resize(n); rr.resize(n);
    ra.resize(n); rb.resize(n); rc.resize(n); rd.resize(n);
    
    for(int i=0;i<n;i++) cin >> px[i] >> py[i] >> rr[i];
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    vector<int> best_ra(n), best_rb(n), best_rc(n), best_rd(n);
    double bestScore = -1;
    mt19937 rng(42);
    
    // Try multiple BSP configs
    int bspTrials = 0;
    while(elapsed() < 0.5) {
        vector<int> ids(n);
        iota(ids.begin(), ids.end(), 0);
        bool randomize = (bspTrials >= 2);
        bool startX = (bspTrials % 2 == 0);
        bspSolve(ids, 0, 0, 10000, 10000, startX, rng, randomize);
        double sc = totalScore();
        if(sc > bestScore) {
            bestScore = sc;
            best_ra = ra; best_rb = rb; best_rc = rc; best_rd = rd;
        }
        bspTrials++;
    }
    ra = best_ra; rb = best_rb; rc = best_rc; rd = best_rd;
    
    // SA refinement
    double timeLimit = 4.7;
    double curScore = totalScore();
    
    vector<double> sc(n);
    for(int i=0;i<n;i++) sc[i] = scoreOf(i);
    
    long long iter = 0;
    while(elapsed() < timeLimit) {
        double progress = elapsed() / timeLimit;
        double T = 0.05 * pow(0.00001 / 0.05, progress);
        
        int i = rng() % n;
        int dir = rng() % 4; // 0=left, 1=bottom, 2=right, 3=top
        int maxAmt = max(1, (int)(500 * (1.0 - progress * 0.9)));
        int amt = (int)(rng() % maxAmt) + 1;
        if(rng()&1) amt = -amt;
        
        int oa=ra[i], ob=rb[i], oc=rc[i], od=rd[i];
        
        if(dir==0) ra[i] += amt;
        else if(dir==1) rb[i] += amt;
        else if(dir==2) rc[i] += amt;
        else rd[i] += amt;
        
        ra[i]=max(0,min(ra[i],px[i]));
        rb[i]=max(0,min(rb[i],py[i]));
        rc[i]=min(10000,max(rc[i],px[i]+1));
        rd[i]=min(10000,max(rd[i],py[i]+1));
        
        if(ra[i]>=rc[i]||rb[i]>=rd[i]){ra[i]=oa;rb[i]=ob;rc[i]=oc;rd[i]=od; iter++; continue;}
        
        double newSi = scoreOf(i);
        double delta = newSi - sc[i];
        
        bool ok = true;
        vector<pair<int,array<int,4>>> changed;
        
        for(int j=0;j<n&&ok;j++) {
            if(j==i) continue;
            if(ra[i]<rc[j]&&ra[j]<rc[i]&&rb[i]<rd[j]&&rb[j]<rd[i]) {
                int oja=ra[j],ojb=rb[j],ojc=rc[j],ojd=rd[j];
                int dxl=rc[j]-ra[i], dxr=rc[i]-ra[j], dyl=rd[j]-rb[i], dyr=rd[i]-rb[j];
                int mn=min({dxl,dxr,dyl,dyr});
                if(mn==dxl) rc[j]=ra[i];
                else if(mn==dxr) ra[j]=rc[i];
                else if(mn==dyl) rd[j]=rb[i];
                else rb[j]=rd[i];
                
                if(ra[j]>px[j]||rc[j]<=px[j]||rb[j]>py[j]||rd[j]<=py[j]||ra[j]>=rc[j]||rb[j]>=rd[j]){
                    ra[j]=oja;rb[j]=ojb;rc[j]=ojc;rd[j]=ojd;
                    ok=false;
                } else {
                    double newSj = scoreOf(j);
                    delta += newSj - sc[j];
                    changed.push_back({j,{oja,ojb,ojc,ojd}});
                }
            }
        }
        
        double rval = (double)(rng()%1000000)/1000000.0;
        if(!ok||(delta<0 && rval > exp(delta/T))){
            ra[i]=oa;rb[i]=ob;rc[i]=oc;rd[i]=od;
            for(auto&[j,v]:changed){ra[j]=v[0];rb[j]=v[1];rc[j]=v[2];rd[j]=v[3];}
        } else {
            sc[i] = scoreOf(i);
            for(auto&[j,v]:changed) sc[j] = scoreOf(j);
            curScore += delta;
        }
        iter++;
    }
    
    for(int i=0;i<n;i++) cout<<ra[i]<<" "<<rb[i]<<" "<<rc[i]<<" "<<rd[i]<<"\n";
}
