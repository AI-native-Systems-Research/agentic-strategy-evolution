Looking at my previous solution, I need to identify what's limiting the score. The main issues are:

1. **MaxRects free rectangle limit of 600 is too aggressive** - cutting good placement opportunities
2. **No sophisticated multi-type strip packing** - the two-type grid is limited
3. **No local search/improvement** - items placed greedily are never reconsidered
4. **Rotation choices could be better optimized per-region**
5. **The strip packing doesn't try both horizontal and vertical orientations of the bin**
6. **Need better guillotine/shelf approaches with mixed types per shelf**

Let me implement key improvements:
- Increase free rect capacity and improve pruning
- Add shelf-based packing with per-shelf best-fit
- Add a recursive guillotine cut approach for small subproblems
- Try both W×H and H×W orientations (transposing)
- Better random search with weighted selection by density
- Smarter strip allocation considering limits properly

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
    int maxFree;
    
    void init(int bw, int bh, int mf = 800) {
        freeRects.clear();
        freeRects.push_back({0, 0, bw, bh});
        maxFree = mf;
    }
    
    bool findBestPos(int rw, int rh, int &bx, int &by, int method) {
        bx = by = -1;
        long long bestA = LLONG_MAX, bestB = LLONG_MAX;
        for (int i = 0; i < (int)freeRects.size(); i++) {
            auto &f = freeRects[i];
            if (rw > f.w || rh > f.h) continue;
            long long a, b;
            if (method == 0) { a = min(f.w-rw, f.h-rh); b = max(f.w-rw, f.h-rh); }
            else if (method == 1) { a = (long long)f.w*f.h - (long long)rw*rh; b = min(f.w-rw, f.h-rh); }
            else if (method == 2) { a = f.y; b = f.x; }
            else if (method == 3) { a = f.x; b = f.y; }
            else if (method == 4) { a = f.y + rh; b = min(f.w - rw, f.h - rh); } // BL + best short side
            else { a = -(long long)(min(f.w, f.h)); b = f.y; } // smallest rect first
            if (a < bestA || (a == bestA && b < bestB)) {
                bestA = a; bestB = b; bx = f.x; by = f.y;
            }
        }
        return bx >= 0;
    }
    
    void place(int px, int py, int rw, int rh) {
        vector<Rect> nf;
        nf.reserve(freeRects.size() + 4);
        for (auto &f : freeRects) {
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
        // Remove contained
        vector<bool> rem(n, false);
        // Sort by area descending for faster containment checks
        vector<int> idx(n);
        iota(idx.begin(), idx.end(), 0);
        sort(idx.begin(), idx.end(), [&](int a, int b){
            return (long long)freeRects[a].w * freeRects[a].h > (long long)freeRects[b].w * freeRects[b].h;
        });
        
        for (int ii = 0; ii < n; ii++) {
            int i = idx[ii];
            if (rem[i]) continue;
            for (int jj = ii+1; jj < n; jj++) {
                int j = idx[jj];
                if (rem[j]) continue;
                auto &a = freeRects[i], &b = freeRects[j];
                if (b.x >= a.x && b.y >= a.y && b.x+b.w <= a.x+a.w && b.y+b.h <= a.y+a.h) {
                    rem[j] = true;
                }
            }
        }
        int k = 0;
        for (int i = 0; i < n; i++) if (!rem[i]) freeRects[k++] = freeRects[i];
        freeRects.resize(k);
        
        if ((int)freeRects.size() > maxFree) {
            sort(freeRects.begin(), freeRects.end(), [](const Rect&a, const Rect&b){
                return (long long)a.w*a.h > (long long)b.w*b.h;
            });
            freeRects.resize(maxFree);
        }
    }
};

struct PackState {
    MaxRects mr;
    vector<int> used;
    vector<Placement> placements;
    long long profit;
    int ox, oy; // offset
    
    void init(int bw, int bh, int offx=0, int offy=0, int mf=800) {
        mr.init(bw, bh, mf);
        used.assign(M, 0);
        placements.clear();
        profit = 0;
        ox = offx; oy = offy;
    }
    
    bool tryPlace(int idx, int method) {
        if (used[idx] >= items[idx].limit) return false;
        int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
        int bestPx = -1, bestPy = -1, bestRot = 0;
        long long bA = LLONG_MAX, bB = LLONG_MAX;
        for (int r = 0; r < nrots; r++) {
            int rw = r ? items[idx].h : items[idx].w;
            int rh = r ? items[idx].w : items[idx].h;
            int px, py;
            if (mr.findBestPos(rw, rh, px, py, method)) {
                // Use bottom-left as tiebreaker
                long long a = py, b = px;
                if (a < bA || (a == bA && b < bB)) {
                    bA = a; bB = b; bestPx = px; bestPy = py; bestRot = r;
                }
            }
        }
        if (bestPx >= 0) {
            int rw = bestRot ? items[idx].h : items[idx].w;
            int rh = bestRot ? items[idx].w : items[idx].h;
            mr.place(bestPx, bestPy, rw, rh);
            placements.push_back({items[idx].type, ox+bestPx, oy+bestPy, bestRot});
            used[idx]++;
            profit += items[idx].v;
            return true;
        }
        return false;
    }
};

void fillRegion(int ox, int oy, int rw, int rh, vector<int>& used, 
                vector<Placement>& placements, long long& profit, double timeLimit, int mf=800) {
    if (rw <= 0 || rh <= 0) return;
    MaxRects mr;
    mr.init(rw, rh, mf);
    vector<pair<double,int>> byDens;
    for (int i = 0; i < M; i++) {
        if (used[i] < items[i].limit)
            byDens.push_back({(double)items[i].v / ((double)items[i].w * items[i].h), i});
    }
    sort(byDens.begin(), byDens.end(), greater<>());
    bool prog = true;
    while (prog) {
        if (elapsed() > timeLimit) return;
        prog = false;
        for (auto &[d, idx] : byDens) {
            while (used[idx] < items[idx].limit) {
                if (elapsed() > timeLimit) return;
                int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
                bool placed = false;
                for (int r = 0; r < nrots; r++) {
                    int iw = r ? items[idx].h : items[idx].w;
                    int ih = r ? items[idx].w : items[idx].h;
                    int px, py;
                    if (mr.findBestPos(iw, ih, px, py, 0)) {
                        mr.place(px, py, iw, ih);
                        placements.push_back({items[idx].type, ox+px, oy+py, r});
                        used[idx]++;
                        profit += items[idx].v;
                        placed = true; prog = true;
                        break;
                    }
                }
                if (!placed) break;
            }
        }
    }
}

void greedyMaxRects(int method, const vector<int>& itemOrder, bool exhaustOne, double timeLimit) {
    MaxRects mr;
    mr.init(W, H);
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    if (exhaustOne) {
        for (int idx : itemOrder) {
            if (elapsed() > timeLimit) break;
            int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
            while (used[idx] < items[idx].limit) {
                if (elapsed() > timeLimit) break;
                int bestPx = -1, bestPy = -1, bestRot = 0;
                long long bA = LLONG_MAX, bB = LLONG_MAX;
                for (int r = 0; r < nrots; r++) {
                    int rw = r ? items[idx].h : items[idx].w;
                    int rh = r ? items[idx].w : items[idx].h;
                    int px, py;
                    if (mr.findBestPos(rw, rh, px, py, method)) {
                        long long a = py, b = px;
                        if (a < bA || (a == bA && b < bB)) {
                            bA = a; bB = b; bestPx = px; bestPy = py; bestRot = r;
                        }
                    }
                }
                if (bestPx < 0) break;
                int rw = bestRot ? items[idx].h : items[idx].w;
                int rh = bestRot ? items[idx].w : items[idx].h;
                mr.place(bestPx, bestPy, rw, rh);
                placements.push_back({items[idx].type, bestPx, bestPy, bestRot});
                used[idx]++;
                profit += items[idx].v;
            }
        }
    } else {
        bool progress = true;
        while (progress) {
            if (elapsed() > timeLimit) break;
            progress = false;
            for (int idx : itemOrder) {
                int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
                int bestPx = -1, bestPy = -1, bestRot = 0;
                long long bA = LLONG_MAX, bB = LLONG_MAX;
                for (int r = 0; r < nrots; r++) {
                    int rw = r ? items[idx].h : items[idx].w;
                    int rh = r ? items[idx].w : items[idx].h;
                    int px, py;
                    if (mr.findBestPos(rw, rh, px, py, method)) {
                        long long a = py, b = px;
                        if (a < bA || (a == bA && b < bB)) {
                            bA = a; bB = b; bestPx = px; bestPy = py; bestRot = r;
                        }
                    }
                }
                if (bestPx >= 0 && used[idx] < items[idx].limit) {
                    int rw = bestRot ? items[idx].h : items[idx].w;
                    int rh = bestRot ? items[idx].w : items[idx].h;
                    mr.place(bestPx, bestPy, rw, rh);
                    placements.push_back({items[idx].type, bestPx, bestPy, bestRot});
                    used[idx]++;
                    profit += items[idx].v;
                    progress = true;
                }
            }
        }
    }
    
    // Fill pass with density order
    vector<pair<double,int>> byDens;
    for (int i = 0; i < M; i++) {
        if (used[i] < items[i].limit)
            byDens.push_back({(double)items[i].v / ((double)items[i].w * items[i].h), i});
    }
    sort(byDens.begin(), byDens.end(), greater<>());
    bool prog = true;
    while (prog) {
        if (elapsed() > timeLimit) break;
        prog = false;
        for (auto &[d, idx] : byDens) {
            while (used[idx] < items[idx].limit) {
                if (elapsed() > timeLimit) break;
                int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
                bool placed = false;
                for (int r = 0; r < nrots; r++) {
                    int rw = r ? items[idx].h : items[idx].w;
                    int rh = r ? items[idx].w : items[idx].h;
                    int px, py;
                    if (mr.findBestPos(rw, rh, px, py, method)) {
                        mr.place(px, py, rw, rh);
                        placements.push_back({items[idx].type, px, py, r});
                        used[idx]++;
                        profit += items[idx].v;
                        placed = true; prog = true;
                        break;
                    }
                }
                if (!placed) break;
            }
        }
    }
    
    updateBest(profit, placements);
}

void gridTiling(int primaryIdx, int rot, double timeLimit) {
    int iw = rot ? items[primaryIdx].h : items[primaryIdx].w;
    int ih = rot ? items[primaryIdx].w : items[primaryIdx].h;
    if (iw > W || ih > H) return;
    
    int cols = W / iw;
    int rows = H / ih;
    long long maxPlace = min((long long)cols * rows, (long long)items[primaryIdx].limit);
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
    
    int rightX = cols * iw;
    int topY = rows * ih;
    
    if (rightX < W && topY > 0)
        fillRegion(rightX, 0, W - rightX, topY, used, placements, profit, timeLimit);
    if (elapsed() < timeLimit && topY < H)
        fillRegion(0, topY, W, H - topY, used, placements, profit, timeLimit);
    
    updateBest(profit, placements);
}

// Multi-strip approach: allocate horizontal strips to different item types
void multiStripPack(const vector<pair<int,int>>& allocation, double timeLimit) {
    // allocation: list of (item_idx, rot) in order from bottom to top
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    int pos = 0;
    
    for (auto &[idx, rot] : allocation) {
        if (pos >= H || elapsed() > timeLimit) break;
        int iw = rot ? items[idx].h : items[idx].w;
        int ih = rot ? items[idx].w : items[idx].h;
        if (iw > W || ih > (H - pos)) continue;
        
        int cols = W / iw;
        int avail = items[idx].limit - used[idx];
        if (avail <= 0 || cols <= 0) continue;
        int maxRows = (H - pos) / ih;
        long long totalPlace = min((long long)cols * maxRows, (long long)avail);
        
        int actualRows = (int)((totalPlace + cols - 1) / cols);
        int placed = 0;
        for (int r = 0; r < actualRows && placed < (int)totalPlace; r++) {
            for (int c = 0; c < cols && placed < (int)totalPlace; c++) {
                placements.push_back({items[idx].type, c * iw, pos + r * ih, rot});
                placed++;
            }
        }
        used[idx] += placed;
        profit += (long long)placed * items[idx].v;
        
        int rightX = cols * iw;
        int stripH = actualRows * ih;
        if (rightX < W && stripH > 0 && elapsed() < timeLimit) {
            fillRegion(rightX, pos, W - rightX, stripH, used, placements, profit, timeLimit);
        }
        pos += actualRows * ih;
    }
    
    if (pos < H && elapsed() < timeLimit) {
        fillRegion(0, pos, W, H - pos, used, placements, profit, timeLimit);
    }
    
    updateBest(profit, placements);
}

// Vertical strip packing
void multiStripPackV(const vector<pair<int,int>>& allocation, double timeLimit) {
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    int pos = 0;
    
    for (auto &[idx, rot] : allocation) {
        if (pos >= W || elapsed() > timeLimit) break;
        int iw = rot ? items[idx].h : items[idx].w;
        int ih = rot ? items[idx].w : items[idx].h;
        if (iw > (W - pos) || ih > H) continue;
        
        int rows = H / ih;
        int avail = items[idx].limit - used[idx];
        if (avail <= 0 || rows <= 0) continue;
        int maxCols = (W - pos) / iw;
        long long totalPlace = min((long long)rows * maxCols, (long long)avail);
        
        int actualCols = (int)((totalPlace + rows - 1) / rows);
        int placed = 0;
        for (int c = 0; c < actualCols && placed < (int)totalPlace; c++) {
            for (int r = 0; r < rows && placed < (int)totalPlace; r++) {
                placements.push_back({items[idx].type, pos + c * iw, r * ih, rot});
                placed++;
            }
        }
        used[idx] += placed;
        profit += (long long)placed * items[idx].v;
        
        int topY = rows * ih;
        int stripW = actualCols * iw;
        if (topY < H && stripW > 0 && elapsed() < timeLimit) {
            fillRegion(pos, topY, stripW, H - topY, used, placements, profit, timeLimit);
        }
        pos += actualCols * iw;
    }
    
    if (pos < W && elapsed() < timeLimit) {
        fillRegion(pos, 0, W - pos, H, used, placements, profit, timeLimit);
    }
    
    updateBest(profit, placements);
}

// Optimal strip allocation using DP
// Given a set of item types and a horizontal bin, find the best allocation of rows
void dpStripPack(bool vertical, double timeLimit) {
    // For each item type and rotation, compute: how many fit per row, item height
    struct Config {
        int idx, rot;
        int perRow; // items per row/col
        int stripSize; // height of one row / width of one col  
        long long valPerRow;
        double density;
    };
    
    int binLen = vertical ? W : H; // length along which we stack strips
    int binWid = vertical ? H : W; // width of each strip
    
    vector<Config> configs;
    for (int i = 0; i < M; i++) {
        int nrots = (allowRotate && items[i].w != items[i].h) ? 2 : 1;
        for (int r = 0; r < nrots; r++) {
            int iw, ih;
            if (!vertical) {
                iw = r ? items[i].h : items[i].w;
                ih = r ? items[i].w : items[i].h;
            } else {
                iw = r ? items[i].w : items[i].h;
                ih = r ? items[i].h : items[i].w;
            }
            if (iw > binWid || ih > binLen) continue;
            int perRow = binWid / iw;
            if (perRow == 0) continue;
            configs.push_back({i, r, perRow, ih, (long long)perRow * items[i].v, 
                              (double)items[i].v * perRow / ((double)ih * binWid)});
        }
    }
    
    if (configs.empty()) return;
    
    // Sort by density
    sort(configs.begin(), configs.end(), [](const Config& a, const Config& b){
        return a.density > b.density;
    });
    
    // Greedy: pick best density config, use as many rows as possible, then next
    // Try starting with each config
    for (int startCfg = 0; startCfg < min((int)configs.size(), 6) && elapsed() < timeLimit; startCfg++) {
        vector<pair<int,int>> allocation;
        vector<int> usedCount(M, 0);
        int remaining = binLen;
        
        // First, use startCfg
        {
            auto& c = configs[startCfg];
            int avail = items[c.idx].limit - usedCount[c.idx];
            int maxStrips = remaining / c.stripSize;
            int canUse = min((long long)maxStrips * c.perRow, (long long)avail);
            int strips = (canUse + c.perRow - 1) / c.perRow;
            if (strips > 0) {
                usedCount[c.idx] += strips * c.perRow; // approximate
                remaining -= strips * c.stripSize;
                for (int s = 0; s < strips; s++)
                    allocation.push_back({c.idx, c.rot});
            }
        }
        
        // Fill remaining with best density that fits
        bool progress = true;
        while (remaining > 0 && progress && elapsed() < timeLimit) {
            progress = false;
            for (auto& c : configs) {
                if (c.stripSize > remaining) continue;
                int avail = items[c.idx].limit - usedCount[c.idx];
                if (avail <= 0) continue;
                int maxStrips = remaining / c.stripSize;
                int canUse = min((long long)maxStrips * c.perRow, (long long)avail);
                int strips = (canUse + c.perRow - 1) / c.perRow;
                if (strips > 0) {
                    usedCount[c.idx] += strips * c.perRow;
                    remaining -= strips * c.stripSize;
                    for (int s = 0; s < strips; s++)
                        allocation.push_back({c.idx, c.rot});
                    progress = true;
                    break;
                }
            }
        }
        
        if (!allocation.empty()) {
            if (vertical)
                multiStripPackV(allocation, timeLimit);
            else
                multiStripPack(allocation, timeLimit);
        }
    }
}

// Two-type grid approach
void twoTypeGrid(int p1, int rot1, int p2, int rot2, double timeLimit) {
    int iw1 = rot1 ? items[p1].h : items[p1].w;
    int ih1 = rot1 ? items[p1].w : items[p1].h;
    if (iw1 > W || ih1 > H) return;
    
    int iw2 = rot2 ? items[p2].h : items[p2].w;
    int ih2 = rot2 ? items[p2].w : items[p2].h;
    if (iw2 > W || ih2 > H) return;
    
    int cols1 = W / iw1;
    int cols2 = W / iw2;
    if (cols1 == 0 || cols2 == 0) return;
    
    int maxRows1 = min(H / ih1, (items[p1].limit + cols1 - 1) / cols1);
    
    long long bestLocal = 0;
    vector<Placement> bestLocalPl;
    
    for (int r1 = 0; r1 <= maxRows1 && elapsed() < timeLimit; r1++) {
        int placed1 = min((long long)r1 * cols1, (long long)items[p1].limit);
        long long prof = (long long)placed1 * items[p1].v;
        
        int usedH = r1 * ih1;
        int remH = H - usedH;
        if (remH < 0) break;
        
        int rows2 = remH / ih2;
        int placed2 = min((long long)rows2 * cols2, (long long)items[p2].limit);
        prof += (long long)placed2 * items[p2].v;
        
        if (prof > bestLocal) {
            bestLocal = prof;
            vector<Placement> pl;
            vector<int> used(M, 0);
            long long actualProf = 0;
            
            int p1count = 0;
            for (int r = 0; r < r1 && p1count < placed1; r++) {
                for (int c = 0; c < cols1 && p1count < placed1; c++) {
                    pl.push_back({items[p1].type, c*iw1, r*ih1, rot1});
                    p1count++;
                }
            }
            used[p1] = p1count;
            actualProf = (long long)p1count * items[p1].v;
            
            int p2count = 0;
            for (int r = 0; r < rows2 && p2count < placed2; r++) {
                for (int c = 0; c < cols2 && p2count < placed2; c++) {
                    pl.push_back({items[p2].type, c*iw2, usedH + r*ih2, rot2});
                    p2count++;
                }
            }
            used[p2] = p2count;
            actualProf += (long long)p2count * items[p2].v;
            
            int rightX1 = cols1 * iw1;
            if (rightX1 < W && usedH > 0 && elapsed() < timeLimit)
                fillRegion(rightX1, 0, W - rightX1, usedH, used, pl, actualProf, timeLimit);
            
            int rightX2 = cols2 * iw2;
            int usedH2 = rows2 * ih2;
            if (rightX2 < W && usedH2 > 0 && elapsed() < timeLimit)
                fillRegion(rightX2, usedH, W - rightX2, usedH2, used, pl, actualProf, timeLimit);
            
            int topY = usedH + usedH2;
            if (topY < H && elapsed() < timeLimit)
                fillRegion(0, topY, W, H - topY, used, pl, actualProf, timeLimit);
            
            bestLocalPl = pl;
            bestLocal = actualProf;
        }
    }
    
    if (!bestLocalPl.empty())
        updateBest(best
