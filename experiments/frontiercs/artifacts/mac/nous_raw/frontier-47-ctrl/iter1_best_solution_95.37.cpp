#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdio>
#include <climits>
#include <cstdlib>
#include <ctime>
#include <chrono>
#include <sstream>
#include <iterator>
#include <random>
using namespace std;

struct Rect { int x, y, w, h; };
struct ItemType { string type; int w, h; long long v; int limit; };
struct Placement { string type; int x, y, rot; };

struct MaxRectsBin {
    int W, H;
    vector<Rect> freeRects;

    void init(int w, int h) {
        W = w; H = h;
        freeRects.clear();
        freeRects.push_back({0, 0, w, h});
    }

    int findBest(int iw, int ih, int &bestX, int &bestY, int heuristic) {
        int bestScore1 = INT_MAX, bestScore2 = INT_MAX;
        int bestIdx = -1;
        for (int i = 0; i < (int)freeRects.size(); i++) {
            auto &r = freeRects[i];
            if (r.w >= iw && r.h >= ih) {
                int s1, s2;
                if (heuristic == 0) { // BSSF
                    s1 = min(r.h - ih, r.w - iw);
                    s2 = max(r.h - ih, r.w - iw);
                } else if (heuristic == 1) { // BAF
                    s1 = r.w * r.h;
                    s2 = min(r.h - ih, r.w - iw);
                } else { // BL (bottom-left)
                    s1 = r.y;
                    s2 = r.x;
                }
                if (s1 < bestScore1 || (s1 == bestScore1 && s2 < bestScore2)) {
                    bestScore1 = s1; bestScore2 = s2;
                    bestIdx = i; bestX = r.x; bestY = r.y;
                }
            }
        }
        return bestIdx;
    }

    bool place(int iw, int ih, int &px, int &py, int heuristic) {
        int bx, by;
        int idx = findBest(iw, ih, bx, by, heuristic);
        if (idx == -1) return false;
        px = bx; py = by;
        Rect placed = {bx, by, iw, ih};
        splitFreeRects(placed);
        pruneFreeRects();
        return true;
    }

    void splitFreeRects(const Rect &p) {
        vector<Rect> nf;
        for (auto &r : freeRects) {
            if (p.x >= r.x + r.w || p.x + p.w <= r.x ||
                p.y >= r.y + r.h || p.y + p.h <= r.y) {
                nf.push_back(r); continue;
            }
            if (p.x > r.x) nf.push_back({r.x, r.y, p.x - r.x, r.h});
            if (p.x + p.w < r.x + r.w) nf.push_back({p.x + p.w, r.y, r.x + r.w - p.x - p.w, r.h});
            if (p.y > r.y) nf.push_back({r.x, r.y, r.w, p.y - r.y});
            if (p.y + p.h < r.y + r.h) nf.push_back({r.x, p.y + p.h, r.w, r.y + r.h - p.y - p.h});
        }
        freeRects = nf;
    }

    void pruneFreeRects() {
        int n = freeRects.size();
        vector<bool> rm(n, false);
        for (int i = 0; i < n; i++) {
            if (rm[i]) continue;
            for (int j = i + 1; j < n; j++) {
                if (rm[j]) continue;
                auto &a = freeRects[i], &b = freeRects[j];
                if (b.x >= a.x && b.y >= a.y && b.x+b.w <= a.x+a.w && b.y+b.h <= a.y+a.h) rm[j] = true;
                else if (a.x >= b.x && a.y >= b.y && a.x+a.w <= b.x+b.w && a.y+a.h <= b.y+b.h) { rm[i] = true; break; }
            }
        }
        vector<Rect> pruned;
        for (int i = 0; i < n; i++) if (!rm[i]) pruned.push_back(freeRects[i]);
        freeRects = pruned;
    }
};

struct Candidate {
    int itemIdx; int w, h, rot;
    double score;
};

int main() {
    auto startTime = chrono::steady_clock::now();

    string input((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());

    int W, H;
    bool allowRotate = false;
    vector<ItemType> items;

    // Parse bin
    {
        auto binPos = input.find("\"bin\"");
        auto pos = input.find("\"W\"", binPos);
        auto col = input.find(':', pos);
        sscanf(input.c_str() + col + 1, " %d", &W);
        pos = input.find("\"H\"", binPos);
        // Careful: "H" might match inside other strings, so search near bin
        // Find "H" that's after "W" within bin section
        col = input.find(':', pos);
        sscanf(input.c_str() + col + 1, " %d", &H);

        pos = input.find("\"allow_rotate\"");
        if (pos != string::npos) {
            auto sub = input.substr(pos, 40);
            allowRotate = (sub.find("true") != string::npos);
        }
    }

    // Parse items
    {
        size_t searchFrom = input.find("\"items\"");
        if (searchFrom == string::npos) { cout << "{\"placements\":[]}" << endl; return 0; }
        while (true) {
            auto typePos = input.find("\"type\"", searchFrom);
            if (typePos == string::npos) break;
            auto q1 = input.find(':', typePos);
            auto q2 = input.find('"', q1 + 1);
            auto q3 = input.find('"', q2 + 1);
            string typeName = input.substr(q2 + 1, q3 - q2 - 1);
            auto nextType = input.find("\"type\"", typePos + 1);
            string block = (nextType == string::npos) ? input.substr(typePos) : input.substr(typePos, nextType - typePos);
            auto extractInt = [&](const string &b, const string &key) -> long long {
                auto p = b.find("\"" + key + "\"");
                if (p == string::npos) return 0;
                auto c = b.find(':', p);
                long long val = 0;
                sscanf(b.c_str() + c + 1, " %lld", &val);
                return val;
            };
            ItemType it;
            it.type = typeName;
            it.w = (int)extractInt(block, "w");
            it.h = (int)extractInt(block, "h");
            it.v = extractInt(block, "v");
            it.limit = (int)extractInt(block, "limit");
            items.push_back(it);
            searchFrom = typePos + 1;
        }
    }

    vector<Placement> bestPlacements;
    long long bestProfit = 0;

    auto tryPacking = [&](vector<Candidate> &cands, int heuristic) {
        MaxRectsBin bin;
        bin.init(W, H);
        vector<int> used(items.size(), 0);
        vector<Placement> pls;
        long long profit = 0;
        for (auto &c : cands) {
            while (used[c.itemIdx] < items[c.itemIdx].limit) {
                int px, py;
                if (bin.place(c.w, c.h, px, py, heuristic)) {
                    pls.push_back({items[c.itemIdx].type, px, py, c.rot});
                    profit += items[c.itemIdx].v;
                    used[c.itemIdx]++;
                } else break;
            }
        }
        if (profit > bestProfit) { bestProfit = profit; bestPlacements = pls; }
    };

    auto makeCandidates = [&]() -> vector<Candidate> {
        vector<Candidate> cands;
        for (int i = 0; i < (int)items.size(); i++) {
            double area = (double)items[i].w * items[i].h;
            cands.push_back({i, items[i].w, items[i].h, 0, (double)items[i].v / area});
            if (allowRotate && items[i].w != items[i].h) {
                cands.push_back({i, items[i].h, items[i].w, 1, (double)items[i].v / area});
            }
        }
        return cands;
    };

    // Deterministic strategies
    auto runDeterministicStrategies = [&]() {
        // By density
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [](auto &a, auto &b){ return a.score > b.score; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By area desc
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [](auto &a, auto &b){ return a.w*a.h > b.w*b.h; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By height desc
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [](auto &a, auto &b){ return a.h > b.h; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By width desc
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [](auto &a, auto &b){ return a.w > b.w; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By value desc
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [&](auto &a, auto &b){ return items[a.itemIdx].v > items[b.itemIdx].v; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By perimeter desc
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [](auto &a, auto &b){ return (a.w+a.h) > (b.w+b.h); }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By value*density
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [&](auto &a, auto &b){ return items[a.itemIdx].v*a.score > items[b.itemIdx].v*b.score; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By max(w,h) desc (longer side first)
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [](auto &a, auto &b){ return max(a.w,a.h) > max(b.w,b.h); }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By limit asc (scarce items first)
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [&](auto &a, auto &b){ return items[a.itemIdx].limit < items[b.itemIdx].limit; }); for(int h=0;h<3;h++) tryPacking(c,h); }
        // By total_value_potential (v * min(limit, area_fit)) desc
        { auto c = makeCandidates(); sort(c.begin(), c.end(), [&](auto &a, auto &b){
            long long pa = items[a.itemIdx].v * (long long)min(items[a.itemIdx].limit, (W*H)/(a.w*a.h+1));
            long long pb = items[b.itemIdx].v * (long long)min(items[b.itemIdx].limit, (W*H)/(b.w*b.h+1));
            return pa > pb;
        }); for(int h=0;h<3;h++) tryPacking(c,h); }
    };

    runDeterministicStrategies();

    // Randomized restarts within time budget
    mt19937 rng(42);
    auto elapsed_ms = [&]() {
        return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - startTime).count();
    };

    while (elapsed_ms() < 750) {
        auto cands = makeCandidates();
        // Shuffle with random perturbation of scores
        for (auto &c : cands) {
            c.score = (double)items[c.itemIdx].v / ((double)c.w * c.h) * (0.5 + (rng() % 1000) / 1000.0);
        }
        sort(cands.begin(), cands.end(), [](auto &a, auto &b){ return a.score > b.score; });
        int h = rng() % 3;
        tryPacking(cands, h);
    }

    // Output
    cout << "{\"placements\":[";
    for (int i = 0; i < (int)bestPlacements.size(); i++) {
        if (i > 0) cout << ",";
        auto &p = bestPlacements[i];
        cout << "{\"type\":\"" << p.type << "\",\"x\":" << p.x
             << ",\"y\":" << p.y << ",\"rot\":" << p.rot << "}";
    }
    cout << "]}" << endl;
    return 0;
}
