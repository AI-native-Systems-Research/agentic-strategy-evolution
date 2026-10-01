#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <algorithm>
#include <functional>
#include <cmath>
#include <climits>
#include <cstring>
#include <random>
#include <chrono>
#include <numeric>
using namespace std;

struct Item { string type; int w, h; long long v; int limit; double density; };
struct Rect { int x, y, w, h; };
struct Placement { string type; int x, y, rot; };

// === Maximal Rectangles Bin ===
struct MaxRectsBin {
    int binW, binH;
    vector<Rect> freeRects;

    void init(int W, int H) {
        binW = W; binH = H;
        freeRects.clear();
        freeRects.reserve(256);
        freeRects.push_back({0, 0, W, H});
    }

    bool findBSSF(int w, int h, int &px, int &py) const {
        int bs = INT_MAX, bl = INT_MAX; px = py = -1;
        for (auto &r : freeRects) {
            if (w <= r.w && h <= r.h) {
                int s = min(r.h-h, r.w-w), l = max(r.h-h, r.w-w);
                if (s < bs || (s == bs && l < bl)) { bs=s; bl=l; px=r.x; py=r.y; }
            }
        }
        return px >= 0;
    }
    bool findBAF(int w, int h, int &px, int &py) const {
        int ba = INT_MAX, bs = INT_MAX; px = py = -1;
        for (auto &r : freeRects) {
            if (w <= r.w && h <= r.h) {
                int a = r.w*r.h - w*h, s = min(r.h-h, r.w-w);
                if (a < ba || (a == ba && s < bs)) { ba=a; bs=s; px=r.x; py=r.y; }
            }
        }
        return px >= 0;
    }
    bool findBL(int w, int h, int &px, int &py) const {
        int by = INT_MAX, bx = INT_MAX; px = py = -1;
        for (auto &r : freeRects) {
            if (w <= r.w && h <= r.h) {
                if (r.y < by || (r.y == by && r.x < bx)) { by=r.y; bx=r.x; px=r.x; py=r.y; }
            }
        }
        return px >= 0;
    }

    bool place(int w, int h, int &px, int &py, int m) {
        bool ok;
        if (m==0) ok = findBSSF(w,h,px,py);
        else if (m==1) ok = findBAF(w,h,px,py);
        else ok = findBL(w,h,px,py);
        if (!ok) return false;
        splitFreeRects({px,py,w,h});
        pruneFreeRects();
        return true;
    }

    void splitFreeRects(const Rect &used) {
        int n = freeRects.size();
        vector<Rect> newRects;
        for (int i = n-1; i >= 0; i--) {
            Rect &r = freeRects[i];
            if (used.x >= r.x+r.w || used.x+used.w <= r.x ||
                used.y >= r.y+r.h || used.y+used.h <= r.y) continue;
            if (used.x > r.x) newRects.push_back({r.x, r.y, used.x-r.x, r.h});
            if (used.x+used.w < r.x+r.w) newRects.push_back({used.x+used.w, r.y, r.x+r.w-used.x-used.w, r.h});
            if (used.y > r.y) newRects.push_back({r.x, r.y, r.w, used.y-r.y});
            if (used.y+used.h < r.y+r.h) newRects.push_back({r.x, used.y+used.h, r.w, r.y+r.h-used.y-used.h});
            freeRects[i] = freeRects[n-1];
            freeRects.resize(n-1);
            n--;
        }
        for (auto &r : newRects) freeRects.push_back(r);
    }

    void pruneFreeRects() {
        for (int i = (int)freeRects.size()-1; i >= 0; i--) {
            for (int j = (int)freeRects.size()-1; j >= 0; j--) {
                if (i==j || i>=(int)freeRects.size()) continue;
                if (freeRects[i].x >= freeRects[j].x && freeRects[i].y >= freeRects[j].y &&
                    freeRects[i].x+freeRects[i].w <= freeRects[j].x+freeRects[j].w &&
                    freeRects[i].y+freeRects[i].h <= freeRects[j].y+freeRects[j].h) {
                    freeRects[i] = freeRects.back(); freeRects.pop_back(); break;
                }
            }
        }
    }
};

// === Skyline Bin Packing ===
struct SkylineBin {
    int binW, binH;
    struct SkyNode { int x, y, w; };
    vector<SkyNode> skyline;

    void init(int W, int H) {
        binW = W; binH = H;
        skyline.clear();
        skyline.push_back({0, 0, W});
    }

    // Find position for item of size w×h using bottom-left with waste minimization
    bool findBL(int w, int h, int &bestIdx, int &px, int &py, int &bestWaste) const {
        bestIdx = -1; px = py = -1;
        int minY = INT_MAX;
        bestWaste = INT_MAX;

        for (int i = 0; i < (int)skyline.size(); i++) {
            int y;
            int waste;
            if (!canFit(i, w, h, y, waste)) continue;
            if (y < minY || (y == minY && waste < bestWaste)) {
                minY = y; bestIdx = i; px = skyline[i].x; py = y; bestWaste = waste;
            }
        }
        return bestIdx >= 0;
    }

    bool canFit(int idx, int w, int h, int &y, int &waste) const {
        int x = skyline[idx].x;
        if (x + w > binW) return false;
        y = 0; waste = 0;
        int wLeft = w;
        int i = idx;
        while (wLeft > 0 && i < (int)skyline.size()) {
            y = max(y, skyline[i].y);
            if (y + h > binH) return false;
            int segW = min(skyline[i].w, wLeft);
            waste += segW * (y - skyline[i].y); // wasted space under the item
            wLeft -= segW;
            i++;
        }
        if (wLeft > 0) return false;
        return true;
    }

    void place(int idx, int w, int h) {
        SkyNode newNode = {skyline[idx].x, skyline[idx].y + h, w};
        // Determine the actual y
        int y = 0;
        int wLeft = w;
        int i = idx;
        while (wLeft > 0) {
            y = max(y, skyline[i].y);
            wLeft -= min(skyline[i].w, wLeft);
            i++;
        }
        newNode.y = y + h;

        // Remove covered segments
        int x = skyline[idx].x;
        wLeft = w;
        while (wLeft > 0 && idx < (int)skyline.size()) {
            int segW = skyline[idx].w;
            if (segW <= wLeft) {
                wLeft -= segW;
                skyline.erase(skyline.begin() + idx);
            } else {
                skyline[idx].x += wLeft;
                skyline[idx].w -= wLeft;
                wLeft = 0;
            }
        }
        skyline.insert(skyline.begin() + idx, newNode);

        // Merge adjacent segments with same y
        for (int j = (int)skyline.size()-2; j >= 0; j--) {
            if (skyline[j].y == skyline[j+1].y) {
                skyline[j].w += skyline[j+1].w;
                skyline.erase(skyline.begin() + j + 1);
            }
        }
    }
};

struct PackResult { vector<Placement> pl; long long profit; };

// MaxRects greedy
PackResult greedyMaxRects(int W, int H, bool allowRotate, const vector<Item> &items,
                           const vector<int> &typeOrder, int method) {
    MaxRectsBin bin; bin.init(W, H);
    PackResult res; res.profit = 0;
    vector<int> used(items.size(), 0);

    for (int ti : typeOrder) {
        const auto &it = items[ti];
        while (used[ti] < it.limit) {
            int px, py;
            bool ok = bin.place(it.w, it.h, px, py, method);
            int rot = 0;
            if (!ok && allowRotate && it.w != it.h) {
                ok = bin.place(it.h, it.w, px, py, method);
                rot = 1;
            }
            if (!ok) break;
            res.pl.push_back({it.type, px, py, rot});
            res.profit += it.v;
            used[ti]++;
        }
    }
    return res;
}

// Skyline greedy
PackResult greedySkyline(int W, int H, bool allowRotate, const vector<Item> &items,
                          const vector<int> &typeOrder) {
    SkylineBin bin; bin.init(W, H);
    PackResult res; res.profit = 0;
    vector<int> used(items.size(), 0);

    for (int ti : typeOrder) {
        const auto &it = items[ti];
        while (used[ti] < it.limit) {
            int idx, px, py, waste;
            int idx2, px2, py2, waste2;
            bool f1 = bin.findBL(it.w, it.h, idx, px, py, waste);
            bool f2 = false;
            int rot = 0;
            if (allowRotate && it.w != it.h) {
                f2 = bin.findBL(it.h, it.w, idx2, px2, py2, waste2);
            }
            if (f1 && f2) {
                // Pick lower waste
                if (waste2 < waste) {
                    bin.place(idx2, it.h, it.w);
                    res.pl.push_back({it.type, px2, py2, 1});
                } else {
                    bin.place(idx, it.w, it.h);
                    res.pl.push_back({it.type, px, py, 0});
                }
            } else if (f1) {
                bin.place(idx, it.w, it.h);
                res.pl.push_back({it.type, px, py, 0});
            } else if (f2) {
                bin.place(idx2, it.h, it.w);
                res.pl.push_back({it.type, px2, py2, 1});
            } else {
                break;
            }
            res.profit += it.v;
            used[ti]++;
        }
    }
    return res;
}

int main(){
    auto t0 = chrono::steady_clock::now();
    string input; { ostringstream o; o << cin.rdbuf(); input = o.str(); }

    auto fI = [&](const string &s, const string &key) -> long long {
        string k = "\"" + key + "\"";
        size_t p = s.find(k); if (p==string::npos) return 0;
        p = s.find(':', p)+1;
        while (p<s.size()&&isspace(s[p])) p++;
        long long v=0; bool neg=false;
        if (s[p]=='-'){neg=true;p++;}
        while (p<s.size()&&isdigit(s[p])){v=v*10+(s[p]-'0');p++;}
        return neg?-v:v;
    };
    auto fB = [&](const string &s, const string &key) -> bool {
        size_t p=s.find("\""+key+"\""); if(p==string::npos) return false;
        p=s.find(':',p)+1; while(p<s.size()&&isspace(s[p]))p++;
        return s.substr(p,4)=="true";
    };
    auto fS = [&](const string &s, const string &key) -> string {
        size_t p=s.find("\""+key+"\""); if(p==string::npos) return "";
        p=s.find(':',p)+1; while(p<s.size()&&isspace(s[p]))p++;
        if(s[p]!='"') return ""; p++; string r;
        while(p<s.size()&&s[p]!='"') r+=s[p++]; return r;
    };

    int W=(int)fI(input,"W"), H=(int)fI(input,"H");
    bool allowRot=fB(input,"allow_rotate");

    vector<Item> items;
    size_t ip=input.find("\"items\""), as=input.find('[',ip);
    int d=0; size_t ae=as;
    for(size_t i=as;i<input.size();i++){if(input[i]=='[')d++;if(input[i]==']'){d--;if(!d){ae=i;break;}}}
    size_t pos=as;
    while(true){
        size_t os=input.find('{',pos+1); if(os==string::npos||os>ae) break;
        size_t oe=input.find('}',os); if(oe==string::npos) break;
        string obj=input.substr(os,oe-os+1);
        Item it; it.type=fS(obj,"type");
        if(it.type.empty()){pos=oe;continue;}
        it.w=(int)fI(obj,"w"); it.h=(int)fI(obj,"h");
        it.v=fI(obj,"v"); it.limit=(int)fI(obj,"limit");
        it.density=(double)it.v/((double)it.w*it.h);
        items.push_back(it); pos=oe;
    }
    int M=items.size();
    if(!M){cout<<"{\"placements\":[]}"<<endl;return 0;}

    vector<Placement> best; long long bestP=-1;
    auto tryR=[&](PackResult &r){if(r.profit>bestP){bestP=r.profit;best=move(r.pl);}};

    auto mkOrd=[&](function<bool(int,int)> cmp){
        vector<int> o(M); iota(o.begin(),o.end(),0);
        sort(o.begin(),o.end(),cmp); return o;
    };

    // Orderings
    vector<function<bool(int,int)>> cmps = {
        [&](int a,int b){return items[a].density>items[b].density;},
        [&](int a,int b){return items[a].v>items[b].v;},
        [&](int a,int b){return (long long)items[a].w*items[a].h>(long long)items[b].w*items[b].h;},
        [&](int a,int b){return max(items[a].w,items[a].h)>max(items[b].w,items[b].h);},
        [&](int a,int b){return items[a].v*(long long)items[a].limit>items[b].v*(long long)items[b].limit;},
        [&](int a,int b){return items[a].w+items[a].h>items[b].w+items[b].h;},
    };

    // MaxRects strategies
    for(auto &c:cmps){
        auto o=mkOrd(c);
        for(int m=0;m<3;m++){auto r=greedyMaxRects(W,H,allowRot,items,o,m);tryR(r);}
    }

    // Skyline strategies
    for(auto &c:cmps){
        auto o=mkOrd(c);
        auto r=greedySkyline(W,H,allowRot,items,o);tryR(r);
    }

    // Randomized MaxRects
    mt19937 rng(12345);
    while(true){
        if(chrono::duration<double>(chrono::steady_clock::now()-t0).count()>0.65) break;
        vector<pair<double,int>> sc(M);
        for(int i=0;i<M;i++) sc[i]={items[i].density*uniform_real_distribution<>(0.1,10.0)(rng),i};
        sort(sc.rbegin(),sc.rend());
        vector<int> o(M); for(int i=0;i<M;i++) o[i]=sc[i].second;
        int m=uniform_int_distribution<>(0,2)(rng);
        auto r=greedyMaxRects(W,H,allowRot,items,o,m);tryR(r);
    }

    // Randomized Skyline
    while(true){
        if(chrono::duration<double>(chrono::steady_clock::now()-t0).count()>0.75) break;
        vector<pair<double,int>> sc(M);
        for(int i=0;i<M;i++) sc[i]={items[i].density*uniform_real_distribution<>(0.1,10.0)(rng),i};
        sort(sc.rbegin(),sc.rend());
        vector<int> o(M); for(int i=0;i<M;i++) o[i]=sc[i].second;
        auto r=greedySkyline(W,H,allowRot,items,o);tryR(r);
    }

    cout<<"{\"placements\":[";
    for(int i=0;i<(int)best.size();i++){
        if(i) cout<<",";
        cout<<"{\"type\":\""<<best[i].type<<"\",\"x\":"<<best[i].x
            <<",\"y\":"<<best[i].y<<",\"rot\":"<<best[i].rot<<"}";
    }
    cout<<"]}"<<endl;
    return 0;
}
