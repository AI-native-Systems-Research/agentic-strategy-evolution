// Skyline-based greedy polyomino packer with multi-width sweep
// Strategy: enumerate all orientations, greedy bottom-left placement,
// sweep across candidate widths, time-managed to stay within 2s.
#include <bits/stdc++.h>
using namespace std;

struct Trans {
    int w, h;
    vector<pair<int,int>> cells; // normalized cells (min at 0,0)
    vector<int> lo, hi; // per-column min/max y
    int r, f; // rotation and flip used
    int orig_minx, orig_miny; // for recovering transform params
};

struct Piece {
    int id, k;
    vector<pair<int,int>> base;
    vector<Trans> orientations;
    int minW, minH;
};

struct Placement {
    int piece_idx, orient_idx, x, y;
};

struct Result {
    long long area;
    int W, H;
    vector<Placement> placements;
};

static pair<int,int> rot90cw(int x, int y, int r) {
    switch(r & 3) {
        case 0: return {x, y};
        case 1: return {y, -x};
        case 2: return {-x, -y};
        default: return {-y, x};
    }
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    cin >> n;

    vector<Piece> pieces(n);
    long long totalCells = 0;

    for(int i = 0; i < n; i++){
        int k; cin >> k;
        pieces[i].id = i;
        pieces[i].k = k;
        pieces[i].base.resize(k);
        for(int j = 0; j < k; j++){
            cin >> pieces[i].base[j].first >> pieces[i].base[j].second;
        }
        totalCells += k;
    }

    // Generate all unique orientations for each piece
    for(int i = 0; i < n; i++){
        auto &p = pieces[i];
        p.minW = INT_MAX;
        p.minH = INT_MAX;
        set<vector<pair<int,int>>> seen;

        for(int flip = 0; flip < 2; flip++){
            vector<pair<int,int>> src = p.base;
            if(flip) for(auto &[x,y] : src) x = -x;

            for(int rot = 0; rot < 4; rot++){
                vector<pair<int,int>> v = src;
                for(auto &[x,y] : v) tie(x,y) = rot90cw(x, y, rot);

                int minx = INT_MAX, miny = INT_MAX;
                int maxx = INT_MIN, maxy = INT_MIN;
                for(auto &[x,y] : v){
                    minx = min(minx, x); miny = min(miny, y);
                    maxx = max(maxx, x); maxy = max(maxy, y);
                }

                // Normalize to origin
                vector<pair<int,int>> norm = v;
                for(auto &[x,y] : norm){ x -= minx; y -= miny; }
                sort(norm.begin(), norm.end());

                if(seen.insert(norm).second){
                    Trans t;
                    t.w = maxx - minx + 1;
                    t.h = maxy - miny + 1;
                    t.cells = norm;
                    t.r = rot;
                    t.f = flip;
                    t.orig_minx = minx;
                    t.orig_miny = miny;
                    t.lo.assign(t.w, INT_MAX);
                    t.hi.assign(t.w, INT_MIN);
                    for(auto &[x,y] : norm){
                        t.lo[x] = min(t.lo[x], y);
                        t.hi[x] = max(t.hi[x], y);
                    }
                    p.orientations.push_back(move(t));
                }
            }
        }

        for(auto &t : p.orientations){
            p.minW = min(p.minW, t.w);
            p.minH = min(p.minH, t.h);
        }
        if(p.orientations.empty()){
            // single cell
            Trans t;
            t.w = 1; t.h = 1; t.cells = {{0,0}};
            t.lo = {0}; t.hi = {0};
            t.r = 0; t.f = 0; t.orig_minx = 0; t.orig_miny = 0;
            p.orientations.push_back(t);
            p.minW = 1; p.minH = 1;
        }
    }

    // Sort pieces: larger pieces first (decreasing area), then by min dimension
    vector<int> order(n);
    iota(order.begin(), order.end(), 0);
    stable_sort(order.begin(), order.end(), [&](int a, int b){
        if(pieces[a].k != pieces[b].k) return pieces[a].k > pieces[b].k;
        int da = min(pieces[a].minW, pieces[a].minH);
        int db = min(pieces[b].minW, pieces[b].minH);
        return da > db;
    });

    // Skyline packer for a given width W
    auto pack = [&](int W, const vector<int>& ord) -> Result {
        vector<int> skyline(W, 0);
        int maxH = 0;
        vector<Placement> placements;
        placements.reserve(n);

        for(int idx : ord){
            auto &p = pieces[idx];
            long long bestScore = LLONG_MAX;
            int bestTi = -1, bestX = 0, bestY = 0;
            int bestLocalH = INT_MAX;
            long long bestDelta = LLONG_MAX;

            for(int ti = 0; ti < (int)p.orientations.size(); ti++){
                auto &t = p.orientations[ti];
                if(t.w > W) continue;

                int positions = W - t.w + 1;
                for(int x0 = 0; x0 < positions; x0++){
                    // Find lowest y where piece fits
                    int y0 = 0;
                    for(int j = 0; j < t.w; j++){
                        if(t.lo[j] != INT_MAX){
                            int needed = skyline[x0+j] - t.lo[j];
                            y0 = max(y0, needed);
                        }
                    }

                    // Compute new local max height
                    int localH = maxH;
                    long long deltaSum = 0;
                    for(int j = 0; j < t.w; j++){
                        int nh = skyline[x0+j];
                        if(t.hi[j] != INT_MIN){
                            nh = max(nh, y0 + t.hi[j] + 1);
                        }
                        localH = max(localH, nh);
                        long long inc = nh - skyline[x0+j];
                        if(inc > 0) deltaSum += inc;
                    }

                    // Score: minimize max height, then delta, then local height
                    long long score = (long long)localH * 1000000LL + deltaSum;
                    if(score < bestScore || (score == bestScore && y0 < bestY)){
                        bestScore = score;
                        bestTi = ti;
                        bestX = x0;
                        bestY = y0;
                        bestLocalH = localH;
                        bestDelta = deltaSum;
                    }
                }
            }

            if(bestTi == -1) continue; // shouldn't happen

            // Apply placement to skyline
            auto &t = p.orientations[bestTi];
            for(int j = 0; j < t.w; j++){
                if(t.hi[j] != INT_MIN){
                    int nh = bestY + t.hi[j] + 1;
                    skyline[bestX+j] = max(skyline[bestX+j], nh);
                }
            }
            maxH = bestLocalH;
            placements.push_back({idx, bestTi, bestX, bestY});
        }

        // Compact: find actual used width
        int usedW = 0;
        for(int x = 0; x < W; x++){
            if(skyline[x] > 0) usedW = x + 1;
        }
        usedW = max(usedW, 1);

        return {(long long)usedW * maxH, usedW, maxH, move(placements)};
    };

    // Determine min possible width
    int minW = 0;
    for(auto &p : pieces) minW = max(minW, p.minW);

    // Generate candidate widths
    double factor;
    if(totalCells < 1000) factor = 0.4;
    else if(totalCells < 3000) factor = 0.5;
    else if(totalCells < 10000) factor = 0.27;
    else if(totalCells < 30000) factor = 0.08;
    else factor = 0.01;

    int base = max(minW, (int)floor(sqrt((double)totalCells * factor)));
    set<int> widthSet;
    widthSet.insert(base);
    int span = min(80, max(15, base/2));
    for(int d = 1; d <= span; d++){
        widthSet.insert(max(minW, base - d));
        widthSet.insert(base + d);
    }
    widthSet.insert(minW);

    // Sort by distance from base
    vector<int> widths(widthSet.begin(), widthSet.end());
    sort(widths.begin(), widths.end(), [&](int a, int b){
        return abs(a - base) < abs(b - base);
    });

    // Try each width, track best
    Result bestResult;
    bestResult.area = LLONG_MAX;
    bool found = false;

    auto t0 = chrono::steady_clock::now();
    double timeLimit = 1900.0; // ms, stay under 2s
    double avgTime = 100.0;
    int cnt = 0;

    for(int W : widths){
        auto now = chrono::steady_clock::now();
        double elapsed = chrono::duration<double, milli>(now - t0).count();
        if(elapsed + avgTime * 1.3 > timeLimit) break;

        auto t1 = chrono::steady_clock::now();
        Result r = pack(W, order);
        auto t2 = chrono::steady_clock::now();
        double dt = chrono::duration<double, milli>(t2 - t1).count();
        cnt++;
        avgTime = (avgTime * (cnt - 1) + dt) / cnt;

        if(!found || r.area < bestResult.area ||
           (r.area == bestResult.area && r.H < bestResult.H)){
            bestResult = r;
            found = true;
        }
    }

    if(!found){
        bestResult = pack(base, order);
    }

    // Output
    // Reconstruct the transform parameters for each piece
    vector<array<int,4>> ans(n, {0, 0, 0, 0});
    for(auto &pl : bestResult.placements){
        auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
        // The checker expects: reflect -> rotate -> translate
        // Our cells are already (reflect -> rotate) applied and normalized
        // We need to find X, Y, R, F such that:
        //   for each cell (cx,cy) in original piece:
        //     rx = (F ? -cx : cx), ry = cy
        //     (qx,qy) = rot90cw(rx, ry, R)
        //     gx = qx + X, gy = qy + Y
        //   and gx,gy are in [0,W) x [0,H)
        //
        // Our trans stores r, f, orig_minx, orig_miny
        // The normalized cell at (nx,ny) maps to grid position (pl.x + nx, pl.y + ny)
        // The orig cell after reflect+rotate is at (orig_minx + nx, orig_miny + ny)
        // So translate X = pl.x + nx - (orig_minx + nx) = pl.x - orig_minx
        //           Y = pl.y + ny - (orig_miny + ny) = pl.y - orig_miny

        int X = pl.x - t.orig_minx;
        int Y = pl.y - t.orig_miny;
        int R = t.r;
        int F = t.f;
        ans[pl.piece_idx] = {X, Y, R, F};
    }

    cout << bestResult.W << " " << bestResult.H << "\n";
    for(int i = 0; i < n; i++){
        cout << ans[i][0] << " " << ans[i][1] << " " << ans[i][2] << " " << ans[i][3] << "\n";
    }

    return 0;
}
