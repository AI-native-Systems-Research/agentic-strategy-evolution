#include <bits/stdc++.h>
using namespace std;

struct ItemType { string type; int w, h, v, limit; };
struct Placement { string type; int x, y, rot; };
struct Rect { int x, y, w, h; };

static int gW, gH;
static bool gAllowRotate;
static int gM;
static vector<ItemType> items;
static vector<double> density;
static vector<Placement> bestPlacements;
static long long bestProfit = 0;

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
    
    void pruneRects() {
        int n = freeRects.size();
        if (n <= 1) return;
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
        vector<Rect> nr;
        for (int i = 0; i < n; i++) if (!rem[i]) nr.push_back(freeRects[i]);
        freeRects = move(nr);
        if ((int)freeRects.size() > 600) {
            sort(freeRects.begin(), freeRects.end(), [](const Rect& a, const Rect& b) {
                return (long long)a.w * a.h > (long long)b.w * b.h;
            });
            freeRects.resize(600);
        }
    }
    
    void splitAndUpdate(int px, int py, int pw, int ph) {
        vector<Rect> newRects;
        newRects.reserve(freeRects.size() + 4);
        int pR = px + pw, pT = py + ph;
        for (auto& fr : freeRects) {
            int frR = fr.x + fr.w, frT = fr.y + fr.h;
            if (px >= frR || pR <= fr.x || py >= frT || pT <= fr.y) {
                newRects.push_back(fr);
                continue;
            }
            if (px > fr.x) newRects.push_back({fr.x, fr.y, px - fr.x, fr.h});
            if (pR < frR) newRects.push_back({pR, fr.y, frR - pR, fr.h});
            if (py > fr.y) newRects.push_back({fr.x, fr.y, fr.w, py - fr.y});
            if (pT < frT) newRects.push_back({fr.x, pT, fr.w, frT - pT});
        }
        freeRects = move(newRects);
        pruneRects();
    }
    
    void doPlace(int ti, int ox, int oy, int rot) {
        int rw = (rot == 0) ? items[ti].w : items[ti].h;
        int rh = (rot == 0) ? items[ti].h : items[ti].w;
        placements.push_back({items[ti].type, ox, oy, rot});
        used[ti]++;
        totalProfit += items[ti].v;
        splitAndUpdate(ox, oy, rw, rh);
    }
    
    void updateBest() {
        if (totalProfit > bestProfit) {
            bestProfit = totalProfit;
            bestPlacements = placements;
        }
    }
};

void runGreedy(vector<pair<int,int>>& order, int strategy) {
    State state;
    state.init();
    for (auto& [ti, rot] : order) {
        if (state.used[ti] >= items[ti].limit) continue;
        int rw = (rot == 0) ? items[ti].w : items[ti].h;
        int rh = (rot == 0) ? items[ti].h : items[ti].w;
        if (rw > gW || rh > gH) continue;
        int bestScore = INT_MIN;
        int ox = -1, oy = -1;
        for (auto& fr : state.freeRects) {
            if (rw <= fr.w && rh <= fr.h) {
                int score;
                switch(strategy) {
                    case 0: score = -min(fr.w - rw, fr.h - rh); break;
                    case 1: score = -max(fr.w - rw, fr.h - rh); break;
                    case 2: score = -(fr.w * fr.h - rw * rh); break;
                    case 3: score = -(fr.y * 20000 + fr.x); break;
                    default: score = 0;
                        if (fr.x == 0) score += rh;
                        if (fr.y == 0) score += rw;
                        if (fr.x + rw == gW) score += rh;
                        if (fr.y + rh == gH) score += rw;
                        break;
                }
                if (score > bestScore) { bestScore = score; ox = fr.x; oy = fr.y; }
            }
        }
        if (ox >= 0) state.doPlace(ti, ox, oy, rot);
    }
    state.updateBest();
}

void runSmart(int strategy, double alpha, mt19937* rng = nullptr, double noise = 0.0) {
    State state;
    state.init();
    while (true) {
        int bestTi = -1, bestRot = -1, bestX = -1, bestY = -1;
        double bestEval = -1e18;
        for (int ti = 0; ti < gM; ti++) {
            if (state.used[ti] >= items[ti].limit) continue;
            int nrots = 1;
            if (gAllowRotate && items[ti].w != items[ti].h) nrots = 2;
            for (int rot = 0; rot < nrots; rot++) {
                int rw = (rot == 0) ? items[ti].w : items[ti].h;
                int rh = (rot == 0) ? items[ti].h : items[ti].w;
                if (rw > gW || rh > gH) continue;
                for (auto& fr : state.freeRects) {
                    if (rw <= fr.w && rh <= fr.h) {
                        double fitScore;
                        switch(strategy) {
                            case 0: fitScore = -min(fr.w - rw, fr.h - rh); break;
                            case 1: fitScore = -max(fr.w - rw, fr.h - rh); break;
                            case 2: fitScore = -(double)(fr.w * fr.h - rw * rh); break;
                            default: fitScore = -(fr.y * 20000.0 + fr.x); break;
                        }
                        double eval = alpha * density[ti] + (1.0 - alpha) * fitScore / (double)(gW + gH);
                        if (rng && noise > 0.0) {
                            eval += uniform_real_distribution<double>(-noise, noise)(*rng);
                        }
                        if (eval > bestEval) {
                            bestEval = eval;
                            bestTi = ti; bestRot = rot; bestX = fr.x; bestY = fr.y;
                        }
                    }
                }
            }
        }
        if (bestTi < 0) break;
        state.doPlace(bestTi, bestX, bestY, bestRot);
    }
    state.updateBest();
}

void runStrip() {
    for (int ti = 0; ti < gM; ti++) {
        int nrots = 1;
        if (gAllowRotate && items[ti].w != items[ti].h) nrots = 2;
        for (int rot = 0; rot < nrots; rot++) {
            int rw = (rot == 0) ? items[ti].w : items[ti].h;
            int rh = (rot == 0) ? items[ti].h : items[ti].w;
            if (rw > gW || rh > gH) continue;
            int nx = gW / rw, ny = gH / rh;
            int count = min((long long)nx * ny, (long long)items[ti].limit);
            if (count == 0) continue;
            State state;
            state.init();
            int placed = 0;
            for (int iy = 0; iy < ny && placed < count; iy++)
                for (int ix = 0; ix < nx && placed < count; ix++, placed++)
                    state.doPlace(ti, ix * rw, iy * rh, rot);
            
            vector<pair<double,int>> densOrder;
            for (int j = 0; j < gM; j++) densOrder.push_back({density[j], j});
            sort(densOrder.begin(), densOrder.end(), greater<>());
            bool changed = true;
            while (changed) {
                changed = false;
                for (auto& [d, tj] : densOrder) {
                    if (state.used[tj] >= items[tj].limit) continue;
                    int nr2 = 1;
                    if (gAllowRotate && items[tj].w != items[tj].h) nr2 = 2;
                    for (int r2 = 0; r2 < nr2; r2++) {
                        int w2 = (r2 == 0) ? items[tj].w : items[tj].h;
                        int h2 = (r2 == 0) ? items[tj].h : items[tj].w;
                        if (w2 > gW || h2 > gH) continue;
                        bool found = true;
                        while (found && state.used[tj] < items[tj].limit) {
                            found = false;
                            int bs = INT_MAX, bx = -1, by = -1;
                            for (auto& fr : state.freeRects) {
                                if (w2 <= fr.w && h2 <= fr.h) {
                                    int s = min(fr.w - w2, fr.h - h2);
                                    if (s < bs) { bs = s; bx = fr.x; by = fr.y; }
                                }
                            }
                            if (bx >= 0) { state.doPlace(tj, bx, by, r2); found = true; changed = true; }
                        }
                    }
                }
            }
            state.updateBest();
        }
    }
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);
    
    string input((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());
    
    // Simple JSON parsing
    auto getInt = [&](const string& s, size_t p) -> pair<int,size_t> {
        while (p < s.size() && !isdigit(s[p]) && s[p]!='-') p++;
        bool neg = s[p]=='-'; if(neg) p++;
        int v=0; while(p<s.size()&&isdigit(s[p])) v=v*10+(s[p++]-'0');
        return {neg?-v:v, p};
    };
    auto getStr = [&](const string& s, size_t p) -> pair<string,size_t> {
        while(p<s.size()&&s[p]!='"') p++; p++;
        string r; while(p<s.size()&&s[p]!='"') r+=s[p++]; p++;
        return {r,p};
    };
    
    // Parse W, H
    size_t p = input.find("\"W\""); auto [W,p1] = getInt(input, p+3); gW=W;
    // Find "H" that's exactly "H" not "Hxxx"
    p = 0;
    while(true) {
        p = input.find("\"H\"", p);
        if(p==string::npos) break;
        auto [H,p2] = getInt(input, p+3); gH=H; break;
    }
    p = input.find("\"allow_rotate\"");
    size_t tp = p+14; while(tp<input.size()&&input[tp]!='t'&&input[tp]!='f') tp++;
    gAllowRotate = input[tp]=='t';
    
    p = input.find("\"items\"");
    p = input.find('[', p);
    size_t endArr = input.rfind(']');
    
    while(true) {
        size_t ob = input.find('{', p);
        if(ob==string::npos||ob>endArr) break;
        size_t cb = input.find('}', ob);
        string obj = input.substr(ob, cb-ob+1);
        ItemType it;
        
        size_t q = obj.find("\"type\""); auto [ts,_1] = getStr(obj, q+6); it.type=ts;
        
        // find "w" exactly
        q=0; while(true){q=obj.find("\"w\"",q); if(q==string::npos)break; break;} 
        auto [wv,_2] = getInt(obj, q+3); it.w=wv;
        q=0; while(true){q=obj.find("\"h\"",q); if(q==string::npos)break; break;}
        auto [hv,_3] = getInt(obj, q+3); it.h=hv;
        q=obj.find("\"v\""); auto [vv,_4] = getInt(obj, q+3); it.v=vv;
        q=obj.find("\"limit\""); auto [lv,_5] = getInt(obj, q+7); it.limit=lv;
        
        items.push_back(it);
        p = cb+1;
    }
    
    gM = items.size();
    density.resize(gM);
    for(int i=0;i<gM;i++) density[i]=(double)items[i].v/((double)items[i].w*items[i].h);
    
    auto t0 = chrono::steady_clock::now();
    auto ms = [&](){return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    
    mt19937 rng(42);
    
    auto makeOrder = [&](int sm) -> vector<pair<int,int>> {
        struct C{int ti,rot;double sc;};
        vector<C> cs;
        for(int i=0;i<gM;i++){
            int nr=1; if(gAllowRotate&&items[i].w!=items[i].h) nr=2;
            for(int r=0;r<nr;r++){
                int rw=(r==0)?items[i].w:items[i].h, rh=(r==0)?items[i].h:items[i].w;
                if(rw>gW||rh>gH) continue;
                double sc; switch(sm){case 0:sc=density[i];break;case 1:sc=items[i].v;break;case 2:sc=-(double)(items[i].w*items[i].h);break;case 3:sc=(double)(items[i].w*items[i].h);break;case 4:sc=-max(rw,rh);break;case 5:sc=max(rw,rh);break;default:sc=uniform_real_distribution<>(0,1)(rng);break;}
                for(int k=0;k<items[i].limit;k++) cs.push_back({i,r,sc});
            }
        }
        if(sm>=6) shuffle(cs.begin(),cs.end(),rng);
        else sort(cs.begin(),cs.end(),[](const C&a,const C&b){return a.sc>b.sc;});
        vector<pair<int,int>> res; vector<int> uc(gM,0);
        for(auto&c:cs) if(uc[c.ti]<items[c.ti].limit){res.push_back({c.ti,c.rot});uc[c.ti]++;}
        return res;
    };
    
    runStrip();
    for(int sm=0;sm<6&&ms()<200;sm++) for(int ps=0;ps<5&&ms()<200;ps++){auto o=makeOrder(sm);runGreedy(o,ps);}
    for(double a:{0.0,0.1,0.2,0.3,0.5,0.7,0.9,1.0}) for(int ps=0;ps<4&&ms()<500;ps++) runSmart(ps,a);
    for(int i=0;i<100&&ms()<700;i++){int ps=rng()%4;double a=uniform_real_distribution<>(0,1)(rng);double n=uniform_real_distribution<>(0.001,0.1)(rng);runSmart(ps,a,&rng,n);}
    while(ms()<920){int c=rng()%2;if(c==0){auto o=makeOrder(6);runGreedy(o,rng()%5);}else{runSmart(rng()%4,uniform_real_distribution<>(0,1)(rng),&rng,uniform_real_distribution<>(0.001,0.05)(rng));}}
    
    // Output JSON
    cout << "{\"placements\":[";
    for(int i=0;i<(int)bestPlacements.size();i++){
        if(i) cout<<",";
        auto&p=bestPlacements[i];
        cout<<"{\"type\":\""<<p.type<<"\",\"x\":"<<p.x<<",\"y\":"<<p.y<<",\"rot\":"<<p.rot<<"}";
    }
    cout<<"]}"<<endl;
    return 0;
}
