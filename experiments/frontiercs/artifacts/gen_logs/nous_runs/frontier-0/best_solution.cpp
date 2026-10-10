// Enhanced skyline-based greedy polyomino packer (v6)
// Strategy: cap lookahead for consistency, maximize width×ordering coverage
// Features: bounded lookahead, roughness tiebreaker, column compaction, 3 orderings
#include <bits/stdc++.h>
using namespace std;

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
        for(int j = 0; j < k; j++)
            cin >> pieces[i].base[j].first >> pieces[i].base[j].second;
        totalCells += k;
    }

    // Generate orientations
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

    // Orderings
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

    // Fixed lookahead cap for predictable timing
    int lookaheadCap;
    if(n <= 200) lookaheadCap = n;
    else if(n <= 500) lookaheadCap = 100;
    else if(n <= 1000) lookaheadCap = 50;
    else if(n <= 3000) lookaheadCap = 20;
    else lookaheadCap = 10;

    // Packer with bounded lookahead and roughness tiebreaker
    auto pack = [&](int W, const vector<int>& ord0) -> Result {
        vector<int> skyline(W, 0);
        int maxH = 0;
        vector<Placement> placements;
        placements.reserve(n);
        vector<int> ord = ord0;
        int placed = 0, nm = (int)ord.size();

        while(placed < nm){
            int lim = min(nm, placed + max(1, lookaheadCap));
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
                    int positions = W - t.w + 1;
                    for(int x0 = 0; x0 < positions; x0++){
                        int y0 = 0;
                        for(int j = 0; j < t.w; j++)
                            if(t.lo[j] != INT_MAX)
                                y0 = max(y0, skyline[x0+j] - t.lo[j]);

                        int localH = maxH;
                        long long deltaSum = 0;
                        int nhBuf[32];
                        for(int j = 0; j < t.w; j++){
                            int nh = skyline[x0+j];
                            if(t.hi[j] != INT_MIN) nh = max(nh, y0 + t.hi[j] + 1);
                            nhBuf[j] = nh;
                            localH = max(localH, nh);
                            long long inc = nh - skyline[x0+j];
                            if(inc > 0) deltaSum += inc;
                        }

                        long long roughDelta = 0;
                        if(x0 > 0)
                            roughDelta += abs((long long)nhBuf[0]-skyline[x0-1]) - abs((long long)skyline[x0]-skyline[x0-1]);
                        for(int j = 0; j < t.w-1; j++)
                            roughDelta += abs((long long)nhBuf[j+1]-nhBuf[j]) - abs((long long)skyline[x0+j+1]-skyline[x0+j]);
                        if(x0+t.w < W)
                            roughDelta += abs((long long)skyline[x0+t.w]-nhBuf[t.w-1]) - abs((long long)skyline[x0+t.w]-skyline[x0+t.w-1]);

                        long long gg = (long long)localH;
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

            if(bestTi == -1){ placed++; continue; }

            int bestId = ord[bestPos];
            auto &t = pieces[bestId].orientations[bestTi];
            for(int j = 0; j < t.w; j++)
                if(t.hi[j] != INT_MIN)
                    skyline[bestX+j] = max(skyline[bestX+j], bestY + t.hi[j] + 1);
            maxH = bestLocalH;
            placements.push_back({bestId, bestTi, bestX, bestY});
            if(bestPos != placed) swap(ord[placed], ord[bestPos]);
            placed++;
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

    auto t0 = chrono::steady_clock::now();
    double timeLimit = 1980.0;
    double avgTime = 100.0;
    int cnt = 0;

    vector<vector<int>> orderings = {orderAscDim, orderDecK, orderDecMaxDim};

    for(int W : widths){
        auto now = chrono::steady_clock::now();
        double elapsed = chrono::duration<double, milli>(now - t0).count();
        if(elapsed + avgTime * 1.3 > timeLimit) break;

        for(int oi = 0; oi < (int)orderings.size(); oi++){
            now = chrono::steady_clock::now();
            elapsed = chrono::duration<double, milli>(now - t0).count();
            if(elapsed + avgTime * 1.15 > timeLimit) goto done;

            auto t1 = chrono::steady_clock::now();
            Result r = pack(W, orderings[oi]);
            auto t2 = chrono::steady_clock::now();
            double dt = chrono::duration<double, milli>(t2 - t1).count();
            cnt++; avgTime = (avgTime*(cnt-1)+dt)/cnt;

            if(!found || r.area < bestResult.area ||
               (r.area == bestResult.area && r.H < bestResult.H) ||
               (r.area == bestResult.area && r.H == bestResult.H && r.W < bestResult.W)){
                bestResult = r; found = true;
            }
        }
    }
    done:

    if(!found) bestResult = pack(base, orderAscDim);

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
