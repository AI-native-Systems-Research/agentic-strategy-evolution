#include <bits/stdc++.h>
using namespace std;

struct JsonVal {
    int type=0; long long ival=0; string sval;
    vector<JsonVal> arr; vector<pair<string,JsonVal>> obj;
    const JsonVal& operator[](const string& k) const {
        for(auto&p:obj) if(p.first==k) return p.second;
        static JsonVal nul; return nul;
    }
    const JsonVal& operator[](int i) const { return arr[i]; }
    int size() const { return type==4?(int)arr.size():(int)obj.size(); }
};
const char* skipws(const char* p){ while(*p==' '||*p=='\n'||*p=='\r'||*p=='\t') p++; return p; }
const char* parseString(const char* p, string& s){
    p++; s.clear();
    while(*p!='"'){ if(*p=='\\'){p++;s+=*p;p++;} else{s+=*p;p++;} }
    return p+1;
}
const char* parseVal(const char* p, JsonVal& v){
    p=skipws(p);
    if(*p=='"'){ v.type=3; p=parseString(p,v.sval); }
    else if(*p=='{'){
        v.type=5; p=skipws(p+1);
        if(*p!='}'){
            while(true){
                p=skipws(p); string key; p=parseString(p,key);
                p=skipws(p); p++; JsonVal child; p=parseVal(p,child);
                v.obj.push_back({key,child}); p=skipws(p);
                if(*p==',') p++; else break;
            }
        }
        p=skipws(p); p++;
    } else if(*p=='['){
        v.type=4; p=skipws(p+1);
        if(*p!=']'){
            while(true){
                JsonVal child; p=parseVal(p,child);
                v.arr.push_back(child); p=skipws(p);
                if(*p==',') p++; else break;
            }
        }
        p=skipws(p); p++;
    } else if(*p=='t'){ v.type=1; v.ival=1; p+=4; }
    else if(*p=='f'){ v.type=1; v.ival=0; p+=5; }
    else if(*p=='n'){ v.type=0; p+=4; }
    else {
        v.type=2; bool neg=false; if(*p=='-'){neg=true;p++;}
        long long n=0; while(*p>='0'&&*p<='9'){n=n*10+(*p-'0');p++;}
        if(*p=='.'){p++;while(*p>='0'&&*p<='9') p++;}
        v.ival=neg?-n:n;
    }
    return p;
}

struct ItemType { string type; int w,h,limit; long long v; double density; };
struct Placement { string type; int x,y,rot; int idx; }; // idx = item type index

struct Rect { int x,y,w,h; };

struct MaxRectsBin {
    int W,H;
    vector<Rect> free_rects;
    void init(int w,int h){ W=w; H=h; free_rects.clear(); free_rects.push_back({0,0,w,h}); }

    tuple<int,int,int,int> scoreRect(int rw, int rh, int method) const {
        int bestS1=INT_MAX, bestS2=INT_MAX, bx=0, by=0;
        for(auto&f:free_rects){
            if(rw<=f.w && rh<=f.h){
                int s1,s2;
                switch(method){
                    case 0: s1=min(f.w-rw,f.h-rh); s2=max(f.w-rw,f.h-rh); break;
                    case 1: s1=max(f.w-rw,f.h-rh); s2=min(f.w-rw,f.h-rh); break;
                    case 2: s1=f.w*f.h-rw*rh; s2=min(f.w-rw,f.h-rh); break;
                    case 3: s1=f.y; s2=f.x; break;
                    default: s1=f.y+rh; s2=f.x; break;
                }
                if(s1<bestS1||(s1==bestS1&&s2<bestS2)){
                    bestS1=s1; bestS2=s2; bx=f.x; by=f.y;
                }
            }
        }
        return {bestS1,bestS2,bx,by};
    }

    void doPlace(int px, int py, int rw, int rh){
        Rect placed={px,py,rw,rh};
        vector<Rect> nf;
        nf.reserve(free_rects.size()+4);
        for(auto&f:free_rects){
            if(placed.x>=f.x+f.w||placed.x+placed.w<=f.x||
               placed.y>=f.y+f.h||placed.y+placed.h<=f.y){
                nf.push_back(f); continue;
            }
            if(placed.x>f.x) nf.push_back({f.x,f.y,placed.x-f.x,f.h});
            if(placed.x+placed.w<f.x+f.w) nf.push_back({placed.x+placed.w,f.y,f.x+f.w-placed.x-placed.w,f.h});
            if(placed.y>f.y) nf.push_back({f.x,f.y,f.w,placed.y-f.y});
            if(placed.y+placed.h<f.y+f.h) nf.push_back({f.x,placed.y+placed.h,f.w,f.y+f.h-placed.y-placed.h});
        }
        // Remove contained rects
        int sz=(int)nf.size();
        vector<bool> del(sz,false);
        for(int i=0;i<sz;i++){
            if(del[i]) continue;
            for(int j=0;j<sz;j++){
                if(i==j||del[j]) continue;
                if(nf[i].x>=nf[j].x&&nf[i].y>=nf[j].y&&
                   nf[i].x+nf[i].w<=nf[j].x+nf[j].w&&
                   nf[i].y+nf[i].h<=nf[j].y+nf[j].h){
                    del[i]=true; break;
                }
            }
        }
        free_rects.clear();
        for(int i=0;i<sz;i++) if(!del[i]) free_rects.push_back(nf[i]);
    }

    bool placeBest(int iw, int ih, bool allowRot, int method, int&px, int&py, int&rot){
        auto [s1a,s2a,xa,ya] = scoreRect(iw,ih,method);
        int s1b=INT_MAX,s2b=INT_MAX,xb=0,yb=0;
        if(allowRot && iw!=ih){
            auto [ts1,ts2,tx,ty] = scoreRect(ih,iw,method);
            s1b=ts1; s2b=ts2; xb=tx; yb=ty;
        }
        if(s1a==INT_MAX && s1b==INT_MAX) return false;
        if(s1b<s1a||(s1b==s1a&&s2b<s2a)){
            px=xb; py=yb; rot=1;
            doPlace(px,py,ih,iw);
        } else {
            px=xa; py=ya; rot=0;
            doPlace(px,py,iw,ih);
        }
        return true;
    }
};

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    string input;
    { ostringstream oss; oss<<cin.rdbuf(); input=oss.str(); }
    JsonVal root;
    parseVal(input.c_str(),root);

    int W=(int)root["bin"]["W"].ival;
    int H=(int)root["bin"]["H"].ival;
    bool allowRot=(root["bin"]["allow_rotate"].ival!=0);

    int M=root["items"].size();
    vector<ItemType> items(M);
    for(int i=0;i<M;i++){
        auto&it=root["items"][i];
        items[i].type=it["type"].sval;
        items[i].w=(int)it["w"].ival;
        items[i].h=(int)it["h"].ival;
        items[i].v=it["v"].ival;
        items[i].limit=(int)it["limit"].ival;
        items[i].density=(double)items[i].v/((double)items[i].w*items[i].h);
    }

    auto startTime=chrono::steady_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };

    long long bestProfit=0;
    vector<Placement> bestPlacements;

    auto updateBest=[&](long long profit, vector<Placement>& pl){
        if(profit>bestProfit){bestProfit=profit;bestPlacements=pl;}
    };

    // Build a solution from a given ordering of (itemIdx, rot) candidates
    // using MaxRects with given method
    auto buildFromOrder=[&](const vector<pair<int,int>>& candidates, int method) -> pair<long long,vector<Placement>> {
        MaxRectsBin bin; bin.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long profit=0;
        for(auto& [idx, forceRot] : candidates){
            if(used[idx]>=items[idx].limit) continue;
            int iw=items[idx].w, ih=items[idx].h;
            if(forceRot){ swap(iw,ih); }
            if(iw>W||ih>H) continue;
            auto [s1,s2,px,py] = bin.scoreRect(iw,ih,method);
            if(s1==INT_MAX) continue;
            bin.doPlace(px,py,iw,ih);
            pl.push_back({items[idx].type,px,py,forceRot,idx});
            profit+=items[idx].v;
            used[idx]++;
        }
        return {profit,pl};
    };

    // Sequential: place items type by type in given order
    auto trySeq=[&](vector<int>& ord, int method) -> pair<long long,vector<Placement>> {
        MaxRectsBin bin; bin.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long profit=0;
        for(int idx:ord){
            while(used[idx]<items[idx].limit){
                int px,py,rot;
                if(bin.placeBest(items[idx].w,items[idx].h,allowRot,method,px,py,rot)){
                    pl.push_back({items[idx].type,px,py,rot,idx});
                    profit+=items[idx].v;
                    used[idx]++;
                } else break;
            }
        }
        return {profit,pl};
    };

    // Interleaved: at each step pick best scoring available item
    auto tryInterleaved=[&](int method, int scoreType) -> pair<long long,vector<Placement>> {
        MaxRectsBin bin; bin.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long profit=0;
        while(true){
            double bestScore=-1e18;
            int bestIdx=-1,bestRot=0,bestPx=0,bestPy=0;
            for(int i=0;i<M;i++){
                if(used[i]>=items[i].limit) continue;
                auto tryO=[&](int ow,int oh,int r){
                    if(ow>W||oh>H) return;
                    auto [s1,s2,px,py]=bin.scoreRect(ow,oh,method);
                    if(s1==INT_MAX) return;
                    double sc;
                    switch(scoreType){
                        case 0: sc=items[i].density; break;
                        case 1: sc=(double)items[i].v; break;
                        case 2: sc=items[i].density*1e6-(double)s1; break;
                        case 3: sc=(double)items[i].v/(double)(ow*oh)*1e6-(double)s1; break;
                        case 4: sc=items[i].density*1e3-(double)py*0.01; break;
                        case 5: sc=(double)items[i].v*1e3-((double)ow*oh); break;
                        case 6: sc=items[i].density*1e6-(double)(ow*oh); break;
                        default: sc=items[i].density*1e6-(double)s1*items[i].density; break;
                    }
                    if(sc>bestScore){bestScore=sc;bestIdx=i;bestRot=r;bestPx=px;bestPy=py;}
                };
                tryO(items[i].w,items[i].h,0);
                if(allowRot&&items[i].w!=items[i].h) tryO(items[i].h,items[i].w,1);
            }
            if(bestIdx==-1) break;
            int ow=bestRot?items[bestIdx].h:items[bestIdx].w;
            int oh=bestRot?items[bestIdx].w:items[bestIdx].h;
            bin.doPlace(bestPx,bestPy,ow,oh);
            pl.push_back({items[bestIdx].type,bestPx,bestPy,bestRot,bestIdx});
            profit+=items[bestIdx].v;
            used[bestIdx]++;
        }
        return {profit,pl};
    };

    auto makeOrd=[&](function<bool(int,int)> cmp)->vector<int>{
        vector<int> o(M); iota(o.begin(),o.end(),0);
        sort(o.begin(),o.end(),cmp); return o;
    };

    vector<vector<int>> orders;
    orders.push_back(makeOrd([&](int a,int b){return items[a].density>items[b].density;}));
    orders.push_back(makeOrd([&](int a,int b){return items[a].v>items[b].v;}));
    orders.push_back(makeOrd([&](int a,int b){return items[a].w*items[a].h>items[b].w*items[b].h;}));
    orders.push_back(makeOrd([&](int a,int b){return max(items[a].w,items[a].h)>max(items[b].w,items[b].h);}));
    orders.push_back(makeOrd([&](int a,int b){return items[a].density*items[a].v>items[b].density*items[b].v;}));
    orders.push_back(makeOrd([&](int a,int b){return items[a].v*(long long)items[a].limit>items[b].v*(long long)items[b].limit;}));
    orders.push_back(makeOrd([&](int a,int b){return items[a].density*items[a].limit>items[b].density*items[b].limit;}));
    orders.push_back(makeOrd([&](int a,int b){return min(items[a].w,items[a].h)<min(items[b].w,items[b].h);}));

    // Phase 1: Sequential orderings
    for(auto&ord:orders)
        for(int m=0;m<5;m++){
            if(elapsed()>0.15) goto dseq;
            auto [p,pl]=trySeq(ord,m);
            updateBest(p,pl);
        }
    dseq:

    // Phase 2: Interleaved
    for(int m=0;m<5&&elapsed()<0.25;m++)
        for(int st=0;st<8&&elapsed()<0.25;st++){
            auto [p,pl]=tryInterleaved(m,st);
            updateBest(p,pl);
        }

    // Phase 3: Random restarts with sequential
    mt19937 rng(42);
    while(elapsed()<0.45){
        vector<int> ord(M); iota(ord.begin(),ord.end(),0);
        sort(ord.begin(),ord.end(),[&](int a,int b){return items[a].density>items[b].density;});
        // Partial shuffle
        for(int i=0;i<M-1;i++){
            if(rng()%3==0){ int j=i+rng()%(M-i); swap(ord[i],ord[j]); }
        }
        int m=rng()%5;
        auto [p,pl]=trySeq(ord,m);
        updateBest(p,pl);
    }

    // Phase 4: Rebuild-based local search
    // Take the best solution, rebuild it in different orders to try to improve
    // Strategy: sort placed items by various criteria, rebuild with MaxRects
    while(elapsed()<0.90){
        if(bestPlacements.empty()) break;
        
        // Create candidate list from current best placements
        vector<pair<int,int>> candidates; // (itemIdx, rot)
        vector<int> used(M,0);
        for(auto&p:bestPlacements){
            candidates.push_back({p.idx, p.rot});
            used[p.idx]++;
        }
        
        // Add more items that weren't placed (up to limit)
        // Sort unplaced by density
        vector<int> unplaced_types;
        for(int i=0;i<M;i++){
            if(used[i]<items[i].limit) unplaced_types.push_back(i);
        }
        sort(unplaced_types.begin(),unplaced_types.end(),[&](int a,int b){
            return items[a].density>items[b].density;
        });
        for(int idx:unplaced_types){
            int remaining=items[idx].limit-used[idx];
            for(int k=0;k<remaining;k++){
                int r=0;
                if(allowRot && items[idx].w!=items[idx].h){
                    // pick orientation that fits better (taller vs wider)
                    r=(rng()%2);
                }
                candidates.push_back({idx,r});
            }
        }
        
        // Shuffle with bias: keep high-value items early
        // Use a weighted shuffle
        int n=candidates.size();
        if(n==0) break;
        
        // Try different shuffle strategies
        int strategy = rng()%5;
        
        if(strategy==0){
            // Sort by density descending, then slight shuffle
            sort(candidates.begin(),candidates.end(),[&](auto&a,auto&b){
                return items[a.first].density>items[b.first].density;
            });
            for(int i=0;i<(int)candidates.size()-1;i++){
                if(rng()%4==0){
                    int j=i+1+rng()%min((int)candidates.size()-i-1,5);
                    if(j<(int)candidates.size()) swap(candidates[i],candidates[j]);
                }
            }
        } else if(strategy==1){
            // Sort by value descending
            sort(candidates.begin(),candidates.end(),[&](auto&a,auto&b){
                return items[a.first].v>items[b.first].v;
            });
            for(int i=0;i<(int)candidates.size()-1;i++){
                if(rng()%4==0){
                    int j=i+1+rng()%min((int)candidates.size()-i-1,5);
                    if(j<(int)candidates.size()) swap(candidates[i],candidates[j]);
                }
            }
        } else if(strategy==2){
            // Sort by area descending (large first)
            sort(candidates.begin(),candidates.end(),[&](auto&a,auto&b){
                return items[a.first].w*items[a.first].h>items[b.first].w*items[b.first].h;
            });
            for(int i=0;i<(int)candidates.size()-1;i++){
                if(rng()%3==0){
                    int j=i+1+rng()%min((int)candidates.size()-i-1,8);
                    if(j<(int)candidates.size()) swap(candidates[i],candidates[j]);
                }
            }
        } else if(strategy==3){
            // Sort by max dimension descending
            sort(candidates.begin(),candidates.end(),[&](auto&a,auto&b){
                return max(items[a.first].w,items[a.first].h)>max(items[b.first].w,items[b.first].h);
            });
            for(int i=0;i<(int)candidates.size()-1;i++){
                if(rng()%3==0){
                    int j=i+1+rng()%min((int)candidates.size()-i-1,5);
                    if(j<(int)candidates.size()) swap(candidates[i],candidates[j]);
                }
            }
        } else {
            // Full random shuffle
            shuffle(candidates.begin(),candidates.end(),rng);
        }
        
        // Flip some rotations randomly
        if(allowRot){
            for(auto&c:candidates){
                if(rng()%5==0 && items[c.first].w!=items[c.first].h){
                    c.second=1-c.second;
                }
            }
        }
        
        int method=rng()%5;
        auto [p,pl]=buildFromOrder(candidates,method);
        updateBest(p,pl);
    }

    cout<<"{\"placements\":[";
    for(int i=0;i<(int)bestPlacements.size();i++){
        if(i) cout<<",";
        auto&p=bestPlacements[i];
        cout<<"{\"type\":\""<<p.type<<"\",\"x\":"<<p.x<<",\"y\":"<<p.y<<",\"rot\":"<<p.rot<<"}";
    }
    cout<<"]}"<<endl;
}
