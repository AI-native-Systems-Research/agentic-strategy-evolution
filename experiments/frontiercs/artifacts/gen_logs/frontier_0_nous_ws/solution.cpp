// Enhanced skyline-based greedy polyomino packer (v10)
// Key changes from v7:
// 1. Fast I/O via custom scanner (~50ms savings on large inputs)
// 2. Unified width sweep: ALL time for primary ordering (no 60/40 split)
// 3. Position-level early termination in inner loop
// 4. Alt orderings in remaining time, then random restart shuffles
// 5. Random restart: for small/medium instances, try many shuffled orderings
//    at bestWidth to exploit ordering diversity
#include <bits/stdc++.h>
using namespace std;

struct FastIO {
    char buf[1<<20];
    int pos=0, len=0;
    inline char gc() {
        if(pos==len) { len=fread(buf,1,sizeof buf,stdin); pos=0; }
        return pos<len ? buf[pos++] : 0;
    }
    inline int readInt() {
        int x=0, neg=0; char c=gc();
        while((c<'0'||c>'9')&&c!='-') c=gc();
        if(c=='-') { neg=1; c=gc(); }
        while(c>='0'&&c<='9') { x=x*10+(c-'0'); c=gc(); }
        return neg?-x:x;
    }
} io;

struct Trans {
    int w, h;
    vector<pair<int,int>> cells;
    vector<int> lo, hi;
    int r, f;
    int orig_minx, orig_miny;
};

struct Piece {
    int id, k;
    vector<pair<int,int>> base;
    vector<Trans> orientations;
    int minW, minH, maxDim;
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
    int n = io.readInt();

    vector<Piece> pieces(n);
    long long totalCells = 0;

    for(int i = 0; i < n; i++){
        int k = io.readInt();
        pieces[i].id = i;
        pieces[i].k = k;
        pieces[i].base.resize(k);
        for(int j = 0; j < k; j++){
            pieces[i].base[j].first = io.readInt();
            pieces[i].base[j].second = io.readInt();
        }
        totalCells += k;
    }

    for(int i = 0; i < n; i++){
        auto &p = pieces[i];
        p.minW = INT_MAX; p.minH = INT_MAX; p.maxDim = 0;
        set<vector<pair<int,int>>> seen;
        for(int flip = 0; flip < 2; flip++){
            vector<pair<int,int>> src = p.base;
            if(flip) for(auto &[x,y] : src) x = -x;
            for(int rot = 0; rot < 4; rot++){
                vector<pair<int,int>> v = src;
                for(auto &[x,y] : v) tie(x,y) = rot90cw(x, y, rot);
                int minx=INT_MAX, miny=INT_MAX, maxx=INT_MIN, maxy=INT_MIN;
                for(auto &[x,y] : v){ minx=min(minx,x); miny=min(miny,y); maxx=max(maxx,x); maxy=max(maxy,y); }
                vector<pair<int,int>> norm = v;
                for(auto &[x,y] : norm){ x-=minx; y-=miny; }
                sort(norm.begin(), norm.end());
                if(seen.insert(norm).second){
                    Trans t;
                    t.w=maxx-minx+1; t.h=maxy-miny+1; t.cells=norm;
                    t.r=rot; t.f=flip; t.orig_minx=minx; t.orig_miny=miny;
                    t.lo.assign(t.w, INT_MAX); t.hi.assign(t.w, INT_MIN);
                    for(auto &[x,y] : norm){ t.lo[x]=min(t.lo[x],y); t.hi[x]=max(t.hi[x],y); }
                    p.orientations.push_back(move(t));
                }
            }
        }
        for(auto &t : p.orientations){ p.minW=min(p.minW,t.w); p.minH=min(p.minH,t.h); p.maxDim=max(p.maxDim,max(t.w,t.h)); }
        if(p.orientations.empty()){
            Trans t; t.w=1;t.h=1;t.cells={{0,0}};t.lo={0};t.hi={0};
            t.r=0;t.f=0;t.orig_minx=0;t.orig_miny=0;
            p.orientations.push_back(t); p.minW=1;p.minH=1;p.maxDim=1;
        }
    }

    // Three orderings
    vector<int> orderAscDim(n), orderDecK(n), orderDecMaxDim(n);
    iota(orderAscDim.begin(), orderAscDim.end(), 0);
    iota(orderDecK.begin(), orderDecK.end(), 0);
    iota(orderDecMaxDim.begin(), orderDecMaxDim.end(), 0);

    stable_sort(orderAscDim.begin(), orderAscDim.end(), [&](int a, int b){
        int da=min(pieces[a].minW,pieces[a].minH), db=min(pieces[b].minW,pieces[b].minH);
        if(da!=db) return da<db;
        if(pieces[a].k!=pieces[b].k) return pieces[a].k<pieces[b].k;
        return pieces[a].id>pieces[b].id;
    });
    stable_sort(orderDecK.begin(), orderDecK.end(), [&](int a, int b){
        if(pieces[a].k!=pieces[b].k) return pieces[a].k>pieces[b].k;
        int da=min(pieces[a].minW,pieces[a].minH), db=min(pieces[b].minW,pieces[b].minH);
        return da>db;
    });
    stable_sort(orderDecMaxDim.begin(), orderDecMaxDim.end(), [&](int a, int b){
        if(pieces[a].maxDim!=pieces[b].maxDim) return pieces[a].maxDim>pieces[b].maxDim;
        if(pieces[a].k!=pieces[b].k) return pieces[a].k>pieces[b].k;
        return pieces[a].id<pieces[b].id;
    });

    bool bigInstance = totalCells > 7000;
    int maxLookahead = max(1, n / 4);

    // Pack function with dynamic lookahead (same as v7)
    auto pack = [&](int W, const vector<int>& ord0) -> Result {
        vector<int> skyline(W, 0);
        int maxH = 0;
        vector<Placement> placements;
        placements.reserve(n);
        vector<int> ord = ord0;
        int placed = 0, nm = (int)ord.size();

        int expLIM = bigInstance
            ? min(maxLookahead, (int)(350000/max(1LL,totalCells-3500)))
            : maxLookahead;
        int dynLIM = bigInstance ? expLIM : maxLookahead;

        auto tStart = chrono::steady_clock::now();
        auto batchStart = tStart;
        double TLms = bigInstance ? 1900.0 : 1e18;
        int stepCnt = 0;

        while(placed < nm){
            int lim = min(nm, placed + max(1, dynLIM));
            long long bestScore1 = LLONG_MAX;
            int bestTi=-1, bestX=0, bestY=0, bestLocalH=INT_MAX;
            long long bestDelta=LLONG_MAX, bestRough=LLONG_MAX;
            int bestY0=INT_MAX, bestX0=INT_MAX, bestPos=placed;

            for(int pos = placed; pos < lim; pos++){
                int id = ord[pos];
                auto &p = pieces[id];
                long long bestScore2=LLONG_MAX;
                int bti2=-1, bx2=0, by2=0, bl2=INT_MAX;
                long long bds2=LLONG_MAX, bdr2=LLONG_MAX;
                int by02=INT_MAX, bx02=INT_MAX;

                for(int ti = 0; ti < (int)p.orientations.size(); ti++){
                    auto &t = p.orientations[ti];
                    if(t.w > W) continue;
                    // Precompute max(hi[j]+1) for quick early termination
                    int tMaxHiP1 = 0;
                    for(int j = 0; j < t.w; j++)
                        if(t.hi[j] != INT_MIN) tMaxHiP1 = max(tMaxHiP1, t.hi[j] + 1);
                    int positions = W - t.w + 1;
                    for(int x0 = 0; x0 < positions; x0++){
                        int y0 = 0;
                        for(int j = 0; j < t.w; j++)
                            if(t.lo[j] != INT_MAX)
                                y0 = max(y0, skyline[x0+j] - t.lo[j]);

                        // Quick early termination: lower bound on localH
                        long long quickGG = (long long)max(maxH, y0 + tMaxHiP1);
                        if(quickGG > bestScore2) continue;

                        int localH = maxH;
                        int nhBuf[32];
                        for(int j = 0; j < t.w; j++){
                            int nh = skyline[x0+j];
                            if(t.hi[j] != INT_MIN) nh = max(nh, y0 + t.hi[j] + 1);
                            nhBuf[j] = nh;
                            localH = max(localH, nh);
                        }

                        long long gg = (long long)localH;
                        if(gg > bestScore2) continue; // Exact early termination

                        long long deltaSum = 0;
                        for(int j = 0; j < t.w; j++){
                            long long inc = nhBuf[j] - skyline[x0+j];
                            if(inc > 0) deltaSum += inc;
                        }

                        long long roughDelta = 0;
                        if(x0 > 0)
                            roughDelta += abs((long long)nhBuf[0]-skyline[x0-1]) - abs((long long)skyline[x0]-skyline[x0-1]);
                        for(int j = 0; j < t.w-1; j++)
                            roughDelta += abs((long long)nhBuf[j+1]-nhBuf[j]) - abs((long long)skyline[x0+j+1]-skyline[x0+j]);
                        if(x0+t.w < W)
                            roughDelta += abs((long long)skyline[x0+t.w]-nhBuf[t.w-1]) - abs((long long)skyline[x0+t.w]-skyline[x0+t.w-1]);

                        bool take = false;
                        if(gg < bestScore2) take = true;
                        else if(gg == bestScore2){
                            if(deltaSum < bds2) take = true;
                            else if(deltaSum == bds2){
                                if(localH < bl2) take = true;
                                else if(localH == bl2){
                                    if(roughDelta < bdr2) take = true;
                                    else if(roughDelta == bdr2){
                                        if(y0 < by02) take = true;
                                        else if(y0 == by02 && x0 < bx02) take = true;
                                    }
                                }
                            }
                        }
                        if(take){
                            bestScore2=gg; bti2=ti; bx2=x0; by2=y0;
                            bl2=localH; bds2=deltaSum; bdr2=roughDelta;
                            by02=y0; bx02=x0;
                        }
                    }
                }
                if(bti2 == -1) continue;
                bool take = false;
                if(bestScore2 < bestScore1) take = true;
                else if(bestScore2 == bestScore1){
                    if(bds2 < bestDelta) take = true;
                    else if(bds2 == bestDelta){
                        if(bl2 < bestLocalH) take = true;
                        else if(bl2 == bestLocalH){
                            if(bdr2 < bestRough) take = true;
                            else if(bdr2 == bestRough){
                                if(by02 < bestY0) take = true;
                                else if(by02 == bestY0 && bx02 < bestX0) take = true;
                            }
                        }
                    }
                }
                if(take){
                    bestScore1=bestScore2; bestTi=bti2; bestX=bx2; bestY=by2;
                    bestLocalH=bl2; bestDelta=bds2; bestRough=bdr2;
                    bestY0=by02; bestX0=bx02; bestPos=pos;
                }
            }

            if(bestTi == -1){ placed++; stepCnt++;
                if(bigInstance && stepCnt==5){
                    auto now=chrono::steady_clock::now();
                    double el=chrono::duration<double,milli>(now-tStart).count();
                    double bt=chrono::duration<double,milli>(now-batchStart).count();
                    double rem=max(0.0,TLms-el); int rs=max(1,nm-placed);
                    double bud=rem*5.0/rs;
                    if(bt<bud) dynLIM=min(maxLookahead,dynLIM+1); else dynLIM=max(1,dynLIM-1);
                    batchStart=now; stepCnt=0;
                }
                continue;
            }

            int bestId = ord[bestPos];
            auto &t = pieces[bestId].orientations[bestTi];
            for(int j = 0; j < t.w; j++)
                if(t.hi[j] != INT_MIN)
                    skyline[bestX+j] = max(skyline[bestX+j], bestY + t.hi[j] + 1);
            maxH = bestLocalH;
            placements.push_back({bestId, bestTi, bestX, bestY});
            if(bestPos != placed) swap(ord[placed], ord[bestPos]);
            placed++; stepCnt++;
            if(bigInstance && stepCnt==5){
                auto now=chrono::steady_clock::now();
                double el=chrono::duration<double,milli>(now-tStart).count();
                double bt=chrono::duration<double,milli>(now-batchStart).count();
                double rem=max(0.0,TLms-el); int rs=max(1,nm-placed);
                double bud=rem*5.0/rs;
                if(bt<bud) dynLIM=min(maxLookahead,dynLIM+1); else dynLIM=max(1,dynLIM-1);
                batchStart=now; stepCnt=0;
            }
        }

        // Column compaction
        int maxX = -1;
        for(auto &pl : placements){
            auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
            for(auto &[cx,cy] : t.cells) maxX = max(maxX, pl.x+cx);
        }
        int usedW = 0;
        if(maxX >= 0){
            vector<bool> used(maxX+1, false);
            for(auto &pl : placements){
                auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
                for(auto &[cx,cy] : t.cells) used[pl.x+cx] = true;
            }
            for(int x=0;x<=maxX;x++) if(used[x]) usedW++;
        }
        usedW = max(usedW, 1);
        return {(long long)usedW * maxH, usedW, maxH, move(placements)};
    };

    int minW = 0;
    for(auto &p : pieces) minW = max(minW, p.minW);

    double factor;
    if(totalCells<1000) factor=0.4;
    else if(totalCells<3000) factor=0.5;
    else if(totalCells<10000) factor=0.27;
    else if(totalCells<30000) factor=0.08;
    else factor=0.01;

    int base = max(minW, (int)floor(sqrt((double)totalCells * factor)));
    set<int> widthSet;
    widthSet.insert(base);
    int span = min(96, max(20, base/2));
    for(int d=1;d<=span;d++){ widthSet.insert(max(minW,base-d)); widthSet.insert(base+d); }
    widthSet.insert(minW);
    long long sqrtS = max((long long)minW, (long long)floor(sqrt((double)totalCells)));
    widthSet.insert((int)max((long long)minW, (totalCells+sqrtS-1)/sqrtS));
    for(int m=2;m<=6;m++){
        int w1=base*m/3;
        widthSet.insert(max(minW,w1));
        if(w1>0) widthSet.insert((int)max((long long)minW, totalCells/w1));
    }

    vector<int> widths(widthSet.begin(), widthSet.end());
    sort(widths.begin(), widths.end(), [&](int a, int b){
        int da=abs(a-base), db=abs(b-base);
        if(da!=db) return da<db;
        return a<b;
    });

    Result bestResult;
    bestResult.area = LLONG_MAX;
    bool found = false;
    int bestWidth = base;

    auto t0 = chrono::steady_clock::now();
    double timeLimit = 1980.0;
    double avgTime = 250.0;
    int cnt = 0;

    // === UNIFIED SWEEP: all time for primary ordering (no 60/40 split) ===
    for(int W : widths){
        auto now = chrono::steady_clock::now();
        double elapsed = chrono::duration<double, milli>(now - t0).count();
        if(elapsed + avgTime * 1.3 > timeLimit) break;

        auto t1 = chrono::steady_clock::now();
        Result r = pack(W, orderAscDim);
        auto t2 = chrono::steady_clock::now();
        double dt = chrono::duration<double, milli>(t2 - t1).count();
        cnt++; avgTime = (avgTime*(cnt-1)+dt)/cnt;

        if(!found || r.area < bestResult.area ||
           (r.area == bestResult.area && r.H < bestResult.H)){
            bestResult = r; found = true; bestWidth = W;
        }
    }

    // === ALT ORDERINGS in remaining time ===
    {
        vector<vector<int>> altOrderings = {orderDecK, orderDecMaxDim};
        set<int> altWidths;
        altWidths.insert(bestWidth);
        for(int d = 1; d <= 2; d++){
            altWidths.insert(max(minW, bestWidth - d));
            altWidths.insert(bestWidth + d);
        }
        for(int W : altWidths){
            for(auto &ord : altOrderings){
                auto now = chrono::steady_clock::now();
                double elapsed = chrono::duration<double, milli>(now - t0).count();
                if(elapsed + avgTime * 1.15 > timeLimit) goto phase3;
                Result r = pack(W, ord);
                if(!found || r.area < bestResult.area ||
                   (r.area == bestResult.area && r.H < bestResult.H)){
                    bestResult = r; found = true;
                }
            }
        }
    }

    phase3:
    // === RANDOM RESTART: shuffled orderings at best width ===
    {
        mt19937 rng(12345);
        vector<int> altWidthsRR = {bestWidth};
        if(bestWidth - 1 >= minW) altWidthsRR.push_back(bestWidth - 1);
        altWidthsRR.push_back(bestWidth + 1);

        while(true){
            auto now = chrono::steady_clock::now();
            double elapsed = chrono::duration<double, milli>(now - t0).count();
            if(elapsed + avgTime * 1.3 > timeLimit) break;

            // Pick a random ordering: shuffle a copy of orderAscDim
            vector<int> randOrd = orderAscDim;
            shuffle(randOrd.begin(), randOrd.end(), rng);
            // Pick a random width from the best neighborhood
            int W = altWidthsRR[rng() % altWidthsRR.size()];

            Result r = pack(W, randOrd);
            if(!found || r.area < bestResult.area ||
               (r.area == bestResult.area && r.H < bestResult.H)){
                bestResult = r; found = true;
            }
        }
    }

    if(!found) bestResult = pack(base, orderAscDim);

    // === BL RE-PLACEMENT POST-PROCESSING ===
    // For each piece (in reverse order), remove it and re-place at the
    // lowest valid BL position using a bitmap for exact overlap checking.
    // This fills gaps that the skyline heuristic left behind.
    {
        auto tnow = chrono::steady_clock::now();
        double elapsed = chrono::duration<double, milli>(tnow - t0).count();
        double blBudget = timeLimit - elapsed - 30; // 30ms safety margin for output

        if(blBudget > 50 && bestResult.H > 0) {
            int W = bestResult.W; // Note: this is the compacted W from pack()
            // We need to work with the UN-compacted width (the W used in pack())
            // The placements use the original (uncompacted) coordinates
            int packW = 0;
            for(auto &pl : bestResult.placements) {
                auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
                for(auto &[cx,cy] : t.cells) packW = max(packW, pl.x + cx + 1);
            }
            int H = bestResult.H;
            int gridH = H + 20;

            // Build bitmap
            vector<char> grid(packW * gridH, 0);
            auto at = [&](int x, int y) -> char& { return grid[x * gridH + y]; };

            for(auto &pl : bestResult.placements) {
                auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
                for(auto &[cx,cy] : t.cells) {
                    int gx = pl.x + cx, gy = pl.y + cy;
                    if(gx >= 0 && gx < packW && gy >= 0 && gy < gridH)
                        at(gx, gy) = 1;
                }
            }

            // BL re-placement passes
            auto tBL = chrono::steady_clock::now();
            bool improved = true;
            int passes = 0;
            while(improved) {
                auto tnow2 = chrono::steady_clock::now();
                double el2 = chrono::duration<double, milli>(tnow2 - tBL).count();
                if(el2 > blBudget) break;

                improved = false;
                passes++;

                // Process pieces from top to bottom (those near the top benefit most)
                vector<int> order(bestResult.placements.size());
                iota(order.begin(), order.end(), 0);
                sort(order.begin(), order.end(), [&](int a, int b){
                    return bestResult.placements[a].y > bestResult.placements[b].y;
                });

                for(int idx : order) {
                    auto tnow3 = chrono::steady_clock::now();
                    double el3 = chrono::duration<double, milli>(tnow3 - tBL).count();
                    if(el3 > blBudget) break;

                    auto &pl = bestResult.placements[idx];
                    int pid = pl.piece_idx;
                    int oldTi = pl.orient_idx, oldX = pl.x, oldY = pl.y;
                    auto &oldT = pieces[pid].orientations[oldTi];

                    // Remove piece from grid
                    for(auto &[cx,cy] : oldT.cells) at(oldX + cx, oldY + cy) = 0;

                    // Find best BL position across all orientations
                    int bestNewY = oldY, bestNewX = oldX, bestNewTi = oldTi;
                    int bestNewMaxY = -1;
                    // Compute current maxY (without this piece)
                    // We track it incrementally: compute oldMaxY
                    // For simplicity, just compute the max height contribution of this piece
                    int oldPieceMaxY = 0;
                    for(auto &[cx,cy] : oldT.cells) oldPieceMaxY = max(oldPieceMaxY, oldY + cy);

                    for(int ti = 0; ti < (int)pieces[pid].orientations.size(); ti++) {
                        auto &t = pieces[pid].orientations[ti];
                        if(t.w > packW) continue;
                        for(int x0 = 0; x0 <= packW - t.w; x0++) {
                            // Find lowest y0 where piece fits (BL approach)
                            // Use column-max scan for speed
                            int y0 = 0;
                            for(int j = 0; j < t.w; j++) {
                                if(t.lo[j] == INT_MAX) continue;
                                // Find highest occupied cell in column x0+j
                                int col = x0 + j;
                                int maxOcc = -1;
                                for(int yy = gridH-1; yy >= 0; yy--) {
                                    if(at(col, yy)) { maxOcc = yy; break; }
                                }
                                y0 = max(y0, maxOcc + 1 - t.lo[j]);
                            }
                            if(y0 < 0) y0 = 0;

                            // Verify no overlap with bitmap (handles non-contiguous columns)
                            bool fits = true;
                            int pieceMaxY = 0;
                            for(auto &[cx,cy] : t.cells) {
                                int gx = x0 + cx, gy = y0 + cy;
                                if(gx < 0 || gx >= packW || gy < 0 || gy >= gridH || at(gx, gy)) {
                                    fits = false; break;
                                }
                                pieceMaxY = max(pieceMaxY, gy);
                            }
                            if(!fits) continue;

                            // Take if lower (BL criterion)
                            bool take = false;
                            if(bestNewTi == -1) take = true;
                            else if(pieceMaxY < bestNewMaxY) take = true;
                            else if(pieceMaxY == bestNewMaxY && y0 < bestNewY) take = true;
                            else if(pieceMaxY == bestNewMaxY && y0 == bestNewY && x0 < bestNewX) take = true;

                            if(take) {
                                bestNewY = y0; bestNewX = x0; bestNewTi = ti;
                                bestNewMaxY = pieceMaxY;
                            }
                        }
                    }

                    if(bestNewTi != -1 && (bestNewY < oldY || (bestNewY == oldY && bestNewTi != oldTi))) {
                        // Place at new position
                        auto &newT = pieces[pid].orientations[bestNewTi];
                        for(auto &[cx,cy] : newT.cells) at(bestNewX + cx, bestNewY + cy) = 1;
                        pl = {pid, bestNewTi, bestNewX, bestNewY};
                        improved = true;
                    } else {
                        // Keep original position
                        for(auto &[cx,cy] : oldT.cells) at(oldX + cx, oldY + cy) = 1;
                    }
                }
                if(passes >= 5) break; // Limit passes
            }

            // Recompute bounding box
            int newMaxY = 0, newMaxX = 0;
            for(auto &pl : bestResult.placements) {
                auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
                for(auto &[cx,cy] : t.cells) {
                    newMaxY = max(newMaxY, pl.y + cy);
                    newMaxX = max(newMaxX, pl.x + cx);
                }
            }
            int newH = newMaxY + 1;

            // Recompute W with column compaction
            int usedW2 = 0;
            {
                vector<bool> used(newMaxX+1, false);
                for(auto &pl : bestResult.placements) {
                    auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
                    for(auto &[cx,cy] : t.cells) used[pl.x + cx] = true;
                }
                for(int x = 0; x <= newMaxX; x++) if(used[x]) usedW2++;
            }
            usedW2 = max(1, usedW2);

            long long newArea = (long long)usedW2 * newH;
            if(newArea < bestResult.area || (newArea == bestResult.area && newH < bestResult.H)) {
                bestResult.area = newArea;
                bestResult.W = usedW2;
                bestResult.H = newH;
            }
        }
    }

    // Reconstruct column map
    int maxX = -1;
    for(auto &pl : bestResult.placements){
        auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
        for(auto &[cx,cy] : t.cells) maxX = max(maxX, pl.x+cx);
    }
    vector<int> colMap;
    if(maxX >= 0){
        vector<bool> used(maxX+1, false);
        for(auto &pl : bestResult.placements){
            auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
            for(auto &[cx,cy] : t.cells) used[pl.x+cx] = true;
        }
        colMap.resize(maxX+1, -1);
        int cur = 0;
        for(int x=0;x<=maxX;x++) if(used[x]) colMap[x] = cur++;
    }

    vector<array<int,4>> ans(n, {0,0,0,0});
    for(auto &pl : bestResult.placements){
        auto &t = pieces[pl.piece_idx].orientations[pl.orient_idx];
        int mappedX = (colMap.empty() ? pl.x : colMap[pl.x]);
        ans[pl.piece_idx] = {mappedX - t.orig_minx, pl.y - t.orig_miny, t.r, t.f};
    }

    cout << bestResult.W << " " << bestResult.H << "\n";
    for(int i=0;i<n;i++)
        cout << ans[i][0] << " " << ans[i][1] << " " << ans[i][2] << " " << ans[i][3] << "\n";

    return 0;
}
