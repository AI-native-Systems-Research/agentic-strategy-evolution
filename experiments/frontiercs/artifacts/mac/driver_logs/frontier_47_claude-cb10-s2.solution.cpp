Looking at the previous solution, I can identify several areas for improvement:

1. **The MaxRects free rectangle list can grow very large**, slowing down placement and causing O(n²) containment checks
2. **Strip packing doesn't fill gaps** between strips well
3. **No hybrid approach** that combines different item types in strips efficiently
4. **Limited search diversity** - the random permutation shuffle is too conservative
5. **No guillotine-cut based approach** or recursive partitioning
6. **Missing key optimization**: trying all permutations of the small number of types (8-12 types means feasible permutation enumeration)

Key improvements:
- Cap free rectangles list size for speed
- Add full permutation search over types (up to 12! is too many, but we can do smarter)
- Better strip-based hybrid: fill strips with one type, then recurse on gaps
- Improve the greedy to consider "value per wasted space" not just density
- Add simulated annealing or more aggressive random restarts
- Better handling of mixed strip strategies with gap filling

```cpp
#include <bits/stdc++.h>
using namespace std;

struct Item { string type; int w,h; long long v; int limit; };
struct Placement { string type; int x,y,rot; };

static const int MAX_FR = 800;

struct MaxRects {
    int W,H;
    vector<array<int,4>> fr;
    
    void init(int w,int h){ W=w; H=h; fr.clear(); fr.push_back({0,0,w,h}); }
    
    bool place(int pw,int ph,int &bx,int &by, int heur=0){
        int bi=-1; bx=by=0;
        long long bs1=LLONG_MAX, bs2=LLONG_MAX;
        for(int i=0;i<(int)fr.size();i++){
            auto &r=fr[i];
            if(pw<=r[2]&&ph<=r[3]){
                long long s1,s2;
                switch(heur){
                    case 0: s1=min(r[2]-pw,r[3]-ph); s2=(long long)r[2]*r[3]; break;
                    case 1: s1=r[1]; s2=r[0]; break;
                    case 2: s1=(long long)r[2]*r[3]; s2=min(r[2]-pw,r[3]-ph); break;
                    case 3: s1=max(r[2]-pw,r[3]-ph); s2=(long long)r[2]*r[3]; break;
                    default: s1=r[1]+r[0]; s2=min(r[2]-pw,r[3]-ph); break;
                }
                if(s1<bs1||(s1==bs1&&s2<bs2)){
                    bs1=s1; bs2=s2; bx=r[0]; by=r[1]; bi=i;
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
        int rx2=px+pw, ry2=py+ph;
        for(auto &r:fr){
            int rr=r[0]+r[2], rt=r[1]+r[3];
            if(px>=rr||rx2<=r[0]||py>=rt||ry2<=r[1]){
                nfr.push_back(r); continue;
            }
            if(px>r[0]) nfr.push_back({r[0],r[1],px-r[0],r[3]});
            if(rx2<rr) nfr.push_back({rx2,r[1],rr-rx2,r[3]});
            if(py>r[1]) nfr.push_back({r[0],r[1],r[2],py-r[1]});
            if(ry2<rt) nfr.push_back({r[0],ry2,r[2],rt-ry2});
        }
        // Remove contained
        int n=nfr.size();
        vector<bool> del(n,false);
        // Sort by area desc for faster pruning
        vector<int> idx(n); iota(idx.begin(),idx.end(),0);
        sort(idx.begin(),idx.end(),[&](int a,int b){
            return (long long)nfr[a][2]*nfr[a][3] > (long long)nfr[b][2]*nfr[b][3];
        });
        for(int ii=0;ii<n;ii++){
            int i=idx[ii];
            if(del[i]) continue;
            for(int jj=ii+1;jj<n;jj++){
                int j=idx[jj];
                if(del[j]) continue;
                if(nfr[i][0]<=nfr[j][0]&&nfr[i][1]<=nfr[j][1]&&
                   nfr[i][0]+nfr[i][2]>=nfr[j][0]+nfr[j][2]&&
                   nfr[i][1]+nfr[i][3]>=nfr[j][1]+nfr[j][3])
                    del[j]=true;
            }
        }
        fr.clear();
        for(int i=0;i<n;i++) if(!del[i]) fr.push_back(nfr[i]);
        // Cap size
        if((int)fr.size()>MAX_FR){
            sort(fr.begin(),fr.end(),[](auto&a,auto&b){
                return (long long)a[2]*a[3]>(long long)b[2]*b[3];
            });
            fr.resize(MAX_FR);
        }
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
    
    struct Cand { int ti; int rot; int pw,ph; double density; };
    vector<Cand> allCands;
    for(int i=0;i<M;i++){
        if(items[i].w<=W && items[i].h<=H)
            allCands.push_back({i,0,items[i].w,items[i].h,(double)items[i].v/(items[i].w*items[i].h)});
        if(allow_rot && items[i].w!=items[i].h && items[i].h<=W && items[i].w<=H)
            allCands.push_back({i,1,items[i].h,items[i].w,(double)items[i].v/(items[i].w*items[i].h)});
    }
    
    auto start=chrono::steady_clock::now();
    auto elapsed=[&]()->int{ return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-start).count(); };
    
    auto updateBest=[&](long long v, vector<Placement> &pl){
        if(v>bestVal){bestVal=v;bestPl=pl;}
    };
    
    // Generic maxrects pack with given candidate order and heuristic
    auto tryPack=[&](vector<Cand> &order, int heur) -> pair<long long, vector<Placement>> {
        MaxRects mr; mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long val=0;
        for(auto &c:order){
            while(used[c.ti]<items[c.ti].limit){
                int bx,by;
                if(!mr.place(c.pw,c.ph,bx,by,heur)) break;
                pl.push_back({items[c.ti].type,bx,by,c.rot});
                val+=items[c.ti].v; used[c.ti]++;
            }
        }
        return {val,pl};
    };
    
    // Greedy: each step pick candidate with best score
    auto tryGreedy=[&](int heur, int scoreMode) -> pair<long long, vector<Placement>> {
        MaxRects mr; mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long val=0;
        while(true){
            int bestCI=-1; int bbx=0,bby=0;
            double bestScore=-1e18;
            for(int ci=0;ci<(int)allCands.size();ci++){
                auto &c=allCands[ci];
                if(used[c.ti]>=items[c.ti].limit) continue;
                int bx2,by2;
                long long bs1=LLONG_MAX,bs2=LLONG_MAX;
                bool found=false;
                for(int i=0;i<(int)mr.fr.size();i++){
                    auto &r=mr.fr[i];
                    if(c.pw<=r[2]&&c.ph<=r[3]){
                        long long s1,s2;
                        switch(heur){
                            case 0: s1=min(r[2]-c.pw,r[3]-c.ph); s2=(long long)r[2]*r[3]; break;
                            case 1: s1=r[1]; s2=r[0]; break;
                            default: s1=(long long)r[2]*r[3]; s2=min(r[2]-c.pw,r[3]-c.ph); break;
                        }
                        if(s1<bs1||(s1==bs1&&s2<bs2)){
                            bs1=s1;bs2=s2;bx2=r[0];by2=r[1];found=true;
                        }
                    }
                }
                if(!found) continue;
                double score;
                if(scoreMode==0) score=c.density;
                else if(scoreMode==1) score=(double)items[c.ti].v;
                else score=c.density * 1000.0 - bs1;
                if(score>bestScore){
                    bestScore=score; bestCI=ci; bbx=bx2; bby=by2;
                }
            }
            if(bestCI<0) break;
            auto &c=allCands[bestCI];
            mr.split(bbx,bby,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bbx,bby,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
        return {val,pl};
    };
    
    // Recursive strip-based: pick a type, fill horizontal strip, then pack remainder
    // Uses recursion on remaining bin region (top part) with maxrects for side gaps
    struct StripState {
        int cy; // current y offset
        vector<int> used;
        vector<Placement> pl;
        long long val;
    };
    
    auto tryMixedStripH=[&](vector<int> &typeOrder, bool fillGaps) -> pair<long long, vector<Placement>> {
        vector<Placement> pl;
        long long val=0;
        vector<int> used(M,0);
        int cy=0;
        
        for(int ti:typeOrder){
            if(cy>=H) break;
            // Try both orientations, pick better
            struct StripConfig { int pw,ph,rot; double eff; };
            vector<StripConfig> configs;
            {
                int w1=items[ti].w, h1=items[ti].h;
                if(w1<=W&&h1<=H){
                    int perRow=W/w1;
                    int rowsNeeded=(min(items[ti].limit-used[ti], perRow*(H-cy)/h1));
                    configs.push_back({w1,h1,0,(double)perRow*w1/W});
                }
                if(allow_rot&&w1!=h1&&h1<=W&&w1<=H){
                    int perRow=W/h1;
                    configs.push_back({h1,w1,1,(double)perRow*h1/W});
                }
            }
            // Sort configs by efficiency
            sort(configs.begin(),configs.end(),[](auto&a,auto&b){return a.eff>b.eff;});
            
            for(auto &cfg:configs){
                int pw=cfg.pw, ph=cfg.ph, rot=cfg.rot;
                if(pw>W||ph>H) continue;
                int perRow=W/pw;
                int gapW=W-perRow*pw;
                
                while(cy+ph<=H && used[ti]<items[ti].limit){
                    int cx=0;
                    bool any=false;
                    int placed_this_row=0;
                    while(cx+pw<=W && used[ti]<items[ti].limit){
                        pl.push_back({items[ti].type,cx,cy,rot});
                        val+=items[ti].v; used[ti]++; cx+=pw; any=true;
                        placed_this_row++;
                    }
                    if(!any) break;
                    // Fill gap on right side of this strip row with other items
                    if(fillGaps && gapW>0){
                        // Try to fit other items in gap [cx, cy, W-cx, ph]
                        int gx=cx, gw=W-cx, gh=ph;
                        for(auto &c2:allCands){
                            if(c2.pw<=gw && c2.ph<=gh && used[c2.ti]<items[c2.ti].limit){
                                // Pack greedily in this small rect
                                int lx=gx;
                                while(lx+c2.pw<=gx+gw && used[c2.ti]<items[c2.ti].limit){
                                    int ly=cy;
                                    while(ly+c2.ph<=cy+gh && used[c2.ti]<items[c2.ti].limit){
                                        pl.push_back({items[c2.ti].type,lx,ly,c2.rot});
                                        val+=items[c2.ti].v; used[c2.ti]++;
                                        ly+=c2.ph;
                                    }
                                    lx+=c2.pw;
                                }
                            }
                        }
                    }
                    cy+=ph;
                    if(used[ti]>=items[ti].limit) break;
                }
                if(used[ti]>=items[ti].limit) break;
            }
        }
        
        // Fill remaining with maxrects
        if(cy<H){
            MaxRects mr; mr.init(W,H-cy);
            auto order=allCands;
            sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
            for(auto &c:order){
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
    
    auto tryMixedStripV=[&](vector<int> &typeOrder, bool fillGaps) -> pair<long long, vector<Placement>> {
        vector<Placement> pl;
        long long val=0;
        vector<int> used(M,0);
        int cx=0;
        
        for(int ti:typeOrder){
            if(cx>=W) break;
            struct StripConfig { int pw,ph,rot; double eff; };
            vector<StripConfig> configs;
            {
                int w1=items[ti].w, h1=items[ti].h;
                if(w1<=W&&h1<=H){
                    int perCol=H/h1;
                    configs.push_back({w1,h1,0,(double)perCol*h1/H});
                }
                if(allow_rot&&w1!=h1&&h1<=W&&w1<=H){
                    int perCol=H/w1;
                    configs.push_back({h1,w1,1,(double)perCol*w1/H});
                }
            }
            sort(configs.begin(),configs.end(),[](auto&a,auto&b){return a.eff>b.eff;});
            
            for(auto &cfg:configs){
                int pw=cfg.pw, ph=cfg.ph, rot=cfg.rot;
                if(pw>W||ph>H) continue;
                
                while(cx+pw<=W && used[ti]<items[ti].limit){
                    int cy2=0; bool any=false;
                    while(cy2+ph<=H && used[ti]<items[ti].limit){
                        pl.push_back({items[ti].type,cx,cy2,rot});
                        val+=items[ti].v; used[ti]++; cy2+=ph; any=true;
                    }
                    if(!any) break;
                    // Fill gap
                    if(fillGaps && cy2<H){
                        int gx=cx, gy=cy2, gw=pw, gh=H-cy2;
                        for(auto &c2:allCands){
                            if(c2.pw<=gw && c2.ph<=gh && used[c2.ti]<items[c2.ti].limit){
                                int ly=gy;
                                while(ly+c2.ph<=gy+gh && used[c2.ti]<items[c2.ti].limit){
                                    int lx=gx;
                                    while(lx+c2.pw<=gx+gw && used[c2.ti]<items[c2.ti].limit){
                                        pl.push_back({items[c2.ti].type,lx,ly,c2.rot});
                                        val+=items[c2.ti].v; used[c2.ti]++;
                                        lx+=c2.pw;
                                    }
                                    ly+=c2.ph;
                                }
                            }
                        }
                    }
                    cx+=pw;
                    if(used[ti]>=items[ti].limit) break;
                }
                if(used[ti]>=items[ti].limit) break;
            }
        }
        
        if(cx<W){
            MaxRects mr; mr.init(W-cx,H);
            auto order=allCands;
            sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
            for(auto &c:order){
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
    
    // Sort candidates by density for gap filling
    sort(allCands.begin(),allCands.end(),[](auto&a,auto&b){return a.density>b.density;});
    
    // Basic strategies
    for(int h=0;h<5;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return a.density>b.density;});
        auto [v,p]=tryPack(order,h);
        updateBest(v,p);
    }
    for(int h=0;h<5;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[&](auto&a,auto&b){return items[a.ti].v>items[b.ti].v;});
        auto [v,p]=tryPack(order,h);
        updateBest(v,p);
    }
    for(int h=0;h<5;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return (long long)a.pw*a.ph>(long long)b.pw*b.ph;});
        auto [v,p]=tryPack(order,h);
        updateBest(v,p);
    }
    for(int h=0;h<5;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return max(a.pw,a.ph)>max(b.pw,b.ph);});
        auto [v,p]=tryPack(order,h);
        updateBest(v,p);
    }
    for(int h=0;h<5;h++){
        auto order=allCands;
        sort(order.begin(),order.end(),[](auto&a,auto&b){return a.ph>b.ph;});
        auto [v,p]=tryPack(order,h);
        updateBest(v,p);
    }
    
    // Greedy strategies
    for(int h=0;h<3&&elapsed()<150;h++){
        for(int s=0;s<3;s++){
            auto [v,p]=tryGreedy(h,s);
            updateBest(v,p);
        }
    }
    
    // Type permutation-based strip strategies
    {
        vector<int> to(M); iota(to.begin(),to.end(),0);
        sort(to.begin(),to.end(),[&](int a,int b){
            return (double)items[a].v/(items[a].w*items[a].h) > (double)items[b].v/(items[b].w*items[b].h);
        });
        
        // Try strip H
        for(int fg=0;fg<2;fg++){
            auto [v,p]=tryMixedStripH(to,fg);
            updateBest(v,p);
        }
        // Try strip V
        for(int fg=0;fg<2;fg++){
            auto [v,p]=tryMixedStripV(to,fg);
            updateBest(v,p);
        }
    }
    
    // Try all sub-permutations of top types for strip packing
    {
        vector<int> to(M); iota(to.begin(),to.end(),0);
        sort(to.begin(),to.end(),[&](int a,int b){
            return (double)items[a].v/(items[a].w*items[a].h) > (double)items[b].v/(items[b].w*items[b].h);
        });
        
        // For each prefix length k, try all permutations of top k, rest in density order
        for(int k=1;k<=min(M,6)&&elapsed()<400;k++){
            vector<int> perm(to.begin(),to.begin()+k);
            sort(perm.begin(),perm.end());
            do {
                if(elapsed()>400) break;
                vector<int> order=perm;
                for(int i=k;i<M;i++) order.push_back(to[i]);
                for(int fg=0;fg<2;fg++){
                    auto [v,p]=tryMixedStripH(order,fg);
                    updateBest(v,p);
                    auto [v2,p2]=tryMixedStripV(order,fg);
                    updateBest(v2,p2);
                }
            } while(next_permutation(perm.begin(),perm.end()));
        }
    }
    
    // Full maxrects on bin, place items one by one considering both orientations
    // with a scoring that combines placement quality and item value
    auto tryFullGreedy2=[&](double alpha, int heur) -> pair<long long, vector<Placement>> {
        MaxRects mr; mr.init(W,H);
        vector<int> used(M,0);
        vector<Placement> pl;
        long long val=0;
        while(true){
            int bestCI=-1; int bbx=0,bby=0;
            double bestScore=-1e18;
            long long bestFit1=LLONG_MAX, bestFit2=LLONG_MAX;
            for(int ci=0;ci<(int)allCands.size();ci++){
                auto &c=allCands[ci];
                if(used[c.ti]>=items[c.ti].limit) continue;
                // Find best position for this candidate
                long long fs1=LLONG_MAX,fs2=LLONG_MAX;
                int fx=-1,fy=-1;
                for(int i=0;i<(int)mr.fr.size();i++){
                    auto &r=mr.fr[i];
                    if(c.pw<=r[2]&&c.ph<=r[3]){
                        long long s1,s2;
                        switch(heur){
                            case 0: s1=min(r[2]-c.pw,r[3]-c.ph); s2=(long long)r[2]*r[3]; break;
                            case 1: s1=r[1]; s2=r[0]; break;
                            default: s1=(long long)r[2]*r[3]; s2=min(r[2]-c.pw,r[3]-c.ph); break;
                        }
                        if(s1<fs1||(s1==fs1&&s2<fs2)){
                            fs1=s1;fs2=s2;fx=r[0];fy=r[1];
                        }
                    }
                }
                if(fx<0) continue;
                // Score: combine density with fit quality
                double fitQuality = 1.0/(1.0+fs1);
                double score = alpha*c.density + (1.0-alpha)*fitQuality*c.density;
                if(score>bestScore){
                    bestScore=score; bestCI=ci; bbx=fx; bby=fy;
                    bestFit1=fs1; bestFit2=fs2;
                }
            }
            if(bestCI<0) break;
            auto &c=allCands[bestCI];
            mr.split(bbx,bby,c.pw,c.ph);
            pl.push_back({items[c.ti].type,bbx,bby,c.rot});
            val+=items[c.ti].v; used[c.ti]++;
        }
        return {val,pl};
    };
    
    for(int h=0;h<3&&elapsed()<500;h++){
        for(double alpha:{0.0,0.3,0.5,0.7,1.0}){
            auto [v,p]=tryFullGreedy2(alpha,h);
            updateBest(v,p);
        }
    }
    
    // Two-phase: for each type, compute best strip configuration (H or V, rot or not)
    // Then do knapsack-like allocation of bin height/width to strips
    auto tryKnapsackStrips=[&](bool horizontal) -> pair<long long, vector<Placement>> {
        // For each (type, rot) combo, compute: strip thickness, items per strip, value per strip
        struct StripInfo {
            int ti, rot, thick, pw, ph;
            int perStrip; // items per strip
            long long stripVal;
            double stripDensity;
        };
        vector<StripInfo> strips;
        for(int i=0;i<M;i++){
            for(int r=0;r<(allow_rot?2:1);r++){
                if(r==1 && items[i].w==items[i].h) continue;
                int pw=r?items[i].h:items[i].w;
                int ph=r?items[i].w:items[i].h;
                if(pw>W||ph>H) continue;
                if(horizontal){
                    int perRow=W/pw;
                    if(perRow<=0) continue;
                    strips.push_back({i,r,ph,pw,ph,perRow,(long long)perRow*items[i].v,
                        (double)items[i].v/(pw*ph)*(double)(perRow*pw)/W});
                } else {
                    int perCol=H/ph;
                    if(perCol<=0) continue
