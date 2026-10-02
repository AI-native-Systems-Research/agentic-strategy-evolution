// Approach: Improved skyline packing with better gap-filling and scoring
// Key improvements over Agent 1:
// 1. Consider rectangular W x H (not just square), pick smallest area with max(W,H)
// 2. Better waste-aware scoring (penalize gaps created)
// 3. Try filling gaps below skyline proactively
// 4. Skyline-aware placement: for each x, compute ideal y from per-column heights of piece
// 5. Sort orientations to prefer flat/wide ones

#include <bits/stdc++.h>
using namespace std;
using namespace chrono;

auto globalStart = steady_clock::now();
long long elapsed_ms() {
    return duration_cast<milliseconds>(steady_clock::now() - globalStart).count();
}

struct Orientation {
    vector<pair<int,int>> cells;
    int w, h;
    int r, f;
    int offx, offy;
    // Per-column info: for each relative x, what's the min and max relative y
    vector<int> colMinY, colMaxY;
};

pair<int,int> transformCell(int x, int y, int r, int f) {
    if (f == 1) x = -x;
    for (int i = 0; i < r; i++) {
        int nx = y, ny = -x;
        x = nx; y = ny;
    }
    return {x, y};
}

vector<Orientation> generateOrientations(const vector<pair<int,int>>& cells) {
    vector<Orientation> result;
    set<vector<pair<int,int>>> seen;
    for (int f = 0; f <= 1; f++) {
        for (int r = 0; r < 4; r++) {
            vector<pair<int,int>> tc;
            int minx = INT_MAX, miny = INT_MAX;
            for (auto [x, y] : cells) {
                auto [tx, ty] = transformCell(x, y, r, f);
                tc.push_back({tx, ty});
                minx = min(minx, tx);
                miny = min(miny, ty);
            }
            vector<pair<int,int>> normalized;
            for (auto [x, y] : tc) {
                normalized.push_back({x - minx, y - miny});
            }
            sort(normalized.begin(), normalized.end());
            if (seen.count(normalized)) continue;
            seen.insert(normalized);
            int w = 0, h = 0;
            for (auto [x, y] : normalized) {
                w = max(w, x + 1);
                h = max(h, y + 1);
            }
            // Compute per-column min/max y
            vector<int> colMin(w, INT_MAX), colMax(w, INT_MIN);
            for (auto [x, y] : normalized) {
                colMin[x] = min(colMin[x], y);
                colMax[x] = max(colMax[x], y);
            }
            result.push_back({normalized, w, h, r, f, minx, miny, colMin, colMax});
        }
    }
    return result;
}

struct Placement {
    int x, y, r, f, offx, offy;
};

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    int n;
    cin >> n;
    
    vector<int> ks(n);
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
    
    vector<vector<Orientation>> allOri(n);
    for (int i = 0; i < n; i++) {
        allOri[i] = generateOrientations(origCells[i]);
    }
    
    int maxDim = 0;
    for (int i = 0; i < n; i++) {
        for (auto& o : allOri[i]) {
            maxDim = max(maxDim, max(o.w, o.h));
        }
    }
    
    // Sort: largest first, then by fewer orientations (more constrained)
    vector<int> order(n);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int a, int b) {
        if (ks[a] != ks[b]) return ks[a] > ks[b];
        return allOri[a].size() < allOri[b].size();
    });
    
    auto tryPack = [&](int S) -> pair<bool, vector<Placement>> {
        vector<uint8_t> grid(S * S, 0);
        vector<int> skyline(S, 0); // skyline[x] = highest occupied y+1 in column x
        vector<Placement> placements(n);
        
        for (int idx = 0; idx < n; idx++) {
            int i = order[idx];
            int bestMaxY = INT_MAX;
            int bestWaste = INT_MAX;
            int bestOri = -1, bestPX = -1, bestPY = -1;
            
            for (int o = 0; o < (int)allOri[i].size(); o++) {
                auto& ori = allOri[i][o];
                if (ori.w > S || ori.h > S) continue;
                
                for (int px = 0; px <= S - ori.w; px++) {
                    // Compute the minimum py such that the piece doesn't go below
                    // any existing skyline cell
                    int minPY = 0;
                    for (int cx = 0; cx < ori.w; cx++) {
                        if (ori.colMinY[cx] == INT_MAX) continue;
                        int needed = skyline[px + cx] - ori.colMinY[cx];
                        minPY = max(minPY, needed);
                    }
                    if (minPY < 0) minPY = 0;
                    if (minPY + ori.h > S) continue;
                    
                    // Try placing at minPY first (skyline-aligned), then a few below if there are gaps
                    // Also try at y=0 to see if we can fill gaps below skyline
                    
                    // We'll try a few y values: starting from 0 (gap filling) and from minPY (skyline)
                    int attempts = 0;
                    for (int py = max(0, minPY - ori.h); py <= min(minPY + 2, S - ori.h); py++) {
                        if (py < 0) continue;
                        if (attempts >= 5) break;
                        
                        bool fits = true;
                        for (auto& [cx, cy] : ori.cells) {
                            if (grid[(px + cx) * S + (py + cy)]) {
                                fits = false;
                                break;
                            }
                        }
                        if (!fits) continue;
                        attempts++;
                        
                        // Compute new maxY across all columns
                        int maxY = 0;
                        for (auto& [cx, cy] : ori.cells) {
                            maxY = max(maxY, py + cy + 1);
                        }
                        // Take the global max with existing skyline
                        for (int c = 0; c < S; c++) {
                            maxY = max(maxY, skyline[c]);
                        }
                        
                        // Compute waste: empty cells between old skyline and new piece placement
                        int waste = 0;
                        for (int cx = 0; cx < ori.w; cx++) {
                            int col = px + cx;
                            int newSky = skyline[col];
                            for (auto& [ccx, ccy] : ori.cells) {
                                if (ccx == cx) {
                                    newSky = max(newSky, py + ccy + 1);
                                }
                            }
                            for (int row = skyline[col]; row < newSky; row++) {
                                bool isPlaced = false;
                                for (auto& [ccx, ccy] : ori.cells) {
                                    if (ccx == cx && py + ccy == row) {
                                        isPlaced = true;
                                        break;
                                    }
                                }
                                if (!isPlaced && !grid[col * S + row]) waste++;
                            }
                        }
                        
                        bool better = false;
                        if (maxY < bestMaxY) better = true;
                        else if (maxY == bestMaxY && waste < bestWaste) better = true;
                        else if (maxY == bestMaxY && waste == bestWaste && bestOri == -1) better = true;
                        
                        if (better) {
                            bestMaxY = maxY;
                            bestWaste = waste;
                            bestOri = o;
                            bestPX = px;
                            bestPY = py;
                        }
                        
                        if (py >= minPY) break; // found valid placement at/above skyline
                    }
                }
            }
            
            if (bestOri < 0) return {false, {}};
            
            auto& ori = allOri[i][bestOri];
            for (auto& [cx, cy] : ori.cells) {
                grid[(bestPX + cx) * S + (bestPY + cy)] = 1;
                skyline[bestPX + cx] = max(skyline[bestPX + cx], bestPY + cy + 1);
            }
            placements[i] = {bestPX, bestPY, ori.r, ori.f, ori.offx, ori.offy};
        }
        
        return {true, placements};
    };
    
    int sqrtTC = (int)ceil(sqrt((double)totalCells));
    int lo = max(sqrtTC, maxDim);
    int initS = (int)ceil(sqrt((double)totalCells * 1.25));
    initS = max(initS, maxDim);
    
    vector<Placement> bestPlacements;
    int bestS = -1;
    
    // First find a valid solution
    for (int s = initS; s <= initS + 500; s += 5) {
        if (elapsed_ms() > 3000) break;
        auto [ok, pl] = tryPack(s);
        if (ok) {
            bestS = s;
            bestPlacements = pl;
            break;
        }
    }
    
    if (bestS < 0) {
        auto [ok, pl] = tryPack(2000);
        if (ok) {
            bestS = 2000;
            bestPlacements = pl;
        }
    }
    
    // Binary search for minimum S
    if (bestS >= 0) {
        int hi = bestS;
        while (lo < hi && elapsed_ms() < 4200) {
            int mid = (lo + hi) / 2;
            auto [ok, pl] = tryPack(mid);
            if (ok) {
                hi = mid;
                bestS = mid;
                bestPlacements = pl;
            } else {
                lo = mid + 1;
            }
        }
    }
    
    cout << bestS << " " << bestS << "\n";
    for (int i = 0; i < n; i++) {
        int X = bestPlacements[i].x - bestPlacements[i].offx;
        int Y = bestPlacements[i].y - bestPlacements[i].offy;
        cout << X << " " << Y << " " << bestPlacements[i].r << " " << bestPlacements[i].f << "\n";
    }
    
    return 0;
}