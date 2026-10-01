#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <algorithm>
#include <functional>
#include <cmath>
#include <climits>
#include <random>
#include <chrono>
#include <numeric>
using namespace std;

struct Item { string type; int w, h; long long v; int limit; double density; };
struct Rect { int x, y, w, h; };
struct PlaceItem { int typeIdx; int x, y, rot; };

struct MaxRectsBin {
    int binW, binH, nFree;
    Rect freeRects[600];
    void init(int W, int H) { binW=W; binH=H; nFree=1; freeRects[0]={0,0,W,H}; }
    struct FR { int px,py,rot; long long score; bool found; };
    FR findBest(int w, int h, bool allowRot, int method) const {
        FR best={-1,-1,0,LLONG_MAX,false};
        tryOri(w,h,0,method,best);
        if(allowRot&&w!=h) tryOri(h,w,1,method,best);
        return best;
    }
    void tryOri(int w, int h, int rot, int method, FR &best) const {
        for(int i=0;i<nFree;i++){
            const Rect&r=freeRects[i];
            if(w>r.w||h>r.h) continue;
            long long score;
            switch(method){
                case 0:{int s=min(r.h-h,r.w-w),l=max(r.h-h,r.w-w);score=(long long)s*100000+l;}break;
                case 1:{score=(long long)(r.w*r.h-w*h)*100000+min(r.h-h,r.w-w);}break;
                case 2:{score=(long long)r.y*100000+r.x;}break;
                case 3:{int c=0;if(r.x==0)c+=h;if(r.y==0)c+=w;if(r.x+w==binW)c+=h;if(r.y+h==binH)c+=w;
                    score=(long long)(10000-c)*1000000LL+(long long)r.y*1000+r.x;}break;
                default:{score=(long long)r.y*10000000LL+(long long)r.x*10000+min(r.h-h,r.w-w);}break;
            }
            if(score<best.score) best={r.x,r.y,rot,score,true};
        }
    }
    void place(int x,int y,int w,int h){
        Rect used={x,y,w,h};
        int origN=nFree;
        for(int i=origN-1;i>=0;i--){
            Rect&r=freeRects[i];
            if(used.x>=r.x+r.w||used.x+used.w<=r.x||used.y>=r.y+r.h||used.y+used.h<=r.y) continue;
            Rect o=r; freeRects[i]=freeRects[--nFree];
            if(used.x>o.x&&nFree<598) freeRects[nFree++]={o.x,o.y,used.x-o.x,o.h};
            if(used.x+used.w<o.x+o.w&&nFree<598) freeRects[nFree++]={used.x+used.w,o.y,o.x+o.w-used.x-used.w,o.h};
            if(used.y>o.y&&nFree<598) freeRects[nFree++]={o.x,o.y,o.w,used.y-o.y};
            if(used.y+used.h<o.y+o.h&&nFree<598) freeRects[nFree++]={o.x,used.y+used.h,o.w,o.y+o.h-used.y-used.h};
        }
        for(int i=nFree-1;i>=0;i--){
            for(int j=nFree-1;j>=0;j--){
                if(i==j||i>=nFree)continue;
                if(freeRects[i].x>=freeRects[j].x&&freeRects[i].y>=freeRects[j].y&&
                   freeRects[i].x+freeRects[i].w<=freeRects[j].x+freeRects[j].w&&
                   freeRects[i].y+freeRects[i].h<=freeRects[j].y+freeRects[j].h){
                    freeRects[i]=freeRects[--nFree];break;
                }
            }
        }
        if(nFree>500){sort(freeRects,freeRects+nFree,[](const Rect&a,const Rect&b){return(long long)a.w*a.h>(long long)b.w*b.h;});nFree=500;}
    }
};

struct PackResult { vector<PlaceItem> pl; long long profit; };

PackResult greedyPackMixed(int W,int H,bool allowRot,const vector<Item>&items,
                            const vector<int>&typeOrder,const vector<int>&mpt,bool transposed){
    int bW=transposed?H:W,bH=transposed?W:H;
    MaxRectsBin bin;bin.init(bW,bH);
    PackResult res;res.profit=0;
    int M=items.size();
    vector<int>used(M,0);
    for(int ti:typeOrder){
        const auto&it=items[ti];
        int iw=transposed?it.h:it.w,ih=transposed?it.w:it.h;
        int method=mpt[ti];
        while(used[ti]<it.limit){
            auto fr=bin.findBest(iw,ih,allowRot,method);
            if(!fr.found)break;
            int pw=(fr.rot==1)?ih:iw,ph=(fr.rot==1)?iw:ih;
            bin.place(fr.px,fr.py,pw,ph);
            if(transposed)res.pl.push_back({ti,fr.py,fr.px,fr.rot});
            else res.pl.push_back({ti,fr.px,fr.py,fr.rot});
            res.profit+=it.v;used[ti]++;
        }
    }
    return res;
}

int main(){
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};

    string input;{ostringstream o;o<<cin.rdbuf();input=o.str();}
    auto fI=[&](const string&s,const string&key)->long long{
        string k="\""+key+"\"";size_t p=s.find(k);if(p==string::npos)return 0;
        p=s.find(':',p)+1;while(p<s.size()&&isspace(s[p]))p++;
        long long v=0;bool neg=false;if(s[p]=='-'){neg=true;p++;}
        while(p<s.size()&&isdigit(s[p])){v=v*10+(s[p]-'0');p++;}return neg?-v:v;
    };
    auto fB=[&](const string&s,const string&key)->bool{
        size_t p=s.find("\""+key+"\"");if(p==string::npos)return false;
        p=s.find(':',p)+1;while(p<s.size()&&isspace(s[p]))p++;return s.substr(p,4)=="true";
    };
    auto fS=[&](const string&s,const string&key)->string{
        size_t p=s.find("\""+key+"\"");if(p==string::npos)return"";
        p=s.find(':',p)+1;while(p<s.size()&&isspace(s[p]))p++;
        if(s[p]!='"')return"";p++;string r;while(p<s.size()&&s[p]!='"')r+=s[p++];return r;
    };

    int W=(int)fI(input,"W"),H=(int)fI(input,"H");
    bool allowRot=fB(input,"allow_rotate");

    vector<Item>items;
    size_t ip=input.find("\"items\""),as=input.find('[',ip);
    int d=0;size_t ae=as;
    for(size_t i=as;i<input.size();i++){if(input[i]=='[')d++;if(input[i]==']'){d--;if(!d){ae=i;break;}}}
    size_t pos=as;
    while(true){
        size_t os=input.find('{',pos+1);if(os==string::npos||os>ae)break;
        size_t oe=input.find('}',os);if(oe==string::npos)break;
        string obj=input.substr(os,oe-os+1);
        Item it;it.type=fS(obj,"type");
        if(it.type.empty()){pos=oe;continue;}
        it.w=(int)fI(obj,"w");it.h=(int)fI(obj,"h");
        it.v=fI(obj,"v");it.limit=(int)fI(obj,"limit");
        it.density=(double)it.v/((double)it.w*it.h);
        items.push_back(it);pos=oe;
    }
    int M=items.size();
    if(!M){cout<<"{\"placements\":[]}"<<endl;return 0;}

    vector<PlaceItem>best;long long bestP=-1;
    vector<int>bestOrder(M);iota(bestOrder.begin(),bestOrder.end(),0);
    vector<int>bestMPT(M,0);
    bool bestTrans=false;

    auto tryR=[&](PackResult&r,const vector<int>&ord,const vector<int>&mpt,bool trans){
        if(r.profit>bestP){bestP=r.profit;best=move(r.pl);bestOrder=ord;bestMPT=mpt;bestTrans=trans;}
    };
    auto mkOrd=[&](function<bool(int,int)>cmp){
        vector<int>o(M);iota(o.begin(),o.end(),0);sort(o.begin(),o.end(),cmp);return o;
    };

    int nM=5;
    vector<function<bool(int,int)>>cmps={
        [&](int a,int b){return items[a].density>items[b].density;},
        [&](int a,int b){return items[a].v>items[b].v;},
        [&](int a,int b){return(long long)items[a].w*items[a].h>(long long)items[b].w*items[b].h;},
        [&](int a,int b){return max(items[a].w,items[a].h)>max(items[b].w,items[b].h);},
        [&](int a,int b){return items[a].v*(long long)items[a].limit>items[b].v*(long long)items[b].limit;},
        [&](int a,int b){return items[a].w+items[a].h>items[b].w+items[b].h;},
        [&](int a,int b){return items[a].density*items[a].limit>items[b].density*items[b].limit;},
        [&](int a,int b){return(double)items[a].v/max(items[a].w,items[a].h)>(double)items[b].v/max(items[b].w,items[b].h);},
        [&](int a,int b){return min(items[a].w,items[a].h)>min(items[b].w,items[b].h);},
        [&](int a,int b){
            double ra=(double)max(items[a].w,items[a].h)/min(items[a].w,items[a].h);
            double rb=(double)max(items[b].w,items[b].h)/min(items[b].w,items[b].h);
            return ra>rb;},
    };

    // Phase 1: Deterministic — all ordering × method combos (uniform mpt)
    for(auto&c:cmps){
        auto o=mkOrd(c);
        for(int m=0;m<nM;m++){
            vector<int>mpt(M,m);
            auto r=greedyPackMixed(W,H,allowRot,items,o,mpt,false);tryR(r,o,mpt,false);
            auto r2=greedyPackMixed(W,H,allowRot,items,o,mpt,true);tryR(r2,o,mpt,true);
        }
    }

    // Phase 2: Local search — swap orderings AND methods
    for(int pass=0;pass<3&&elapsed()<0.22;pass++){
        bool imp=false;
        // Ordering swaps
        for(int i=0;i<M&&elapsed()<0.18;i++){
            for(int j=i+1;j<M&&elapsed()<0.18;j++){
                vector<int>o=bestOrder;swap(o[i],o[j]);
                auto r=greedyPackMixed(W,H,allowRot,items,o,bestMPT,bestTrans);
                long long old=bestP;tryR(r,o,bestMPT,bestTrans);
                if(bestP>old)imp=true;
            }
        }
        // Method changes per type
        for(int ti=0;ti<M&&elapsed()<0.22;ti++){
            for(int m=0;m<nM;m++){
                if(m==bestMPT[ti])continue;
                vector<int>mpt=bestMPT;mpt[ti]=m;
                auto r=greedyPackMixed(W,H,allowRot,items,bestOrder,mpt,bestTrans);
                long long old=bestP;tryR(r,bestOrder,mpt,bestTrans);
                if(bestP>old)imp=true;
            }
        }
        if(!imp)break;
    }

    // Phase 3: Random search — evolve both ordering and method-per-type
    mt19937 rng(42);
    struct Elite{vector<int>order;vector<int>mpt;long long profit;bool trans;};
    vector<Elite>elites;
    elites.push_back({bestOrder,bestMPT,bestP,bestTrans});

    while(elapsed()<0.84){
        vector<int>o(M);iota(o.begin(),o.end(),0);
        vector<int>mpt(M);
        int s=rng()%12;

        if(s==0){
            shuffle(o.begin(),o.end(),rng);
            for(int i=0;i<M;i++)mpt[i]=rng()%nM;
        } else if(s==1){
            vector<pair<double,int>>sc(M);
            for(int i=0;i<M;i++)sc[i]={items[i].density*exp(uniform_real_distribution<>(-3.0,3.0)(rng)),i};
            sort(sc.rbegin(),sc.rend());for(int i=0;i<M;i++)o[i]=sc[i].second;
            mpt=bestMPT; // keep best methods
        } else if(s==2||s==3){
            o=bestOrder;swap(o[rng()%M],o[rng()%M]);
            mpt=bestMPT;
            // Also mutate 1-2 methods
            int nm=1+rng()%2;for(int k=0;k<nm;k++)mpt[rng()%M]=rng()%nM;
        } else if(s==4){
            vector<pair<double,int>>sc(M);
            for(int i=0;i<M;i++)sc[i]={items[i].v*(double)items[i].limit*exp(uniform_real_distribution<>(-2.0,2.0)(rng)),i};
            sort(sc.rbegin(),sc.rend());for(int i=0;i<M;i++)o[i]=sc[i].second;
            mpt=bestMPT;
        } else if(s==5){
            o=bestOrder;int from=rng()%M,val=o[from];
            o.erase(o.begin()+from);o.insert(o.begin()+(rng()%M),val);
            mpt=bestMPT;
        } else if(s==6){
            int ei=rng()%(int)elites.size();
            o=elites[ei].order;mpt=elites[ei].mpt;
            int ns=1+rng()%3;for(int k=0;k<ns;k++)swap(o[rng()%M],o[rng()%M]);
            if(rng()%2)mpt[rng()%M]=rng()%nM;
        } else if(s==7){
            vector<pair<double,int>>sc(M);
            for(int i=0;i<M;i++)sc[i]={items[i].density*items[i].limit*exp(uniform_real_distribution<>(-2.5,2.5)(rng)),i};
            sort(sc.rbegin(),sc.rend());for(int i=0;i<M;i++)o[i]=sc[i].second;
            for(int i=0;i<M;i++)mpt[i]=rng()%nM;
        } else if(s==8){
            // Crossover ordering, keep best mpt
            int ei=rng()%(int)elites.size();o=bestOrder;mpt=bestMPT;
            int cut=1+rng()%(M-1);vector<bool>placed(M,false);
            for(int i=0;i<cut;i++)placed[o[i]]=true;
            int p2=cut;for(int ti:elites[ei].order)if(!placed[ti]){o[p2++]=ti;placed[ti]=true;}
        } else if(s==9){
            // Keep best order, randomize all methods
            o=bestOrder;
            for(int i=0;i<M;i++)mpt[i]=rng()%nM;
        } else if(s==10){
            // Keep best order, mutate just one method
            o=bestOrder;mpt=bestMPT;
            mpt[rng()%M]=rng()%nM;
        } else {
            o=bestOrder;mpt=bestMPT;
            int i=rng()%M,j=rng()%M;if(i>j)swap(i,j);
            if(j-i>=2)reverse(o.begin()+i,o.begin()+j+1);else swap(o[i],o[j]);
        }

        bool trans=(rng()%4==0);
        auto r=greedyPackMixed(W,H,allowRot,items,o,mpt,trans);
        tryR(r,o,mpt,trans);

        if(r.profit>0){
            if((int)elites.size()<8)elites.push_back({o,mpt,r.profit,trans});
            else{
                int worst=0;for(int i=1;i<(int)elites.size();i++)if(elites[i].profit<elites[worst].profit)worst=i;
                if(r.profit>elites[worst].profit)elites[worst]={o,mpt,r.profit,trans};
            }
        }
    }

    // Phase 4: Gap-fill
    if(elapsed()<0.92){
        int bW=bestTrans?H:W,bH=bestTrans?W:H;
        MaxRectsBin bin;bin.init(bW,bH);
        PackResult res;res.profit=0;
        vector<int>used(M,0);
        for(int ti:bestOrder){
            const auto&it=items[ti];
            int iw=bestTrans?it.h:it.w,ih=bestTrans?it.w:it.h;
            while(used[ti]<it.limit){
                auto fr=bin.findBest(iw,ih,allowRot,bestMPT[ti]);
                if(!fr.found)break;
                int pw=(fr.rot==1)?ih:iw,ph=(fr.rot==1)?iw:ih;
                bin.place(fr.px,fr.py,pw,ph);
                if(bestTrans)res.pl.push_back({ti,fr.py,fr.px,fr.rot});
                else res.pl.push_back({ti,fr.px,fr.py,fr.rot});
                res.profit+=it.v;used[ti]++;
            }
        }
        // Gap fill by density
        vector<int>byDen(M);iota(byDen.begin(),byDen.end(),0);
        sort(byDen.begin(),byDen.end(),[&](int a,int b){return items[a].density>items[b].density;});
        bool found=true;int att=0;
        while(found&&att<100&&elapsed()<0.96){
            found=false;
            for(int ti:byDen){
                if(used[ti]>=items[ti].limit)continue;
                const auto&it=items[ti];
                int iw=bestTrans?it.h:it.w,ih=bestTrans?it.w:it.h;
                while(used[ti]<it.limit&&att<100){
                    auto fr=bin.findBest(iw,ih,allowRot,0);
                    if(!fr.found)break;
                    int pw=(fr.rot==1)?ih:iw,ph=(fr.rot==1)?iw:ih;
                    bin.place(fr.px,fr.py,pw,ph);
                    if(bestTrans)res.pl.push_back({ti,fr.py,fr.px,fr.rot});
                    else res.pl.push_back({ti,fr.px,fr.py,fr.rot});
                    res.profit+=it.v;used[ti]++;found=true;att++;
                }
            }
        }
        if(res.profit>bestP){bestP=res.profit;best=move(res.pl);}
    }

    cout<<"{\"placements\":[";
    for(int i=0;i<(int)best.size();i++){
        if(i)cout<<",";
        cout<<"{\"type\":\""<<items[best[i].typeIdx].type<<"\",\"x\":"<<best[i].x
            <<",\"y\":"<<best[i].y<<",\"rot\":"<<best[i].rot<<"}";
    }
    cout<<"]}"<<endl;
}
