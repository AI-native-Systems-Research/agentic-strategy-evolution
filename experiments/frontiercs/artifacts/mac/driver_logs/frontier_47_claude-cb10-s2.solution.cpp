Looking at the previous attempt, it was clearly incomplete (cut off mid-code) and had a parse error. I need to write a complete, well-structured solution.

My approach:
1. Parse JSON input properly
2. Use MaxRects bin packing with multiple heuristics and item orderings
3. Use strip-based packing approaches
4. Try many combinations within the time budget and keep the best result

```cpp
#include <bits/stdc++.h>
using namespace std;

int W, H, M;
bool allow_rot;

struct Item { string type; int w, h; long long v; int limit; };
vector<Item> items;

struct Placement { string type; int x, y, rot; };
struct Rect { int x, y, w, h; };

// JSON parser
int skipWS(const string& s, int p) {
    while(p<(int)s.size()&&(s[p]==' '||s[p]=='\n'||s[p]=='\r'||s[p]=='\t'))p++;
    return p;
}

struct JVal {
    int tp=0; long long iv=0; bool bv=false; string sv;
    vector<JVal> arr;
    vector<pair<string,JVal>> obj;
    const JVal& operator[](const string& key) const {
        for(auto&p:obj) if(p.first==key) return p.second;
        static JVal nil; return nil;
    }
};

pair<string,int> parseStr(const string& s, int p) {
    p++; string r;
    while(p<(int)s.size()&&s[p]!='"') {
        if(s[p]=='\\'){p++;if(p<(int)s.size())r+=s[p];}
        else r+=s[p]; p++;
    }
    return {r,p+1};
}

pair<JVal,int> parseVal(const string& s, int p) {
    p=skipWS(s,p); JVal v;
    if(s[p]=='"'){auto[str,np]=parseStr(s,p);v.tp=3;v.sv=str;return{v,np};}
    if(s[p]=='{'){
        v.tp=5;p++;p=skipWS(s,p);
        if(p<(int)s.size()&&s[p]!='}'){
            while(true){
                p=skipWS(s,p);auto[key,np1]=parseStr(s,p);p=np1;
                p=skipWS(s,p);p++;
                auto[val2,np2]=parseVal(s,p);p=np2;
                v.obj.push_back({key,val2});
                p=skipWS(s,p);if(p<(int)s.size()&&s[p]==',')p++;else break;
            }
        }
        p=skipWS(s,p);p++;return{v,p};
    }
    if(s[p]=='['){
        v.tp=4;p++;p=skipWS(s,p);
        if(p<(int)s.size()&&s[p]!=']'){
            while(true){
                auto[val2,np]=parseVal(s,p);p=np;
                v.arr.push_back(val2);
                p=skipWS(s,p);if(p<(int)s.size()&&s[p]==',')p++;else break;
            }
        }
        p=skipWS(s,p);p++;return{v,p};
    }
    if(s[p]=='t'){v.tp=1;v.bv=true;return{v,p+4};}
    if(s[p]=='f'){v.tp=1;v.bv=false;return{v,p+5};}
    if(s[p]=='n'){v.tp=0;return{v,p+4};}
    v.tp=2;bool neg=false;
    if(s[p]=='-'){neg=true;p++;}
    long long num=0;
    while(p<(int)s.size()&&s[p]>='0'&&s[p]<='9'){num=num*10+(s[p]-'0');p++;}
    if(p<(int)s.size()&&s[p]=='.'){p++;while(p<(int)s.size()&&s[p]>='0'&&s[p]<='9')p++;}
    if(p<(int)s.size()&&(s[p]=='e'||s[p]=='E')){p++;if(p<(int)s.size()&&(s[p]=='+'||s[p]=='-'))p++;while(p<(int)s.size()&&s[p]>='0'&&s[p]<='9')p++;}
    v.iv=neg?-num:num;return{v,p};
}

struct MaxRects {
    vector<Rect> fr;
    int BW, BH;
    void init(int w, int h){BW=w;BH=h;fr.clear();fr.push_back({0,0,w,h});}
    
    void prune(){
        int n=fr.size();
        vector<bool> del(n,false);
        for(int i=0;i<n;i++){
            if(del[i])continue;
            for(int j=i+1;j<n;j++){
                if(del[j])continue;
                auto&a=fr[i];auto&b=fr[j];
                if(a.x<=b.x&&a.y<=b.y&&a.x+a.w>=b.x+b.w&&a.y+a.h>=b.y+b.h){del[j]=true;}
                else if(b.x<=a.x&&b.y<=a.y&&b.x+b.w>=a.x+a.w&&b.y+b.h>=a.y+a.h){del[i]=true;break;}
            }
        }
        vector<Rect> nf;
        for(int i=0;i<n;i++)if(!del[i])nf.push_back(fr[i]);
        fr=nf;
        if((int)fr.size()>2000){
            sort(fr.begin(),fr.end(),[](auto&a,auto&b){return(long long)a.w*a.h>(long long)b.w*b.h;});
            fr.resize(2000);
        }
    }
    
    void insert(int px,int py,int pw,int ph){
        int rx2=px+pw,ry2=py+ph;
        vector<Rect> nf;
        for(auto&r:fr){
            int rr=r.x+r.w,rt=r.y+r.h;
            if(px>=rr||rx2<=r.x||py>=rt||ry2<=r.y){nf.push_back(r);continue;}
            if(px>r.x)nf.push_back({r.x,r.y,px-r.x,r.h});
            if(rx2<rr)nf.push_back({rx2,r.y,rr-rx2,r.h});
            if(py>r.y)nf.push_back({r.x,r.y,r.w,py-r.y});
            if(ry2<rt)nf.push_back({r.x,ry2,r.w,rt-ry2});
        }
        fr=nf;prune();
    }
    
    // heur: 0=BSSF, 1=BL, 2=BAF, 3=BLSF, 4=BL-x-first, 5=contact
    bool findPos(int pw,int ph,int&bx,int&by,int heur){
        bx=by=-1;long long bs1=LLONG_MAX,bs2=LLONG_MAX;
        for(auto&r:fr){
            if(pw>r.w||ph>r.h)continue;
            long long s1,s2;
            int sf1=r.w-pw,sf2=r.h-ph;
            switch(heur){
                case 0:s1=min(sf1,sf2);s2=max(sf1,sf2);break;
                case 1:s1=r.y;s2=r.x;break;
                case 2:s1=(long long)r.w*r.h-(long long)pw*ph;s2=min(sf1,sf2);break;
                case 3:s1=max(sf1,sf2);s2=min(sf1,sf2);break;
                case 4:s1=r.x;s2=r.y;break;
                case 5:s1=r.x+r.y;s2=min(sf1,sf2);break;
                default:s1=min(sf1,sf2);s2=max(sf1,sf2);break;
            }
            if(s1<bs1||(s1==bs1&&s2<bs2)){bs1=s1;bs2=s2;bx=r.x;by=r.y;}
        }
        return bx>=0;
    }
};

struct Cand { int ti, rot, pw, ph; double density; };

long long bestVal=0;
vector<Placement> bestPl;

void updateBest(long long v, const vector<Placement>& pl){
    if(v>bestVal){bestVal=v;bestPl=pl;}
}

// Sequential packing: go through candidates in order, pack each greedily
pair<long long,vector<Placement>> packSeq(const vector<Cand>& order, int heur){
    MaxRects mr; mr.init(W,H);
    vector<int> used(M,0);
    vector<Placement> pl; long long val=0;
    for(auto&c:order){
        while(used[c.ti]<items[c.ti].limit){
            int bx,by;
            if(!mr.findPos(c.pw,c.ph,bx,by,heur))break;
            mr.insert(bx,by,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bx,by,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
    }
    return{val,pl};
}

// Greedy best-fit: at each step pick item with best score
pair<long long,vector<Placement>> greedyBest(const vector<Cand>& allCands, int heur, int scoreMode){
    MaxRects mr; mr.init(W,H);
    vector<int> used(M,0);
    vector<Placement> pl; long long val=0;
    while(true){
        int bestCI=-1; int bbx=0,bby=0; double bestScore=-1e30;
        for(int ci=0;ci<(int)allCands.size();ci++){
            auto&c=allCands[ci];
            if(used[c.ti]>=items[c.ti].limit)continue;
            int fx,fy;
            if(!mr.findPos(c.pw,c.ph,fx,fy,heur))continue;
            double score;
            switch(scoreMode){
                case 0:score=c.density;break;
                case 1:score=(double)items[c.ti].v;break;
                case 2:score=c.density*1e6-(double)(fx+fy);break;
                case 3:score=(double)items[c.ti].v/max(c.pw,c.ph);break;
                default:score=c.density;
            }
            if(score>bestScore){bestScore=score;bestCI=ci;bbx=fx;bby=fy;}
        }
        if(bestCI<0)break;
        auto&c=allCands[bestCI];
        mr.insert(bbx,bby,c.pw,c.ph);
        pl.push_back({items[c.ti].type,bbx,bby,c.rot});
        val+=items[c.ti].v; used[c.ti]++;
    }
    return{val,pl};
}

// Fill a sub-region with MaxRects
void fillRegion(int rx,int ry,int rw,int rh,vector<int>&used,vector<Placement>&pl,long long&val,
                const vector<Cand>& allCands, int heur, int sortMode){
    if(rw<=0||rh<=0)return;
    MaxRects mr; mr.init(rw,rh);
    auto cands=allCands;
    switch(sortMode){
        case 0:sort(cands.begin(),cands.end(),[](auto&a,auto&b){return a.density>b.density;});break;
        case 1:sort(cands.begin(),cands.end(),[](auto&a,auto&b){return items[a.ti].v>items[b.ti].v;});break;
        case 2:sort(cands.begin(),cands.end(),[](auto&a,auto&b){return a.pw*a.ph>b.pw*b.ph;});break;
        default:sort(cands.begin(),cands.end(),[](auto&a,auto&b){return a.density>b.density;});break;
    }
    for(auto&c:cands){
        while(used[c.ti]<items[c.ti].limit){
            int bx,by;
            if(!mr.findPos(c.pw,c.ph,bx,by,heur))break;
            mr.insert(bx,by,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bx+rx,by+ry,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
    }
}

// Mixed strip: greedily pick best strip at each row
pair<long long,vector<Placement>> mixedStrip(bool horiz, int mode, const vector<Cand>& allCands){
    int mainDim=horiz?H:W;
    int crossDim=horiz?W:H;
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl; long long val=0;
    vector<array<int,4>> gaps;
    
    while(pos<mainDim){
        int bestTi=-1,bestR=0,bestThick=0,bestCross=0,bestPer=0;
        double bestScore=-1;
        for(int i=0;i<M;i++){
            if(used[i]>=items[i].limit)continue;
            for(int r=0;r<(allow_rot?2:1);r++){
                int pw=r?items[i].h:items[i].w;
                int ph=r?items[i].w:items[i].h;
                if(pw>W||ph>H)continue;
                int thick=horiz?ph:pw;
                int cross=horiz?pw:ph;
                if(pos+thick>mainDim||cross>crossDim||thick<=0||cross<=0)continue;
                int per=crossDim/cross;
                int avail=items[i].limit-used[i];
                per=min(per,avail);
                if(per<=0)continue;
                double score;
                switch(mode){
                    case 0:score=(double)per*items[i].v/thick;break;
                    case 1:score=(double)items[i].v/((double)thick*cross);break;
                    case 2:score=(double)per*items[i].v;break;
                    case 3:score=(double)per*items[i].v/(thick*crossDim);break;
                    default:score=(double)per*items[i].v/thick;
                }
                if(score>bestScore){bestScore=score;bestTi=i;bestR=r;bestThick=thick;bestCross=cross;bestPer=per;}
            }
        }
        if(bestTi<0)break;
        for(int j=0;j<bestPer;j++){
            int x,y;
            if(horiz){x=j*bestCross;y=pos;}else{x=pos;y=j*bestCross;}
            pl.push_back({items[bestTi].type,x,y,bestR});
            val+=items[bestTi].v; used[bestTi]++;
        }
        int ec=bestPer*bestCross;
        int gs=crossDim-ec;
        if(gs>0){
            if(horiz)gaps.push_back({ec,pos,gs,bestThick});
            else gaps.push_back({pos,ec,bestThick,gs});
        }
        pos+=bestThick;
    }
    if(pos<mainDim){
        if(horiz)gaps.push_back({0,pos,crossDim,mainDim-pos});
        else gaps.push_back({pos,0,mainDim-pos,crossDim});
    }
    for(auto&g:gaps) fillRegion(g[0],g[1],g[2],g[3],used,pl,val,allCands,0,0);
    return{val,pl};
}

// Strip with 1D knapsack per strip thickness
// For a given thickness, solve bounded knapsack on cross dimension
struct StripConfig {
    int ti, rot, thick, cross;
};

void solve1DKnapsack(int capacity, const vector<pair<int,int>>& itemsCrossVal, const vector<int>& itemsLimAvail,
                     vector<int>& bestCounts){
    // bounded knapsack with small number of items
    int n = itemsCrossVal.size();
    bestCounts.assign(n, 0);
    
    // DP approach - but capacity can be up to 2000, items up to ~24
    // Use standard bounded knapsack DP
    vector<long long> dp(capacity+1, 0);
    vector<vector<int>> from(capacity+1, vector<int>(n, 0));
    
    // For each item, binary splitting
    for(int i=0;i<n;i++){
        int cross = itemsCrossVal[i].first;
        long long v = itemsCrossVal[i].second;
        int lim = itemsLimAvail[i];
        if(cross<=0||lim<=0||v<=0)continue;
        
        // Binary decomposition
        vector<pair<int,long long>> packs; // (weight, value) for each "group"
        int rem = lim;
        int k = 1;
        while(rem > 0){
            int take = min(k, rem);
            packs.push_back({take*cross, take*v});
            rem -= take;
            k *= 2;
        }
        // 0-1 knapsack on these groups (standard trick)
        // But we need to track counts... this is complex.
        // Simpler: just greedy for speed
    }
    
    // Simpler: greedy by value density
    vector<int> order(n);
    iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){
        return (double)itemsCrossVal[a].second/itemsCrossVal[a].first > 
               (double)itemsCrossVal[b].second/itemsCrossVal[b].first;
    });
    int rem = capacity;
    for(int idx : order){
        int cross = itemsCrossVal[idx].first;
        long long v = itemsCrossVal[idx].second;
        int lim = itemsLimAvail[idx];
        if(cross<=0)continue;
        int take = min(lim, rem/cross);
        bestCounts[idx] = take;
        rem -= take * cross;
    }
}

// Strip B&B with mixed rows
pair<long long,vector<Placement>> stripBnB(bool horiz, const vector<Cand>& allCands, 
                                            chrono::steady_clock::time_point deadline){
    int mainDim=horiz?H:W;
    int crossDim=horiz?W:H;
    
    // Collect unique thicknesses
    set<int> thickSet;
    vector<StripConfig> configs;
    for(int i=0;i<M;i++){
        for(int r=0;r<(allow_rot?2:1);r++){
            int pw=r?items[i].h:items[i].w;
            int ph=r?items[i].w:items[i].h;
            if(pw>W||ph>H)continue;
            int thick=horiz?ph:pw;
            int cross=horiz?pw:ph;
            if(thick<=0||cross<=0||cross>crossDim||thick>mainDim)continue;
            configs.push_back({i,r,thick,cross});
            thickSet.insert(thick);
        }
    }
    
    // For each thickness, compute the value of filling a row
    struct RowOption {
        int thick;
        long long val;
        vector<pair<int,int>> placements; // (config_idx, count)
    };
    
    vector<int> thicks(thickSet.begin(), thickSet.end());
    sort(thicks.begin(), thicks.end());
    
    // For each thickness, greedily fill a row
    // We do greedy per-row, then do a 1D knapsack over rows
    // But limits are shared across rows... complex.
    // Simplified: just use the mixedStrip approach which is already good.
    
    // Instead, let's do a B&B over which item type to use for each strip level
    // Keep it simple: iterate strip configs sorted by row-density, 
    // try to place as many rows as possible of each
    
    struct SC {
        int ti, rot, thick, cross, per;
        long long valPer;
        double dens;
    };
    vector<SC> scs;
    for(auto& c : configs){
        int per = crossDim / c.cross;
        if(per <= 0) continue;
        scs.push_back({c.ti, c.rot, c.thick, c.cross, per, 
                       (long long)per * items[c.ti].v,
                       (double)per * items[c.ti].v / c.thick});
    }
    
    int nC = scs.size();
    if(nC == 0) return {0, {}};
    
    vector<int> order(nC);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int a, int b){ return scs[a].dens > scs[b].dens; });
    
    long long bbBestV = 0;
    vector<int> bbBestCounts(nC, 0);
    vector<int> curCounts(nC, 0);
    vector<int> typeUsed(M, 0);
    long long curVal = 0;
    int curUsedSpace = 0;
    int nodeCount = 0;
    bool timedOut = false;
    
    function<void(int)> solve = [&](int idx){
        if(timedOut) return;
        nodeCount++;
        if(nodeCount % 3000 == 0){
            if(chrono::steady_clock::now() > deadline){timedOut = true; return;}
        }
        if(curVal > bbBestV){
            bbBestV = curVal;
            bbBestCounts = curCounts;
        }
        if(idx >= nC) return;
        int rem = mainDim - curUsedSpace;
        if(rem <= 0) return;
        
        // Upper bound: fractional fill of remaining space
        long long ub = curVal;
        double remD = rem;
        vector<int> tmpU = typeUsed;
        for(int i = idx; i < nC; i++){
            int oi = order[i];
            auto& c = scs[oi];
            int av = items[c.ti].limit - tmpU[c.ti];
            if(av <= 0) continue;
            int maxRows = (int)(remD / c.thick);
            if(maxRows <= 0){
                // fractional
                double frac = remD / c.thick;
                int fracItems = min((int)(frac * c.per), av);
                ub += (long long)fracItems * items[c.ti].v;
                // don't subtract remD since this is fractional
                continue;
            }
            int totalCanPlace = maxRows * c.per;
            int actual = min(totalCanPlace, av);
            int fullRows = actual / c.per;
            int leftover = actual % c.per;
            ub += (long long)actual * items[c.ti].v;
            remD -= (double)fullRows * c.thick;
            if(leftover > 0 && remD >= c.thick){
                remD -= c.thick;
            }
            tmpU[c.ti] += actual;
            if(remD <= 0) break;
        }
        if(ub <= bbBestV) return;
        
        int oi = order[idx];
        auto& c = scs[oi];
        int av = items[c.ti].limit - typeUsed[c.ti];
        int maxRows = min(rem / c.thick, av > 0 ? (av + c.per - 1) / c.per : 0);
        maxRows = min(maxRows, 200); // limit branching
        
        for(int s = maxRows; s >= 0; s--){
            if(timedOut) return;
            int act = min(s * c.per, av);
            long long addV = (long long)act * items[c.ti].v;
            curCounts[oi] = s;
            curVal += addV;
            curUsedSpace += s * c.thick;
            typeUsed[c.ti] += act;
            solve(idx + 1);
            curVal -= addV;
            curUsedSpace -= s * c.thick;
            typeUsed[c.ti] -= act;
            curCounts[oi] = 0;
        }
    };
    
    solve(0);
    
    // Reconstruct
    vector<int> used(M, 0);
    int pos = 0;
    vector<Placement> pl;
    long long val = 0;
    vector<array<int,4>> gaps;
    
    for(int i = 0; i < nC; i++){
        int oi = order[i];
        auto& c = scs[oi];
        for(int s = 0; s < bbBestCounts[oi]; s++){
            int placed = 0;
            for(int j = 0; j < c.per && used[c.ti] < items[c.ti].limit; j++){
                int x, y;
                if(horiz){x = j * c.cross; y = pos;} else {x = pos; y = j * c.cross;}
                pl.push_back({items[c.ti].type, x, y, c.rot});
                val += items[c.ti].v;
                used[c.ti]++;
                placed++;
            }
            int ec = placed * c.cross;
            int gs = crossDim - ec;
            if(gs > 0){
                if(horiz) gaps.push_back({ec, pos, gs, c.thick});
                else gaps.push_back({pos, ec, c.thick, gs});
            }
            pos += c.thick;
        }
    }
    if(pos < mainDim){
        if(horiz) gaps.push_back({0, pos, crossDim, mainDim - pos});
        else gaps.push_back({pos, 0, mainDim - pos, crossDim});
    }
    for(auto& g : gaps){
        fillRegion(g[0], g[1], g[2], g[3], used, pl, val, allCands, 0, 0);
    }
    return {val, pl};
}

// Mixed strip with gap filling using different heuristics for gaps
pair<long long,vector<Placement>> mixedStripEnhanced(bool horiz, int mode, const vector<Cand>& allCands,
                                                      int gapHeur, int gapSort){
    int mainDim=horiz?H:W;
    int crossDim=horiz?W:H;
    vector<int> used(M,0);
    int pos=0;
    vector<Placement> pl; long long val=0;
    vector<array<int,4>> gaps;
    
    while(pos<mainDim){
        int bestTi=-1,bestR=0,bestThick=0,bestCross=0,bestPer=0;
        double bestScore=-1;
        for(int i=0;i<M;i++){
            if(used[i]>=items[i].limit)continue;
            for(int r=0;r<(allow_rot?2:1);r++){
                int pw=r?items[i].h:items[i].w;
                int ph=r?items[i].w:items[i].h;
                if(pw>W||ph>H)continue;
                int thick=horiz?ph:pw;
                int cross=horiz?pw:ph;
                if(pos+thick>mainDim||cross>crossDim||thick<=0||cross<=0)continue;
                int per=crossDim/cross;
                int avail=items[i].limit-used[i];
                per=min(per,avail);
                if(per<=0)continue;
                double score;
                double utilization = (double)(per*cross)/crossDim;
                switch(mode){
                    case 0:score=(double)per*items[i].v/thick;break;
                    case 1:score=(double)items[i].v/((double)thick*cross);break;
                    case 2:score=(double)per*items[i].v;break;
                    case 3:score=(double)per*items[i].v*utilization/thick;break;
                    case 4:score=(double)items[i].v/((double)thick*cross)*utilization;break;
                    case 5:score=(double)per*items[i].v/(thick*thick);break;
                    default:score=(double)per*items[i].v/thick;
                }
                if(score>bestScore){bestScore=score;bestTi=i;bestR=r;bestThick=thick;bestCross=cross;bestPer=per;}
            }
        }
        if(bestTi<0)break;
        for(int j=0;j<bestPer;j++){
            int x,y;
            if(horiz){x=j*bestCross;y=pos;}else{x=pos;y=j*bestCross;}
            pl.push_back({items[bestTi].type,x
