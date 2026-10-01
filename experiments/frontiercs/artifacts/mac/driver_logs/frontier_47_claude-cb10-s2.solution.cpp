Looking at the previous attempt, it was truncated mid-code and had the code block nested incorrectly. I need to write a complete, working solution.

My approach:
1. Parse JSON input
2. Try multiple packing strategies: MaxRects with various heuristics, strip-based packing, greedy approaches, and a strip knapsack with branch-and-bound
3. Fill gaps recursively
4. Pick the best result within the time budget

```cpp
#include <bits/stdc++.h>
using namespace std;

int W, H, M;
bool allow_rot;

struct Item { string type; int w, h; long long v; int limit; };
vector<Item> items;

struct Placement { string type; int x, y, rot; };

struct Rect { int x, y, w, h; };

struct MaxRects {
    int BW, BH;
    vector<Rect> fr;
    
    void init(int w, int h) { BW=w; BH=h; fr.clear(); fr.push_back({0,0,w,h}); }
    
    void prune() {
        int n = fr.size();
        vector<bool> del(n, false);
        for (int i = 0; i < n; i++) {
            if (del[i]) continue;
            for (int j = i+1; j < n; j++) {
                if (del[j]) continue;
                auto &a=fr[i], &b=fr[j];
                if (a.x<=b.x && a.y<=b.y && a.x+a.w>=b.x+b.w && a.y+a.h>=b.y+b.h)
                    del[j]=true;
                else if (b.x<=a.x && b.y<=a.y && b.x+b.w>=a.x+a.w && b.y+b.h>=a.y+a.h)
                    { del[i]=true; break; }
            }
        }
        vector<Rect> nfr;
        for (int i=0;i<n;i++) if(!del[i]) nfr.push_back(fr[i]);
        fr=nfr;
        if ((int)fr.size() > 2000) {
            sort(fr.begin(), fr.end(), [](auto&a,auto&b){return (long long)a.w*a.h>(long long)b.w*b.h;});
            fr.resize(2000);
        }
    }
    
    void insert(int px, int py, int pw, int ph) {
        int rx2=px+pw, ry2=py+ph;
        vector<Rect> nfr;
        for (auto& r : fr) {
            int rr=r.x+r.w, rt=r.y+r.h;
            if (px>=rr || rx2<=r.x || py>=rt || ry2<=r.y) {
                nfr.push_back(r); continue;
            }
            if (px > r.x) nfr.push_back({r.x, r.y, px-r.x, r.h});
            if (rx2 < rr) nfr.push_back({rx2, r.y, rr-rx2, r.h});
            if (py > r.y) nfr.push_back({r.x, r.y, r.w, py-r.y});
            if (ry2 < rt) nfr.push_back({r.x, ry2, r.w, rt-ry2});
        }
        fr=nfr;
        prune();
    }
    
    bool findPos(int pw, int ph, int& bx, int& by, int heur) {
        bx=by=-1;
        long long bs1=LLONG_MAX, bs2=LLONG_MAX;
        for (auto& r : fr) {
            if (pw>r.w || ph>r.h) continue;
            long long s1,s2;
            int sf1=r.w-pw, sf2=r.h-ph;
            switch(heur) {
                case 0: s1=min(sf1,sf2); s2=max(sf1,sf2); break;
                case 1: s1=r.y; s2=r.x; break;
                case 2: s1=(long long)r.w*r.h; s2=min(sf1,sf2); break;
                case 3: s1=max(sf1,sf2); s2=min(sf1,sf2); break;
                default: s1=min(sf1,sf2); s2=max(sf1,sf2); break;
            }
            if (s1<bs1||(s1==bs1&&s2<bs2)) { bs1=s1;bs2=s2;bx=r.x;by=r.y; }
        }
        return bx>=0;
    }
};

struct Cand { int ti, rot, pw, ph; double density; };
vector<Cand> allCands;

long long bestVal = 0;
vector<Placement> bestPl;

void updateBest(long long v, const vector<Placement>& pl) {
    if (v > bestVal) { bestVal = v; bestPl = pl; }
}

void fillRegion(int rx, int ry, int rw, int rh, vector<int>& used, vector<Placement>& pl, long long& val, int heur) {
    if (rw<=0||rh<=0) return;
    MaxRects mr; mr.init(rw,rh);
    auto cands = allCands;
    sort(cands.begin(),cands.end(),[](auto&a,auto&b){return a.density>b.density;});
    for (auto& c : cands) {
        if (c.pw>rw&&c.ph>rh) continue;
        while (used[c.ti]<items[c.ti].limit) {
            int bx,by;
            if (!mr.findPos(c.pw,c.ph,bx,by,heur)) break;
            if (bx+c.pw+rx>W || by+c.ph+ry>H) break;
            mr.insert(bx,by,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bx+rx,by+ry,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
    }
}

pair<long long,vector<Placement>> packSequential(vector<Cand>& order, int heur) {
    MaxRects mr; mr.init(W,H);
    vector<int> used(M,0);
    vector<Placement> pl;
    long long val=0;
    for (auto& c : order) {
        while (used[c.ti]<items[c.ti].limit) {
            int bx,by;
            if (!mr.findPos(c.pw,c.ph,bx,by,heur)) break;
            mr.insert(bx,by,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bx,by,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
    }
    return {val,pl};
}

pair<long long,vector<Placement>> greedyBest(int heur, int scoreMode) {
    MaxRects mr; mr.init(W,H);
    vector<int> used(M,0);
    vector<Placement> pl;
    long long val=0;
    
    while(true) {
        int bestCI=-1; int bbx=0,bby=0;
        double bestScore=-1e30;
        for (int ci=0;ci<(int)allCands.size();ci++) {
            auto& c=allCands[ci];
            if (used[c.ti]>=items[c.ti].limit) continue;
            int fx,fy;
            if (!mr.findPos(c.pw,c.ph,fx,fy,heur)) continue;
            double score;
            switch(scoreMode) {
                case 0: score=c.density; break;
                case 1: score=(double)items[c.ti].v; break;
                case 2: score=c.density*1e6 - (double)(fx+fy); break;
                case 3: score=(double)items[c.ti].v / max(c.pw,c.ph); break;
                default: score=c.density;
            }
            if (score>bestScore) { bestScore=score; bestCI=ci; bbx=fx; bby=fy; }
        }
        if (bestCI<0) break;
        auto& c=allCands[bestCI];
        mr.insert(bbx,bby,c.pw,c.ph);
        pl.push_back({items[c.ti].type,bbx,bby,c.rot});
        val+=items[c.ti].v; used[c.ti]++;
    }
    return {val,pl};
}

pair<long long,vector<Placement>> adaptiveStrip(bool horiz) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl;
    long long val=0;
    vector<array<int,4>> gaps;
    
    while (pos < mainDim) {
        int bestTi=-1,bestR=0,bestThick=0,bestCross=0,bestPer=0;
        double bestDens=-1;
        for (int i=0;i<M;i++) {
            if (used[i]>=items[i].limit) continue;
            for (int r=0;r<(allow_rot?2:1);r++) {
                int pw=r?items[i].h:items[i].w;
                int ph=r?items[i].w:items[i].h;
                if (pw>W||ph>H) continue;
                int thick=horiz?ph:pw;
                int cross=horiz?pw:ph;
                if (pos+thick>mainDim) continue;
                int per=crossDim/cross;
                if (per<=0) continue;
                int avail=items[i].limit-used[i];
                per=min(per,avail);
                if (per<=0) continue;
                double d=(double)per*items[i].v/thick;
                if (d>bestDens) {
                    bestDens=d; bestTi=i; bestR=r; bestThick=thick; bestCross=cross; bestPer=per;
                }
            }
        }
        if (bestTi<0) break;
        
        int placed=0;
        for (int j=0;j<bestPer;j++) {
            int x,y;
            if (horiz) {x=j*bestCross;y=pos;}
            else {x=pos;y=j*bestCross;}
            pl.push_back({items[bestTi].type,x,y,bestR});
            val+=items[bestTi].v; used[bestTi]++; placed++;
        }
        int endCoord=placed*bestCross;
        int gapSize=crossDim-endCoord;
        if (gapSize>0) {
            if (horiz) gaps.push_back({endCoord,pos,gapSize,bestThick});
            else gaps.push_back({pos,endCoord,bestThick,gapSize});
        }
        pos+=bestThick;
    }
    
    if (pos<mainDim) {
        if (horiz) gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    
    for (auto& g : gaps) {
        fillRegion(g[0],g[1],g[2],g[3],used,pl,val,0);
    }
    
    return {val,pl};
}

pair<long long,vector<Placement>> mixedStrip(bool horiz) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    struct SC { int ti, rot, thick, cross, per; long long valPer; double dens; };
    vector<SC> allSC;
    
    for (int i=0;i<M;i++) {
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw=r?items[i].h:items[i].w;
            int ph=r?items[i].w:items[i].h;
            if (pw>W||ph>H) continue;
            int thick=horiz?ph:pw;
            int cross=horiz?pw:ph;
            int per=crossDim/cross;
            if (per<=0||thick<=0) continue;
            allSC.push_back({i,r,thick,cross,per,(long long)per*items[i].v,
                (double)per*items[i].v/thick});
        }
    }
    
    sort(allSC.begin(),allSC.end(),[](auto&a,auto&b){return a.dens>b.dens;});
    
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl;
    long long val=0;
    vector<array<int,4>> gaps;
    
    for (auto& sc : allSC) {
        while (pos+sc.thick<=mainDim && used[sc.ti]<items[sc.ti].limit) {
            int avail=items[sc.ti].limit-used[sc.ti];
            if (avail<=0) break;
            int toPlace=min(sc.per,avail);
            int placed=0;
            for (int j=0;j<toPlace;j++) {
                int x,y;
                if (horiz) {x=j*sc.cross;y=pos;}
                else {x=pos;y=j*sc.cross;}
                pl.push_back({items[sc.ti].type,x,y,sc.rot});
                val+=items[sc.ti].v; used[sc.ti]++; placed++;
            }
            int endCoord=placed*sc.cross;
            int gapSize=crossDim-endCoord;
            if (gapSize>0) {
                if (horiz) gaps.push_back({endCoord,pos,gapSize,sc.thick});
                else gaps.push_back({pos,endCoord,sc.thick,gapSize});
            }
            pos+=sc.thick;
        }
    }
    
    if (pos<mainDim) {
        if (horiz) gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    
    for (auto& g : gaps) {
        fillRegion(g[0],g[1],g[2],g[3],used,pl,val,0);
    }
    
    return {val,pl};
}

// Strip knapsack with branch-and-bound
pair<long long,vector<Placement>> stripKnapsack(bool horiz, chrono::steady_clock::time_point deadline) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    struct SC { int ti, rot, thick, cross, per; long long valPer; double dens; };
    vector<SC> configs;
    
    for (int i=0;i<M;i++) {
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw=r?items[i].h:items[i].w;
            int ph=r?items[i].w:items[i].h;
            if (pw>W||ph>H) continue;
            int thick=horiz?ph:pw;
            int cross=horiz?pw:ph;
            int per=crossDim/cross;
            if (per<=0||thick<=0) continue;
            configs.push_back({i,r,thick,cross,per,(long long)per*items[i].v,
                (double)per*items[i].v/thick});
        }
    }
    
    int nC=configs.size();
    if (nC==0) return {0,{}};
    
    vector<int> order(nC);
    iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){return configs[a].dens>configs[b].dens;});
    
    long long bbBestV=0;
    vector<int> bbBestCounts(nC,0);
    vector<int> curCounts(nC,0);
    vector<int> typeUsed(M,0);
    long long curVal=0;
    int curUsed=0;
    int nodeCount=0;
    bool timedOut=false;
    
    function<void(int)> solve = [&](int idx) {
        if (timedOut) return;
        nodeCount++;
        if (nodeCount%5000==0) {
            if (chrono::steady_clock::now()>deadline) { timedOut=true; return; }
        }
        
        if (curVal>bbBestV) { bbBestV=curVal; bbBestCounts=curCounts; }
        if (idx>=nC) return;
        
        int rem=mainDim-curUsed;
        if (rem<=0) return;
        
        // Upper bound using fractional relaxation
        long long ub=curVal;
        double remD=rem;
        vector<int> tmpUsed=typeUsed;
        for (int i=idx;i<nC;i++) {
            int oi=order[i];
            auto& c=configs[oi];
            int availItems=items[c.ti].limit-tmpUsed[c.ti];
            if (availItems<=0) continue;
            int maxSbySpace=(int)(remD/c.thick);
            int maxSbyItems=(availItems+c.per-1)/c.per;
            int maxS=min(maxSbySpace, maxSbyItems);
            if (maxS>0) {
                int actualItems=min(maxS*c.per,availItems);
                ub+=(long long)actualItems*items[c.ti].v;
                remD-=(double)maxS*c.thick;
                tmpUsed[c.ti]+=actualItems;
            }
            if (remD>0 && tmpUsed[c.ti]<items[c.ti].limit) {
                int remItems=items[c.ti].limit-tmpUsed[c.ti];
                double fracStrips=min(remD/c.thick, (double)remItems/c.per);
                ub+=(long long)(fracStrips*c.valPer);
                remD-=fracStrips*c.thick;
            }
            if (remD<=0) break;
        }
        if (ub<=bbBestV) return;
        
        int oi=order[idx];
        auto& c=configs[oi];
        int availItems=items[c.ti].limit-typeUsed[c.ti];
        int maxSbySpace=rem/c.thick;
        int maxSbyItems=(availItems>0)?(availItems+c.per-1)/c.per:0;
        int maxS=min(maxSbySpace, maxSbyItems);
        
        for (int s=maxS;s>=0;s--) {
            if (timedOut) return;
            int actualItems=min(s*c.per, availItems);
            long long addVal=(long long)actualItems*items[c.ti].v;
            curCounts[oi]=s;
            curVal+=addVal;
            curUsed+=s*c.thick;
            typeUsed[c.ti]+=actualItems;
            solve(idx+1);
            curVal-=addVal;
            curUsed-=s*c.thick;
            typeUsed[c.ti]-=actualItems;
            curCounts[oi]=0;
        }
    };
    
    solve(0);
    
    // Reconstruct
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl;
    long long val=0;
    vector<array<int,4>> gaps;
    
    for (int i=0;i<nC;i++) {
        int oi=order[i];
        auto& c=configs[oi];
        for (int s=0;s<bbBestCounts[oi];s++) {
            int placed=0;
            for (int j=0;j<c.per&&used[c.ti]<items[c.ti].limit;j++) {
                int x,y;
                if (horiz) {x=j*c.cross;y=pos;}
                else {x=pos;y=j*c.cross;}
                pl.push_back({items[c.ti].type,x,y,c.rot});
                val+=items[c.ti].v; used[c.ti]++; placed++;
            }
            int endCoord=placed*c.cross;
            int gapSize=crossDim-endCoord;
            if (gapSize>0) {
                if (horiz) gaps.push_back({endCoord,pos,gapSize,c.thick});
                else gaps.push_back({pos,endCoord,c.thick,gapSize});
            }
            pos+=c.thick;
        }
    }
    
    if (pos<mainDim) {
        if (horiz) gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    
    for (auto& g : gaps) {
        fillRegion(g[0],g[1],g[2],g[3],used,pl,val,0);
    }
    
    return {val,pl};
}

// JSON parsing helpers
int skipWS(const string& s, int p) {
    while(p<(int)s.size()&&(s[p]==' '||s[p]=='\n'||s[p]=='\r'||s[p]=='\t'))p++;
    return p;
}

struct JVal {
    int type; // 0=null,1=bool,2=int,3=str,4=arr,5=obj
    long long ival;
    bool bval;
    string sval;
    vector<JVal> arr;
    vector<pair<string,JVal>> obj;
    
    JVal():type(0),ival(0),bval(false){}
    
    const JVal& operator[](const string& key) const {
        for(auto&p:obj) if(p.first==key) return p.second;
        static JVal nil; return nil;
    }
    const JVal& operator[](int i) const { return arr[i]; }
    int asize() const { return (int)arr.size(); }
};

pair<string,int> parseStr(const string& s, int p) {
    p++; // skip "
    string r;
    while(p<(int)s.size()&&s[p]!='"') {
        if(s[p]=='\\'){p++;if(p<(int)s.size())r+=s[p];}
        else r+=s[p];
        p++;
    }
    p++; // skip closing "
    return {r,p};
}

pair<JVal,int> parseVal(const string& s, int p) {
    p=skipWS(s,p);
    JVal v;
    if(s[p]=='"') {
        auto[str,np]=parseStr(s,p);
        v.type=3; v.sval=str; return {v,np};
    }
    if(s[p]=='{') {
        v.type=5; p++;
        p=skipWS(s,p);
        if(p<(int)s.size()&&s[p]!='}') {
            while(true) {
                p=skipWS(s,p);
                auto[key,np1]=parseStr(s,p); p=np1;
                p=skipWS(s,p); p++; // skip :
                auto[val2,np2]=parseVal(s,p); p=np2;
                v.obj.push_back({key,val2});
                p=skipWS(s,p);
                if(p<(int)s.size()&&s[p]==',')p++; else break;
            }
        }
        p=skipWS(s,p); p++; // skip }
        return {v,p};
    }
    if(s[p]=='[') {
        v.type=4; p++;
        p=skipWS(s,p);
        if(p<(int)s.size()&&s[p]!=']') {
            while(true) {
                auto[val2,np]=parseVal(s,p); p=np;
                v.arr.push_back(val2);
                p=skipWS(s,p);
                if(p<(int)s.size()&&s[p]==',')p++; else break;
            }
        }
        p=skipWS(s,p); p++; // skip ]
        return {v,p};
    }
    if(s[p]=='t') { v.type=1; v.bval=true; p+=4; return {v,p}; }
    if(s[p]=='f') { v.type=1; v.bval=false; p+=5; return {v,p}; }
    if(s[p]=='n') { v.type=0; p+=4; return {v,p}; }
    // number
    v.type=2;
    bool neg=false;
    if(s[p]=='-'){neg=true;p++;}
    long long num=0;
    while(p<(int)s.size()&&s[p]>='0'&&s[p]<='9'){num=num*10+(s[p]-'0');p++;}
    // skip fractional/exponent if any
    if(p<(int)s.size()&&s[p]=='.'){p++;while(p<(int)s.size()&&s[p]>='0'&&s[p]<='9')p++;}
    if(p<(int)s.size()&&(s[p]=='e'||s[p]=='E')){p++;if(p<(int)s.size()&&(s[p]=='+'||s[p]=='-'))p++;while(p<(int)s.size()&&s[p]>='0'&&s[p]<='9')p++;}
    v.ival=neg?-num:num;
    return {v,p};
}

// Enhanced strip knapsack: try multiple strip thickness combos with DP
pair<long long,vector<Placement>> dpStripPack(bool horiz, chrono::steady_clock::time_point deadline) {
    int mainDim = horiz ? H : W;
    int crossDim = horiz ? W : H;
    
    // Each "strip config" = (type, rot, thick, items_per_strip, value_per_strip)
    struct SC { int ti, rot, thick, cross, per; long long valPer; };
    vector<SC> configs;
    
    for (int i=0;i<M;i++) {
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw=r?items[i].h:items[i].w;
            int ph=r?items[i].w:items[i].h;
            if (pw>W||ph>H) continue;
            int thick=horiz?ph:pw;
            int cross=horiz?pw:ph;
            int per=crossDim/cross;
            if (per<=0||thick<=0) continue;
            configs.push_back({i,r,thick,cross,per,(long long)per*items[i].v});
        }
    }
    
    if (configs.empty()) return {0,{}};
    
    // Group by (ti, rot) => already unique per config
    // This is a bounded knapsack: capacity = mainDim, each config has weight=thick, 
    // value=valPer, and bound = min(mainDim/thick, ceil(limit/per))
    // But items share type limits, making it coupled.
    
    // Since M is small (8-12), configs might be ~24, we use the B&B approach
    return stripKnapsack(horiz, deadline);
}

// Guillotine-style recursive packing
void guillotinePack(int rx, int ry, int rw, int rh, vector<int>& used, 
                     vector<Placement>& pl, long long& val, int depth) {
    if (rw<=0||rh<=0||depth>20) return;
    
    // Find best single item to place at bottom-left
    int bestTi=-1, bestR=0;
    double bestDens=-1;
    for (int i=0;i<M;i++) {
        if (used[i]>=items[i].limit) continue;
        for (int r=0;r<(allow_rot?2:1);r++) {
            int pw=r?items[i].h:items[i].w;
            int ph=r?items[i].w:items[i].h;
            if (pw>rw||ph>rh) continue;
            double d=(double)items[i].v/(pw*ph);
            if (d>bestDens) { bestDens=d; bestTi=i; bestR=r; }
        }
    }
    if (bestTi<0) return;
    
    int pw=bestR?items[bestTi].h:items[bestTi].w;
    int ph=bestR?items[bestTi].w:items[bestTi].h;
    
    // Fill as many as possible in a strip
    int numX=rw/pw;
    int numY=rh/ph;
    int avail=items[bestTi].limit-used[bestTi];
    
    // Try horizontal strip first
    int stripCount=min(numX, avail);
    if (stripCount>0) {
        for (int j=0;j<stripCount;j++) {
            pl.push_back({items[bestTi].type, rx+j*pw, ry, bestR});
            val+=items[bestTi].v; used[bestTi]++;
        }
        // Right remainder
        int rightX=rx+stripCount*pw;
        int rightW=rw-stripCount*pw;
        guillotinePack(rightX, ry, rightW, ph, used, pl, val, depth+1);
        // Top remainder
        guillot
