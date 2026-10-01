MY PLAN: Improve the existing best solution by adding a more sophisticated local search phase that removes low-value-density items from the best solution found so far and attempts to repack the freed space with higher-value items, plus add column-generation style strip packing where we try all combinations of 2-3 top items filling horizontal/vertical strips with optimal row counts determined by value maximization.

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

void fillRemainingMultiStrat(State& state) {
    // Try multiple placement strategies for filling
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
                    // Try multiple strategies, pick best position
                    for (int strat = 0; strat < 7; strat++) {
                        auto [sc, bx, by] = state.findBestRect(w2, h2, strat);
                        if (bx >= 0) { state.doPlace(tj, bx, by, r2); found = true; changed = true; break; }
                    }
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
            
            int maxRows = gH / rh;
            int nx = gW / rw;
            if (nx == 0) continue;
            
            set<int> rowSet;
            rowSet.insert(maxRows);
            if (maxRows > 0) rowSet.insert(maxRows - 1);
            rowSet.insert(maxRows / 2);
            rowSet.insert(1);
            for (int b = 0; b < (int)topItems.size() && b < 4; b++) {
                if (topItems[b] == ti) continue;
                int tj = topItems[b];
                for (int r2 = 0; r2 < (gAllowRotate && items[tj].w != items[tj].h ? 2 : 1); r2++) {
                    int h2 = (r2 == 0) ? items[tj].h : items[tj].w;
                    int neededRows = maxRows;
                    while (neededRows > 0 && gH - neededRows * rh < h2) neededRows--;
                    if (neededRows > 0 && neededRows != maxRows) rowSet.insert(neededRows);
                }
            }
            
            for (int rows : rowSet) {
                if (rows <= 0 || rows > maxRows) continue;
                int count = min((long long)nx * rows, (long long)items[ti].limit);
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

void runMultiStrip() {
    if (gM < 1) return;
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
        for(int i=0;i<min((int)di.size(),5);i++) topItems.push_back(di[i].second);
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

// Three-item strip packing
void runTripleStrip(chrono::steady_clock::time_point t0, int timeLimit) {
    if (gM < 3) return;
    auto ms = [&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
        for(int i=0;i<min((int)di.size(),4);i++) topItems.push_back(di[i].second);
    }
    
    for (int ai = 0; ai < (int)topItems.size() && ms() < timeLimit; ai++) {
        for (int bi = ai; bi < (int)topItems.size() && ms() < timeLimit; bi++) {
            for (int ci = bi; ci < (int)topItems.size() && ms() < timeLimit; ci++) {
                int ta = topItems[ai], tb = topItems[bi], tc = topItems[ci];
                
                int nra = gAllowRotate && items[ta].w != items[ta].h ? 2 : 1;
                for (int ra = 0; ra < nra && ms() < timeLimit; ra++) {
                    int ha = (ra == 0) ? items[ta].h : items[ta].w;
                    int wa = (ra == 0) ? items[ta].w : items[ta].h;
                    if (wa > gW || ha > gH) continue;
                    int nxa = gW / wa;
                    if (nxa == 0) continue;
                    
                    int nrb = gAllowRotate && items[tb].w != items[tb].h ? 2 : 1;
                    for (int rb = 0; rb < nrb && ms() < timeLimit; rb++) {
                        int hb = (rb == 0) ? items[tb].h : items[tb].w;
                        int wb = (rb == 0) ? items[tb].w : items[tb].h;
                        if (wb > gW || hb > gH) continue;
                        int nxb = gW / wb;
                        if (nxb == 0) continue;
                        
                        int nrc = gAllowRotate && items[tc].w != items[tc].h ? 2 : 1;
                        for (int rc = 0; rc < nrc && ms() < timeLimit; rc++) {
                            int hc = (rc == 0) ? items[tc].h : items[tc].w;
                            int wc = (rc == 0) ? items[tc].w : items[tc].h;
                            if (wc > gW || hc > gH) continue;
                            int nxc = gW / wc;
                            if (nxc == 0) continue;
                            
                            int maxRowsA = min(gH / ha, items[ta].limit / nxa + 1);
                            maxRowsA = min(maxRowsA, gH / ha);
                            // Sample some row counts for A
                            vector<int> rowsAList;
                            for (int r = 0; r <= maxRowsA; r++) rowsAList.push_back(r);
                            if ((int)rowsAList.size() > 10) {
                                vector<int> sampled;
                                sampled.push_back(0);
                                for (int k = 1; k <= 8; k++) sampled.push_back(min(maxRowsA, maxRowsA * k / 8));
                                sampled.push_back(maxRowsA);
                                sort(sampled.begin(), sampled.end());
                                sampled.erase(unique(sampled.begin(), sampled.end()), sampled.end());
                                rowsAList = sampled;
                            }
                            
                            for (int rowsA : rowsAList) {
                                if (ms() >= timeLimit) break;
                                int usedH_A = rowsA * ha;
                                if (usedH_A > gH) continue;
                                int countA = min(rowsA * nxa, items[ta].limit);
                                
                                int remainH1 = gH - usedH_A;
                                int maxRowsB = remainH1 / hb;
                                // Sample B rows
                                vector<int> rowsBList;
                                for (int r = 0; r <= maxRowsB; r++) rowsBList.push_back(r);
                                if ((int)rowsBList.size() > 6) {
                                    vector<int> sampled;
                                    sampled.push_back(0);
                                    for (int k = 1; k <= 4; k++) sampled.push_back(min(maxRowsB, maxRowsB * k / 4));
                                    sampled.push_back(maxRowsB);
                                    sort(sampled.begin(), sampled.end());
                                    sampled.erase(unique(sampled.begin(), sampled.end()), sampled.end());
                                    rowsBList = sampled;
                                }
                                
                                for (int rowsB : rowsBList) {
                                    if (ms() >= timeLimit) break;
                                    int usedH_B = rowsB * hb;
                                    int remainH2 = remainH1 - usedH_B;
                                    if (remainH2 < 0) continue;
                                    int rowsC = remainH2 / hc;
                                    
                                    int countB = min(rowsB * nxb, items[tb].limit);
                                    int countC = min(rowsC * nxc, items[tc].limit);
                                    
                                    // Handle same-type overlaps
                                    if (ta == tb) countB = min(countB, items[ta].limit - countA);
                                    if (ta == tc) countC = min(countC, items[ta].limit - countA - (ta==tb?countB:0));
                                    if (tb == tc && tb != ta) countC = min(countC, items[tb].limit - countB);
                                    
                                    if (countA + countB + countC == 0) continue;
                                    
                                    State state;
                                    state.init();
                                    int placed = 0;
                                    for (int iy = 0; iy < rowsA && placed < countA; iy++)
                                        for (int ix = 0; ix < nxa && placed < countA; ix++, placed++)
                                            state.doPlace(ta, ix * wa, iy * ha, ra);
                                    
                                    int baseY = usedH_A;
                                    placed = 0;
                                    for (int iy = 0; iy < rowsB && placed < countB; iy++)
                                        for (int ix = 0; ix < nxb && placed < countB; ix++, placed++)
                                            state.doPlace(tb, ix * wb, baseY + iy * hb, rb);
                                    
                                    baseY += usedH_B;
                                    placed = 0;
                                    for (int iy = 0; iy < rowsC && placed < countC; iy++)
                                        for (int ix = 0; ix < nxc && placed < countC; ix++, placed++)
                                            state.doPlace(tc, ix * wc, baseY + iy * hc, rc);
                                    
                                    fillRemaining(state);
                                    state.updateBest();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// Vertical strip approach: divide bin into vertical strips
void runVerticalStrip(chrono::steady_clock::time_point t0, int timeLimit) {
    auto ms = [&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    
    vector<int> topItems;
    {
        vector<pair<double,int>> di;
        for(int i=0;i<gM;i++) di.push_back({density[i],i});
        sort(di.begin(),di.end(),greater<>());
