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
    
    void init(int bw, int bh) {
        freeRects.clear();
        freeRects.push_back({0, 0, bw, bh});
    }
    
    int findPos(int rw, int rh, int &bx, int &by, int method) {
        bx = by = -1;
        long long bestA = LLONG_MAX, bestB = LLONG_MAX;
        int bestIdx = -1;
        for (int i = 0; i < (int)freeRects.size(); i++) {
            auto &f = freeRects[i];
            if (rw > f.w || rh > f.h) continue;
            long long a, b;
            if (method == 0) { a = min(f.w-rw, f.h-rh); b = max(f.w-rw, f.h-rh); }
            else if (method == 1) { a = (long long)f.w*f.h - (long long)rw*rh; b = min(f.w-rw, f.h-rh); }
            else if (method == 2) { a = f.y; b = f.x; }
            else { a = f.x; b = f.y; }
            if (a < bestA || (a == bestA && b < bestB)) {
                bestA = a; bestB = b; bx = f.x; by = f.y; bestIdx = i;
            }
        }
        return bestIdx;
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
        if (n > 600) {
            sort(freeRects.begin(), freeRects.end(), [](const Rect&a, const Rect&b){
                return (long long)a.w*a.h > (long long)b.w*b.h;
            });
            freeRects.resize(600);
            n = 600;
        }
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
        int k = 0;
        for (int i = 0; i < n; i++) if (!rem[i]) freeRects[k++] = freeRects[i];
        freeRects.resize(k);
    }
};

bool tryPlaceInMR(MaxRects& mr, int idx, int method, vector<int>& used, 
                   vector<Placement>& placements, long long& profit, int ox=0, int oy=0) {
    if (used[idx] >= items[idx].limit) return false;
    int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
    int bestPx = -1, bestPy = -1, bestRot2 = 0;
    long long bestFitA = LLONG_MAX, bestFitB = LLONG_MAX;
    for (int r = 0; r < nrots; r++) {
        int rw = r ? items[idx].h : items[idx].w;
        int rh = r ? items[idx].w : items[idx].h;
        int px, py;
        if (mr.findPos(rw, rh, px, py, method) >= 0) {
            long long fa, fb;
            if (method == 0) { fa = 0; fb = 0; } // use method's own ranking
            fa = py; fb = px;
            if (bestPx < 0 || fa < bestFitA || (fa == bestFitA && fb < bestFitB)) {
                bestFitA = fa; bestFitB = fb;
                bestPx = px; bestPy = py; bestRot2 = r;
            }
        }
    }
    if (bestPx >= 0) {
        int rw = bestRot2 ? items[idx].h : items[idx].w;
        int rh = bestRot2 ? items[idx].w : items[idx].h;
        mr.place(bestPx, bestPy, rw, rh);
        placements.push_back({items[idx].type, ox+bestPx, oy+bestPy, bestRot2});
        used[idx]++;
        profit += items[idx].v;
        return true;
    }
    return false;
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
            while (tryPlaceInMR(mr, idx, method, used, placements, profit)) {
                if (elapsed() > timeLimit) break;
            }
        }
    } else {
        bool progress = true;
        while (progress) {
            if (elapsed() > timeLimit) break;
            progress = false;
            for (int idx : itemOrder) {
                if (tryPlaceInMR(mr, idx, method, used, placements, profit))
                    progress = true;
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
                if (!tryPlaceInMR(mr, idx, method, used, placements, profit)) break;
                else prog = true;
            }
        }
    }
    
    updateBest(profit, placements);
}

void fillRegion(int ox, int oy, int rw, int rh, vector<int>& used, 
                vector<Placement>& placements, long long& profit, double timeLimit) {
    if (rw <= 0 || rh <= 0) return;
    MaxRects mr;
    mr.init(rw, rh);
    vector<pair<double,int>> byDens;
    for (int i = 0; i < M; i++) {
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
                if (!tryPlaceInMR(mr, idx, 0, used, placements, profit, ox, oy)) break;
                else prog = true;
            }
        }
    }
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
    
    fillRegion(rightX, 0, W - rightX, topY, used, placements, profit, timeLimit);
    if (elapsed() < timeLimit)
        fillRegion(0, topY, W, H - topY, used, placements, profit, timeLimit);
    
    updateBest(profit, placements);
}

// Two-type grid: tile with primary, then fill remainder strips with secondary
void twoTypeGrid(int p1, int rot1, int p2, int rot2, double timeLimit) {
    int iw1 = rot1 ? items[p1].h : items[p1].w;
    int ih1 = rot1 ? items[p1].w : items[p1].h;
    if (iw1 > W || ih1 > H) return;
    
    int cols1 = W / iw1;
    int rows1 = H / ih1;
    long long maxPlace1 = min((long long)cols1 * rows1, (long long)items[p1].limit);
    
    // Try using fewer rows to leave more space for type 2
    int iw2 = rot2 ? items[p2].h : items[p2].w;
    int ih2 = rot2 ? items[p2].w : items[p2].h;
    if (iw2 > W || ih2 > H) return;
    
    double d1 = (double)items[p1].v / ((double)iw1 * ih1);
    double d2 = (double)items[p2].v / ((double)iw2 * ih2);
    
    long long bestLocal = 0;
    vector<Placement> bestLocalPl;
    
    // Try different number of rows for type 1
    int maxRows = min(rows1, (int)((items[p1].limit + cols1 - 1) / cols1));
    
    for (int r1 = 0; r1 <= maxRows && elapsed() < timeLimit; r1++) {
        int placed1 = min((long long)r1 * cols1, (long long)items[p1].limit);
        long long prof = (long long)placed1 * items[p1].v;
        
        int usedH = r1 * ih1;
        int remH = H - usedH;
        if (remH < 0) break;
        
        // Fill remaining height with type 2
        int rows2 = remH / ih2;
        int cols2 = W / iw2;
        int placed2 = min((long long)rows2 * cols2, (long long)items[p2].limit);
        prof += (long long)placed2 * items[p2].v;
        
        // Rough estimate of right-strip fill for type 1 region
        int rightW1 = W - cols1 * iw1;
        int rightW2 = W - cols2 * iw2;
        // Ignore for now, just use this as estimate
        
        if (prof > bestLocal) {
            bestLocal = prof;
            // Build actual placements
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
            
            // Fill gaps
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
        updateBest(bestLocal, bestLocalPl);
}

void stripPack(const vector<pair<int,int>>& allocation, double timeLimit) {
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
        for (int r = 0; r < actualRows && placed < totalPlace; r++) {
            for (int c = 0; c < cols && placed < totalPlace; c++) {
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

string readAll() {
    ostringstream ss;
    ss << cin.rdbuf();
    return ss.str();
}

void skipWS(const string& s, int& p) {
    while (p < (int)s.size() && isspace((unsigned char)s[p])) p++;
}

string parseString(const string& s, int& p) {
    skipWS(s, p);
    if (p >= (int)s.size() || s[p] != '"') return "";
    p++;
    string res;
    while (p < (int)s.size() && s[p] != '"') {
        if (s[p] == '\\') { p++; if (p < (int)s.size()) res += s[p++]; }
        else res += s[p++];
    }
    if (p < (int)s.size()) p++;
    return res;
}

long long parseInt2(const string& s, int& p) {
    skipWS(s, p);
    long long sign = 1;
    if (p < (int)s.size() && s[p] == '-') { sign = -1; p++; }
    long long v = 0;
    while (p < (int)s.size() && isdigit((unsigned char)s[p])) v = v*10 + (s[p++]-'0');
    return sign * v;
}

bool parseBool(const string& s, int& p) {
    skipWS(s, p);
    if (p+4 <= (int)s.size() && s.substr(p, 4) == "true") { p += 4; return true; }
    if (p+5 <= (int)s.size() && s.substr(p, 5) == "false") { p += 5; return false; }
    return false;
}

void parseInput(const string& s) {
    int p = 0;
    skipWS(s, p); p++; // {
    
    while (p < (int)s.size()) {
        skipWS(s, p);
        if (s[p] == '}') break;
        if (s[p] == ',') { p++; continue; }
        string key = parseString(s, p);
        skipWS(s, p); p++; // :
        
        if (key == "bin") {
            skipWS(s, p); p++; // {
            while (p < (int)s.size() && s[p] != '}') {
                skipWS(s, p);
                if (s[p] == ',') { p++; continue; }
                string bk = parseString(s, p);
                skipWS(s, p); p++; // :
                if (bk == "W") W = (int)parseInt2(s, p);
                else if (bk == "H") H = (int)parseInt2(s, p);
                else if (bk == "allow_rotate") allowRotate = parseBool(s, p);
                skipWS(s, p);
            }
            p++; // }
        } else if (key == "items") {
            skipWS(s, p); p++; // [
            while (true) {
                skipWS(s, p);
                if (p >= (int)s.size() || s[p] == ']') { p++; break; }
                if (s[p] == ',') { p++; continue; }
                p++; // {
                Item it;
                while (p < (int)s.size() && s[p] != '}') {
                    skipWS(s, p);
                    if (s[p] == ',') { p++; continue; }
                    string ik = parseString(s, p);
                    skipWS(s, p); p++; // :
                    if (ik == "type") it.type = parseString(s, p);
                    else if (ik == "w") it.w = (int)parseInt2(s, p);
                    else if (ik == "h") it.h = (int)parseInt2(s, p);
                    else if (ik == "v") it.v = parseInt2(s, p);
                    else if (ik == "limit") it.limit = (int)parseInt2(s, p);
                    skipWS(s, p);
                }
                p++; // }
                items.push_back(it);
            }
        }
        skipWS(s, p);
    }
    M = items.size();
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    string input = readAll();
    parseInput(input);
    
    vector<int> byDensity(M), byValue(M), byArea(M), byTotalVal(M);
    iota(byDensity.begin(), byDensity.end(), 0);
    iota(byValue.begin(), byValue.end(), 0);
    iota(byArea.begin(), byArea.end(), 0);
    iota(byTotalVal.begin(), byTotalVal.end(), 0);
    
    sort(byDensity.begin(), byDensity.end(), [](int a, int b){
        double da = (double)items[a].v / ((double)items[a].w * items[a].h);
        double db = (double)items[b].v / ((double)items[b].w * items[b].h);
        return da > db;
    });
    sort(byValue.begin(), byValue.end(), [](int a, int b){ return items[a].v > items[b].v; });
    sort(byArea.begin(), byArea.end(), [](int a, int b){ return items[a].w*items[a].h > items[b].w*items[b].h; });
    sort(byTotalVal.begin(), byTotalVal.end(), [](int a, int b){
        return items[a].v*(long long)items[a].limit > items[b].v*(long long)items[b].limit;
    });
    
    double tlim = 0.85;
    
    // MaxRects strategies
    vector<vector<int>> orderings = {byDensity, byValue, byArea, byTotalVal};
    {
        vector<int> r1 = byDensity; reverse(r1.begin(), r1.end()); orderings.push_back(r1);
        vector<int> r2 = byValue; reverse(r2.begin(), r2.end()); orderings.push_back(r2);
    }
    
    for (auto& ord : orderings) {
        for (int method = 0; method < 4 && elapsed() < tlim; method++) {
            greedyMaxRects(method, ord, true, tlim);
            if (elapsed() > tlim) break;
            greedyMaxRects(method, ord, false, tlim);
            if (elapsed() > tlim) break;
        }
        if (elapsed() > tlim) break;
    }
    
    // Grid tiling
    for (int i = 0; i < M && elapsed() < tlim; i++) {
        gridTiling(i, 0, tlim);
        if (allowRotate && items[i].w != items[i].h && elapsed() < tlim) {
            gridTiling(i, 1, tlim);
        }
    }
    
    // Two-type grid for top density pairs
    if (elapsed() < tlim) {
        for (int i = 0; i < min(M, 5) && elapsed() < tlim; i++) {
            int p1 = byDensity[i];
            for (int j = 0; j < min(M, 5) && elapsed() < tlim; j++) {
                int p2 = byDensity[j];
                if (p1 == p2) continue;
                int nrots1 = (allowRotate && items[p1].w != items[p1].h) ? 2 : 1;
                int nrots2 = (allowRotate && items[p2].w != items[p2].h) ? 2 : 1;
                for (int r1 = 0; r1 < nrots1 && elapsed() < tlim; r1++) {
                    for (int r2 = 0; r2 < nrots2 && elapsed() < tlim; r2++) {
                        twoTypeGrid(p1, r1, p2, r2, tlim);
                    }
                }
            }
        }
    }
    
    // Strip packing
    auto buildAlloc = [&](const vector<int>& order) {
        vector<pair<int,int>> alloc;
        for (int idx : order) {
            int bestRot = 0;
            int nrots = (allowRotate && items[idx].w != items[idx].h) ? 2 : 1;
            double bestVal = -1;
            for (int r = 0; r < nrots; r++) {
                int iw = r ? items[idx].h : items[idx].w;
                int ih = r ? items[idx].w : items[idx].h;
                if (iw > W || ih > H) continue;
                int cols = W / iw;
                double val = (double)items[idx].v * cols / (double)(iw * ih);
                if (val > bestVal) { bestVal = val; bestRot = r; }
            }
            alloc.push_back({idx, bestRot});
        }
        return alloc;
    };
    
    if (elapsed() < tlim) stripPack(buildAlloc(byDensity), tlim);
    if (elapsed() < tlim) stripPack(buildAlloc(byValue), tlim);
    if (elapsed() < tlim) stripPack(buildAlloc(byTotalVal), tlim);
    
    // Try permutations of top items for strip packing (if M is small enough)
    if (M <= 10 && elapsed() < tlim) {
        // Random shuffles
        mt19937 rng(42);
        for (int iter = 0; iter < 200 && elapsed() < tlim; iter++) {
            vector<int> perm(M);
            iota(perm.begin(), perm.end(), 0);
            shuffle(perm.begin(), perm.end(), rng);
            stripPack(buildAlloc(perm), tlim);
        }
    }
    
    // More random MaxRects attempts
    if (elapsed() < tlim) {
        mt19937 rng(123);
        for (int iter = 0; iter < 300 && elapsed() < tlim; iter++) {
            vector<int> perm(M);
            iota(perm.begin(), perm.end(), 0);
            shuffle(perm.begin(), perm.end(), rng);
            int method = rng() % 4;
            bool exh = rng() % 2;
            greedyMaxRects(method, perm, exh, tlim);
        }
    }
    
    // Output
    printf("{\"placements\":[");
    for (int i = 0; i < (int)bestPlacements.size(); i++) {
        if (i) printf(",");
        auto& p = bestPlacements[i];
        printf("{\"type\":\"%s\",\"x\":%d,\"y\":%d,\"rot\":%d}", 
               p.type.c_str(), p.x, p.y, p.rot);
    }
    printf("]}");
    
    return 0;
}
