#include <bits/stdc++.h>
using namespace std;

struct Item { string type; int w,h; long long v; int limit; };
struct Placement { string type; int x,y,rot; };

struct MaxRects {
    int W,H;
    vector<array<int,4>> fr; // x,y,w,h
    
    void init(int w,int h){ W=w; H=h; fr.push_back({0,0,w,h}); }
    
    // heuristic: 0=BSSF, 1=BL, 2=BAF, 3=BLSF
    bool place(int pw,int ph,int &bx,int &by, int heur=0){
        int bi=-1; bx=by=0;
        long long bestScore1=LLONG_MAX, bestScore2=LLONG_MAX;
        for(int i=0;i<(int)fr.size();i++){
            auto &r=fr[i];
            if(pw<=r[2] && ph<=r[3]){
                long long s1,s2;
                if(heur==0){ s1=min(r[2]-pw,r[3]-ph); s2=(long long)r[2]*r[3]; }
                else if(heur==1){ s1=r[1]; s2=r[0]; }
                else if(heur==2){ s1=(long long)r[2]*r[3]; s2=min(r[2]-pw,r[3]-ph); }
                else { s1=max(r[2]-pw,r[3]-ph); s2=(long long)r[2]*r[3]; }
                if(s1<bestScore1||(s1==bestScore1&&s2<bestScore2)){
                    bestScore1=s1; bestScore2=s2;
                    bx=r[0]; by=r[1]; bi=i;
                }
            }
        }
        if(bi<0) return false;
        split(bx,by,pw,ph);
        return true;
    }
    
    void split(int px,int py,int pw,int ph){
        vector<array<int,4>> nfr;
        nfr.reserve(fr.size()+4);
        for(auto &r:fr){
            if(px>=r[0]+r[2]||px+pw<=r[0]||py>=r[1]+r[3]||py+ph<=r[1]){
                nfr.push_back(r); continue;
            }
            if(px>r[0]) nfr.push_back({r[0],r[1],px-r[0],r[3]});
            if(px+pw<r[0]+r[2]) nfr.push_back({px+pw,r[1],r[0]+r[2]-px-pw,r[3]});
            if(py>r[1]) nfr.push_back({r[0],r[1],r[2],py-r[1]});
            if(py+ph<r[1]+r[3]) nfr.push_back({r[0],py+ph,r[2],r[1]+r[3]-py-ph});
        }
        // remove contained - use a more efficient approach
        int n=nfr.size();
        vector<bool> del(n,false);
        // Sort by area descending to speed up containment check
        for(int i=0;i<n;i++){
            if(del[i]) continue;
            for(int j=0;j<n;j++){
                if(i==j||del[j]) continue;
                if(nfr[i][0]<=nfr[j][0]&&nfr[i][1]<=nfr[j][1]&&
                   nfr[i][0]+nfr[i][2]>=nfr[j][0]+nfr[j][2]&&
                   nfr[i][1]+nfr[i][3]>=nfr[j][1]+nfr[j][3])
                    del[j]=true;
            }
        }
        fr.clear();
        for(int i=0;i<n;i++) if(!del[i]) fr.push_back(nfr[i]);
    }
};

int main(){
    ios::sync_with_stdio(false);
    string input((istreambuf_iterator<char>(cin)),{});
    
    auto getInt=[&](const string &s,const string &key)->long long{
        auto p=s.find("\""+key+"\"");
        p=s.find(':',p); p++;
        while(p<s.size()&&(s[p]==' '||s[p]=='\n'||s[p]=='\r'||s[p]=='\t'))p++;
        bool neg=false; if(s[p]=='-'){neg=true;p++;}
        long long v=0; while(p<s.size()&&isdigit(s[p]))v=v*10+(s[p++]-'0');
        return neg?-v:v;
    };
    auto getStr=[&](const string &s,const string &key)->string{
        auto p=s.find("\""+key+"\""); p=s.find(':',p); p=s.find('"',p); p++;
        string r; while(s[p]!='"')r+=s[p++]; return r;
    };
    auto getBool=[&](const string &s,const string &key)->bool{
        auto p=s.find("\""+key+"\""); p=s.find(':',p);
        return s.find("true",p)<s.find("false",p);
    };
    
    int W=(int)getInt(input,"W"), H=(int)getInt(input,"H");
    bool allow_rot=getBool(input,"allow_rotate");
    
    vector<Item> items;
    {
        auto p=input.find("\"items\""); p=input.find('[',p);
        while(true){
            auto q=input.find('{',p); if(q==string::npos)break;
            auto e=input.find('}',q); string sub=input.substr(q,e-q+1);
            Item it; it.type=getStr(sub,"type"); it.w=(int)getInt(sub,"w");
            it.h=(int)getInt(sub,"h"); it.v=getInt(sub,"v"); it.limit=(int)getInt(sub,"limit");
            items.push_back(it); p=e+1;
        }
    }
    
    int M=items.size();
    long long bestVal=0;
    vector<Placement> bestPl;
    
    // Generate all (type, rot) candidates
    struct Cand { int ti; int rot; int pw,ph; double density; };
    vector<Cand> allCands;
    for(int i=0;i<M;i++){
        if(items[i].w<=W && items[i].h<=H)
            allCands.push_back({i,0,items[i].w,items[i].h,(double)items[i].v/(items[i].w*items[i].h)});
        if(allow_rot && items[i].w!=items[i].h && items[i].h<=W && items[i].w<=H)
            allCands.push_back({i,1,items[i].h,items[i].w,(double)items[i].v/(items[i].w*items[i].h)});
    }
    
    auto tryPack=[&](vector<Cand> &order, int heur) -> pair<long long, vector<Placement>> {
        MaxRects mr; mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long val=0;
        for(auto &c:order){
            if(c.pw>W||c.ph>H) continue;
            while(used[c.ti]<items[c.ti].limit){
                int bx,by;
                if(!mr.place(c.pw,c.ph,bx,by,heur)) break;
                pl.push_back({items[c.ti].type,bx,by,c.rot});
                val+=items[c.ti].v; used[c.ti]++;
            }
        }
        return {val,pl};
    };
    
    // Also try: place items one at a time picking best candidate each time
    auto tryGreedy=[&](int heur) -> pair<long long, vector<Placement>> {
        MaxRects mr; mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long val=0;
        while(true){
            // For each candidate, find best placement and pick the one with highest value
            int bestTi=-1, bestRot=0, bbx=0, bby=0;
            double bestScore=-1;
            for(auto &c:allCands){
                if(used[c.ti]>=items[c.ti].limit) continue;
                // Try to find placement
                int bx2,by2;
                long long bs1=LLONG_MAX,bs2=LLONG_MAX;
                int bi2=-1;
                for(int i=0;i<(int)mr.fr.size();i++){
                    auto &r=mr.fr[i];
                    if(c.pw<=r[2]&&c.ph<=r[3]){
                        long long s1,s2;
                        if(heur==0){ s1=min(r[2]-c.pw,r[3]-c.ph); s2=(long long)r[2]*r[3]; }
                        else{ s1=r[1]; s2=r[0]; }
                        if(s1<bs1||(s1==bs1&&s2<bs2)){
                            bs1=s1;bs2=s2;bx2=r[0];by2=r[1];bi2=i;
                        }
                    }
                }
                if(bi2<0) continue;
                double score=c.density;
                if(score>bestScore){
                    bestScore=score; bestTi=c.ti; bestRot=c.rot; bbx=bx2; bby=by2;
                }
            }
            if(bestTi<0) break;
            int pw=bestRot?items[bestTi].h:items[bestTi].w;
            int ph=bestRot?items[bestTi].w:items[bestTi].h;
            mr.split(bbx,bby,pw,ph);
            pl.push_back({items[bestTi].type,bbx,bby,bestRot});
            val+=items[bestTi].v; used[bestTi]++;
        }
        return {val,pl};
    };
    
    // Strip packing: for each candidate, compute how many fit in strips
    auto tryStrips=[&](vector<int> &typeOrder) -> pair<long long, vector<Placement>> {
        // Pack horizontal strips from bottom up
        vector<Placement> pl;
        long long val=0;
        vector<int> used(M,0);
        int cy=0; // current y
        for(int ti:typeOrder){
            if(cy>=H) break;
            // Try both orientations
            vector<pair<int,int>> rots;
            rots.push_back({items[ti].w, items[ti].h});
            if(allow_rot && items[ti].w!=items[ti].h)
                rots.push_back({items[ti].h, items[ti].w});
            
            for(auto [pw,ph]:rots){
                int rot_val=(pw==items[ti].w)?0:1;
                if(pw>W||ph>H) continue;
                // Fill strips
                while(cy+ph<=H && used[ti]<items[ti].limit){
                    int cx=0;
                    bool placed_any=false;
                    while(cx+pw<=W && used[ti]<items[ti].limit){
                        pl.push_back({items[ti].type,cx,cy,rot_val});
                        val+=items[ti].v; used[ti]++;
                        cx+=pw; placed_any=true;
                    }
                    if(placed_any) cy+=ph;
                    else break;
                    if(used[ti]>=items[ti].limit) break;
                }
            }
        }
        return {val,pl};
    };
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->int{ return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-start).count(); };
    
    auto updateBest=[&](pair<long long,vector<Placement>> &res){
        if(res.first>bestVal){bestVal=res.first;bestPl=res.second;}
    };
    
    // Strategy 1: sorted by density, different heuristics
    for(int h=0;h<4;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
        auto res=tryPack(order,h);
        updateBest(res);
    }
    
    // Strategy 2: sorted by value
    for(int h=0;h<4;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[&](auto&a,auto&b){return items[a.ti].v>items[b.ti].v;});
        auto res=tryPack(order,h);
        updateBest(res);
    }
    
    // Strategy 3: sorted by area desc
    for(int h=0;h<4;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return a.pw*a.ph>b.pw*b.ph;});
        auto res=tryPack(order,h);
        updateBest(res);
    }
    
    // Strategy 4: sorted by max(w,h) desc (tall/wide first)
    for(int h=0;h<4;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return max(a.pw,a.ph)>max(b.pw,b.ph);});
        auto res=tryPack(order,h);
        updateBest(res);
    }
    
    // Strategy 5: sorted by height desc
    for(int h=0;h<4;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return a.ph>b.ph;});
        auto res=tryPack(order,h);
        updateBest(res);
    }
    
    // Greedy per-item
    for(int h=0;h<2&&elapsed()<200;h++){
        auto res=tryGreedy(h);
        updateBest(res);
    }
    
    // Strip packing with type permutations by density
    {
        vector<int> to(M); iota(to.begin(),to.end(),0);
        sort(to.begin(),to.end(),[&](int a,int b){
            double da=(double)items[a].v/(items[a].w*items[a].h);
            double db=(double)items[b].v/(items[b].w*items[b].h);
            return da>db;
        });
        auto res=tryStrips(to);
        updateBest(res);
    }
    
    // Mixed strip + maxrects: fill strips of highest density, then maxrects for remainder
    auto tryMixedStrip=[&](int topK) -> pair<long long, vector<Placement>> {
        vector<int> to(M); iota(to.begin(),to.end(),0);
        sort(to.begin(),to.end(),[&](int a,int b){
            double da=(double)items[a].v/(items[a].w*items[a].h);
            double db=(double)items[b].v/(items[b].w*items[b].h);
            return da>db;
        });
        
        vector<Placement> pl;
        long long val=0;
        vector<int> used(M,0);
        int cy=0;
        
        for(int k=0;k<min(topK,(int)to.size());k++){
            int ti=to[k];
            // find best orientation for strip
            int bestPW=items[ti].w, bestPH=items[ti].h, bestRot=0;
            if(allow_rot && items[ti].w!=items[ti].h){
                // pick orientation that wastes less width
                int w1=items[ti].w, h1=items[ti].h;
                int w2=items[ti].h, h2=items[ti].w;
                int r1=W%w1, r2=W%w2;
                double eff1=(double)(W/w1)*w1/W;
                double eff2=(double)(W/w2)*w2/W;
                if(eff2>eff1 && w2<=W && h2<=H){ bestPW=w2; bestPH=h2; bestRot=1; }
                else if(w1<=W && h1<=H){ bestPW=w1; bestPH=h1; bestRot=0; }
            }
            if(bestPW>W||bestPH>H) continue;
            
            while(cy+bestPH<=H && used[ti]<items[ti].limit){
                int cx=0;
                bool any=false;
                while(cx+bestPW<=W && used[ti]<items[ti].limit){
                    pl.push_back({items[ti].type,cx,cy,bestRot});
                    val+=items[ti].v; used[ti]++; cx+=bestPW; any=true;
                }
                if(any) cy+=bestPH; else break;
                if(used[ti]>=items[ti].limit) break;
            }
        }
        
        // Now use maxrects for remaining space
        // Create maxrects with the remaining area
        if(cy<H){
            MaxRects mr; mr.init(W,H-cy);
            auto order=allCands;
            sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
            for(auto &c:order){
                if(c.pw>W||c.ph>(H-cy)) continue;
                while(used[c.ti]<items[c.ti].limit){
                    int bx,by;
                    if(!mr.place(c.pw,c.ph,bx,by,0)) break;
                    pl.push_back({items[c.ti].type,bx,by+cy,c.rot});
                    val+=items[c.ti].v; used[c.ti]++;
                }
            }
        }
        return {val,pl};
    };
    
    for(int k=1;k<=M&&elapsed()<400;k++){
        auto res=tryMixedStrip(k);
        updateBest(res);
    }
    
    // Also try W/H swapped approach: strips going vertically
    auto tryStripVert=[&](int topK) -> pair<long long, vector<Placement>> {
        vector<int> to(M); iota(to.begin(),to.end(),0);
        sort(to.begin(),to.end(),[&](int a,int b){
            return (double)items[a].v/(items[a].w*items[a].h) > (double)items[b].v/(items[b].w*items[b].h);
        });
        
        vector<Placement> pl;
        long long val=0;
        vector<int> used(M,0);
        int cx=0;
        
        for(int k=0;k<min(topK,(int)to.size());k++){
            int ti=to[k];
            int bestPW=items[ti].w, bestPH=items[ti].h, bestRot=0;
            if(allow_rot && items[ti].w!=items[ti].h){
                int w2=items[ti].h, h2=items[ti].w;
                if(H%h2 < H%bestPH && w2<=W && h2<=H){ bestPW=w2; bestPH=h2; bestRot=1; }
            }
            if(bestPW>W||bestPH>H) continue;
            
            while(cx+bestPW<=W && used[ti]<items[ti].limit){
                int cy2=0; bool any=false;
                while(cy2+bestPH<=H && used[ti]<items[ti].limit){
                    pl.push_back({items[ti].type,cx,cy2,bestRot});
                    val+=items[ti].v; used[ti]++; cy2+=bestPH; any=true;
                }
                if(any) cx+=bestPW; else break;
                if(used[ti]>=items[ti].limit) break;
            }
        }
        
        if(cx<W){
            MaxRects mr; mr.init(W-cx,H);
            auto order=allCands;
            sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
            for(auto &c:order){
                if(c.pw>(W-cx)||c.ph>H) continue;
                while(used[c.ti]<items[c.ti].limit){
                    int bx,by;
                    if(!mr.place(c.pw,c.ph,bx,by,0)) break;
                    pl.push_back({items[c.ti].type,bx+cx,by,c.rot});
                    val+=items[c.ti].v; used[c.ti]++;
                }
            }
        }
        return {val,pl};
    };
    
    for(int k=1;k<=M&&elapsed()<500;k++){
        auto res=tryStripVert(k);
        updateBest(res);
    }
    
    // Random permutation exploration
    mt19937 rng(42);
    while(elapsed()<900){
        auto order=allCands;
        // Weighted shuffle: bias towards high density
        sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
        // Partial shuffle
        for(int i=0;i<(int)order.size();i++){
            int range=min((int)order.size()-i, max(1,(int)(order.size()/3)));
            int j=i+rng()%range;
            swap(order[i],order[j]);
        }
        int h=rng()%4;
        auto res=tryPack(order,h);
        updateBest(res);
    }
    
    printf("{\"placements\":[");
    for(int i=0;i<(int)bestPl.size();i++){
        if(i) printf(",");
        printf("{\"type\":\"%s\",\"x\":%d,\"y\":%d,\"rot\":%d}",bestPl[i].type.c_str(),bestPl[i].x,bestPl[i].y,bestPl[i].rot);
    }
    printf("]}\n");
}
