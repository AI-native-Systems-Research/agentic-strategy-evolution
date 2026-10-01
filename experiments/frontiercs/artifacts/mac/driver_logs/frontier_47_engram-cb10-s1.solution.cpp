MY PLAN: Improve the existing best solution by adding a more sophisticated local search phase that removes low-value-density placed items and tries to repack freed space with higher-value items, plus better guillotine-cut strip packing with more combinations, and improved free-rectangle management to handle larger numbers of rectangles efficiently.

```cpp
#include <bits/stdc++.h>
using namespace std;

struct ItemType { string type; int w, h, v, limit; };
struct Placement { string type; int x, y, rot; };
struct Rect { int x, y, w, h; };

static int gW, gH;
static bool gAllowRotate;
static int gM;
static vector<ItemType> items;
static vector<double> density;
static vector<Placement> bestPlacements;
static long long bestProfit = 0;

struct State {
    vector<Rect> freeRects;
    vector<Placement> placements;
    vector<int> used;
    long long totalProfit;
    
    void init() {
        freeRects.clear();
        freeRects.push_back({0, 0, gW, gH});
        used.assign(gM, 0);
        totalProfit = 0;
        placements.clear();
    }
    
    void pruneRects() {
        int n = freeRects.size();
        if (n <= 1) return;
        vector<bool> rem(n, false);
        for (int i = 0; i < n; i++) {
            if (rem[i]) continue;
            for (int j = i+1; j < n; j++) {
                if (rem[j]) continue;
                auto &a = freeRects[i], &b = freeRects[j];
                if (b.x >= a.x && b.y >= a.y && b.x+b.w <= a.x+a.w && b.y+b.h <= a.y+a.h) {
                    rem[j] = true;
                } else if (a.x >= b.x && a.y >= b.y && a.x+a.w <= b.x+b.w && a.y+a.h <= b.y+b.h) {
                    rem[i] = true; break;
                }
            }
        }
        vector<Rect> nr;
        nr.reserve(n);
        for (int i = 0; i < n; i++) if (!rem[i]) nr.push_back(freeRects[i]);
        freeRects = move(nr);
        if ((int)freeRects.size() > 2000) {
            sort(freeRects.begin(), freeRects.end(), [](const Rect& a, const Rect& b) {
                return (long long)a.w * a.h > (long long)b.w * b.h;
            });
            freeRects.resize(2000);
        }
    }
    
    void splitAndUpdate(int px, int py, int pw, int ph) {
        vector<Rect> newRects;
        newRects.reserve(freeRects.size() + 4);
        int pR = px + pw, pT = py + ph;
        for (auto& fr : freeRects) {
            int frR = fr.x + fr.w, frT = fr.y + fr.h;
            if (px >= frR || pR <= fr.x || py >= frT || pT <= fr.y) {
                newRects.push_back(fr);
                continue;
            }
            if (px > fr.x) newRects.push_back({fr.x, fr.y, px - fr.x, fr.h});
            if (pR < frR) newRects.push_back({pR, fr.y, frR - pR, fr.h});
            if (py > fr.y) newRects.push_back({fr.x, fr.y, fr.w, py - fr.y});
            if (pT < frT) newRects.push_back({fr.x, pT, fr.w, frT - pT});
        }
        freeRects = move(newRects);
        pruneRects();
    }
    
    void doPlace(int ti, int ox, int oy, int rot) {
        int rw = (rot == 0) ? items[ti].w : items[ti].h;
        int rh = (rot == 0) ? items[ti].h : items[ti].w;
        placements.push_back({items[ti].type, ox, oy, rot});
        used[ti]++;
        totalProfit += items[ti].v;
        splitAndUpdate(ox, oy, rw, rh);
    }
    
    void updateBest() {
        if (totalProfit > bestProfit) {
            bestProfit = totalProfit;
            bestPlacements = placements;
        }
    }
    
    int contactScore(int ox, int oy, int rw, int rh) {
        int score = 0;
        if (ox == 0) score += rh;
        if (oy == 0) score += rw;
        if (ox + rw == gW) score += rh;
        if (oy + rh == gH) score += rw;
        return score;
    }
    
    tuple<int,int,int> findBestRect(int rw, int rh, int strategy) {
        int bestScore = INT_MIN, ox = -1, oy = -1;
        for (auto& fr : freeRects) {
            if (rw <= fr.w && rh <= fr.h) {
                int score;
                switch(strategy) {
                    case 0: score = -min(fr.w - rw, fr.h - rh); break;
                    case 1: score = -max(fr.w - rw, fr.h - rh); break;
                    case 2: score = -(fr.w * fr.h - rw * rh); break;
                    case 3: score = -(fr.y * 20000 + fr.x); break;
                    case 4: score = contactScore(fr.x, fr.y, rw, rh) * 10000 - min(fr.w - rw, fr.h - rh); break;
                    case 5: score = contactScore(fr.x, fr.y, rw, rh) * 100000 - (fr.w * fr.h - rw * rh); break;
                    case 6: {
                        int exact = 0;
                        if (fr.w == rw) exact++;
                        if (fr.h == rh) exact++;
                        score = exact * 100000 - min(fr.w - rw, fr.h - rh);
                        break;
                    }
                    default: score = -min(fr.w - rw, fr.h - rh); break;
                }
                if (score > bestScore) { bestScore = score; ox = fr.x; oy = fr.y; }
            }
        }
        return {bestScore, ox, oy};
    }
};

void runGreedy(vector<pair<int,int>>& order, int strategy) {
    State state;
    state.init();
    for (auto& [ti, rot] : order) {
        if (state.used[ti] >= items[ti].limit) continue;
        int rw = (rot == 0) ? items[ti].w : items[ti].h;
        int rh = (rot == 0) ? items[ti].h : items[ti].w;
        if (rw > gW || rh > gH) continue;
        auto [sc, ox, oy] = state.findBestRect(rw, rh, strategy);
        if (ox >= 0) state.doPlace(ti, ox, oy, rot);
    }
    state.updateBest();
}

void runSmart(int strategy, double alpha, mt19937* rng = nullptr, double noise = 0.0) {
    State state;
    state.init();
    while (true) {
        int bestTi = -1, bestRot = -1, bestX = -1, bestY = -1;
        double bestEval = -1e18;
        for (int ti = 0; ti < gM; ti++) {
            if (state.used[ti] >= items[ti].limit) continue;
            int nrots = 1;
            if (gAllowRotate && items[ti].w != items[ti].h) nrots = 2;
            for (int rot = 0; rot < nrots; rot++) {
                int rw = (rot == 0) ? items[ti].w : items[ti].h;
                int rh = (rot == 0) ? items[ti].h : items[ti].w;
                if (rw > gW || rh > gH) continue;
                for (auto& fr : state.freeRects) {
                    if (rw <= fr.w && rh <= fr.h) {
                        double fitScore;
                        switch(strategy) {
                            case 0: fitScore = -min(fr.w - rw, fr.h - rh); break;
                            case 1: fitScore = -max(fr.w - rw, fr.h - rh); break;
                            case 2: fitScore = -(double)(fr.w * fr.h - rw * rh); break;
                            case 3: fitScore = -(fr.y * 20000.0 + fr.x); break;
                            case 4: fitScore = state.contactScore(fr.x, fr.y, rw, rh) * 10000.0 - min(fr.w - rw, fr.h - rh); break;
                            default: fitScore = -min(fr.w - rw, fr.h - rh); break;
                        }
                        double normFit = fitScore / (double)(gW + gH);
                        double eval = alpha * density[ti] + (1.0 - alpha) * normFit;
                        if (rng && noise > 0.0) {
                            eval += uniform_real_distribution<double>(-noise, noise)(*rng);
                        }
                        if (eval > bestEval) {
                            bestEval = eval;
                            bestTi = ti; bestRot = rot; bestX = fr.x; bestY = fr.y;
                        }
                    }
                }
            }
        }
        if (bestTi < 0) break;
        state.doPlace(bestTi, bestX, bestY, bestRot);
    }
    state.updateBest();
}

void fillRemaining(State& state) {
    vector<pair<double,int>> densOrder;
    for (int j = 0; j < gM; j++) densOrder.push_back({density[j], j});
    sort(densOrder.begin(), densOrder.end(), greater<>());
    bool changed = true;
    while (changed) {
        changed = false;
        for (auto& [d, tj] : densOrder) {
            if (state.used[tj] >= items[tj].limit) continue;
            int nr2 = 1;
            if (gAllowRotate && items[tj].w != items[tj].h) nr2 = 2;
            for (int r2 = 0; r2 < nr2; r2++) {
                int w2 = (r2 == 0) ? items[tj].w : items[tj].h;
                int h2 = (r2 == 0) ? items[tj].h : items[tj].w;
                if (w2 > gW || h2 > gH) continue;
                bool found = true;
                while (found && state.used[tj] < items[tj].limit) {
                    found = false;
                    auto [sc, bx, by] = state.findBestRect(w2, h2, 0);
                    if (bx >= 0) { state.doPlace(tj, bx, by, r2); found = true; changed = true; }
                }
            }
        }
    }
}

void runStrip() {
    for (int ti = 0; ti < gM; ti++) {
        int nrots = 1;
        if (gAllowRotate && items[ti].w != items[ti].h) nrots = 2;
        for (int rot = 0; rot < nrots; rot++) {
            int rw = (rot == 0) ? items[ti].w : items[ti].h;
            int rh = (rot == 0) ? items[ti].h : items[ti].w;
            if (rw > gW || rh > gH) continue;
            int nx = gW / rw, ny = gH / rh;
            int maxCount = min((long long)nx * ny, (long long)items[ti].limit);
            if (maxCount == 0) continue;
            
            vector<int> counts = {maxCount};
            if (nx * (ny-1) > 0 && nx*(ny-1) != maxCount) counts.push_back(min((long long)nx*(ny-1), (long long)items[ti].limit));
            if (nx > 0 && nx != maxCount) counts.push_back(min((long long)nx, (long long)items[ti].limit));
            
            for (int count : counts) {
                if (count <= 0) continue;
                State state;
                state.init();
                int placed = 0;
                for (int iy = 0; iy < ny && placed < count; iy++)
                    for (int ix = 0; ix < nx && placed < count; ix++, placed++)
                        state.doPlace(ti, ix * rw, iy * rh, rot);
                
                fillRemaining(state);
                state.updateBest();
            }
        }
    }
}

void runDualStrip() {
    if (gM < 2) return;
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
        for(int i=0;i<min((int)di.size(),8);i++) topItems.push_back(di[i].second);
    }
    
    for (int a = 0; a < (int)topItems.size(); a++) {
        int ti = topItems[a];
        int nrots = 1;
        if (gAllowRotate && items[ti].w != items[ti].h) nrots = 2;
        for (int rot = 0; rot < nrots; rot++) {
            int rw = (rot == 0) ? items[ti].w : items[ti].h;
            int rh = (rot == 0) ? items[ti].h : items[ti].w;
            if (rw > gW || rh > gH) continue;
            int nx = gW / rw;
            if (nx == 0) continue;
            int maxRows = gH / rh;
            
            set<int> rowSet;
            rowSet.insert(maxRows);
            if (maxRows > 0) rowSet.insert(maxRows - 1);
            rowSet.insert(maxRows / 2);
            rowSet.insert(1);
            for (int b = 0; b < (int)topItems.size() && b < 6; b++) {
                if (topItems[b] == ti) continue;
                int tj = topItems[b];
                for (int r2 = 0; r2 < (gAllowRotate && items[tj].w != items[tj].h ? 2 : 1); r2++) {
                    int h2 = (r2 == 0) ? items[tj].h : items[tj].w;
                    for (int mr = maxRows; mr >= max(0, maxRows-3); mr--) {
                        int remainH = gH - mr * rh;
                        if (remainH >= h2 && mr > 0) { rowSet.insert(mr); break; }
                    }
                }
            }
            
            for (int rows : rowSet) {
                if (rows <= 0 || rows > maxRows) continue;
                int count = min((long long)rows * nx, (long long)items[ti].limit);
                if (count == 0) continue;
                
                State state;
                state.init();
                int placed = 0;
                for (int iy = 0; iy < rows && placed < count; iy++)
                    for (int ix = 0; ix < nx && placed < count; ix++, placed++)
                        state.doPlace(ti, ix * rw, iy * rh, rot);
                
                fillRemaining(state);
                state.updateBest();
            }
        }
    }
}

// Two-type horizontal strip packing
void runMultiStrip() {
    if (gM < 1) return;
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
        for(int i=0;i<min((int)di.size(),6);i++) topItems.push_back(di[i].second);
    }
    
    for (int ai = 0; ai < (int)topItems.size(); ai++) {
        for (int bi = ai; bi < (int)topItems.size(); bi++) {
            int ta = topItems[ai], tb = topItems[bi];
            int nra = gAllowRotate && items[ta].w != items[ta].h ? 2 : 1;
            int nrb = gAllowRotate && items[tb].w != items[tb].h ? 2 : 1;
            for (int ra = 0; ra < nra; ra++) {
                int ha = (ra == 0) ? items[ta].h : items[ta].w;
                int wa = (ra == 0) ? items[ta].w : items[ta].h;
                if (wa > gW || ha > gH) continue;
                int nxa = gW / wa;
                if (nxa == 0) continue;
                
                for (int rb = 0; rb < nrb; rb++) {
                    int hb = (rb == 0) ? items[tb].h : items[tb].w;
                    int wb = (rb == 0) ? items[tb].w : items[tb].h;
                    if (wb > gW || hb > gH) continue;
                    int nxb = gW / wb;
                    if (nxb == 0) continue;
                    
                    int maxRowsA = min((int)(gH / ha), (int)((long long)items[ta].limit / nxa + 1));
                    maxRowsA = min(maxRowsA, gH / ha);
                    for (int rowsA = 0; rowsA <= maxRowsA; rowsA++) {
                        int remainH = gH - rowsA * ha;
                        int rowsB = remainH / hb;
                        if (ta == tb) {
                            int totalCount = rowsA * nxa + rowsB * nxb;
                            if (totalCount > items[ta].limit) {
                                int excess = totalCount - items[ta].limit;
                                int removeRows = (excess + nxb - 1) / nxb;
                                rowsB = max(0, rowsB - removeRows);
                            }
                        }
                        int countA = min((long long)rowsA * nxa, (long long)items[ta].limit);
                        int countB = min((long long)rowsB * nxb, (long long)items[tb].limit);
                        if (ta == tb) countB = min(countB, items[ta].limit - countA);
                        if (countA + countB == 0) continue;
                        
                        State state;
                        state.init();
                        int placed = 0;
                        for (int iy = 0; iy < rowsA && placed < countA; iy++)
                            for (int ix = 0; ix < nxa && placed < countA; ix++, placed++)
                                state.doPlace(ta, ix * wa, iy * ha, ra);
                        
                        int baseY = rowsA * ha;
                        placed = 0;
                        for (int iy = 0; iy < rowsB && placed < countB; iy++)
                            for (int ix = 0; ix < nxb && placed < countB; ix++, placed++)
                                state.doPlace(tb, ix * wb, baseY + iy * hb, rb);
                        
                        fillRemaining(state);
                        state.updateBest();
                    }
                }
            }
        }
    }
}

// Three-type horizontal strip packing
void runTripleStrip(chrono::steady_clock::time_point t0) {
    if (gM < 3) return;
    auto ms = [&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
        for(int i=0;i<min((int)di.size(),5);i++) topItems.push_back(di[i].second);
    }
    
    for (int ai = 0; ai < (int)topItems.size() && ms() < 350; ai++) {
        for (int bi = ai; bi < (int)topItems.size() && ms() < 350; bi++) {
            for (int ci = bi; ci < (int)topItems.size() && ms() < 350; ci++) {
                int ta = topItems[ai], tb = topItems[bi], tc = topItems[ci];
                // Pick best rotation for each
                auto bestRot = [&](int t) -> pair<int,int> {
                    int best_r = 0;
                    double best_d = -1;
                    int nr = gAllowRotate && items[t].w != items[t].h ? 2 : 1;
                    for (int r = 0; r < nr; r++) {
                        int rw = (r==0)?items[t].w:items[t].h;
                        int rh = (r==0)?items[t].h:items[t].w;
                        if (rw > gW || rh > gH) continue;
                        int nx = gW / rw;
                        if (nx == 0) continue;
                        double d = density[t] * min((long long)nx * (gH/rh), (long long)items[t].limit);
                        if (d > best_d) { best_d = d; best_r = r; }
                    }
                    return {best_r, (int)best_d};
                };
                
                auto [ra, _a] = bestRot(ta);
                auto [rb, _b] = bestRot(tb);
                auto [rc, _c] = bestRot(tc);
                
                int wa = (ra==0)?items[ta].w:items[ta].h, ha = (ra==0)?items[ta].h:items[ta].w;
                int wb = (rb==0)?items[tb].w:items[tb].h, hb = (rb==0)?items[tb].h:items[tb].w;
                int wc = (rc==0)?items[tc].w:items[tc].h, hc = (rc==0)?items[tc].h:items[tc].w;
                
                if (wa > gW || ha > gH) continue;
                if (wb > gW || hb > gH) continue;
                if (wc > gW || hc > gH) continue;
                
                int nxa = gW / wa, nxb = gW / wb, nxc = gW / wc;
                if (nxa == 0 || nxb == 0 || nxc == 0) continue;
                
                int maxRowsA = min(gH / ha, (items[ta].limit + nxa - 1) / nxa);
                for (int rowsA = 0; rowsA <= maxRowsA && ms() < 350; rowsA += max(1, maxRowsA/5)) {
                    int remH1 = gH - rowsA * ha;
                    int maxRowsB = min(remH1 / hb, (items[tb].limit + nxb - 1) / nxb);
                    for (int rowsB = 0; rowsB <= maxRowsB; rowsB += max(1, maxRowsB/5)) {
                        int remH2 = remH1 - rowsB * hb;
                        int rowsC = remH2 / hc;
                        
                        map<int, int> typeCounts;
                        typeCounts[ta] += rowsA * nxa;
                        typeCounts[tb] += rowsB * nxb;
                        typeCounts[tc] += rowsC * nxc;
                        
                        bool valid = true;
                        for (auto& [t, cnt] : typeCounts) {
                            if (cnt > items[t].limit) {
                                valid = false; break;
                            }
                        }
                        if (!valid) continue;
                        
                        State state;
                        state.init();
                        int placed, baseY = 0;
                        
                        int countA = min((int)typeCounts[ta], items[ta].limit);
                        // Actually recount properly
                        int cntA = min(rowsA * nxa, items[ta].limit);
                        placed = 0;
                        for (int iy = 0; iy < rowsA && placed < cntA; iy++)
                            for (int ix = 0; ix < nxa && placed < cntA; ix++, placed++)
                                state.doPlace(ta, ix * wa, baseY + iy * ha, ra);
                        baseY += rowsA * ha;
                        
                        int cntB = min(rowsB * nxb, items[tb].limit - (ta==tb ? state.used[tb] : 0));
                        if (ta == tb) cntB = min(cntB, items[tb].limit - state.used[tb]);
                        placed = 0;
                        for (int iy = 0; iy < rowsB && placed < cntB; iy++)
                            for (int ix = 0; ix < nxb && placed < cntB; ix++, placed++)
                                state.doPlace(tb, ix * wb, baseY + iy * hb, rb);
                        baseY += rowsB * hb;
                        
                        int cntC = min(rowsC * nxc, items[tc].limit - state.used[tc]);
                        placed = 0;
                        for (int iy = 0; iy < rowsC && placed < cntC; iy++)
                            for (int ix = 0; ix < nxc && placed < cntC; ix++, placed++)
                                state.doPlace(tc, ix * wc, baseY + iy * hc, rc);
                        
                        fillRemaining(state);
                        state.updateBest();
                    }
                }
            }
        }
    }
}

// Vertical+horizontal mixed: split bin vertically, fill each half with a strip type
void runVerticalSplit(chrono::steady_clock::time_point t0) {
    auto ms = [&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
        for(int i=0;i<min((int)di.size(),5);i++) topItems.push_back(di[i].second);
    }
    
    for (int ai = 0; ai < (int)topItems.size() && ms() < 450; ai++) {
        for (int bi = 0; bi < (int)topItems.size() && ms() < 450; bi++) {
            int ta = topItems[ai], tb = topItems[bi];
            int nra = gAllowRotate && items[ta].w != items[ta].h ? 2 : 1;
            int nrb = gAllowRotate && items[tb].w != items[tb].h ? 2 : 1;
            for (int ra = 0; ra < nra; ra++) {
                int wa = (ra==0)?items[ta].w:items[ta].h, ha = (ra==0)?items[ta].h:items[ta].w;
                if (wa > gW || ha > gH) continue;
                for (int rb = 0; rb < nrb; rb++) {
                    int wb = (rb==0)?items[tb].w:items[tb].h, hb = (rb==0)?items[tb].h:items[tb].w;
                    if (wb > gW || hb > gH) continue;
                    
                    // Try vertical splits: colsA columns of type A, then remaining for type B
                    int maxColsA = gW / wa;
                    for (int colsA : {maxColsA, maxColsA/2, 1, maxColsA-1}) {
                        if (colsA <= 0 || colsA > maxColsA) continue;
                        int splitX = colsA * wa;
                        int remW = gW - splitX;
                        int colsB = remW / wb;
                        if (colsB <= 0 && remW > 0) continue;
                        
                        int rowsA = gH / ha;
                        int rowsB = gH / hb;
                        
                        int cntA = min((long long)colsA * rowsA, (long long)items[ta].limit);
                        int cntB = min((long long)colsB * rowsB, (long long)items[tb].limit);
                        if (ta == tb) cntB = min(cntB, items[ta].limit - cntA);
                        
                        State state;
                        state.init();
                        int placed = 0;
                        for (int ix = 0; ix < colsA && placed < cntA; ix++)
                            for (int iy = 0; iy < rowsA && placed < cntA; iy++, placed++)
                                state.doPlace(ta, ix * wa, iy * ha, ra);
                        
                        placed = 0
