Looking at the previous submission, it was literally cut off mid-code (ends with `double time`) and had the C++ code nested inside a markdown explanation, causing a parse error. I need to write a complete, well-structured solution.

My approach:
1. Parse JSON input properly
2. Implement multiple packing strategies: grid tiling, strip packing, MaxRects with various heuristics
3. Try many orderings and combinations within the time budget
4. Output the best result found

```cpp
#include <bits/stdc++.h>
using namespace std;

static auto startTime = chrono::steady_clock::now();
static double elapsed() {
    return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
}

int W, H, M;
bool allowRotate;

struct Item { string type; int w, h; long long v; int limit; };
struct Placement { string type; int x, y, rot; };
struct Rect { int x, y, w, h; };

vector<Item> items;
long long bestProfit = 0;
vector<Placement> bestPlacements;

void updateBest(long long profit, const vector<Placement>& pl) {
    if (profit > bestProfit) {
        bestProfit = profit;
        bestPlacements = pl;
    }
}

struct MaxRects {
    vector<Rect> freeRects;
    int maxFree;
    
    void init(int bw, int bh, int mf = 500) {
        freeRects.clear();
        freeRects.push_back({0, 0, bw, bh});
        maxFree = mf;
    }
    
    bool findBestPos(int rw, int rh, int &bx, int &by, int method) {
        bx = by = -1;
        long long bestA = LLONG_MAX, bestB = LLONG_MAX;
        for (auto &f : freeRects) {
            if (rw > f.w || rh > f.h) continue;
            long long a, b;
            if (method == 0) { a = min(f.w - rw, f.h - rh); b = max(f.w - rw, f.h - rh); }
            else if (method == 1) { a = (long long)f.w * f.h - (long long)rw * rh; b = min(f.w - rw, f.h - rh); }
            else if (method == 2) { a = f.y; b = f.x; }
            else { a = f.x; b = f.y; }
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
            if (px >= f.x + f.w || px + rw <= f.x || py >= f.y + f.h || py + rh <= f.y) {
                nf.push_back(f); continue;
            }
            if (px > f.x) nf.push_back({f.x, f.y, px - f.x, f.h});
            if (px + rw < f.x + f.w) nf.push_back({px + rw, f.y, f.x + f.w - px - rw, f.h});
            if (py > f.y) nf.push_back({f.x, f.y, f.w, py - f.y});
            if (py + rh < f.y + f.h) nf.push_back({f.x, py + rh, f.w, f.y + f.h - py - rh});
        }
        freeRects = nf;
        prune();
    }
    
    void prune() {
        int n = freeRects.size();
        vector<bool> rem(n, false);
        for (int i = 0; i < n; i++) {
            if (rem[i]) continue;
            for (int j = 0; j < n; j++) {
                if (i == j || rem[j]) continue;
                if (freeRects[j].x >= freeRects[i].x && freeRects[j].y >= freeRects[i].y &&
                    freeRects[j].x + freeRects[j].w <= freeRects[i].x + freeRects[i].w &&
                    freeRects[j].y + freeRects[j].h <= freeRects[i].y + freeRects[i].h) {
                    rem[j] = true;
                }
            }
        }
        int k = 0;
        for (int i = 0; i < n; i++) if (!rem[i]) freeRects[k++] = freeRects[i];
        freeRects.resize(k);
        if ((int)freeRects.size() > maxFree) {
            sort(freeRects.begin(), freeRects.end(), [](const Rect&a, const Rect&b){
                return (long long)a.w * a.h > (long long)b.w * b.h;
            });
            freeRects.resize(maxFree);
        }
    }
};

void fillWithMaxRects(MaxRects& mr, int ox, int oy, vector<int>& used,
                      vector<Placement>& placements, long long& profit, int method, double tl) {
    bool prog = true;
    while (prog && elapsed() < tl) {
        prog = false;
        long long bestScore = -1;
        int bestIdx = -1, bestRot = 0, bestPx = -1, bestPy = -1;
        
        for (int i = 0; i < M; i++) {
            if (used[i] >= items[i].limit) continue;
            int nrots = (allowRotate && items[i].w != items[i].h) ? 2 : 1;
            for (int r = 0; r < nrots; r++) {
                int rw = r ? items[i].h : items[i].w;
                int rh = r ? items[i].w : items[i].h;
                int px, py;
                if (mr.findBestPos(rw, rh, px, py, method)) {
                    long long sc = items[i].v;
                    if (sc > bestScore) {
                        bestScore = sc; bestIdx = i; bestRot = r; bestPx = px; bestPy = py;
                    }
                }
            }
        }
        if (bestIdx >= 0) {
            int rw = bestRot ? items[bestIdx].h : items[bestIdx].w;
            int rh = bestRot ? items[bestIdx].w : items[bestIdx].h;
            mr.place(bestPx, bestPy, rw, rh);
            placements.push_back({items[bestIdx].type, ox + bestPx, oy + bestPy, bestRot});
            used[bestIdx]++;
            profit += items[bestIdx].v;
            prog = true;
        }
    }
}

void fillRegionSimple(int ox, int oy, int rw, int rh, vector<int>& used,
                       vector<Placement>& pl, long long& profit, int method, double tl) {
    if (rw <= 0 || rh <= 0 || elapsed() > tl) return;
    MaxRects mr;
    mr.init(rw, rh, 300);
    fillWithMaxRects(mr, ox, oy, used, pl, profit, method, tl);
}

void greedyExhaust(const vector<int>& order, int method, double tl) {
    MaxRects mr;
    mr.init(W, H, 600);
    vector<int> used(M, 0);
    vector<Placement> pl;
    long long profit = 0;
    
    for (int idx : order) {
        if (elapsed() > tl) break;
        int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
        while (used[idx] < items[idx].limit && elapsed() < tl) {
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
            pl.push_back({items[idx].type, bestPx, bestPy, bestRot});
            used[idx]++;
            profit += items[idx].v;
        }
    }
    
    fillWithMaxRects(mr, 0, 0, used, pl, profit, method, tl);
    updateBest(profit, pl);
}

void greedyRoundRobin(const vector<int>& order, int method, double tl) {
    MaxRects mr;
    mr.init(W, H, 600);
    vector<int> used(M, 0);
    vector<Placement> pl;
    long long profit = 0;
    
    bool prog = true;
    while (prog && elapsed() < tl) {
        prog = false;
        for (int idx : order) {
            if (used[idx] >= items[idx].limit) continue;
            if (elapsed() > tl) break;
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
            if (bestPx >= 0) {
                int rw = bestRot ? items[idx].h : items[idx].w;
                int rh = bestRot ? items[idx].w : items[idx].h;
                mr.place(bestPx, bestPy, rw, rh);
                pl.push_back({items[idx].type, bestPx, bestPy, bestRot});
                used[idx]++;
                profit += items[idx].v;
                prog = true;
            }
        }
    }
    updateBest(profit, pl);
}

void gridTiling(int pidx, int rot, int fillMethod, double tl) {
    int iw = rot ? items[pidx].h : items[pidx].w;
    int ih = rot ? items[pidx].w : items[pidx].h;
    if (iw > W || ih > H) return;
    
    int cols = W / iw;
    int rows = H / ih;
    if (cols == 0 || rows == 0) return;
    int maxPlace = (int)min((long long)cols * rows, (long long)items[pidx].limit);
    if (maxPlace == 0) return;
    
    vector<Placement> pl;
    long long profit = 0;
    vector<int> used(M, 0);
    
    int actualRows = (maxPlace + cols - 1) / cols;
    int placed = 0;
    for (int r = 0; r < actualRows && placed < maxPlace; r++)
        for (int c = 0; c < cols && placed < maxPlace; c++) {
            pl.push_back({items[pidx].type, c * iw, r * ih, rot});
            placed++;
        }
    used[pidx] = placed;
    profit = (long long)placed * items[pidx].v;
    
    int usedH = actualRows * ih;
    int rightX = cols * iw;
    
    if (rightX < W && usedH > 0 && elapsed() < tl)
        fillRegionSimple(rightX, 0, W - rightX, usedH, used, pl, profit, fillMethod, tl);
    if (usedH < H && elapsed() < tl)
        fillRegionSimple(0, usedH, W, H - usedH, used, pl, profit, fillMethod, tl);
    
    updateBest(profit, pl);
}

void twoTypeStrip(int p1, int rot1, int p2, int rot2, int fillMethod, double tl) {
    int iw1 = rot1 ? items[p1].h : items[p1].w;
    int ih1 = rot1 ? items[p1].w : items[p1].h;
    int iw2 = rot2 ? items[p2].h : items[p2].w;
    int ih2 = rot2 ? items[p2].w : items[p2].h;
    if (iw1 > W || ih1 > H || iw2 > W || ih2 > H) return;
    
    int cols1 = W / iw1;
    int cols2 = W / iw2;
    if (cols1 == 0 || cols2 == 0) return;
    
    int maxRows1 = min(H / ih1, (items[p1].limit + cols1 - 1) / cols1);
    
    long long bestLocal = 0;
    int bestR1 = -1;
    
    for (int r1 = 0; r1 <= maxRows1; r1++) {
        int placed1 = (int)min((long long)r1 * cols1, (long long)items[p1].limit);
        long long prof1 = (long long)placed1 * items[p1].v;
        int usedH = r1 * ih1;
        int remH = H - usedH;
        if (remH < 0) break;
        int rows2 = remH / ih2;
        int placed2 = (int)min((long long)rows2 * cols2, (long long)items[p2].limit);
        long long prof = prof1 + (long long)placed2 * items[p2].v;
        if (prof > bestLocal) { bestLocal = prof; bestR1 = r1; }
    }
    
    if (bestR1 < 0 || bestLocal == 0) return;
    
    int r1 = bestR1;
    int placed1 = (int)min((long long)r1 * cols1, (long long)items[p1].limit);
    int usedH1 = r1 * ih1;
    int rows2 = (H - usedH1) / ih2;
    int placed2 = (int)min((long long)rows2 * cols2, (long long)items[p2].limit);
    int actualRows2 = placed2 > 0 ? (placed2 + cols2 - 1) / cols2 : 0;
    
    vector<Placement> pl;
    vector<int> used(M, 0);
    long long profit = 0;
    
    int cnt = 0;
    for (int r = 0; r < r1 && cnt < placed1; r++)
        for (int c = 0; c < cols1 && cnt < placed1; c++) {
            pl.push_back({items[p1].type, c * iw1, r * ih1, rot1});
            cnt++;
        }
    used[p1] = cnt;
    profit = (long long)cnt * items[p1].v;
    
    cnt = 0;
    for (int r = 0; r < actualRows2 && cnt < placed2; r++)
        for (int c = 0; c < cols2 && cnt < placed2; c++) {
            pl.push_back({items[p2].type, c * iw2, usedH1 + r * ih2, rot2});
            cnt++;
        }
    used[p2] += cnt;
    profit += (long long)cnt * items[p2].v;
    
    int rightX1 = cols1 * iw1;
    if (rightX1 < W && usedH1 > 0 && elapsed() < tl)
        fillRegionSimple(rightX1, 0, W - rightX1, usedH1, used, pl, profit, fillMethod, tl);
    
    int rightX2 = cols2 * iw2;
    int usedH2 = actualRows2 * ih2;
    if (rightX2 < W && usedH2 > 0 && elapsed() < tl)
        fillRegionSimple(rightX2, usedH1, W - rightX2, usedH2, used, pl, profit, fillMethod, tl);
    
    int topY = usedH1 + usedH2;
    if (topY < H && elapsed() < tl)
        fillRegionSimple(0, topY, W, H - topY, used, pl, profit, fillMethod, tl);
    
    updateBest(profit, pl);
}

void threeTypeStrip(int p1, int rot1, int p2, int rot2, int p3, int rot3, int fillMethod, double tl) {
    int iw1 = rot1 ? items[p1].h : items[p1].w, ih1 = rot1 ? items[p1].w : items[p1].h;
    int iw2 = rot2 ? items[p2].h : items[p2].w, ih2 = rot2 ? items[p2].w : items[p2].h;
    int iw3 = rot3 ? items[p3].h : items[p3].w, ih3 = rot3 ? items[p3].w : items[p3].h;
    if (iw1>W||ih1>H||iw2>W||ih2>H||iw3>W||ih3>H) return;
    
    int cols1=W/iw1, cols2=W/iw2, cols3=W/iw3;
    if (!cols1||!cols2||!cols3) return;
    
    int maxR1 = min(H/ih1, (items[p1].limit+cols1-1)/cols1);
    
    long long bestVal = 0;
    int brr1=-1, brr2=-1;
    
    for (int r1=0; r1<=maxR1 && elapsed()<tl; r1++) {
        int pl1 = (int)min((long long)r1*cols1,(long long)items[p1].limit);
        long long v1 = (long long)pl1*items[p1].v;
        int y1 = r1*ih1;
        int rem1 = H-y1;
        if (rem1<0) break;
        int maxR2 = min(rem1/ih2, (items[p2].limit+cols2-1)/cols2);
        for (int r2=0; r2<=maxR2; r2++) {
            int pl2 = (int)min((long long)r2*cols2,(long long)items[p2].limit);
            long long v2 = (long long)pl2*items[p2].v;
            int y2 = y1+r2*ih2;
            int rem2 = H-y2;
            int r3v = rem2/ih3;
            int pl3 = (int)min((long long)r3v*cols3,(long long)items[p3].limit);
            long long v3 = (long long)pl3*items[p3].v;
            long long total = v1+v2+v3;
            if (total>bestVal) { bestVal=total; brr1=r1; brr2=r2; }
        }
    }
    if (brr1<0) return;
    
    int pl1c = (int)min((long long)brr1*cols1,(long long)items[p1].limit);
    int y1e = brr1*ih1;
    int pl2c = (int)min((long long)brr2*cols2,(long long)items[p2].limit);
    int y2e = y1e+brr2*ih2;
    int r3v = (H-y2e)/ih3;
    int pl3c = (int)min((long long)r3v*cols3,(long long)items[p3].limit);
    int ar3 = pl3c>0?(pl3c+cols3-1)/cols3:0;
    
    vector<Placement> pl;
    vector<int> used(M,0);
    long long profit=0;
    
    auto placeGrid=[&](int pidx,int rot,int iw,int ih,int cols,int numRows,int maxCnt,int ofy){
        int cnt=0;
        for(int r=0;r<numRows&&cnt<maxCnt;r++)
            for(int c=0;c<cols&&cnt<maxCnt;c++){
                pl.push_back({items[pidx].type,c*iw,ofy+r*ih,rot});
                cnt++;
            }
        used[pidx]+=cnt;
        profit+=(long long)cnt*items[pidx].v;
        int rx=cols*iw;
        int bh=numRows*ih;
        if(rx<W&&bh>0&&elapsed()<tl)
            fillRegionSimple(rx,ofy,W-rx,bh,used,pl,profit,fillMethod,tl);
    };
    
    placeGrid(p1,rot1,iw1,ih1,cols1,brr1,pl1c,0);
    placeGrid(p2,rot2,iw2,ih2,cols2,brr2,pl2c,y1e);
    placeGrid(p3,rot3,iw3,ih3,cols3,ar3,pl3c,y2e);
    
    int topY=y2e+ar3*ih3;
    if(topY<H&&elapsed()<tl)
        fillRegionSimple(0,topY,W,H-topY,used,pl,profit,fillMethod,tl);
    
    updateBest(profit,pl);
}

// Vertical column-based packing
void verticalStripPack(const vector<int>& order, double tl) {
    vector<Placement> pl;
    vector<int> used(M, 0);
    long long profit = 0;
    int curX = 0;
    
    for (int idx : order) {
        if (elapsed() > tl || curX >= W) break;
        if (used[idx] >= items[idx].limit) continue;
        int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
        
        // Try both rotations, pick the one giving more profit in columns
        int bestRotHere = -1;
        long long bestProfHere = 0;
        int bestColsHere = 0, bestRowsHere = 0, bestPlaceHere = 0;
        int bestIW = 0, bestIH = 0;
        
        for (int r = 0; r < nrots; r++) {
            int iw = r ? items[idx].h : items[idx].w;
            int ih = r ? items[idx].w : items[idx].h;
            if (iw > W - curX || ih > H) continue;
            
            int cols = (W - curX) / iw;
            int rows = H / ih;
            int avail = items[idx].limit - used[idx];
            int canPlace = (int)min((long long)cols * rows, (long long)avail);
            long long pr = (long long)canPlace * items[idx].v;
            if (pr > bestProfHere) {
                bestProfHere = pr; bestRotHere = r;
                bestColsHere = cols; bestRowsHere = rows;
                bestPlaceHere = canPlace; bestIW = iw; bestIH = ih;
            }
        }
        
        if (bestRotHere < 0 || bestPlaceHere == 0) continue;
        
        int actualCols = min(bestColsHere, (bestPlaceHere + bestRowsHere - 1) / bestRowsHere);
        int cnt = 0;
        for (int c = 0; c < actualCols && cnt < bestPlaceHere; c++)
            for (int row = 0; row < bestRowsHere && cnt < bestPlaceHere; row++) {
                pl.push_back({items[idx].type, curX + c * bestIW, row * bestIH, bestRotHere});
                cnt++;
            }
        used[idx] += cnt;
        profit += (long long)cnt * items[idx].v;
        
        int usedH = bestRowsHere * bestIH;
        int usedW = actualCols * bestIW;
        if (usedH < H && usedW > 0 && elapsed() < tl)
            fillRegionSimple(curX, usedH, usedW, H - usedH, used, pl, profit, 0, tl);
        
        curX += usedW;
    }
    
    if (curX < W && elapsed() < tl)
        fillRegionSimple(curX, 0, W - curX, H, used, pl, profit, 0, tl);
    
    updateBest(profit, pl);
}

string readAll() {
    string s, line;
    while (getline(cin, line)) s += line + "\n";
    return s;
}

void skipWS(const string& s, int& p) {
    while (p < (int)s.size() && isspace((unsigned char)s[p])) p++;
}

string parseString(const string& s, int& p) {
    skipWS(s, p);
    if (p >= (int)s.size() || s[p] != '"') return "";
    p++;
    string r;
    while (p < (int)s.size() && s[p] != '"') {
        if (s[p] == '\\') { p++; if (p < (int)s.size()) r += s[p++]; }
        else r += s[p++];
    }
    if (p < (int)s.size()) p++;
    return r;
}

long long parseInt(const string& s, int& p) {
    skipWS(s, p);
    long long sign = 1;
    if (p < (int)s.size() && s[p] == '-') { sign = -1; p++; }
    long long v = 0;
    while (p < (int)s.size() && isdigit((unsigned char)s[p])) v = v * 10 + (s[p++] - '0');
    return sign * v;
}

bool parseBool(const string& s, int& p) {
    skipWS(s, p);
    if (p + 4 <= (int)s.size() && s.substr(p, 4) == "true") { p += 4; return true; }
    if (p + 5 <= (int)s.size() && s.substr(p, 5) == "false") { p += 5; return false; }
    return false;
}

void parseInput(const string& s) {
    int p = 0;
    skipWS(s, p); p++; // {
    
    while (p < (int)s.size()) {
        skipWS(s, p);
        if (s[p] == '}') break;
        if (s[p] == ',') p++;
        skipWS(s, p);
        string key = parseString(s, p);
        skipWS(s, p); p++; // :
        
        if (key == "bin") {
            skipWS(s, p); p++; // {
            while (true) {
                skipWS(s, p);
                if (s[p] == '}') { p++; break; }
                if (s[p] == ',') p++;
                string k = parseString(s, p);
                skipWS(s, p); p++; // :
                if (k == "W") W = (int)parseInt(s, p);
                else if (k == "H") H = (int)parseInt(s, p);
                else if (k == "allow_rotate") allowRotate = parseBool(s, p);
            }
        } else if (key == "items") {
            skipWS(s, p); p++; // [
            while (true) {
                skipWS(s, p);
                if (s[p] == ']') { p++; break; }
                if (s[p] == ',') p++;
                skipWS(s, p); p++; // {
                Item it;
                while (true) {
                    skipWS(s, p);
                    if (s[p] == '}') { p++; break; }
                    if (s[p] == ',') p++;
                    string k = parseString(s, p);
                    skipWS(s, p); p++; // :
                    if (k == "type") it.type = parseString(s, p);
                    else if (k == "w") it.w = (int)parseInt(s, p);
                    else if (k == "h") it.h = (int)parseInt(s, p);
                    else if (k == "v") it
