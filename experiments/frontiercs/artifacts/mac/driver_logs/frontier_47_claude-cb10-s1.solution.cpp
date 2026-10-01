Looking at the previous solution, I can identify several areas for improvement:

1. **MaxRects pruning is O(n²)** which becomes very slow as free rectangles grow, limiting the number of items we can place
2. **No skyline-based packing** which is often superior for grid-like placements
3. **Strip packing doesn't consider mixing types** within remaining space efficiently
4. **No attempt at guillotine-cut based recursive packing** for better space utilization
5. **Time management** could be better - we should spend more time on promising approaches

Key improvements:
- Implement a faster skyline bottom-left packer
- Better MaxRects with more efficient pruning
- Try all single-type tilings (which can be very effective for high-density items)
- Implement a hybrid approach: tile the best density items first in a grid, then fill remaining with MaxRects
- Add more diverse random restarts with weighted selection toward high-value items

```cpp
#include <bits/stdc++.h>
using namespace std;

static auto startTime = chrono::steady_clock::now();
static double elapsed() {
    return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
}

struct Item { string type; int w, h; long long v; int limit; };
struct Placement { string type; int x, y, rot; };

int W, H, M;
bool allowRotate;
vector<Item> items;
long long bestProfit = 0;
vector<Placement> bestPlacements;

void updateBest(long long profit, const vector<Placement>& pl) {
    if (profit > bestProfit) {
        bestProfit = profit;
        bestPlacements = pl;
    }
}

struct Rect { int x, y, w, h; };

struct MaxRects {
    vector<Rect> freeRects;
    int binW, binH;
    
    void init(int bw, int bh) {
        binW = bw; binH = bh;
        freeRects.clear();
        freeRects.push_back({0, 0, bw, bh});
    }
    
    // method: 0=BSSF, 1=BAF, 2=BL, 3=BLx
    int findPos(int rw, int rh, int &bx, int &by, int method) {
        bx = by = -1;
        long long bestA = LLONG_MAX, bestB = LLONG_MAX;
        int bestIdx = -1;
        for (int fi = 0; fi < (int)freeRects.size(); fi++) {
            auto &f = freeRects[fi];
            if (rw > f.w || rh > f.h) continue;
            long long a, b;
            if (method == 0) { a = min(f.w-rw, f.h-rh); b = max(f.w-rw, f.h-rh); }
            else if (method == 1) { a = (long long)f.w*f.h - (long long)rw*rh; b = min(f.w-rw, f.h-rh); }
            else if (method == 2) { a = f.y; b = f.x; }
            else { a = f.x; b = f.y; }
            if (a < bestA || (a == bestA && b < bestB)) {
                bestA = a; bestB = b; bx = f.x; by = f.y; bestIdx = fi;
            }
        }
        return bestIdx;
    }
    
    void place(int px, int py, int rw, int rh) {
        int n = freeRects.size();
        vector<Rect> nf;
        nf.reserve(n + n/2);
        for (int i = 0; i < n; i++) {
            auto &f = freeRects[i];
            if (px >= f.x+f.w || px+rw <= f.x || py >= f.y+f.h || py+rh <= f.y) {
                nf.push_back(f); continue;
            }
            if (px > f.x) nf.push_back({f.x, f.y, px-f.x, f.h});
            if (px+rw < f.x+f.w) nf.push_back({px+rw, f.y, f.x+f.w-px-rw, f.h});
            if (py > f.y) nf.push_back({f.x, f.y, f.w, py-f.y});
            if (py+rh < f.y+f.h) nf.push_back({f.x, py+rh, f.w, f.y+f.h-py-rh});
        }
        freeRects = nf;
        prune();
    }
    
    void prune() {
        int n = freeRects.size();
        if (n <= 1) return;
        vector<bool> rem(n, false);
        // Sort by area descending for faster pruning
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
        int k = 0;
        for (int i = 0; i < n; i++) if (!rem[i]) freeRects[k++] = freeRects[i];
        freeRects.resize(k);
    }
};

// Grid tiling: fill as much as possible with a single item type in a grid pattern,
// then fill remaining with other items
void gridTiling(int primaryIdx, int rot, const vector<int>& fillOrder) {
    int iw = rot ? items[primaryIdx].h : items[primaryIdx].w;
    int ih = rot ? items[primaryIdx].w : items[primaryIdx].h;
    if (iw > W || ih > H) return;
    
    int cols = W / iw;
    int rows = H / ih;
    int maxPlace = min((long long)cols * rows, (long long)items[primaryIdx].limit);
    if (maxPlace == 0) return;
    
    vector<Placement> placements;
    long long profit = 0;
    vector<int> used(M, 0);
    
    int placed = 0;
    for (int r = 0; r < rows && placed < maxPlace; r++) {
        for (int c = 0; c < cols && placed < maxPlace; c++) {
            placements.push_back({items[primaryIdx].type, c*iw, r*ih, rot});
            placed++;
        }
    }
    used[primaryIdx] = placed;
    profit = (long long)placed * items[primaryIdx].v;
    
    // Remaining areas: right strip and top strip
    // Right strip: x from cols*iw to W, y from 0 to rows*ih
    // Top strip: x from 0 to W, y from rows*ih to H
    // Bottom-right corner counted in top strip
    
    int rightX = cols * iw;
    int topY = rows * ih;
    int rightW = W - rightX;
    int topH = H - topY;
    
    auto fillRegion = [&](int ox, int oy, int rw, int rh) {
        if (rw <= 0 || rh <= 0) return;
        MaxRects mr;
        mr.init(rw, rh);
        
        bool prog = true;
        while (prog) {
            if (elapsed() > 0.9) return;
            prog = false;
            for (int idx : fillOrder) {
                while (used[idx] < items[idx].limit) {
                    int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
                    bool found = false;
                    for (int r2 = 0; r2 < nrots; r2++) {
                        int pw = r2 ? items[idx].h : items[idx].w;
                        int ph = r2 ? items[idx].w : items[idx].h;
                        if (pw > rw || ph > rh) continue;
                        int px, py;
                        if (mr.findPos(pw, ph, px, py, 0) >= 0) {
                            mr.place(px, py, pw, ph);
                            placements.push_back({items[idx].type, ox+px, oy+py, r2});
                            used[idx]++;
                            profit += items[idx].v;
                            found = true; prog = true;
                            break;
                        }
                    }
                    if (!found) break;
                }
            }
        }
    };
    
    fillRegion(rightX, 0, rightW, rows * ih);
    fillRegion(0, topY, W, topH);
    
    updateBest(profit, placements);
}

// Multi-type grid: allocate horizontal strips to different item types
void multiStripPack(const vector<int>& typeOrder, bool horizontal) {
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    int maxDim = horizontal ? H : W;
    int crossDim = horizontal ? W : H;
    int pos = 0;
    
    for (int idx : typeOrder) {
        if (pos >= maxDim) break;
        if (used[idx] >= items[idx].limit) continue;
        
        // Try both rotations, pick the one that gives better value
        int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
        
        long long bestVal = 0;
        int bestRot = 0, bestRows = 0, bestCols = 0, bestIw = 0, bestIh = 0;
        
        for (int r = 0; r < nrots; r++) {
            int iw, ih;
            if (horizontal) {
                iw = r ? items[idx].h : items[idx].w;
                ih = r ? items[idx].w : items[idx].h;
            } else {
                iw = r ? items[idx].w : items[idx].h;
                ih = r ? items[idx].h : items[idx].w;
            }
            if (ih <= 0 || pos + ih > maxDim || iw <= 0 || iw > crossDim) continue;
            int nCols = crossDim / iw;
            int avail = items[idx].limit - used[idx];
            int maxRows = (maxDim - pos) / ih;
            int totalFit = min((long long)nCols * maxRows, (long long)avail);
            long long val = (long long)totalFit * items[idx].v;
            if (val > bestVal) {
                bestVal = val;
                bestRot = r;
                bestCols = nCols;
                bestRows = (totalFit + nCols - 1) / nCols;
                bestIw = iw;
                bestIh = ih;
            }
        }
        
        if (bestVal == 0) continue;
        
        int totalFit = min((long long)bestCols * bestRows, (long long)(items[idx].limit - used[idx]));
        int placed = 0;
        for (int row = 0; row < bestRows && placed < totalFit; row++) {
            for (int col = 0; col < bestCols && placed < totalFit; col++) {
                int px, py;
                if (horizontal) { px = col * bestIw; py = pos + row * bestIh; }
                else { px = pos + row * bestIh; py = col * bestIw; }
                placements.push_back({items[idx].type, px, py, bestRot});
                placed++;
            }
        }
        used[idx] += placed;
        profit += (long long)placed * items[idx].v;
        pos += bestRows * bestIh;
    }
    
    // Fill remaining with MaxRects
    if (pos < maxDim) {
        int ox, oy, rw, rh;
        if (horizontal) { ox = 0; oy = pos; rw = W; rh = H - pos; }
        else { ox = pos; oy = 0; rw = W - pos; rh = H; }
        
        if (rw > 0 && rh > 0) {
            MaxRects mr;
            mr.init(rw, rh);
            
            vector<pair<double,int>> byDens;
            for (int i = 0; i < M; i++) {
                if (used[i] < items[i].limit)
                    byDens.push_back({(double)items[i].v / ((double)items[i].w * items[i].h), i});
            }
            sort(byDens.begin(), byDens.end(), greater<>());
            
            bool prog = true;
            while (prog) {
                if (elapsed() > 0.9) break;
                prog = false;
                for (auto &[d, idx2] : byDens) {
                    while (used[idx2] < items[idx2].limit) {
                        int nrots2 = (allowRotate && items[idx2].w != items[idx2].h) ? 2 : 1;
                        bool found = false;
                        for (int r2 = 0; r2 < nrots2; r2++) {
                            int pw = r2 ? items[idx2].h : items[idx2].w;
                            int ph = r2 ? items[idx2].w : items[idx2].h;
                            if (pw > rw || ph > rh) continue;
                            int px, py;
                            if (mr.findPos(pw, ph, px, py, 0) >= 0) {
                                mr.place(px, py, pw, ph);
                                placements.push_back({items[idx2].type, ox+px, oy+py, r2});
                                used[idx2]++;
                                profit += items[idx2].v;
                                found = true; prog = true;
                                break;
                            }
                        }
                        if (!found) break;
                    }
                }
            }
        }
    }
    
    // Also fill cross-strip gaps (right side of each strip)
    // This is handled implicitly by the MaxRects fill above for the bottom region
    // For strip side gaps, let's do another pass
    
    updateBest(profit, placements);
}

void greedyMaxRects(int method, const vector<int>& itemOrder, bool exhaustOne) {
    MaxRects mr;
    mr.init(W, H);
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    auto tryPlace = [&](int idx) -> bool {
        if (used[idx] >= items[idx].limit) return false;
        int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
        int bestPx = -1, bestPy = -1, bestRot = 0;
        long long bestFitA = LLONG_MAX, bestFitB = LLONG_MAX;
        for (int r = 0; r < nrots; r++) {
            int rw = r ? items[idx].h : items[idx].w;
            int rh = r ? items[idx].w : items[idx].h;
            if (rw > W || rh > H) continue;
            int px, py;
            if (mr.findPos(rw, rh, px, py, method) >= 0) {
                long long fa, fb;
                if (method == 0) { fa = py; fb = px; }
                else if (method == 1) { fa = py; fb = px; }
                else { fa = py; fb = px; }
                if (fa < bestFitA || (fa == bestFitA && fb < bestFitB)) {
                    bestFitA = fa; bestFitB = fb;
                    bestPx = px; bestPy = py; bestRot = r;
                }
            }
        }
        if (bestPx >= 0) {
            int rw = bestRot ? items[idx].h : items[idx].w;
            int rh = bestRot ? items[idx].w : items[idx].h;
            mr.place(bestPx, bestPy, rw, rh);
            placements.push_back({items[idx].type, bestPx, bestPy, bestRot});
            used[idx]++;
            profit += items[idx].v;
            return true;
        }
        return false;
    };
    
    if (exhaustOne) {
        for (int idx : itemOrder) {
            if (elapsed() > 0.88) break;
            while (tryPlace(idx)) {
                if (elapsed() > 0.88) break;
            }
        }
    } else {
        bool progress = true;
        while (progress) {
            if (elapsed() > 0.88) break;
            progress = false;
            for (int idx : itemOrder) {
                if (tryPlace(idx)) progress = true;
            }
        }
    }
    
    // Fill remaining gaps with density-ordered items
    {
        vector<pair<double,int>> byDens;
        for (int i = 0; i < M; i++) {
            if (used[i] < items[i].limit)
                byDens.push_back({(double)items[i].v / ((double)items[i].w * items[i].h), i});
        }
        sort(byDens.begin(), byDens.end(), greater<>());
        bool prog = true;
        while (prog) {
            if (elapsed() > 0.9) break;
            prog = false;
            for (auto &[d, idx] : byDens) {
                while (used[idx] < items[idx].limit) {
                    if (!tryPlace(idx)) break;
                    else prog = true;
                }
            }
        }
    }
    
    updateBest(profit, placements);
}

// Two-phase: pick top-K item types by adjusted value, grid-pack them, fill rest
void twoPhaseGridPack(const vector<int>& primaryTypes, const vector<int>& fillOrder) {
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    // Use full MaxRects for everything but try to place primary types first in bulk
    MaxRects mr;
    mr.init(W, H);
    
    for (int idx : primaryTypes) {
        if (elapsed() > 0.88) break;
        while (used[idx] < items[idx].limit) {
            int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
            bool found = false;
            for (int r = 0; r < nrots; r++) {
                int rw = r ? items[idx].h : items[idx].w;
                int rh = r ? items[idx].w : items[idx].h;
                if (rw > W || rh > H) continue;
                int px, py;
                if (mr.findPos(rw, rh, px, py, 2) >= 0) {
                    mr.place(px, py, rw, rh);
                    placements.push_back({items[idx].type, px, py, r});
                    used[idx]++;
                    profit += items[idx].v;
                    found = true;
                    break;
                }
            }
            if (!found) break;
        }
    }
    
    // Fill remaining
    bool prog = true;
    while (prog) {
        if (elapsed() > 0.9) break;
        prog = false;
        for (int idx : fillOrder) {
            while (used[idx] < items[idx].limit) {
                int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
                bool found = false;
                for (int r = 0; r < nrots; r++) {
                    int rw = r ? items[idx].h : items[idx].w;
                    int rh = r ? items[idx].w : items[idx].h;
                    if (rw > W || rh > H) continue;
                    int px, py;
                    if (mr.findPos(rw, rh, px, py, 0) >= 0) {
                        mr.place(px, py, rw, rh);
                        placements.push_back({items[idx].type, px, py, r});
                        used[idx]++;
                        profit += items[idx].v;
                        found = true; prog = true;
                        break;
                    }
                }
                if (!found) break;
            }
        }
    }
    
    updateBest(profit, placements);
}

// Skyline bottom-left packer
struct Skyline {
    struct Seg { int x, w, y; };
    vector<Seg> segs;
    int binW, binH;
    
    void init(int bw, int bh) {
        binW = bw; binH = bh;
        segs.clear();
        segs.push_back({0, bw, 0});
    }
    
    bool findPos(int rw, int rh, int &bx, int &by) {
        bx = by = -1;
        int bestWaste = INT_MAX;
        
        for (int i = 0; i < (int)segs.size(); i++) {
            int y = segs[i].y;
            if (y + rh > binH) continue;
            
            // Check if item fits starting from segment i
            int remainW = rw;
            int maxY = y;
            int j = i;
            bool fits = true;
            while (remainW > 0 && j < (int)segs.size()) {
                maxY = max(maxY, segs[j].y);
                if (maxY + rh > binH) { fits = false; break; }
                remainW -= segs[j].w;
                j++;
            }
            if (!fits || remainW > 0) continue;
            // remainW <= 0 means it fits
            
            int x = segs[i].x;
            if (x + rw > binW) continue;
            
            int waste = (maxY - y) * rw; // approximate waste
            if (bx < 0 || maxY < by || (maxY == by && x < bx)) {
                bx = x; by = maxY;
            }
        }
        return bx >= 0;
    }
    
    void place(int px, int py, int rw, int rh) {
        // Add the placed rect to the skyline
        int newY = py + rh;
        
        vector<Seg> newSegs;
        for (int i = 0; i < (int)segs.size(); i++) {
            int sx = segs[i].x;
            int sw = segs[i].w;
            int sy = segs[i].y;
            int se = sx + sw;
            
            if (se <= px || sx >= px + rw) {
                newSegs.push_back(segs[i]);
            } else {
                // This segment overlaps with placement
                if (sx < px) {
                    newSegs.push_back({sx, px - sx, sy});
                }
                // The overlapping part gets raised
                int overlapStart = max(sx, px);
                int overlapEnd = min(se, px + rw);
                newSegs.push_back({overlapStart, overlapEnd - overlapStart, newY});
                if (se > px + rw) {
                    newSegs.push_back({px + rw, se - (px + rw), sy});
                }
            }
        }
        
        // Merge adjacent segments with same y
        segs.clear();
        for (auto &s : newSegs) {
            if (!segs.empty() && segs.back().y == s.y && segs.back().x + segs.back().w == s.x) {
                segs.back().w += s.w;
            } else {
                segs.push_back(s);
            }
        }
    }
};

void skylinePack(const vector<int>& itemOrder, bool exhaustOne) {
    Skyline sl;
    sl.init(W, H);
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    auto tryPlace = [&](int idx) -> bool {
        if (used[idx] >= items[idx].limit) return false;
        int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
        int bestPx = -1, bestPy = -1, bestRot = 0;
        for (int r = 0; r < nrots; r++) {
            int rw = r ? items[idx].h : items[idx].w;
            int rh = r ? items[idx].w : items[idx].h;
            if (rw > W || rh > H) continue;
            int px, py;
            if (sl.findPos(rw, rh, px, py)) {
                if (bestPx < 0 || py < bestPy || (py == bestPy && px < bestPx)) {
                    bestPx = px; bestPy = py; bestRot = r;
                }
            }
        }
        if (bestPx >= 0) {
            int rw = bestRot ? items[idx].h : items[idx].w;
            int rh = bestRot ? items[idx].w : items[idx].h;
            sl.place(bestPx, bestPy, rw, rh);
            placements.push_back({items[idx].type, bestPx, bestPy, bestRot});
            used[idx]++;
            profit += items[idx].v;
            return true;
        }
        return false;
    };
    
    if (exhaustOne) {
        for (int idx : itemOrder) {
            if (elapsed() > 0.88) break;
            while (tryPlace(idx)) { if (elapsed() > 0.88) break; }
        }
    } else {
        bool progress = true;
        while (progress) {
            if (elapsed() > 0.88) break;
            progress = false;
            for (int idx : itemOrder) {
                if (tryPlace(idx)) progress = true;
            }
        }
    }
    
    // Fill remaining
    vector<pair<double,int>> byDens;
    for (int i = 0; i < M; i++) {
        if (used[i] < items[i].limit)
            byDens.push_back({(double)items[i].v / ((double)items[i].w * items[i].h), i});
    }
    sort(byDens.begin(), byDens.end(), greater<>());
    bool prog = true;
    while (prog) {
        if (elapsed() > 0.9) break;
        prog = false;
        for (auto &[d, idx] : byDens) {
            while (used[idx] < items[idx].limit) {
                if (!tryPlace(idx)) break;
                else prog = true;
            }
        }
    }
    
    updateBest(profit, placements);
}

// Guillotine cut approach: divide bin into strips for different items
void guillotineMixedStrips(const vector<pair<int,int>>& allocation) {
    // allocation: list of (itemIdx, rot) with allocated strip heights
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    int pos = 0;
    
    for (auto &[idx, rot] : allocation) {
        if (pos >= H) break;
        int iw = rot ? items[idx].h : items[idx].w;
        int ih = rot ? items[idx].w : items[idx].h;
        if (iw > W || ih > (H - pos)) continue;
        
        int cols = W / iw;
        int avail = items[idx].limit - used[idx];
        if (avail <= 0) continue;
        int rows = min((H - pos) / ih, (avail + cols - 1) / cols);
        int totalPlace = min(rows * cols, avail);
        
        int placed = 0;
        for (int r = 0; r < rows && placed < totalPlace; r++) {
            for (int c = 0; c < cols && placed < totalPlace; c++) {
                placements.push_back({items[idx].type, c * iw, pos + r * ih, rot});
                placed++;
            }
        }
        used[idx] += placed;
        profit += (long long)placed * items[idx].v;
        pos += rows * ih;
    }
    
    // Fill remaining with MaxRects
    if (pos < H) {
        MaxRects mr;
        mr.init(W, H - pos);
        
        vector<pair<double,int>> byDens;
        for (int i = 0; i < M; i++) {
            if (used[i] < items[i].limit)
                byDens.push_back({(double)items[i].v / ((double)items[i].w * items[i].h), i});
        }
        sort(byDens.begin(), byDens.end(), greater<>());
        
        bool prog = true;
        while (prog) {
            if (elapsed() > 0.9) break;
            prog = false;
            for (auto &[d, idx2] : byDens) {
                while (used[idx2] < items[idx2].limit) {
                    int nrots2 = (allowRotate && items[idx2].w != items[idx2].h) ? 2 : 1;
                    bool found = false;
                    for (int r2 = 0; r2 < nrots2; r2++) {
                        int pw = r2 ? items[idx2].h : items[idx2].w
