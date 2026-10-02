#include <bits/stdc++.h>
using namespace std;

struct Item { string type; int w,h; long long v; int limit; };
struct Placement { string type; int x,y,rot; };
struct Rect { int x,y,w,h; };

struct MaxRectsPacker {
    int W,H;
    vector<Rect> freeRects;
    
    void init(int w, int h) {
        W=w; H=h;
        freeRects.clear();
        freeRects.push_back({0,0,w,h});
    }
    
    // Returns index of best free rect, -1 if none
    int findBSSF(int w, int h, int &bestX, int &bestY) {
        int bestSS=INT_MAX, bestLS=INT_MAX, bestIdx=-1;
        for(int i=0;i<(int)freeRects.size();i++) {
            auto &r=freeRects[i];
            if(w<=r.w && h<=r.h) {
                int ss=min(abs(r.h-h),abs(r.w-w));
                int ls=max(abs(r.h-h),abs(r.w-w));
                if(ss<bestSS||(ss==bestSS&&ls<bestLS)) {
                    bestSS=ss; bestLS=ls; bestX=r.x; bestY=r.y; bestIdx=i;
                }
            }
        }
        return bestIdx;
    }
    
    int findBLBF(int w, int h, int &bestX, int &bestY) {
        int bestBL=INT_MAX, bestSS=INT_MAX, bestIdx=-1;
        for(int i=0;i<(int)freeRects.size();i++) {
            auto &r=freeRects[i];
            if(w<=r.w && h<=r.h) {
                int bl=r.y; // bottom-left: minimize y then x
                int ss=r.x;
                if(bl<bestBL||(bl==bestBL&&ss<bestSS)) {
                    bestBL=bl; bestSS=ss; bestX=r.x; bestY=r.y; bestIdx=i;
                }
            }
        }
        return bestIdx;
    }
    
    int findBAF(int w, int h, int &bestX, int &bestY) {
        long long bestArea=LLONG_MAX; int bestSS=INT_MAX, bestIdx=-1;
        for(int i=0;i<(int)freeRects.size();i++) {
            auto &r=freeRects[i];
            if(w<=r.w && h<=r.h) {
                long long af=(long long)r.w*r.h-(long long)w*h;
                int ss=min(abs(r.h-h),abs(r.w-w));
                if(af<bestArea||(af==bestArea&&ss<bestSS)) {
                    bestArea=af; bestSS=ss; bestX=r.x; bestY=r.y; bestIdx=i;
                }
            }
        }
        return bestIdx;
    }
    
    bool canFit(int w, int h) {
        for(auto &r:freeRects) if(w<=r.w&&h<=r.h) return true;
        return false;
    }
    
    void placeRect(Rect used) {
        vector<Rect> newFree;
        newFree.reserve(freeRects.size()+4);
        for(auto &f : freeRects) {
            if(used.x>=f.x+f.w || used.x+used.w<=f.x ||
               used.y>=f.y+f.h || used.y+used.h<=f.y) {
                newFree.push_back(f);
            } else {
                if(used.x > f.x)
                    newFree.push_back({f.x, f.y, used.x-f.x, f.h});
                if(used.x+used.w < f.x+f.w)
                    newFree.push_back({used.x+used.w, f.y, f.x+f.w-used.x-used.w, f.h});
                if(used.y > f.y)
                    newFree.push_back({f.x, f.y, f.w, used.y-f.y});
                if(used.y+used.h < f.y+f.h)
                    newFree.push_back({f.x, used.y+used.h, f.w, f.y+f.h-used.y-used.h});
            }
        }
        // Remove contained
        int n=newFree.size();
        vector<bool> del(n,false);
        for(int i=0;i<n;i++) {
            if(del[i]) continue;
            for(int j=0;j<n;j++) {
                if(i!=j && !del[j] &&
                   newFree[i].x>=newFree[j].x && newFree[i].y>=newFree[j].y &&
                   newFree[i].x+newFree[i].w<=newFree[j].x+newFree[j].w &&
                   newFree[i].y+newFree[i].h<=newFree[j].y+newFree[j].h) {
                    del[i]=true; break;
                }
            }
        }
        freeRects.clear();
        for(int i=0;i<n;i++) if(!del[i]) freeRects.push_back(newFree[i]);
    }
};

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    string input;
    {
        ostringstream oss;
        oss << cin.rdbuf();
        input = oss.str();
    }
    
    int W,H; bool allowRotate;
    vector<Item> items;
    
    {
        auto findKey=[&](const string&key)->int{
            size_t p=input.find("\""+key+"\"");
            if(p==string::npos) return -1;
            p+=key.size()+2;
            while(p<input.size()&&(input[p]==':'||isspace(input[p])))p++;
            return (int)p;
        };
        {int p=findKey("W"); W=0; while(p<(int)input.size()&&isdigit(input[p]))W=W*10+(input[p++]-'0');}
        {int p=findKey("H"); H=0; while(p<(int)input.size()&&isdigit(input[p]))H=H*10+(input[p++]-'0');}
        {int p=findKey("allow_rotate"); allowRotate=(input.substr(p,4)=="true");}
    }
    
    {
        size_t pos=input.find("\"items\"");
        pos=input.find('[',pos); pos++;
        while(true){
            size_t ob=input.find('{',pos);
            if(ob==string::npos)break;
            size_t cb=input.find('}',ob);
            if(cb==string::npos)break;
            string chunk=input.substr(ob,cb-ob+1);
            Item it;
            {
                size_t tp=chunk.find("\"type\"");
                tp=chunk.find('\"',tp+6); tp++;
                size_t te=chunk.find('\"',tp);
                it.type=chunk.substr(tp,te-tp);
            }
            auto getLL=[&](const string&key)->long long{
                size_t kp=chunk.find("\""+key+"\"");
                kp+=key.size()+2;
                while(kp<chunk.size()&&(chunk[kp]==':'||isspace(chunk[kp])))kp++;
                long long val=0;bool neg=false;
                if(chunk[kp]=='-'){neg=true;kp++;}
                while(kp<chunk.size()&&isdigit(chunk[kp]))val=val*10+(chunk[kp++]-'0');
                return neg?-val:val;
            };
            it.w=(int)getLL("w"); it.h=(int)getLL("h"); it.v=getLL("v"); it.limit=(int)getLL("limit");
            items.push_back(it);
            pos=cb+1;
            while(pos<input.size()&&isspace(input[pos]))pos++;
            if(pos<input.size()&&input[pos]==',')pos++;
            while(pos<input.size()&&isspace(input[pos]))pos++;
            if(pos<input.size()&&input[pos]==']')break;
        }
    }
    
    int M=items.size();
    long long bestProfit=0;
    vector<Placement> bestPlacements;
    
    // For each item type + rotation, precompute value density
    struct Config { int idx; int rot; int pw,ph; double density; };
    vector<Config> configs;
    for(int i=0;i<M;i++){
        for(int r=0;r<=(allowRotate?1:0);r++){
            int pw=r?items[i].h:items[i].w;
            int ph=r?items[i].w:items[i].h;
            if(pw>W||ph>H) continue;
            // Avoid duplicates when w==h
            if(r==1 && items[i].w==items[i].h) continue;
            double d=(double)items[i].v/(pw*ph);
            configs.push_back({i,r,pw,ph,d});
        }
    }
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->double{return chrono::duration<double>(chrono::steady_clock::now()-start).count();};
    
    // Greedy: repeatedly pick best available item that fits
    auto greedyPack=[&](vector<int>&order, int method) {
        // order gives priority among configs
        MaxRectsPacker mr;
        mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> placements;
        long long profit=0;
        
        bool progress=true;
        while(progress) {
            progress=false;
            for(int ci : order) {
                auto &c=configs[ci];
                if(used[c.idx]>=items[c.idx].limit) continue;
                int bx,by;
                int fi;
                if(method==0) fi=mr.findBSSF(c.pw,c.ph,bx,by);
                else if(method==1) fi=mr.findBAF(c.pw,c.ph,bx,by);
                else fi=mr.findBLBF(c.pw,c.ph,bx,by);
                if(fi<0) continue;
                Rect r{bx,by,c.pw,c.ph};
                mr.placeRect(r);
                placements.push_back({items[c.idx].type,bx,by,c.rot});
                profit+=items[c.idx].v;
                used[c.idx]++;
                progress=true;
                break; // restart from top priority
            }
        }
        
        if(profit>bestProfit){bestProfit=profit;bestPlacements=placements;}
    };
    
    // Batch greedy: place all copies of each config in priority order
    auto batchPack=[&](vector<int>&order, int method) {
        MaxRectsPacker mr;
        mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> placements;
        long long profit=0;
        
        for(int ci : order) {
            auto &c=configs[ci];
            while(used[c.idx]<items[c.idx].limit) {
                int bx,by,fi;
                if(method==0) fi=mr.findBSSF(c.pw,c.ph,bx,by);
                else if(method==1) fi=mr.findBAF(c.pw,c.ph,bx,by);
                else fi=mr.findBLBF(c.pw,c.ph,bx,by);
                if(fi<0) break;
                Rect r{bx,by,c.pw,c.ph};
                mr.placeRect(r);
                placements.push_back({items[c.idx].type,bx,by,c.rot});
                profit+=items[c.idx].v;
                used[c.idx]++;
            }
        }
        
        if(profit>bestProfit){bestProfit=profit;bestPlacements=placements;}
    };
    
    int NC=configs.size();
    
    // Sort configs by various criteria
    auto makeOrder=[&](auto cmp)->vector<int>{
        vector<int> ord(NC);
        iota(ord.begin(),ord.end(),0);
        sort(ord.begin(),ord.end(),[&](int a,int b){return cmp(a)<cmp(b);});
        return ord;
    };
    
    vector<function<double(int)>> sortKeys={
        [&](int i)->double{return -configs[i].density;},
        [&](int i)->double{return -(double)items[configs[i].idx].v;},
        [&](int i)->double{return (double)configs[i].pw*configs[i].ph;},
        [&](int i)->double{return -(double)configs[i].pw*configs[i].ph;},
        [&](int i)->double{return -configs[i].density*(double)items[configs[i].idx].v;},
        [&](int i)->double{return -(double)max(configs[i].pw,configs[i].ph);},
        [&](int i)->double{return -(double)items[configs[i].idx].v/(double)max(configs[i].pw,configs[i].ph);},
        [&](int i)->double{return -configs[i].density*min(items[configs[i].idx].limit,(W/max(1,configs[i].pw))*(H/max(1,configs[i].ph)));},
    };
    
    // Run deterministic strategies
    for(int m=0;m<3&&elapsed()<0.7;m++){
        for(auto&sk:sortKeys){
            if(elapsed()>0.7)break;
            auto ord=makeOrder(sk);
            greedyPack(ord,m);
            batchPack(ord,m);
        }
    }
    
    // Random perturbations
    mt19937 rng(12345);
    while(elapsed()<0.9){
        int ski=rng()%sortKeys.size();
        auto ord=makeOrder(sortKeys[ski]);
        // Perturb
        int nswaps=1+rng()%max(1,NC);
        for(int s=0;s<nswaps;s++){
            int a=rng()%NC, b=rng()%NC;
            swap(ord[a],ord[b]);
        }
        int m=rng()%3;
        if(rng()%2) greedyPack(ord,m);
        else batchPack(ord,m);
    }
    
    printf("{\"placements\":[");
    for(int i=0;i<(int)bestPlacements.size();i++){
        if(i)printf(",");
        printf("{\"type\":\"%s\",\"x\":%d,\"y\":%d,\"rot\":%d}",
            bestPlacements[i].type.c_str(),bestPlacements[i].x,bestPlacements[i].y,bestPlacements[i].rot);
    }
    printf("]}");
    return 0;
}
