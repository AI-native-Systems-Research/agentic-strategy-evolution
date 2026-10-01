#include <bits/stdc++.h>
using namespace std;

struct ItemType {
    string type;
    int w, h, v, limit;
};

struct Placement {
    string type;
    int x, y, rot;
};

struct Rect {
    int x, y, w, h;
};

static int gW, gH;
static bool gAllowRotate;
static int gM;
static vector<ItemType> items;
static vector<double> density;

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
    
    void splitAndUpdate(int px, int py, int pw, int ph) {
        vector<Rect> newRects;
        newRects.reserve(freeRects.size() * 4);
        for (auto& fr : freeRects) {
            int frR = fr.x + fr.w, frT = fr.y + fr.h;
            int pR = px + pw, pT = py + ph;
            if (px >= frR || pR <= fr.x || py >= frT || pT <= fr.y) {
                newRects.push_back(fr);
                continue;
            }
            if (px > fr.x) newRects.push_back({fr.x, fr.y, px - fr.x, fr.h});
            if (pR < frR) newRects.push_back({pR, fr.y, frR - pR, fr.h});
            if (py > fr.y) newRects.push_back({fr.x, fr.y, fr.w, py - fr.y});
            if (pT < frT) newRects.push_back({fr.x, pT, fr.w, frT - pT});
        }
        // Remove dominated
        int n = newRects.size();
        vector<bool> rem(n, false);
        // Sort by area descending for faster pruning
        for (int i = 0; i < n; i++) {
            if (rem[i]) continue;
            for (int j = 0; j < n; j++) {
                if (i == j || rem[j]) continue;
                if (newRects[j].x >= newRects[i].x && newRects[j].y >= newRects[i].y &&
                    newRects[j].x + newRects[j].w <= newRects[i].x + newRects[i].w &&
                    newRects[j].y + newRects[j].h <= newRects[i].y + newRects[i].h) {
                    rem[j] = true;
                }
            }
        }
        freeRects.clear();
        for (int i = 0; i < n; i++)
            if (!rem[i]) freeRects.push_back(newRects[i]);
    }
    
    // Try placing item, return true if successful
    // strategy: 0=best-short-side, 1=best-long-side, 2=best-area, 3=bottom-left, 4=contact
    bool tryPlace(int ti, int rw, int rh, int rot, int strategy, int& ox, int& oy) {
        int bestScore = INT_MIN;
        ox = -1; oy = -1;
        for (auto& fr : freeRects) {
            if (rw <= fr.w && rh <= fr.h) {
                int x = fr.x, y = fr.y;
                int score;
                switch(strategy) {
                    case 0: score = -min(fr.w - rw, fr.h - rh); break;
                    case 1: score = -max(fr.w - rw, fr.h - rh); break;
                    case 2: score = -(fr.w * fr.h - rw * rh); break;
                    case 3: score = -(y * 20000 + x); break;
                    default: {
                        score = 0;
                        if (x == 0) score += rh;
                        if (y == 0) score += rw;
                        if (x + rw == gW) score += rh;
                        if (y + rh == gH) score += rw;
                    }
                }
                if (score > bestScore) {
                    bestScore = score;
                    ox = x; oy = y;
                }
            }
        }
        return ox >= 0;
    }
    
    void doPlace(int ti, int ox, int oy, int rot) {
        int rw = (rot == 0) ? items[ti].w : items[ti].h;
        int rh = (rot == 0) ? items[ti].h : items[ti].w;
        placements.push_back({items[ti].type, ox, oy, rot});
        used[ti]++;
        totalProfit += items[ti].v;
        splitAndUpdate(ox, oy, rw, rh);
    }
};

static vector<Placement> bestPlacements;
static long long bestProfit = 0;

void updateBest(State& s) {
    if (s.totalProfit > bestProfit) {
        bestProfit = s.totalProfit;
        bestPlacements = s.placements;
    }
}

// Greedy: given ordered list of (typeIdx, rot), place greedily
void runGreedy(vector<pair<int,int>>& order, int strategy) {
    State state;
    state.init();
    for (auto& [ti, rot] : order) {
        if (state.used[ti] >= items[ti].limit) continue;
        int rw = (rot == 0) ? items[ti].w : items[ti].h;
        int rh = (rot == 0) ? items[ti].h : items[ti].w;
        if (rw > gW || rh > gH) continue;
        int ox, oy;
        if (state.tryPlace(ti, rw, rh, rot, strategy, ox, oy)) {
            state.doPlace(ti, ox, oy, rot);
        }
    }
    updateBest(state);
}

// Smart greedy: at each step pick best item
void runSmart(int strategy, double alpha) {
    State state;
    state.init();
    while (true) {
        int bestTi = -1, bestRot = -1, bestX = -1, bestY = -1;
        double bestEval = -1e18;
        for (int ti = 0; ti < gM; ti++) {
            if (state.used[ti] >= items[ti].limit) continue;
            int rots_arr[2] = {0, 1};
            int nrots = 1;
            if (gAllowRotate && items[ti].w != items[ti].h) nrots = 2;
            for (int ri = 0; ri < nrots; ri++) {
                int rot = rots_arr[ri];
                int rw = (rot == 0) ? items[ti].w : items[ti].h;
                int rh = (rot == 0) ? items[ti].h : items[ti].w;
                if (rw > gW || rh > gH) continue;
                for (auto& fr : state.freeRects) {
                    if (rw <= fr.w && rh <= fr.h) {
                        int x = fr.x, y = fr.y;
                        double fitScore;
                        int ss = min(fr.w - rw, fr.h - rh);
                        int ls = max(fr.w - rw, fr.h - rh);
                        switch(strategy) {
                            case 0: fitScore = -ss; break;
                            case 1: fitScore = -ls; break;
                            case 2: fitScore = -(double)(fr.w * fr.h - rw * rh); break;
                            default: fitScore = -(y * 20000.0 + x); break;
                        }
                        double eval = alpha * density[ti] + (1.0 - alpha) * fitScore / (double)(gW + gH);
                        if (eval > bestEval) {
                            bestEval = eval;
                            bestTi = ti; bestRot = rot; bestX = x; bestY = y;
                        }
                    }
                }
            }
        }
        if (bestTi < 0) break;
        state.doPlace(bestTi, bestX, bestY, bestRot);
    }
    updateBest(state);
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);
    
    string input((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());
    
    auto findKey = [&](const string& s, const string& key, size_t start = 0) -> size_t {
        string k = "\"" + key + "\"";
        return s.find(k, start);
    };
    auto readInt = [&](const string& s, size_t pos) -> pair<long long, size_t> {
        while (pos < s.size() && !isdigit(s[pos]) && s[pos] != '-') pos++;
        bool neg = false;
        if (s[pos] == '-') { neg = true; pos++; }
        long long v = 0;
        while (pos < s.size() && isdigit(s[pos])) { v = v * 10 + (s[pos] - '0'); pos++; }
        return {neg ? -v : v, pos};
    };
    auto readString = [&](const string& s, size_t pos) -> pair<string, size_t> {
        while (pos < s.size() && s[pos] != '"') pos++;
        pos++;
        string result;
        while (pos < s.size() && s[pos] != '"') { result += s[pos]; pos++; }
        pos++;
        return {result, pos};
    };
    auto readBool = [&](const string& s, size_t pos) -> pair<bool, size_t> {
        while (pos < s.size() && s[pos] != 't' && s[pos] != 'f') pos++;
        if (s[pos] == 't') return {true, pos + 4};
        return {false, pos + 5};
    };
    
    {
        size_t p = findKey(input, "W");
        auto [v, np] = readInt(input, p + 3);
        gW = (int)v;
        p = findKey(input, "H");
        // Make sure we find standalone "H" not part of another key
        while (p != string::npos) {
            // Check it's "H" exactly
            if (input[p+1] == 'H' && input[p+2] == '"') break;
            p = findKey(input, "H", p + 1);
        }
        auto [v2, np2] = readInt(input, p + 3);
        gH = (int)v2;
        p = findKey(input, "allow_rotate");
        auto [b, np3] = readBool(input, p + 14);
        gAllowRotate = b;
    }
    
    {
        size_t p = findKey(input, "items");
        p = input.find('[', p);
        while (true) {
            size_t nextObj = input.find('{', p);
            if (nextObj == string::npos) break;
            // Find matching closing brace
            size_t endObj = input.find('}', nextObj);
            if (endObj == string::npos) break;
            // Check if this is past the items array
            size_t closeBracket = input.find(']', p);
            if (closeBracket != string::npos && nextObj > closeBracket) break;
            
            string obj = input.substr(nextObj, endObj - nextObj + 1);
            ItemType it;
            
            size_t tp = findKey(obj, "type");
            auto [ts, _1] = readString(obj, tp + 6);
            it.type = ts;
            
            // Find "w" key carefully
            size_t wp = 0;
            while (true) {
                wp = findKey(obj, "w", wp);
                if (wp == string::npos) break;
                if (obj[wp+1] == 'w' && obj[wp+2] == '"') break;
                wp += 2;
            }
            auto [wv, _2] = readInt(obj, wp + 3);
            it.w = (int)wv;
            
            size_t hp = 0;
            while (true) {
                hp = findKey(obj, "h", hp);
                if (hp == string::npos) break;
                if (obj[hp+1] == 'h' && obj[hp+2] == '"') break;
                hp += 2;
            }
            auto [hv, _3] = readInt(obj, hp + 3);
            it.h = (int)hv;
            
            size_t vp = findKey(obj, "v");
            auto [vv, _4] = readInt(obj, vp + 3);
            it.v = (int)vv;
            
            size_t lp = findKey(obj, "limit");
            auto [lv, _5] = readInt(obj, lp + 7);
            it.limit = (int)lv;
            
            items.push_back(it);
            p = endObj + 1;
        }
    }
    
    gM = (int)items.size();
    density.resize(gM);
    for (int i = 0; i < gM; i++)
        density[i] = (double)items[i].v / ((double)items[i].w * items[i].h);
    
    auto clock_start = chrono::steady_clock::now();
    auto elapsed_ms = [&]() {
        return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - clock_start).count();
    };
    
    // Helper to build order
    auto makeOrder = [&](int sortMode, mt19937& rng) -> vector<pair<int,int>> {
        struct Cand { int ti, rot; double score; };
        vector<Cand> cands;
        for (int i = 0; i < gM; i++) {
            vector<int> rots = {0};
            if (gAllowRotate && items[i].w != items[i].h) rots.push_back(1);
            for (int r : rots) {
                int rw = (r == 0) ? items[i].w : items[i].h;
                int rh = (r == 0) ? items[i].h : items[i].w;
                if (rw > gW || rh > gH) continue;
                double sc;
                switch(sortMode) {
                    case 0: sc = density[i]; break;
                    case 1: sc = (double)items[i].v; break;
                    case 2: sc = -(double)(items[i].w * items[i].h); break;
                    case 3: sc = (double)(items[i].w * items[i].h); break;
                    case 4: sc = -max(rw, rh); break;
                    case 5: sc = max(rw, rh); break;
                    case 6: sc = density[i] + 0.001 * max(rw, rh); break;
                    case 7: sc = density[i] - 0.001 * max(rw, rh); break;
                    default: {
                        uniform_real_distribution<double> dist(0.0, 1.0);
                        sc = dist(rng);
                        break;
                    }
                }
                for (int k = 0; k < items[i].limit; k++)
                    cands.push_back({i, r, sc});
            }
        }
        if (sortMode >= 8) {
            shuffle(cands.begin(), cands.end(), rng);
        } else {
            sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) { return a.score > b.score; });
        }
        vector<pair<int,int>> result;
        vector<int> uc(gM, 0);
        for (auto& c : cands) {
            if (uc[c.ti] < items[c.ti].limit) {
                result.push_back({c.ti, c.rot});
                uc[c.ti]++;
            }
        }
        return result;
    };
    
    mt19937 rng(42);
    
    // Deterministic orderings
    for (int sm = 0; sm < 8 && elapsed_ms() < 300; sm++) {
        for (int ps = 0; ps < 5 && elapsed_ms() < 300; ps++) {
            auto order = makeOrder(sm, rng);
            runGreedy(order, ps);
        }
    }
    
    // Smart greedy with different alpha values
    for (double alpha : {0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0}) {
        for (int ps = 0; ps < 4 && elapsed_ms() < 600; ps++) {
            runSmart(ps, alpha);
        }
    }
    
    // Random restarts for remaining time
    while (elapsed_ms() < 900) {
        int sm = 8; // random
        int ps = rng() % 5;
        auto order = makeOrder(sm, rng);
        runGreedy(order, ps);
    }
    
    // Output
    cout << "{\"placements\":[";
    for (int i = 0; i < (int)bestPlacements.size(); i++) {
        if (i > 0) cout << ",";
        auto& p = bestPlacements[i];
        cout << "{\"type\":\"" << p.type << "\",\"x\":" << p.x << ",\"y\":" << p.y << ",\"rot\":" << p.rot << "}";
    }
    cout << "]}" << endl;
    
    return 0;
}
