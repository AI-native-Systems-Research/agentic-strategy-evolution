// Best approach so far: skyline packing with multiple orderings
// Focus on smart width selection
// 90 CW = (x,y) -> (y, -x)
#include <bits/stdc++.h>
using namespace std;

struct Orientation {
    vector<pair<int,int>> cells;
    int w, h;
    int rot, flip;
    int minx_raw, miny_raw;
};

pair<int,int> transformCell(int x, int y, int rot, int flip) {
    if (flip) x = -x;
    for (int r = 0; r < rot; r++) {
        int nx = y, ny = -x;
        x = nx; y = ny;
    }
    return {x, y};
}

vector<Orientation> getOrientations(const vector<pair<int,int>>& cells) {
    set<vector<pair<int,int>>> seen;
    vector<Orientation> result;
    for (int flip = 0; flip <= 1; flip++) {
        for (int rot = 0; rot < 4; rot++) {
            vector<pair<int,int>> transformed;
            for (auto [x, y] : cells) {
                auto [nx, ny] = transformCell(x, y, rot, flip);
                transformed.push_back({nx, ny});
            }
            int minx = INT_MAX, miny = INT_MAX;
            for (auto [x, y] : transformed) {
                minx = min(minx, x);
                miny = min(miny, y);
            }
            vector<pair<int,int>> normalized;
            for (auto [x, y] : transformed) {
                normalized.push_back({x - minx, y - miny});
            }
            sort(normalized.begin(), normalized.end());
            if (seen.insert(normalized).second) {
                int w = 0, h = 0;
                for (auto [x, y] : normalized) {
                    w = max(w, x + 1);
                    h = max(h, y + 1);
                }
                result.push_back({normalized, w, h, rot, flip, minx, miny});
            }
        }
    }
    return result;
}

int n;
vector<int> ks;
vector<vector<Orientation>> allOrients;

struct PlaceInfo { int px, py, oi; };

int solveSkyline(int W, const vector<int>& order, vector<PlaceInfo>& placements) {
    vector<int> skyline(W, 0);
    placements.resize(n);
    
    for (int idx = 0; idx < n; idx++) {
        int i = order[idx];
        int bestMaxH = INT_MAX, bestY = INT_MAX, bestX = INT_MAX, bestOI = -1;
        
        for (int oi = 0; oi < (int)allOrients[i].size(); oi++) {
            auto& ori = allOrients[i][oi];
            if (ori.w > W) continue;
            
            for (int sx = 0; sx <= W - ori.w; sx++) {
                int minY = 0;
                for (auto& [cx, cy] : ori.cells) {
                    int needed = skyline[sx + cx] - cy;
                    if (needed > minY) minY = needed;
                }
                int maxH = 0;
                for (auto& [cx, cy] : ori.cells) {
                    int h = minY + cy + 1;
                    if (h > maxH) maxH = h;
                }
                if (maxH < bestMaxH || (maxH == bestMaxH && minY < bestY) ||
                    (maxH == bestMaxH && minY == bestY && sx < bestX)) {
                    bestMaxH = maxH;
                    bestY = minY;
                    bestX = sx;
                    bestOI = oi;
                }
            }
        }
        
        if (bestOI == -1) return INT_MAX;
        
        auto& ori = allOrients[i][bestOI];
        placements[i] = {bestX, bestY, bestOI};
        for (auto& [cx, cy] : ori.cells) {
            int col = bestX + cx;
            int h = bestY + cy + 1;
            if (h > skyline[col]) skyline[col] = h;
        }
    }
    return *max_element(skyline.begin(), skyline.end());
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    cin >> n;
    ks.resize(n);
    vector<vector<pair<int,int>>> origCells(n);
    int totalCells = 0;
    
    for (int i = 0; i < n; i++) {
        cin >> ks[i];
        origCells[i].resize(ks[i]);
        for (int j = 0; j < ks[i]; j++) {
            cin >> origCells[i][j].first >> origCells[i][j].second;
        }
        totalCells += ks[i];
    }
    
    allOrients.resize(n);
    for (int i = 0; i < n; i++) {
        allOrients[i] = getOrientations(origCells[i]);
    }
    
    int sideEst = (int)ceil(sqrt((double)totalCells));
    
    int minWidth = 1;
    for (int i = 0; i < n; i++) {
        int minW = INT_MAX;
        for (auto& ori : allOrients[i]) {
            minW = min(minW, ori.w);
        }
        minWidth = max(minWidth, minW);
    }
    
    // Create orderings
    vector<vector<int>> orderings;
    
    auto addOrdering = [&](auto cmp) {
        vector<int> ord(n);
        iota(ord.begin(), ord.end(), 0);
        sort(ord.begin(), ord.end(), cmp);
        orderings.push_back(ord);
    };
    
    // 1. By size descending
    addOrdering([&](int a, int b) { return ks[a] > ks[b]; });
    
    // 2. By max bounding box dim descending
    addOrdering([&](int a, int b) {
        int ma = 0, mb = 0;
        for (auto& o : allOrients[a]) ma = max(ma, max(o.w, o.h));
        for (auto& o : allOrients[b]) mb = max(mb, max(o.w, o.h));
        return ma != mb ? ma > mb : ks[a] > ks[b];
    });
    
    // 3. By height descending
    addOrdering([&](int a, int b) {
        int ha = 0, hb = 0;
        for (auto& o : allOrients[a]) ha = max(ha, o.h);
        for (auto& o : allOrients[b]) hb = max(hb, o.h);
        return ha != hb ? ha > hb : ks[a] > ks[b];
    });
    
    // 4. By width descending
    addOrdering([&](int a, int b) {
        int wa = 0, wb = 0;
        for (auto& o : allOrients[a]) wa = max(wa, o.w);
        for (auto& o : allOrients[b]) wb = max(wb, o.w);
        return wa != wb ? wa > wb : ks[a] > ks[b];
    });
    
    // 5. By number of orientations ascending (most constrained first)
    addOrdering([&](int a, int b) {
        if (allOrients[a].size() != allOrients[b].size())
            return allOrients[a].size() < allOrients[b].size();
        return ks[a] > ks[b];
    });
    
    int64_t bestArea = (int64_t)1e18;
    int bestW = -1, bestH = -1;
    vector<PlaceInfo> bestPlacements;
    
    auto start_time = chrono::steady_clock::now();
    auto elapsed_ms = [&]() {
        return chrono::duration_cast<chrono::milliseconds>(
            chrono::steady_clock::now() - start_time).count();
    };
    
    auto tryConfig = [&](int W, const vector<int>& order) {
        if (W < minWidth) return;
        int minH = (totalCells + W - 1) / W;
        if ((int64_t)W * minH >= bestArea) return; // can't improve
        vector<PlaceInfo> placements;
        int H = solveSkyline(W, order, placements);
        if (H == INT_MAX) return;
        int64_t area = (int64_t)W * H;
        if (area < bestArea || (area == bestArea && H < bestH)) {
            bestArea = area;
            bestW = W; bestH = H;
            bestPlacements = placements;
        }
    };
    
    // For each ordering, try widths around sideEst
    for (auto& ord : orderings) {
        if (elapsed_ms() > 1800) break;
        
        tryConfig(sideEst, ord);
        
        for (int delta = 1; delta <= sideEst * 2; delta++) {
            if (elapsed_ms() > 1800) break;
            
            if (sideEst - delta >= minWidth)
                tryConfig(sideEst - delta, ord);
            if (sideEst + delta <= totalCells)
                tryConfig(sideEst + delta, ord);
        }
    }
    
    // Fallback
    if (bestW == -1) {
        vector<int> ord(n);
        iota(ord.begin(), ord.end(), 0);
        tryConfig(totalCells, ord);
    }
    
    cout << bestW << " " << bestH << "\n";
    for (int i = 0; i < n; i++) {
        auto& pi = bestPlacements[i];
        auto& ori = allOrients[i][pi.oi];
        int X = pi.px - ori.minx_raw;
        int Y = pi.py - ori.miny_raw;
        cout << X << " " << Y << " " << ori.rot << " " << ori.flip << "\n";
    }
    
    return 0;
}
