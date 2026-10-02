#include <iostream>
#include <vector>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <numeric>
#include <chrono>

using namespace std;

struct Piece {
    int id;
    int k;
    vector<pair<int,int>> cells; // original cells
};

struct Orientation {
    vector<pair<int,int>> cells; // normalized to (0,0) origin
    int w, h; // bounding box
    int r, f;
};

vector<pair<int,int>> normalize(vector<pair<int,int>>& cells) {
    int minx = 1e9, miny = 1e9;
    for (auto& c : cells) { minx = min(minx, c.first); miny = min(miny, c.second); }
    vector<pair<int,int>> res;
    for (auto& c : cells) res.push_back({c.first - minx, c.second - miny});
    sort(res.begin(), res.end());
    return res;
}

vector<Orientation> getOrientations(vector<pair<int,int>>& orig) {
    vector<Orientation> oris;
    // Generate all 8 transforms
    for (int f = 0; f <= 1; f++) {
        for (int r = 0; r < 4; r++) {
            vector<pair<int,int>> cells;
            for (auto& c : orig) {
                int x = c.first, y = c.second;
                // reflect first
                if (f) x = -x;
                // rotate r times 90° clockwise: (x,y) -> (y,-x)
                for (int rr = 0; rr < r; rr++) {
                    int nx = y, ny = -x;
                    x = nx; y = ny;
                }
                cells.push_back({x, y});
            }
            auto nc = normalize(cells);
            // check duplicate
            bool dup = false;
            for (auto& o : oris) {
                if (o.cells == nc) { dup = true; break; }
            }
            if (!dup) {
                Orientation ori;
                ori.cells = nc;
                ori.r = r;
                ori.f = f;
                int mx = 0, my = 0;
                for (auto& c : nc) { mx = max(mx, c.first); my = max(my, c.second); }
                ori.w = mx + 1;
                ori.h = my + 1;
                oris.push_back(ori);
            }
        }
    }
    return oris;
}

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    auto t0 = chrono::steady_clock::now();
    
    int n;
    cin >> n;
    
    vector<Piece> pieces(n);
    int totalCells = 0;
    for (int i = 0; i < n; i++) {
        pieces[i].id = i;
        cin >> pieces[i].k;
        pieces[i].cells.resize(pieces[i].k);
        for (int j = 0; j < pieces[i].k; j++) {
            cin >> pieces[i].cells[j].first >> pieces[i].cells[j].second;
        }
        totalCells += pieces[i].k;
    }
    
    // Precompute orientations for each piece
    vector<vector<Orientation>> allOris(n);
    for (int i = 0; i < n; i++) {
        allOris[i] = getOrientations(pieces[i].cells);
    }
    
    // Sort pieces by decreasing size, then by fewer orientations (more constrained first)
    vector<int> order(n);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int a, int b){
        if (pieces[a].k != pieces[b].k) return pieces[a].k > pieces[b].k;
        return allOris[a].size() < allOris[b].size();
    });
    
    // Target width: try to make roughly square
    int targetW = max(10, (int)ceil(sqrt((double)totalCells * 1.15)));
    // We'll try a few widths and pick the best
    
    auto tryWidth = [&](int W) -> tuple<int, vector<int>, vector<int>, vector<int>, vector<int>> {
        // grid: maxH
        int maxH = (totalCells + W - 1) / W + 200; // generous
        if (maxH > 100000) maxH = 100000;
        // Use a compact representation: for each row, a bitset or vector<bool>
        // For large W, use vector<uint8_t>
        vector<vector<uint8_t>> grid(maxH, vector<uint8_t>(W, 0));
        
        vector<int> px(n), py(n), pr(n), pf(n);
        int usedH = 0;
        
        // For each row, track how many free cells
        vector<int> rowFree(maxH, W);
        
        for (int idx = 0; idx < n; idx++) {
            int i = order[idx];
            auto& oris = allOris[i];
            
            int bestScore = 1e9;
            int bestX = -1, bestY = -1, bestOi = -1;
            
            for (int oi = 0; oi < (int)oris.size(); oi++) {
                auto& ori = oris[oi];
                if (ori.w > W) continue;
                
                // Try bottom-left placement
                int limY = min(usedH + 1, maxH - ori.h);
                for (int y = 0; y <= limY && y < maxH - ori.h + 1; y++) {
                    for (int x = 0; x <= W - ori.w; x++) {
                        // Check if fits
                        bool fits = true;
                        for (auto& c : ori.cells) {
                            if (grid[y + c.second][x + c.first]) { fits = false; break; }
                        }
                        if (fits) {
                            int score = max(usedH, y + ori.h);
                            // prefer smaller area = score * W, then smaller y, then smaller x
                            if (score < bestScore || (score == bestScore && (bestY > y || (bestY == y && bestX > x)))) {
                                bestScore = score;
                                bestX = x;
                                bestY = y;
                                bestOi = oi;
                            }
                            goto nextOri; // first valid position in this orientation (BL)
                        }
                    }
                }
                nextOri:;
            }
            
            if (bestOi == -1) {
                // Place at bottom of grid
                int y = usedH;
                bestOi = 0;
                // find first orientation that fits width
                for (int oi = 0; oi < (int)oris.size(); oi++) {
                    if (oris[oi].w <= W) { bestOi = oi; break; }
                }
                bestX = 0; bestY = y;
                bestScore = y + oris[bestOi].h;
            }
            
            auto& ori = oris[bestOi];
            for (auto& c : ori.cells) {
                grid[bestY + c.second][bestX + c.first] = 1;
            }
            usedH = max(usedH, bestY + (int)ori.h);
            
            px[i] = bestX;
            py[i] = bestY;
            pr[i] = ori.r;
            pf[i] = ori.f;
        }
        
        return {usedH, px, py, pr, pf};
    };
    
    int bestArea = 1e9;
    int bestW, bestH;
    vector<int> bpx, bpy, bpr, bpf;
    
    // Try several widths
    for (int dw = -5; dw <= 15; dw++) {
        int W = targetW + dw;
        if (W < 1) continue;
        auto elapsed = chrono::steady_clock::now() - t0;
        if (chrono::duration_cast<chrono::milliseconds>(elapsed).count() > 8000) break;
        
        auto [H, px, py, pr, pf] = tryWidth(W);
        int area = W * H;
        if (area < bestArea || (area == bestArea && (H < bestH || (H == bestH && W < bestW)))) {
            bestArea = area;
            bestW = W;
            bestH = H;
            bpx = px; bpy = py; bpr = pr; bpf = pf;
        }
    }
    
    cout << bestW << " " << bestH << "\n";
    for (int i = 0; i < n; i++) {
        cout << bpx[i] << " " << bpy[i] << " " << bpr[i] << " " << bpf[i] << "\n";
    }
    
    return 0;
}