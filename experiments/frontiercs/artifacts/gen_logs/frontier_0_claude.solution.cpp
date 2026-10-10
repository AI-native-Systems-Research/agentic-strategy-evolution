#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n; cin>>n;
    vector<int> ks(n);
    vector<vector<pair<int,int>>> raw(n);
    int totalCells=0;
    for(int i=0;i<n;i++){
        cin>>ks[i]; raw[i].resize(ks[i]);
        for(int j=0;j<ks[i];j++) cin>>raw[i][j].first>>raw[i][j].second;
        totalCells+=ks[i];
    }
    
    auto normalize=[](vector<pair<int,int>> cs)->vector<pair<int,int>>{
        int mx=INT_MAX,my=INT_MAX;
        for(auto&c:cs) mx=min(mx,c.first),my=min(my,c.second);
        for(auto&c:cs) c.first-=mx,c.second-=my;
        sort(cs.begin(),cs.end());
        return cs;
    };
    
    auto getTransformed=[&](const vector<pair<int,int>>&cs,int f,int r)->vector<pair<int,int>>{
        vector<pair<int,int>> res=cs;
        if(f) for(auto&c:res) c.first=-c.first;
        for(int rr=0;rr<r;rr++) for(auto&c:res){int x=c.first,y=c.second;c.first=y;c.second=-x;}
        return normalize(res);
    };
    
    struct Orient{
        vector<pair<int,int>> cs;
        int r,f,w,h;
        vector<int> botProf, topProf;
    };
    
    vector<vector<Orient>> allOri(n);
    for(int i=0;i<n;i++){
        set<vector<pair<int,int>>> seen;
        for(int f=0;f<2;f++) for(int r=0;r<4;r++){
            auto t=getTransformed(raw[i],f,r);
            if(seen.count(t)) continue; seen.insert(t);
            int mw=0,mh=0;
            for(auto&c:t) mw=max(mw,c.first),mh=max(mh,c.second);
            Orient o;
            o.cs=t; o.r=r; o.f=f; o.w=mw+1; o.h=mh+1;
            o.botProf.assign(o.w, o.h);
            o.topProf.assign(o.w, 0);
            for(auto&c:t){
                o.botProf[c.first]=min(o.botProf[c.first],c.second);
                o.topProf[c.first]=max(o.topProf[c.first],c.second+1);
            }
            allOri[i].push_back(o);
        }
    }
    
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&]()->long long{return chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();};
    
    int sq=(int)ceil(sqrt((double)totalCells*1.02));
    
    long long bestArea=LLONG_MAX;
    int bestW=0,bestH=0;
    vector<tuple<int,int,int,int>> bestPl;
    
    // Sort pieces: larger first, then by max dimension
    vector<int> order(n);
    iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){
        if(ks[a]!=ks[b]) return ks[a]>ks[b];
        int ha=0,hb=0;
        for(auto&o:allOri[a]) ha=max(ha,max(o.h,o.w));
        for(auto&o:allOri[b]) hb=max(hb,max(o.h,o.w));
        return ha>hb;
    });
    
    auto tryPack=[&](int W) -> pair<int,vector<tuple<int,int,int,int>>>{
        int maxH = max(totalCells/max(W,1)+20, 20);
        maxH = max(maxH, 12);
        if(bestArea!=LLONG_MAX){
            int limH=(int)((bestArea-1)/W);
            if(limH<1) return{-1,{}};
            maxH=min(maxH,limH);
        }
        // Cap grid
        long long gs=(long long)W*maxH;
        if(gs>80000000LL){
            maxH=(int)(80000000LL/W);
            if(maxH<12) return{-1,{}};
        }
        
        vector<int> sky(W,0);
        // Use a grid for collision detection
        int allocH=maxH;
        vector<vector<bool>> grid(allocH, vector<bool>(W, false));
        
        vector<tuple<int,int,int,int>> pl(n);
        int curH=0;
        
        for(int idx=0;idx<n;idx++){
            int i=order[idx];
            int bx=-1,by=-1,boi=-1;
            long long bScore=LLONG_MAX;
            
            for(int oi=0;oi<(int)allOri[i].size();oi++){
                auto&o=allOri[i][oi];
                if(o.w>W) continue;
                
                for(int x=0;x<=W-o.w;x++){
                    int baseY=0;
                    for(int cx=0;cx<o.w;cx++){
                        if(o.topProf[cx]==0) continue;
                        int v=sky[x+cx]-o.botProf[cx];
                        if(v>baseY) baseY=v;
                    }
                    if(baseY<0) baseY=0;
                    
                    int tries=0;
                    for(int tryY=baseY; tryY+o.h<=allocH && tries<5; tryY++){
                        bool ok=true;
                        for(auto&c:o.cs){
                            int gy=tryY+c.second;
                            int gx=x+c.first;
                            if(grid[gy][gx]){ok=false;break;}
                        }
                        if(!ok){tries++;continue;}
                        
                        int topY=tryY+o.h;
                        int nH=max(curH,topY);
                        if((long long)W*nH>=bestArea) break;
                        long long sc=(long long)nH*1000000LL+(long long)topY*10000LL+x;
                        if(sc<bScore){bScore=sc;bx=x;by=tryY;boi=oi;}
                        break;
                    }
                    if(boi>=0 && by==baseY) break; // found perfect fit for this x, but keep trying other x
                }
            }
            if(boi<0) return{-1,{}};
            auto&o=allOri[i][boi];
            for(auto&c:o.cs){
                int gx=bx+c.first, gy=by+c.second;
                grid[gy][gx]=true;
                if(gy+1>sky[gx]) sky[gx]=gy+1;
            }
            pl[i]={bx,by,o.r,o.f};
            curH=max(curH,by+o.h);
        }
        return{curH,pl};
    };
    
    int lo=max(1,sq/3), hi=min(totalCells, sq*3+20);
    
    for(int w=max(1,sq-5);w<=hi&&elapsed()<8500;w++){
        auto[H,pl]=tryPack(w);
        if(H<0) continue;
        long long area=(long long)w*H;
        if(area<bestArea||(area==bestArea&&(H<bestH||(H==bestH&&w<bestW)))){
            bestArea=area;bestW=w;bestH=H;bestPl=pl;
        }
    }
    for(int w=max(1,sq-6);w>=lo&&elapsed()<8500;w--){
        auto[H,pl]=tryPack(w);
        if(H<0) continue;
        long long area=(long long)w*H;
        if(area<bestArea||(area==bestArea&&(H<bestH||(H==bestH&&w<bestW)))){
            bestArea=area;bestW=w;bestH=H;bestPl=pl;
        }
    }
    
    if(bestArea==LLONG_MAX){
        bestW=totalCells; bestH=11; bestPl.resize(n);
        int cx=0;
        for(int i=0;i<n;i++){auto&o=allOri[i][0];bestPl[i]={cx,0,o.r,o.f};cx+=o.w;bestW=max(bestW,cx);bestH=max(bestH,o.h);}
    }
    
    cout<<bestW<<" "<<bestH<<"\n";
    for(int i=0;i<n;i++){auto[x,y,r,f]=bestPl[i];cout<<x<<" "<<y<<" "<<r<<" "<<f<<"\n";}
}
