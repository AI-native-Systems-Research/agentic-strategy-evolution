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

void bspSolve(vector<int>& ids, int lx, int ly, int ux, int uy, int depth, mt19937& rng, bool randomize) {
    if(ids.empty()) return;
    if(ids.size() == 1) {
        int i = ids[0];
        ra[i] = lx; rb[i] = ly; rc[i] = ux; rd[i] = uy;
        return;
    }
    
    int sz = ids.size();
    double bestCost = 1e18;
    int bestK = -1, bestSplit = -1;
    bool bestDir = true;
    
    for(int trySplitX = 0; trySplitX < 2; trySplitX++) {
        bool splitX = (trySplitX == 0);
        if(splitX) sort(ids.begin(), ids.end(), [](int a, int b){ return px[a] < px[b]; });
        else sort(ids.begin(), ids.end(), [](int a, int b){ return py[a] < py[b]; });
        
        long long totalR = 0;
        for(int i : ids) totalR += rr[i];
        
        long long cumR = 0;
        for(int k = 1; k < sz; k++) {
            cumR += rr[ids[k-1]];
            double frac = (double)cumR / totalR;
            
            int lo, hi, maxL, minR;
            if(splitX) {
                lo = lx; hi = ux;
                maxL = px[ids[k-1]];
                minR = px[ids[k]];
            } else {
                lo = ly; hi = uy;
                maxL = py[ids[k-1]];
                minR = py[ids[k]];
            }
            
            int splitPos = lo + (int)round(frac * (hi - lo));
            splitPos = max(splitPos, maxL + 1);
            splitPos = min(splitPos, minR + 1);
            if(splitPos <= lo || splitPos >= hi) continue;
            
            double actualFrac = (double)(splitPos - lo) / (hi - lo);
            double cost = (frac - actualFrac) * (frac - actualFrac);
            
            if(randomize) cost += (double)(rng() % 1000) * 1e-9;
            
            if(cost < bestCost) {
                bestCost = cost;
                bestK = k;
                bestSplit = splitPos;
                bestDir = splitX;
            }
        }
    }
    
    if(bestSplit < 0) {
        for(int idx : ids) {
            ra[idx]=px[idx]; rb[idx]=py[idx]; rc[idx]=px[idx]+1; rd[idx]=py[idx]+1;
        }
        return;
    }
    
    if(bestDir) sort(ids.begin(), ids.end(), [](int a, int b){ return px[a] < px[b]; });
    else sort(ids.begin(), ids.end(), [](int a, int b){ return py[a] < py[b]; });
    
    vector<int> left(ids.begin(), ids.begin()+bestK);
    vector<int> right(ids.begin()+bestK, ids.end());
    
    if(bestDir) {
        bspSolve(left, lx, ly, bestSplit, uy, depth+1, rng, randomize);
        bspSolve(right, bestSplit, ly, ux, uy, depth+1, rng, randomize);
    } else {
        bspSolve(left, lx, ly, ux, bestSplit, depth+1, rng, randomize);
        bspSolve(right, lx, bestSplit, ux, uy, depth+1, rng, randomize);
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
    
    int trials = 0;
    while(elapsed() < 1.0) {
        vector<int> ids(n); iota(ids.begin(), ids.end(), 0);
        bspSolve(ids, 0, 0, 10000, 10000, 0, rng, trials >= 2);
        double sc = 0; for(int i=0;i<n;i++) sc += scoreOf(i);
        if(sc > bestScore) { bestScore = sc; best_ra=ra; best_rb=rb; best_rc=rc; best_rd=rd; }
        trials++;
    }
    ra=best_ra; rb=best_rb; rc=best_rc; rd=best_rd;
    
    vector<double> sc(n);
    for(int i=0;i<n;i++) sc[i]=scoreOf(i);
    double curScore = bestScore;
    
    while(elapsed() < 4.7) {
        double progress = min(1.0, elapsed() / 4.7);
        double T = 0.05 * pow(0.0001 / 0.05, progress);
        
        int i = rng() % n;
        int dir = rng() % 4;
        int maxAmt = max(1, (int)(300 * (1.0 - progress * 0.8)));
        int amt = (int)(rng() % maxAmt) + 1;
        if(rng()&1) amt = -amt;
        
        int oa=ra[i],ob=rb[i],oc=rc[i],od=rd[i];
        if(dir==0) ra[i]+=amt; else if(dir==1) rb[i]+=amt; else if(dir==2) rc[i]+=amt; else rd[i]+=amt;
        ra[i]=max(0,min(ra[i],px[i])); rb[i]=max(0,min(rb[i],py[i]));
        rc[i]=min(10000,max(rc[i],px[i]+1)); rd[i]=min(10000,max(rd[i],py[i]+1));
        if(ra[i]>=rc[i]||rb[i]>=rd[i]){ra[i]=oa;rb[i]=ob;rc[i]=oc;rd[i]=od;continue;}
        
        double newSi=scoreOf(i), delta=newSi-sc[i];
        bool ok=true;
        vector<pair<int,array<int,4>>> changed;
        
        for(int j=0;j<n&&ok;j++){
            if(j==i)continue;
            if(ra[i]<rc[j]&&ra[j]<rc[i]&&rb[i]<rd[j]&&rb[j]<rd[i]){
                int oja=ra[j],ojb=rb[j],ojc=rc[j],ojd=rd[j];
                int dxl=rc[j]-ra[i],dxr=rc[i]-ra[j],dyl=rd[j]-rb[i],dyr=rd[i]-rb[j];
                int mn=min({dxl,dxr,dyl,dyr});
                if(mn==dxl)rc[j]=ra[i]; else if(mn==dxr)ra[j]=rc[i]; else if(mn==dyl)rd[j]=rb[i]; else rb[j]=rd[i];
                if(ra[j]>px[j]||rc[j]<=px[j]||rb[j]>py[j]||rd[j]<=py[j]||ra[j]>=rc[j]||rb[j]>=rd[j]){
                    ra[j]=oja;rb[j]=ojb;rc[j]=ojc;rd[j]=ojd;ok=false;
                } else {
                    double nj=scoreOf(j); delta+=nj-sc[j];
                    changed.push_back({j,{oja,ojb,ojc,ojd}});
                }
            }
        }
        
        if(!ok||(delta<0&&(double)(rng()%1000000)/1000000.0>exp(delta/T))){
            ra[i]=oa;rb[i]=ob;rc[i]=oc;rd[i]=od;
            for(auto&[j,v]:changed){ra[j]=v[0];rb[j]=v[1];rc[j]=v[2];rd[j]=v[3];}
        } else {
            sc[i]=scoreOf(i);
            for(auto&[j,v]:changed) sc[j]=scoreOf(j);
            curScore+=delta;
        }
    }
    
    for(int i=0;i<n;i++) cout<<ra[i]<<" "<<rb[i]<<" "<<rc[i]<<" "<<rd[i]<<"\n";
}
