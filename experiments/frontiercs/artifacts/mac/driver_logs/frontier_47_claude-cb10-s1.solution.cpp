#include <bits/stdc++.h>
using namespace std;

struct Item { string type; int w, h; long long v; int limit; };
struct Placement { string type; int x, y, rot; };
struct Rect { int x, y, w, h; };

struct MaxRects {
    int binW, binH;
    vector<Rect> freeRects;
    
    void init(int w, int h) {
        binW = w; binH = h;
        freeRects.clear();
        freeRects.push_back({0, 0, w, h});
    }
    
    bool findPosition(int rw, int rh, int &bx, int &by, int method) {
        bx = by = -1;
        if (method == 0) { // Best Area Fit
            int bestArea = INT_MAX, bestSS = INT_MAX;
            for (auto &f : freeRects) {
                if (rw <= f.w && rh <= f.h) {
                    int area = f.w * f.h - rw * rh;
                    int ss = min(f.w - rw, f.h - rh);
                    if (area < bestArea || (area == bestArea && ss < bestSS)) {
                        bx = f.x; by = f.y; bestArea = area; bestSS = ss;
                    }
                }
            }
        } else if (method == 1) { // Best Short Side Fit
            int bestSS = INT_MAX, bestLS = INT_MAX;
            for (auto &f : freeRects) {
                if (rw <= f.w && rh <= f.h) {
                    int ss = min(f.w - rw, f.h - rh);
                    int ls = max(f.w - rw, f.h - rh);
                    if (ss < bestSS || (ss == bestSS && ls < bestLS)) {
                        bx = f.x; by = f.y; bestSS = ss; bestLS = ls;
                    }
                }
            }
        } else if (method == 2) { // Bottom Left
            int bestY = INT_MAX, bestX = INT_MAX;
            for (auto &f : freeRects) {
                if (rw <= f.w && rh <= f.h) {
                    if (f.y < bestY || (f.y == bestY && f.x < bestX)) {
                        bx = f.x; by = f.y; bestY = f.y; bestX = f.x;
                    }
                }
            }
        } else { // Contact Point (approximate: prefer positions touching more edges)
            int bestScore = -1;
            for (auto &f : freeRects) {
                if (rw <= f.w && rh <= f.h) {
                    int score = 0;
                    if (f.x == 0) score += rh;
                    if (f.y == 0) score += rw;
                    if (f.x + rw == binW) score += rh;
                    if (f.y + rh == binH) score += rw;
                    if (score > bestScore) {
                        bx = f.x; by = f.y; bestScore = score;
                    }
                }
            }
            if (bestScore < 0) return false;
        }
        return bx >= 0;
    }
    
    void place(int px, int py, int rw, int rh) {
        Rect placed = {px, py, rw, rh};
        int n = freeRects.size();
        vector<Rect> newFree;
        newFree.reserve(n + 4);
        for (int i = 0; i < n; i++) {
            auto &f = freeRects[i];
            if (placed.x >= f.x + f.w || placed.x + placed.w <= f.x ||
                placed.y >= f.y + f.h || placed.y + placed.h <= f.y) {
                newFree.push_back(f);
                continue;
            }
            if (placed.x > f.x)
                newFree.push_back({f.x, f.y, placed.x - f.x, f.h});
            if (placed.x + placed.w < f.x + f.w)
                newFree.push_back({placed.x + placed.w, f.y, f.x + f.w - placed.x - placed.w, f.h});
            if (placed.y > f.y)
                newFree.push_back({f.x, f.y, f.w, placed.y - f.y});
            if (placed.y + placed.h < f.y + f.h)
                newFree.push_back({f.x, placed.y + placed.h, f.w, f.y + f.h - placed.y - placed.h});
        }
        freeRects = newFree;
        pruneContained();
    }
    
    void pruneContained() {
        int n = freeRects.size();
        vector<bool> rem(n, false);
        for (int i = 0; i < n; i++) {
            if (rem[i]) continue;
            for (int j = i+1; j < n; j++) {
                if (rem[j]) continue;
                if (contains(freeRects[i], freeRects[j])) rem[j] = true;
                else if (contains(freeRects[j], freeRects[i])) { rem[i] = true; break; }
            }
        }
        int k = 0;
        for (int i = 0; i < n; i++) if (!rem[i]) freeRects[k++] = freeRects[i];
        freeRects.resize(k);
    }
    
    static bool contains(const Rect &a, const Rect &b) {
        return b.x >= a.x && b.y >= a.y && b.x + b.w <= a.x + a.w && b.y + b.h <= a.y + a.h;
    }
};

int W, H;
bool allowRotate;
vector<Item> items;
int M;

long long bestProfit;
vector<Placement> bestPlacements;

struct TypeOrder { int idx; int preferRot; double score; };

void runPack(vector<TypeOrder>& order, int method, bool dynamicRot, bool onePass) {
    MaxRects mr;
    mr.init(W, H);
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    if (onePass) {
        for (auto &o : order) {
            int i = o.idx;
            while (used[i] < items[i].limit) {
                int bx0=-1, by0=-1, bx1=-1, by1=-1;
                int w0 = items[i].w, h0 = items[i].h;
                int w1 = h0, h1 = w0;
                bool ok0 = (w0 <= W && h0 <= H) && mr.findPosition(w0, h0, bx0, by0, method);
                bool ok1 = false;
                if (dynamicRot && allowRotate && (w0 != h0)) {
                    ok1 = (w1 <= W && h1 <= H) && mr.findPosition(w1, h1, bx1, by1, method);
                }
                if (!ok0 && !ok1) break;
                // Choose better fit
                int rot, px, py, pw, ph;
                if (ok0 && !ok1) { rot=0; px=bx0; py=by0; pw=w0; ph=h0; }
                else if (!ok0 && ok1) { rot=1; px=bx1; py=by1; pw=w1; ph=h1; }
                else {
                    // Both fit, choose by method heuristic - pick the one with lower y then x
                    if (by0 < by1 || (by0 == by1 && bx0 <= bx1)) { rot=0; px=bx0; py=by0; pw=w0; ph=h0; }
                    else { rot=1; px=bx1; py=by1; pw=w1; ph=h1; }
                }
                if (!dynamicRot) { rot = o.preferRot; pw = rot ? h0 : w0; ph = rot ? w0 : h0; }
                mr.place(px, py, pw, ph);
                placements.push_back({items[i].type, px, py, rot});
                used[i]++;
                profit += items[i].v;
            }
        }
    } else {
        // Multi-pass: keep cycling until no progress
        bool progress = true;
        while (progress) {
            progress = false;
            for (auto &o : order) {
                int i = o.idx;
                if (used[i] >= items[i].limit) continue;
                int w0 = items[i].w, h0 = items[i].h;
                int w1 = h0, h1 = w0;
                int bx0=-1, by0=-1, bx1=-1, by1=-1;
                bool ok0 = (w0 <= W && h0 <= H) && mr.findPosition(w0, h0, bx0, by0, method);
                bool ok1 = false;
                if (dynamicRot && allowRotate && w0 != h0)
                    ok1 = (w1 <= W && h1 <= H) && mr.findPosition(w1, h1, bx1, by1, method);
                if (!ok0 && !ok1) continue;
                int rot, px, py, pw, ph;
                if (ok0 && !ok1) { rot=0; px=bx0; py=by0; pw=w0; ph=h0; }
                else if (!ok0 && ok1) { rot=1; px=bx1; py=by1; pw=w1; ph=h1; }
                else {
                    if (by0 < by1 || (by0==by1 && bx0<=bx1)) { rot=0; px=bx0; py=by0; pw=w0; ph=h0; }
                    else { rot=1; px=bx1; py=by1; pw=w1; ph=h1; }
                }
                mr.place(px, py, pw, ph);
                placements.push_back({items[i].type, px, py, rot});
                used[i]++;
                profit += items[i].v;
                progress = true;
            }
        }
    }
    
    if (profit > bestProfit) {
        bestProfit = profit;
        bestPlacements = placements;
    }
}

// Shelf packing
void runShelf(vector<TypeOrder>& order, bool dynamicRot) {
    vector<int> used(M, 0);
    vector<Placement> placements;
    long long profit = 0;
    
    int curY = 0;
    
    while (curY < H) {
        // Find best item to start a shelf
        int shelfH = 0;
        int curX = 0;
        bool placed = false;
        
        for (auto &o : order) {
            int i = o.idx;
            while (used[i] < items[i].limit) {
                int w0 = items[i].w, h0 = items[i].h;
                // Try both rotations
                int bestW = -1, bestH = -1, bestRot = 0;
                if (dynamicRot && allowRotate) {
                    // Try rotation that gives smaller height if starting shelf, or fits in shelf
                    for (int r = 0; r < 2; r++) {
                        int cw = r ? h0 : w0, ch = r ? w0 : h0;
                        if (cw > W || ch > H) continue;
                        if (shelfH == 0) {
                            if (curX + cw <= W && curY + ch <= H) {
                                if (bestW < 0 || ch < bestH) { bestW=cw; bestH=ch; bestRot=r; }
                            }
                        } else {
                            if (curX + cw <= W && ch <= shelfH && curY + ch <= H) {
                                if (bestW < 0) { bestW=cw; bestH=ch; bestRot=r; }
                            }
                        }
                    }
                } else {
                    int cw = w0, ch = h0;
                    if (shelfH == 0) {
                        if (curX + cw <= W && curY + ch <= H) { bestW=cw; bestH=ch; bestRot=0; }
                    } else {
                        if (curX + cw <= W && ch <= shelfH && curY + ch <= H) { bestW=cw; bestH=ch; bestRot=0; }
                    }
                }
                if (bestW < 0) break;
                
                if (shelfH == 0) shelfH = bestH;
                placements.push_back({items[i].type, curX, curY, bestRot});
                curX += bestW;
                used[i]++;
                profit += items[i].v;
                placed = true;
            }
        }
        if (!placed) break;
        curY += shelfH;
    }
    
    if (profit > bestProfit) {
        bestProfit = profit;
        bestPlacements = placements;
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now() - startTime).count();
    };
    
    string input((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());
    
    auto findKey = [&](const string& s, const string& key, size_t start=0) -> size_t {
        string k = "\"" + key + "\"";
        return s.find(k, start);
    };
    
    {
        size_t binPos = findKey(input, "bin");
        size_t p = findKey(input, "W", binPos);
        sscanf(input.c_str()+input.find(':', p)+1, "%d", &W);
        p = findKey(input, "H", binPos);
        sscanf(input.c_str()+input.find(':', p)+1, "%d", &H);
        p = findKey(input, "allow_rotate");
        size_t cp = input.find(':', p);
        string rest = input.substr(cp+1, 10);
        allowRotate = rest.find("true") < rest.find("false");
    }
    
    {
        size_t p = findKey(input, "items");
        size_t arrStart = input.find('[', p);
        size_t arrEnd = input.rfind(']');
        string arr = input.substr(arrStart, arrEnd - arrStart + 1);
        
        size_t pos = 0;
        while(true) {
            size_t ob = arr.find('{', pos);
            if (ob == string::npos) break;
            size_t cb = arr.find('}', ob);
            string obj = arr.substr(ob, cb - ob + 1);
            
            Item it;
            size_t tp = obj.find("\"type\"");
            size_t q1 = obj.find('\"', obj.find(':', tp)+1);
            size_t q2 = obj.find('\"', q1+1);
            it.type = obj.substr(q1+1, q2-q1-1);
            
            auto getInt = [&](const string& key) -> long long {
                size_t kp = obj.find("\"" + key + "\"");
                size_t cp2 = obj.find(':', kp);
                long long val;
                sscanf(obj.c_str()+cp2+1, "%lld", &val);
                return val;
            };
            it.w = (int)getInt("w");
            it.h = (int)getInt("h");
            it.v = getInt("v");
            it.limit = (int)getInt("limit");
            items.push_back(it);
            pos = cb + 1;
        }
    }
    
    M = items.size();
    bestProfit = 0;
    
    // Sorting strategies for TypeOrder
    auto makeSorters = [&]() {
        vector<function<bool(const TypeOrder&, const TypeOrder&)>> s;
        // By density desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){ 
            double da = (double)items[a.idx].v / ((double)items[a.idx].w * items[a.idx].h);
            double db = (double)items[b.idx].v / ((double)items[b.idx].w * items[b.idx].h);
            return da > db;
        });
        // By value desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){ return items[a.idx].v > items[b.idx].v; });
        // By area desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){ 
            return (long long)items[a.idx].w*items[a.idx].h > (long long)items[b.idx].w*items[b.idx].h; 
        });
        // By height desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){
            int ha = a.preferRot ? items[a.idx].w : items[a.idx].h;
            int hb = b.preferRot ? items[b.idx].w : items[b.idx].h;
            return ha > hb;
        });
        // By width desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){
            int wa = a.preferRot ? items[a.idx].h : items[a.idx].w;
            int wb = b.preferRot ? items[b.idx].h : items[b.idx].w;
            return wa > wb;
        });
        // By total possible value (v * limit) desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){
            return items[a.idx].v * (long long)items[a.idx].limit > items[b.idx].v * (long long)items[b.idx].limit;
        });
        // Area ascending (small first)
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){ 
            return (long long)items[a.idx].w*items[a.idx].h < (long long)items[b.idx].w*items[b.idx].h; 
        });
        // Density * sqrt(limit) desc
        s.push_back([&](const TypeOrder&a, const TypeOrder&b){
            double sa = (double)items[a.idx].v / ((double)items[a.idx].w * items[a.idx].h) * sqrt(items[a.idx].limit);
            double sb = (double)items[b.idx].v / ((double)items[b.idx].w * items[b.idx].h) * sqrt(items[b.idx].limit);
            return sa > sb;
        });
        return s;
    };
    
    auto sorters = makeSorters();
    
    // Generate base orders with different rotation preferences
    auto genOrders = [&](int rotPref) -> vector<TypeOrder> {
        vector<TypeOrder> ord;
        for (int i = 0; i < M; i++) {
            int rot = 0;
            if (allowRotate && items[i].w != items[i].h) {
                if (rotPref == 1) rot = (items[i].h > items[i].w) ? 1 : 0; // prefer wide
                else if (rotPref == 2) rot = (items[i].w > items[i].h) ? 1 : 0; // prefer tall
            }
            ord.push_back({i, rot, 0.0});
        }
        return ord;
    };
    
    // Systematic exploration
    for (int rp = 0; rp <= 2; rp++) {
        auto base = genOrders(rp);
        for (int si = 0; si < (int)sorters.size(); si++) {
            for (int method = 0; method < 4; method++) {
                for (int onePass = 0; onePass < 2; onePass++) {
                    if (elapsed() > 0.6) goto randomPhase;
                    auto ord = base;
                    sort(ord.begin(), ord.end(), sorters[si]);
                    runPack(ord, method, true, onePass);
                    // Also try with fixed rotation
                    runPack(ord, method, false, onePass);
                }
            }
        }
        // Shelf packing
        for (int si = 0; si < (int)sorters.size(); si++) {
            if (elapsed() > 0.6) goto randomPhase;
            auto ord = base;
            sort(ord.begin(), ord.end(), sorters[si]);
            runShelf(ord, true);
        }
    }
    
    randomPhase:
    {
        mt19937 rng(12345);
        while (elapsed() < 0.9) {
            auto ord = genOrders(rng() % 3);
            // Random permutation
            shuffle(ord.begin(), ord.end(), rng);
            int method = rng() % 4;
            int onePass = rng() % 2;
            runPack(ord, method, true, onePass);
            if (elapsed() > 0.9) break;
            runShelf(ord, true);
        }
    }
    
    printf("{\"placements\":[");
    for (int i = 0; i < (int)bestPlacements.size(); i++) {
        if (i) printf(",");
        printf("{\"type\":\"%s\",\"x\":%d,\"y\":%d,\"rot\":%d}",
            bestPlacements[i].type.c_str(), bestPlacements[i].x, bestPlacements[i].y, bestPlacements[i].rot);
    }
    printf("]}");
}
