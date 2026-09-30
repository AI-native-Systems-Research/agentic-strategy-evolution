#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n; cin>>n;
    vector<int> ksz(n);
    vector<vector<pair<int,int>>> raw(n);
    int totalCells=0;
    for(int i=0;i<n;i++){
        cin>>ksz[i]; raw[i].resize(ksz[i]);
        for(int j=0;j<ksz[i];j++) cin>>raw[i][j].first>>raw[i][j].second;
        totalCells+=ksz[i];
    }
    
    // Generate all distinct orientations for piece i
    // Convention: flip f=1 means negate x, then rotate r times 90° CCW
    // Rotate CCW: (x,y) -> (-y, x)
    auto getOrients=[&](int i)->vector<tuple<vector<pair<int,int>>,int,int,int,int>>{
        vector<tuple<vector<pair<int,int>>,int,int,int,int>> res;
        set<vector<pair<int,int>>> seen;
        for(int f=0;f<2;f++) for(int r=0;r<4;r++){
            vector<pair<int,int>> cells;
            for(auto [x,y]:raw[i]){
                int tx=x,ty=y;
                if(f) tx=-tx;
                for(int rr=0;rr<r;rr++){int nx=-ty,ny=tx;tx=nx;ty=ny;}
                cells.push_back({tx,ty});
            }
            int mx=INT_MAX,my=INT_MAX;
            for(auto&[x,y]:cells){mx=min(mx,x);my=min(my,y);}
            for(auto&[x,y]:cells){x-=mx;y-=my;}
            sort(cells.begin(),cells.end());
            if(seen.insert(cells).second){
                int w=0,h=0;
                for(auto[x,y]:cells){w=max(w,x+1);h=max(h,y+1);}
                res.push_back({cells,w,h,r,f});
            }
        }
        return res;
    };
    
    vector<vector<tuple<vector<pair<int,int>>,int,int,int,int>>> orients(n);
    for(int i=0;i<n;i++) orients[i]=getOrients(i);
    
    vector<int> order(n); iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){return ksz[a]>ksz[b];});
    
    int bestArea=INT_MAX;
    vector<int> bx(n),by(n),br(n),bf(n);
    int bW=0,bH=0;
    int sq=max(1,(int)ceil(sqrt((double)totalCells)));
    
    auto t0=chrono::steady_clock::now();
    for(int W=max(1,sq/2);W<=min(totalCells,sq*4);W++){
        if(chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count()>8000) break;
        int MH=totalCells/max(1,W)+n*12+20;
        if((long long)W*MH>20000000LL) continue;
        vector<int16_t> grid(W*MH,0);
        vector<int> colH(W,0);
        int curH=0; bool ok=true;
        vector<int> px(n),py(n),pr(n),pf(n);
        for(int idx=0;idx<n;idx++){
            int i=order[idx]; int bs=INT_MAX,bxx=-1,byy=-1,boi=-1;
            for(int oi=0;oi<(int)orients[i].size();oi++){
                auto&[cells,w,h,rot,flip]=orients[i][oi];
                if(w>W) continue;
                for(int x=0;x<=W-w;x++){
                    int miny=0;
                    for(auto[cx,cy]:cells) miny=max(miny,colH[x+cx]-cy);
                    if(miny+h>MH) continue;
                    for(int y=miny;;y++){
                        if(y+h>MH) break;
                        bool fit=true;
                        for(auto[cx,cy]:cells) if(grid[(x+cx)*MH+(y+cy)]){fit=false;break;}
                        if(fit){
                            int nH=max(curH,y+h);
                            int sc=nH*100000+y*100+x;
                            if(sc<bs){bs=sc;bxx=x;byy=y;boi=oi;}
                            break;
                        }
                    }
                }
            }
            if(boi<0){ok=false;break;}
            auto&[cells,w,h,rot,flip]=orients[i][boi];
            px[i]=bxx;py[i]=byy;pr[i]=rot;pf[i]=flip;
            for(auto[cx,cy]:cells){
                grid[(bxx+cx)*MH+(byy+cy)]=1;
                colH[bxx+cx]=max(colH[bxx+cx],byy+cy+1);
                curH=max(curH,byy+cy+1);
            }
        }
        if(!ok) continue;
        int area=W*curH;
        if(area<bestArea){bestArea=area;bW=W;bH=curH;bx=px;by=py;br=pr;bf=pf;}
    }
    
    if(bestArea==INT_MAX){
        bW=totalCells;bH=1;
        int x=0;
        for(int i=0;i<n;i++){bx[i]=x;by[i]=0;br[i]=0;bf[i]=0;x+=ksz[i];}
        bH=1;bW=totalCells;
    }
    
    cout<<bW<<" "<<bH<<"\n";
    for(int i=0;i<n;i++) cout<<bx[i]<<" "<<by[i]<<" "<<br[i]<<" "<<bf[i]<<"\n";
}
