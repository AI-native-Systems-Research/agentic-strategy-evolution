Looking at the previous solution, I can identify several key limitations:

1. **MaxRects pruning too aggressive** (capping at 500 free rects loses precision)
2. **Strip packing is too rigid** - only packs uniform strips, missing mixed-type opportunities
3. **No proper gap filling** - leftover spaces aren't well utilized
4. **Two-type split is simplistic** - doesn't explore partial strip allocations well
5. **No simulated annealing or local search** to refine solutions
6. **Missing key heuristic**: for each type, computing optimal tiling of the full bin as strips in both orientations, then combining best types

The main improvement strategy: implement a much better solver that uses:
- Better MaxRects with proper containment pruning
- Multiple placement heuristics (BSSF, BL, BAF, etc.)
- A proper multi-restart search over type orderings and split ratios
- Column-based strip optimization: for each combination of types allocated to horizontal strips, optimize strip counts via knapsack/DP
- Recursive gap filling

```cpp
#include <bits/stdc++.h>
using namespace std;

struct Item { string type; int w, h; long long v; int limit; };
struct Placement { string type; int x, y, rot; };

int W, H, M;
bool allow_rot;
vector<Item> items;
long long bestVal = 0;
vector<Placement> bestPl;

void updateBest(long long v, vector<Placement>& pl) {
    if (v > bestVal) { bestVal = v; bestPl = pl; }
}

struct Rect { int x,y,w,h; };

struct MaxRects {
    int BW, BH;
    vector<Rect> fr;
    
    void init(int w, int h) { BW=w; BH=h; fr.clear(); fr.push_back({0,0,w,h}); }
    
    void prune() {
        int n = fr.size();
        vector<bool> del(n, false);
        for (int i = 0; i < n; i++) {
            if (del[i]) continue;
            for (int j = i+1; j < n; j++) {
                if (del[j]) continue;
                auto &a=fr[i], &b=fr[j];
                if (a.x<=b.x && a.y<=b.y && a.x+a.w>=b.x+b.w && a.y+a.h>=b.y+b.h)
                    del[j]=true;
                else if (b.x<=a.x && b.y<=a.y && b.x+b.w>=a.x+a.w && b.y+b.h>=a.y+a.h)
                    { del[i]=true; break; }
            }
        }
        vector<Rect> nfr;
        for (int i=0;i<n;i++) if(!del[i]) nfr.push_back(fr[i]);
        fr=nfr;
        // Keep manageable size
        if ((int)fr.size() > 2000) {
            sort(fr.begin(), fr.end(), [](auto&a,auto&b){return (long long)a.w*a.h>(long long)b.w*b.h;});
            fr.resize(2000);
        }
    }
    
    void insert(int px, int py, int pw, int ph) {
        int rx2=px+pw, ry2=py+ph;
        vector<Rect> add;
        vector<Rect> nfr;
        for (auto& r : fr) {
            int rr=r.x+r.w, rt=r.y+r.h;
            if (px>=rr || rx2<=r.x || py>=rt || ry2<=r.y) {
                nfr.push_back(r); continue;
            }
            if (px > r.x) nfr.push_back({r.x, r.y, px-r.x, r.h});
            if (rx2 < rr) nfr.push_back({rx2, r.y, rr-rx2, r.h});
            if (py > r.y) nfr.push_back({r.x, r.y, r.w, py-r.y});
            if (ry2 < rt) nfr.push_back({r.x, ry2, r.w, rt-ry2});
        }
        fr=nfr;
        prune();
    }
    
    // heuristics: 0=BSSF, 1=BL, 2=BAF, 3=BLSF, 4=contact point (approx)
    bool findPos(int pw, int ph, int& bx, int& by, int heur) {
        bx=by=-1;
        long long bs1=LLONG_MAX, bs2=LLONG_MAX;
        for (auto& r : fr) {
            if (pw>r.w || ph>r.h) continue;
            long long s1,s2;
            int sf1=r.w-pw, sf2=r.h-ph;
            switch(heur) {
                case 0: s1=min(sf1,sf2); s2=max(sf1,sf2); break;
                case 1: s1=r.y; s2=r.x; break;
                case 2: s1=(long long)r.w*r.h; s2=min(sf1,sf2); break;
                case 3: s1=max(sf1,sf2); s2=min(sf1,sf2); break;
                default: s1=r.x+r.y; s2=min(sf1,sf2); break;
            }
            if (s1<bs1||(s1==bs1&&s2<bs2)) { bs1=s1;bs2=s2;bx=r.x;by=r.y; }
        }
        return bx>=0;
    }
};

struct Cand { int ti, rot, pw, ph; double density; };
vector<Cand> allCands;

// Try packing candidates in order, each until exhausted
pair<long long,vector<Placement>> packOrder(vector<Cand>& order, int heur) {
    MaxRects mr; mr.init(W,H);
    vector<int> used(M,0);
    vector<Placement> pl;
    long long val=0;
    for (auto& c : order) {
        while (used[c.ti]<items[c.ti].limit) {
            int bx,by;
            if (!mr.findPos(c.pw,c.ph,bx,by,heur)) break;
            mr.insert(bx,by,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bx,by,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
    }
    return {val,pl};
}

// Greedy: pick best candidate at each step
pair<long long,vector<Placement>> greedyPack(int heur, int scoreMode) {
    MaxRects mr; mr.init(W,H);
    vector<int> used(M,0);
    vector<Placement> pl;
    long long val=0;
    while(true) {
        int bestCI=-1; int bbx=0,bby=0;
        double bestScore=-1e30;
        for (int ci=0;ci<(int)allCands.size();ci++) {
            auto& c=allCands[ci];
            if (used[c.ti]>=items[c.ti].limit) continue;
            int fx,fy;
            if (!mr.findPos(c.pw,c.ph,fx,fy,heur)) continue;
            double score;
            switch(scoreMode) {
                case 0: score=c.density; break;
                case 1: score=(double)items[c.ti].v; break;
                case 2: score=c.density*(c.pw*c.ph); break;
                case 3: score=c.density-0.0001*(fx+fy); break;
                default: score=c.density; break;
            }
            if (score>bestScore) { bestScore=score; bestCI=ci; bbx=fx; bby=fy; }
        }
        if (bestCI<0) break;
        auto& c=allCands[bestCI];
        mr.insert(bbx,bby,c.pw,c.ph);
        pl.push_back({items[c.ti].type,bbx,bby,c.rot});
        val+=items[c.ti].v; used[c.ti]++;
    }
    return {val,pl};
}

// Strip-based DP: allocate horizontal strips for types, then fill gaps
// For each type+rotation, compute (strip_height, items_per_strip, value_per_strip)
struct StripConfig {
    int ti, rot, pw, ph;
    int stripThick; // thickness of one strip
    int perStrip;   // items per strip row
    long long valPerStrip;
    int maxStrips;  // limited by item count
};

pair<long long,vector<Placement>> stripDP(bool horiz) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    vector<StripConfig> configs;
    for (int i=0;i<M;i++) {
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw = r ? items[i].h : items[i].w;
            int ph = r ? items[i].w : items[i].h;
            if (pw>W||ph>H) continue;
            int thick = horiz ? ph : pw;
            int cross = horiz ? pw : ph;
            int per = crossDim / cross;
            if (per<=0||thick<=0) continue;
            int maxS = items[i].limit / per;
            if (maxS<=0) continue;
            configs.push_back({i,r,pw,ph,thick,per,(long long)per*items[i].v,min(maxS,mainDim/thick)});
        }
    }
    
    if (configs.empty()) return {0,{}};
    
    // DP on mainDim with knapsack over strip configs
    // State: remaining main dimension, used count per type
    // Too expensive for full DP. Use greedy: pick best value-per-thickness strips
    
    // Sort by value density per unit of main dimension
    sort(configs.begin(), configs.end(), [](auto&a,auto&b){
        return (double)a.valPerStrip/a.stripThick > (double)b.valPerStrip/b.stripThick;
    });
    
    // Greedy allocation
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl;
    long long val=0;
    vector<array<int,4>> gaps;
    
    for (auto& sc : configs) {
        while (pos+sc.stripThick<=mainDim) {
            int avail = items[sc.ti].limit - used[sc.ti];
            if (avail < sc.perStrip) break; // need full strip (could do partial)
            // Place a strip
            int placed=0;
            for (int j=0;j<sc.perStrip && used[sc.ti]<items[sc.ti].limit;j++) {
                int x,y;
                if (horiz) { x=j*sc.pw; y=pos; }
                else { x=pos; y=j*sc.ph; }
                pl.push_back({items[sc.ti].type,x,y,sc.rot});
                val+=items[sc.ti].v; used[sc.ti]++; placed++;
            }
            int endCoord = horiz ? placed*sc.pw : placed*sc.ph;
            int gapSize = crossDim - endCoord;
            if (gapSize>0) {
                if (horiz) gaps.push_back({endCoord,pos,gapSize,sc.stripThick});
                else gaps.push_back({pos,endCoord,sc.stripThick,gapSize});
            }
            pos+=sc.stripThick;
        }
    }
    
    // Also allow partial strips
    for (auto& sc : configs) {
        while (pos+sc.stripThick<=mainDim && used[sc.ti]<items[sc.ti].limit) {
            int placed=0;
            int startPos=pos;
            for (int j=0;j<sc.perStrip && used[sc.ti]<items[sc.ti].limit;j++) {
                int x,y;
                if (horiz) { x=j*sc.pw; y=pos; }
                else { x=pos; y=j*sc.ph; }
                pl.push_back({items[sc.ti].type,x,y,sc.rot});
                val+=items[sc.ti].v; used[sc.ti]++; placed++;
            }
            if (placed==0) break;
            int endCoord = horiz ? placed*sc.pw : placed*sc.ph;
            int gapSize = crossDim - endCoord;
            if (gapSize>0) {
                if (horiz) gaps.push_back({endCoord,startPos,gapSize,sc.stripThick});
                else gaps.push_back({startPos,endCoord,sc.stripThick,gapSize});
            }
            pos+=sc.stripThick;
        }
    }
    
    if (pos<mainDim) {
        if (horiz) gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    
    // Fill gaps with MaxRects
    auto candOrder=allCands;
    sort(candOrder.begin(),candOrder.end(),[](auto&a,auto&b){return a.density>b.density;});
    
    for (auto& g : gaps) {
        if (g[2]<=0||g[3]<=0) continue;
        MaxRects mr; mr.init(g[2],g[3]);
        for (auto& c : candOrder) {
            while (used[c.ti]<items[c.ti].limit) {
                int bx,by;
                if (!mr.findPos(c.pw,c.ph,bx,by,0)) break;
                mr.insert(bx,by,c.pw,c.ph);
                pl.push_back({items[c.ti].type,bx+g[0],by+g[1],c.rot});
                val+=items[c.ti].v; used[c.ti]++;
            }
        }
    }
    return {val,pl};
}

// Advanced strip: enumerate allocations of top types to strips using bounded knapsack
pair<long long,vector<Placement>> advancedStripKnapsack(bool horiz) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    struct SC {
        int ti, rot, pw, ph;
        int thick, per;
        long long valPer;
        int maxCount; // max strips
    };
    
    vector<SC> scs;
    for (int i=0;i<M;i++) {
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw = r?items[i].h:items[i].w;
            int ph = r?items[i].w:items[i].h;
            if (pw>W||ph>H) continue;
            int thick = horiz?ph:pw;
            int cross = horiz?pw:ph;
            int per = crossDim/cross;
            if (per<=0||thick<=0) continue;
            int maxS = min(items[i].limit/per, mainDim/thick);
            if (maxS<=0) continue;
            scs.push_back({i,r,pw,ph,thick,per,(long long)per*items[i].v,maxS});
        }
    }
    
    if (scs.empty()) return {0,{}};
    
    // Remove dominated: for same ti, keep best valPer/thick
    // Actually keep all since different thick values can fill differently
    
    // Bounded knapsack on mainDim
    // capacity = mainDim, items = strip configs with weight=thick, value=valPer, count=maxCount
    // But types share limits! Two configs for same type consume the same item pool.
    // This makes it a complex problem. Simplify: for each type, pick best config.
    
    // Per type, pick config with best valPer/thick
    map<int, SC> bestConfig;
    for (auto& sc : scs) {
        auto it = bestConfig.find(sc.ti);
        if (it==bestConfig.end() || (double)sc.valPer/sc.thick > (double)it->second.valPer/it->second.thick) {
            bestConfig[sc.ti] = sc;
        }
    }
    
    vector<SC> typeConfigs;
    for (auto& [k,v] : bestConfig) typeConfigs.push_back(v);
    
    int nTypes = typeConfigs.size();
    
    // Bounded knapsack DP
    // dp[cap] = best value achievable with 'cap' main dimension
    // But we need to track per-type usage for limit checking
    // With M<=12 types and mainDim<=2000, we can do DP differently
    
    // Since nTypes<=12 (at most), and each has maxCount potentially up to ~200,
    // we can binary-split the bounded knapsack
    
    vector<long long> dp(mainDim+1, 0);
    vector<vector<pair<int,int>>> dpChoice(mainDim+1); // (type_config_idx, count) - track via backtracking
    
    // Actually, let's just do a simple DP with binary splitting
    // dp[j] = max value using j units of mainDim
    // For each type config, do bounded knapsack with binary decomposition
    
    struct KItem { int weight; long long value; int origType; };
    vector<KItem> kitems;
    for (int i=0;i<nTypes;i++) {
        auto& tc = typeConfigs[i];
        int cnt = tc.maxCount;
        int k=1;
        while (cnt>0) {
            int take = min(k, cnt);
            kitems.push_back({tc.thick*take, tc.valPer*take, i});
            cnt -= take;
            k *= 2;
        }
    }
    
    // 0-1 knapsack (each kitem used at most once)
    // But we need to track which items are used for reconstruction
    // Use parent tracking
    
    vector<long long> dpv(mainDim+1, 0);
    vector<int> from(mainDim+1, -1); // which kitem was last added
    vector<int> prev(mainDim+1, -1); // previous capacity
    
    // This is too memory-heavy for proper backtracking with many kitems
    // Use simpler approach: enumerate combinations of strip counts for top types
    
    // Since nTypes<=12, and we want to fill mainDim, let's do recursive search with pruning
    
    long long bestV = 0;
    vector<int> bestCounts(nTypes, 0);
    
    // Sort by value density descending
    vector<int> order(nTypes);
    iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){
        return (double)typeConfigs[a].valPer/typeConfigs[a].thick >
               (double)typeConfigs[b].valPer/typeConfigs[b].thick;
    });
    
    vector<int> curCounts(nTypes, 0);
    long long curVal = 0;
    int curUsed = 0;
    
    // Compute upper bound for remaining types
    function<void(int)> solve = [&](int idx) {
        if (curVal > bestV) { bestV = curVal; bestCounts = curCounts; }
        if (idx >= nTypes) return;
        
        // Upper bound: fill remaining with best density
        int rem = mainDim - curUsed;
        if (rem <= 0) return;
        
        // Compute UB
        long long ub = curVal;
        int remCap = rem;
        for (int i=idx;i<nTypes && remCap>0;i++) {
            int oi = order[i];
            int maxS = min(typeConfigs[oi].maxCount, remCap/typeConfigs[oi].thick);
            ub += (long long)maxS * typeConfigs[oi].valPer;
            remCap -= maxS * typeConfigs[oi].thick;
        }
        if (ub <= bestV) return;
        
        int oi = order[idx];
        int maxS = min(typeConfigs[oi].maxCount, rem/typeConfigs[oi].thick);
        
        // Try from maxS down to 0
        for (int s=maxS; s>=0; s--) {
            curCounts[oi] = s;
            curVal += (long long)s * typeConfigs[oi].valPer;
            curUsed += s * typeConfigs[oi].thick;
            solve(idx+1);
            curVal -= (long long)s * typeConfigs[oi].valPer;
            curUsed -= s * typeConfigs[oi].thick;
            curCounts[oi] = 0;
            
            // Early termination check
            if (s > 0) {
                long long potVal = curVal + (long long)(s-1)*typeConfigs[oi].valPer;
                int potRem = mainDim - curUsed - (s-1)*typeConfigs[oi].thick;
                long long potUB = potVal;
                int rc = potRem;
                for (int i=idx+1;i<nTypes&&rc>0;i++) {
                    int oj=order[i];
                    int ms=min(typeConfigs[oj].maxCount,rc/typeConfigs[oj].thick);
                    potUB+=(long long)ms*typeConfigs[oj].valPer;
                    rc-=ms*typeConfigs[oj].thick;
                }
                if (potUB<=bestV) break;
            }
        }
    };
    
    solve(0);
    
    // Reconstruct placement
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl;
    long long val=0;
    vector<array<int,4>> gaps;
    
    // Place strips in order of density
    for (int i=0;i<nTypes;i++) {
        int oi=order[i];
        auto& tc=typeConfigs[oi];
        for (int s=0;s<bestCounts[oi];s++) {
            int placed=0;
            for (int j=0;j<tc.per&&used[tc.ti]<items[tc.ti].limit;j++) {
                int x,y;
                if (horiz) {x=j*tc.pw;y=pos;}
                else {x=pos;y=j*tc.ph;}
                pl.push_back({items[tc.ti].type,x,y,tc.rot});
                val+=items[tc.ti].v; used[tc.ti]++; placed++;
            }
            int endCoord = horiz?placed*tc.pw:placed*tc.ph;
            int gapSize = crossDim - endCoord;
            if (gapSize>0) {
                if (horiz) gaps.push_back({endCoord,pos,gapSize,tc.thick});
                else gaps.push_back({pos,endCoord,tc.thick,gapSize});
            }
            pos+=tc.thick;
        }
    }
    
    if (pos<mainDim) {
        if (horiz) gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    
    // Fill gaps
    auto candOrder=allCands;
    sort(candOrder.begin(),candOrder.end(),[](auto&a,auto&b){return a.density>b.density;});
    
    for (auto& g : gaps) {
        if (g[2]<=0||g[3]<=0) continue;
        MaxRects mr; mr.init(g[2],g[3]);
        for (auto& c : candOrder) {
            while (used[c.ti]<items[c.ti].limit) {
                int bx,by;
                if (!mr.findPos(c.pw,c.ph,bx,by,0)) break;
                mr.insert(bx,by,c.pw,c.ph);
                pl.push_back({items[c.ti].type,bx+g[0],by+g[1],c.rot});
                val+=items[c.ti].v; used[c.ti]++;
            }
        }
    }
    
    return {val,pl};
}

// Multi-config strip: for each type, also consider multiple rotations 
// and try to allocate the best combo of strips along mainDim
pair<long long,vector<Placement>> multiConfigStrip(vector<int>& typeOrder, bool horiz) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl;
    long long val=0;
    vector<array<int,4>> gaps;
    
    for (int ti : typeOrder) {
        if (pos>=mainDim) break;
        
        struct SC { int rot,pw,ph,thick,per; double eff; };
        vector<SC> cfgs;
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw=r?items[ti].h:items[ti].w;
            int ph=r?items[ti].w:items[ti].h;
            if (pw>W||ph>H) continue;
            int thick=horiz?ph:pw;
            int cross=horiz?pw:ph;
            int per=crossDim/cross;
            if (per<=0||thick<=0) continue;
            cfgs.push_back({r,pw,ph,thick,per,(double)per*cross/crossDim});
        }
        // Sort by efficiency
        sort(cfgs.begin(),cfgs.end(),[](auto&a,auto&b){return a.eff>b.eff;});
        
        for (auto& cfg : cfgs) {
            while (pos+cfg.thick<=mainDim && used[ti]<items[ti].limit) {
                int avail = items[ti].limit-used[ti];
                if (avail<=0) break;
                int toPlace = min(cfg.per, avail);
                int placed=0;
                for (int j=0;j<toPlace;j++) {
                    int x,y;
                    if (horiz) {x=j*cfg.pw;y=pos;}
                    else {x=pos;y=j*cfg.ph;}
                    pl.push_back({items[ti].type,x,y,cfg.rot});
                    val+=items[ti].v; used[ti]++; placed++;
                }
                int endCoord=horiz?placed*cfg.pw:placed*cfg.ph;
                int gapSize=crossDim-endCoord;
                if (gapSize>0) {
                    if (horiz) gaps.push_back({endCoord,pos,gapSize,cfg.thick});
                    else gaps.push_back({pos,endCoord,cfg.thick,gapSize});
                }
                pos+=cfg.thick;
            }
        }
    }
    
    if (pos<mainDim) {
        if (horiz) gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    
    // Fill gaps
    auto candOrder=allCands;
    sort(candOrder.begin(),candOrder.end(),[](auto&a,auto&b){return a.density>b.density;});
    
    for (auto& g : gaps) {
        if (g[2]<=0||g[3]<=0) continue;
        MaxRects mr; mr.init(g[2],g[3]);
        for (auto& c : candOrder) {
            while (used[c.ti]<items[c.ti].limit) {
                int bx,by;
                if (!mr.findPos(c.pw,c.ph,bx,by,0)) break;
                mr.insert(bx,by,c.pw,c.ph);
                pl.push_back({items[c.ti].type,bx+g[0],by+g[1],c.rot});
                val+=items[c.ti].v; used[c.ti]++;
            }
        }
    }
    return {val,pl};
}

// Skyline bottom-left packer
struct Skyline {
    int BW, BH;
    vector<pair<int,int>> segs; // (x_end, height) segments left to right
    
    void init(int w, int h) {
        BW=w; BH=h;
        segs.clear();
        segs.push_back({w,0});
    }
    
    // Find the leftmost position where we can place pw x ph
    bool findPos(int pw, int ph, int& rx, int& ry) {
        rx=ry=-1;
        int bestWaste = INT_MAX;
        int cx=0;
        for (int i=0;i<(int)segs.size();i++) {
            int sh = segs[i].second;
            if (sh+ph>BH) { cx=segs[i].first; continue; }
            // Check if pw fits starting from cx
            int endx = cx+pw;
            if (endx>BW) { cx=segs[i].first; continue; }
            // Find max height in [cx, cx+pw)
            int maxH = 0;
            int tx = cx;
            bool fits = true;
            for (int j=i;j<(int)segs.size()&&tx<endx;j++) {
                maxH = max(maxH, segs[j].second);
                if (maxH+ph>BH) { fits=false; break; }
                tx = segs[j].first;
            }
            if (fits && maxH+ph<=BH) {
                int waste = maxH - sh; // how much wasted space under the item
                if (rx<0 || maxH <
