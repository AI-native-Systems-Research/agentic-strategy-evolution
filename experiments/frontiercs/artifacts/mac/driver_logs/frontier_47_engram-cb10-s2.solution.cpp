#include <bits/stdc++.h>
using namespace std;

// Minimal JSON parser
struct JsonVal {
    int type; // 0=null,1=bool,2=int,3=string,4=array,5=object
    long long ival;
    string sval;
    vector<JsonVal> arr;
    vector<pair<string,JsonVal>> obj;
    JsonVal():type(0),ival(0){}
    const JsonVal& operator[](const string& k) const {
        for(auto&p:obj) if(p.first==k) return p.second;
        static JsonVal nul; return nul;
    }
    const JsonVal& operator[](int i) const { return arr[i]; }
    int size() const { return type==4?(int)arr.size():(int)obj.size(); }
};

const char* skipws(const char* p){
    while(*p==' '||*p=='\n'||*p=='\r'||*p=='\t') p++;
    return p;
}

const char* parseVal(const char* p, JsonVal& v);

const char* parseString(const char* p, string& s){
    p++; // skip "
    s.clear();
    while(*p!='"'){
        if(*p=='\\'){p++; s+=*p; p++;}
        else{s+=*p; p++;}
    }
    p++; // skip "
    return p;
}

const char* parseVal(const char* p, JsonVal& v){
    p=skipws(p);
    if(*p=='"'){
        v.type=3;
        p=parseString(p,v.sval);
    } else if(*p=='{'){
        v.type=5;
        p=skipws(p+1);
        if(*p!='}'){
            while(true){
                p=skipws(p);
                string key;
                p=parseString(p,key);
                p=skipws(p);
                p++; // :
                JsonVal child;
                p=parseVal(p,child);
                v.obj.push_back({key,child});
                p=skipws(p);
                if(*p==',') p++; else break;
            }
        }
        p=skipws(p); p++; // }
    } else if(*p=='['){
        v.type=4;
        p=skipws(p+1);
        if(*p!=']'){
            while(true){
                JsonVal child;
                p=parseVal(p,child);
                v.arr.push_back(child);
                p=skipws(p);
                if(*p==',') p++; else break;
            }
        }
        p=skipws(p); p++; // ]
    } else if(*p=='t'){
        v.type=1; v.ival=1; p+=4;
    } else if(*p=='f'){
        v.type=1; v.ival=0; p+=5;
    } else if(*p=='n'){
        v.type=0; p+=4;
    } else {
        // number
        v.type=2;
        bool neg=false;
        if(*p=='-'){neg=true;p++;}
        long long n=0;
        while(*p>='0'&&*p<='9'){n=n*10+(*p-'0');p++;}
        if(*p=='.'){ // skip fractional
            p++;
            while(*p>='0'&&*p<='9') p++;
        }
        v.ival=neg?-n:n;
    }
    return p;
}

struct ItemType {
    string type;
    int w,h,limit;
    long long v;
    double density;
};

struct Placement {
    string type;
    int x,y,rot;
};

// Skyline bottom-left packer
struct SkylineBin {
    int W,H;
    vector<pair<int,int>> sky; // (x_start, height)
    
    void init(int w,int h){
        W=w; H=h;
        sky.clear();
        sky.push_back({0,0});
    }
    
    // Try to place rectangle of size rw x rh
    // Returns true and sets px,py if successful
    bool place(int rw, int rh, int& px, int& py){
        int bestY=INT_MAX, bestX=INT_MAX, bestIdx=-1;
        // Try each skyline segment as leftmost position
        for(int i=0;i<(int)sky.size();i++){
            int x=sky[i].second; // this is wrong, sky is (x_start, height)
            // Actually let me redo: sky[i] = {x_start, y_height}
            int sx=sky[i].first;
            if(sx+rw>W) continue;
            // Find max height under this rectangle
            int maxH=0;
            int j=i;
            int curX=sx;
            while(j<(int)sky.size() && curX<sx+rw){
                maxH=max(maxH,sky[j].second);
                j++;
                curX=(j<(int)sky.size())?sky[j].first:W;
            }
            if(maxH+rh>H) continue;
            if(maxH<bestY||(maxH==bestY&&sx<bestX)){
                bestY=maxH; bestX=sx; bestIdx=i;
            }
        }
        if(bestIdx==-1) return false;
        px=bestX; py=bestY;
        
        // Update skyline
        int newLeft=bestX, newRight=bestX+rw, newTop=bestY+rh;
        vector<pair<int,int>> newSky;
        for(int i=0;i<(int)sky.size();i++){
            int segLeft=sky[i].first;
            int segRight=(i+1<(int)sky.size())?sky[i+1].first:W;
            if(segRight<=newLeft||segLeft>=newRight){
                newSky.push_back(sky[i]);
            } else {
                if(segLeft<newLeft){
                    newSky.push_back(sky[i]);
                }
                if(segLeft>=newLeft && segLeft<newRight){
                    // This segment is covered
                    if(segLeft==newLeft){
                        newSky.push_back({newLeft,newTop});
                    }
                }
                if(segRight>newRight){
                    newSky.push_back({newRight,sky[i].second});
                }
            }
        }
        // Ensure newLeft is in there with newTop
        bool found=false;
        for(auto&s:newSky) if(s.first==newLeft){s.second=newTop;found=true;break;}
        if(!found){
            newSky.push_back({newLeft,newTop});
        }
        sort(newSky.begin(),newSky.end());
        // Merge consecutive same height
        vector<pair<int,int>> merged;
        for(auto&s:newSky){
            if(!merged.empty()&&merged.back().second==s.second) continue;
            merged.push_back(s);
        }
        sky=merged;
        return true;
    }
};

// MaxRects packer (cleaner version)
struct MaxRectsBin {
    int W,H;
    struct Rect { int x,y,w,h; };
    vector<Rect> free_rects;
    
    void init(int w,int h){
        W=w;H=h;
        free_rects.clear();
        free_rects.push_back({0,0,w,h});
    }
    
    bool place(int rw,int rh,int&px,int&py,int method){
        int bestScore1=INT_MAX,bestScore2=INT_MAX;
        int bi=-1,bx=0,by=0;
        for(int i=0;i<(int)free_rects.size();i++){
            auto&f=free_rects[i];
            if(rw<=f.w&&rh<=f.h){
                int s1,s2;
                if(method==0){s1=min(f.w-rw,f.h-rh);s2=max(f.w-rw,f.h-rh);}
                else if(method==1){s1=max(f.w-rw,f.h-rh);s2=min(f.w-rw,f.h-rh);}
                else if(method==2){s1=f.w*f.h-rw*rh;s2=min(f.w-rw,f.h-rh);}
                else{s1=f.y;s2=f.x;}
                if(s1<bestScore1||(s1==bestScore1&&s2<bestScore2)){
                    bestScore1=s1;bestScore2=s2;bi=i;bx=f.x;by=f.y;
                }
            }
        }
        if(bi==-1) return false;
        px=bx;py=by;
        Rect placed={bx,by,rw,rh};
        int n=(int)free_rects.size();
        vector<Rect> newFree;
        for(int i=0;i<n;i++){
            auto&f=free_rects[i];
            if(placed.x>=f.x+f.w||placed.x+placed.w<=f.x||
               placed.y>=f.y+f.h||placed.y+placed.h<=f.y){
                newFree.push_back(f);
                continue;
            }
            if(placed.x>f.x)
                newFree.push_back({f.x,f.y,placed.x-f.x,f.h});
            if(placed.x+placed.w<f.x+f.w)
                newFree.push_back({placed.x+placed.w,f.y,f.x+f.w-placed.x-placed.w,f.h});
            if(placed.y>f.y)
                newFree.push_back({f.x,f.y,f.w,placed.y-f.y});
            if(placed.y+placed.h<f.y+f.h)
                newFree.push_back({f.x,placed.y+placed.h,f.w,f.y+f.h-placed.y-placed.h});
        }
        // Remove contained rects
        int sz=(int)newFree.size();
        vector<bool> del(sz,false);
        for(int i=0;i<sz;i++){
            if(del[i]) continue;
            for(int j=0;j<sz;j++){
                if(i==j||del[j]) continue;
                if(newFree[i].x>=newFree[j].x&&newFree[i].y>=newFree[j].y&&
                   newFree[i].x+newFree[i].w<=newFree[j].x+newFree[j].w&&
                   newFree[i].y+newFree[i].h<=newFree[j].y+newFree[j].h){
                    del[i]=true;break;
                }
            }
        }
        free_rects.clear();
        for(int i=0;i<sz;i++) if(!del[i]) free_rects.push_back(newFree[i]);
        return true;
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
    
    JsonVal root;
    parseVal(input.c_str(), root);
    
    int W=(int)root["bin"]["W"].ival;
    int H=(int)root["bin"]["H"].ival;
    bool allowRotate=(root["bin"]["allow_rotate"].ival!=0);
    
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
    
    // Try adaptive packing with MaxRects
    auto tryPacking=[&](vector<int>& typeOrder, int method) -> pair<long long,vector<Placement>> {
        MaxRectsBin bin;
        bin.init(W,H);
        vector<int> used(M,0);
        vector<Placement> placements;
        long long totalProfit=0;
        
        for(int idx:typeOrder){
            while(used[idx]<items[idx].limit){
                bool placed=false;
                // Try both orientations, pick whichever places
                struct Option { int rw,rh,rot,px,py; };
                vector<Option> opts;
                
                {
                    int rw=items[idx].w, rh=items[idx].h;
                    if(rw<=W&&rh<=H){
                        MaxRectsBin tb=bin;
                        int px,py;
                        if(tb.place(rw,rh,px,py,method)){
                            opts.push_back({rw,rh,0,px,py});
                        }
                    }
                }
                if(allowRotate&&items[idx].w!=items[idx].h){
                    int rw=items[idx].h, rh=items[idx].w;
                    if(rw<=W&&rh<=H){
                        MaxRectsBin tb=bin;
                        int px,py;
                        if(tb.place(rw,rh,px,py,method)){
                            opts.push_back({rw,rh,1,px,py});
                        }
                    }
                }
                
                if(!opts.empty()){
                    // Pick the option with lower y then lower x (bottom-left preference)
                    auto& best=opts[0];
                    for(int k=1;k<(int)opts.size();k++){
                        if(opts[k].py<best.py||(opts[k].py==best.py&&opts[k].px<best.px))
                            best=opts[k];
                    }
                    // Actually place it
                    int px2,py2;
                    bin.place(best.rw,best.rh,px2,py2,method);
                    placements.push_back({items[idx].type,px2,py2,best.rot});
                    totalProfit+=items[idx].v;
                    used[idx]++;
                    placed=true;
                }
                if(!placed) break;
            }
        }
        return {totalProfit,placements};
    };
    
    // Generate various orderings
    auto makeOrder=[&](function<bool(int,int)> cmp) -> vector<int> {
        vector<int> ord(M);
        iota(ord.begin(),ord.end(),0);
        sort(ord.begin(),ord.end(),cmp);
        return ord;
    };
    
    vector<vector<int>> orders;
    orders.push_back(makeOrder([&](int a,int b){return items[a].density>items[b].density;}));
    orders.push_back(makeOrder([&](int a,int b){return items[a].v>items[b].v;}));
    orders.push_back(makeOrder([&](int a,int b){return items[a].w*items[a].h>items[b].w*items[b].h;}));
    orders.push_back(makeOrder([&](int a,int b){return max(items[a].w,items[a].h)>max(items[b].w,items[b].h);}));
    orders.push_back(makeOrder([&](int a,int b){return items[a].h>items[b].h;}));
    orders.push_back(makeOrder([&](int a,int b){return items[a].w>items[b].w;}));
    // value * density
    orders.push_back(makeOrder([&](int a,int b){return items[a].v*items[a].density>items[b].v*items[b].density;}));
    
    for(auto&ord:orders){
        for(int method=0;method<4;method++){
            if(elapsed()>0.6) break;
            auto [profit,pl]=tryPacking(ord,method);
            if(profit>bestProfit){bestProfit=profit;bestPlacements=pl;}
        }
        if(elapsed()>0.6) break;
    }
    
    // Interleaved: always pick highest density available item
    for(int method=0;method<4&&elapsed()<0.7;method++){
        MaxRectsBin bin;
        bin.init(W,H);
        vector<int> used(M,0);
        vector<Placement> placements;
        long long totalProfit=0;
        
        while(true){
            double bestDens=-1;
            int bestType=-1,bestRot=0,bestPx=0,bestPy=0;
            MaxRectsBin bestBin;
            
            for(int i=0;i<M;i++){
                if(used[i]>=items[i].limit) continue;
                vector<tuple<int,int,int>> orients;
                orients.push_back({items[i].w,items[i].h,0});
                if(allowRotate&&items[i].w!=items[i].h)
                    orients.push_back({items[i].h,items[i].w,1});
                for(auto&[ow,oh,rot]:orients){
                    if(ow>W||oh>H) continue;
                    MaxRectsBin tb=bin;
                    int px,py;
                    if(tb.place(ow,oh,px,py,method)){
                        if(items[i].density>bestDens){
                            bestDens=items[i].density;
                            bestType=i;bestRot=rot;bestPx=px;bestPy=py;
                            bestBin=tb;
                        }
                    }
                }
            }
            if(bestType==-1) break;
            bin=bestBin;
            placements.push_back({items[bestType].type,bestPx,bestPy,bestRot});
            totalProfit+=items[bestType].v;
            used[bestType]++;
            if(elapsed()>0.85) break;
        }
        if(totalProfit>bestProfit){bestProfit=totalProfit;bestPlacements=placements;}
    }
    
    // Random permutations
    mt19937 rng(12345);
    while(elapsed()<0.9){
        vector<int> ord(M);
        iota(ord.begin(),ord.end(),0);
        shuffle(ord.begin(),ord.end(),rng);
        int method=rng()%4;
        auto [profit,pl]=tryPacking(ord,method);
        if(profit>bestProfit){bestProfit=profit;bestPlacements=pl;}
    }
    
    // Output
    cout<<"{\"placements\":[";
    for(int i=0;i<(int)bestPlacements.size();i++){
        if(i) cout<<",";
        auto&p=bestPlacements[i];
        cout<<"{\"type\":\""<<p.type<<"\",\"x\":"<<p.x<<",\"y\":"<<p.y<<",\"rot\":"<<p.rot<<"}";
    }
    cout<<"]}";
    cout<<endl;
    
    return 0;
}
