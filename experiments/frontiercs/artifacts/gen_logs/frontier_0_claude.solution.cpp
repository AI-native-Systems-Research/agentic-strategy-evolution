#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n; cin>>n;
    vector<vector<pair<int,int>>> raw(n);
    int totalCells=0;
    for(int i=0;i<n;i++){
        int k; cin>>k;
        raw[i].resize(k);
        totalCells+=k;
        for(int j=0;j<k;j++) cin>>raw[i][j].first>>raw[i][j].second;
    }
    
    struct Ori { vector<pair<int,int>> cells; int f,r,w,h; };
    vector<vector<Ori>> allOri(n);
    
    for(int i=0;i<n;i++){
        set<vector<pair<int,int>>> seen;
        for(int ff=0;ff<2;ff++) for(int rr=0;rr<4;rr++){
            vector<pair<int,int>> res=raw[i];
            // reflect then rotate
            if(ff) for(auto&[x,y]:res) x=-x;
            for(int t=0;t<rr;t++) for(auto&[x,y]:res){int tmp=x;x=y;y=-tmp;}
            int mx=INT_MAX,my=INT_MAX;
            for(auto&[x,y]:res){mx=min(mx,x);my=min(my,y);}
            for(auto&[x,y]:res){x-=mx;y-=my;}
            sort(res.begin(),res.end());
            if(seen.insert(res).second){
                int mxv=0,myv=0;
                for(auto&[x,y]:res){mxv=max(mxv,x);myv=max(myv,y);}
                allOri[i].push_back({res,ff,rr,mxv+1,myv+1});
            }
        }
    }
    
    vector<int> order(n);
    iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){
        int sa=(int)raw[a].size(), sb=(int)raw[b].size();
        if(sa!=sb) return sa>sb;
        int ma=0,mb=0;
        for(auto&o:allOri[a]) ma=max(ma,max(o.w,o.h));
        for(auto&o:allOri[b]) mb=max(mb,max(o.w,o.h));
        return ma>mb;
    });
    
    int minW=1;
    for(int i=0;i<n;i++){
        int bw=INT_MAX;
        for(auto&o:allOri[i]) bw=min(bw,min(o.w,o.h));
        minW=max(minW,bw);
    }
    
    long long bestA=LLONG_MAX;
    int bestH=0,bestW=0;
    vector<tuple<int,int,int,int>> bestPlace;
    
    auto tryWidth=[&](int W) -> bool {
        int maxH = (totalCells + W - 1) / W + 300;
        if(maxH > 200000) maxH = 200000;
        vector<int> hmap(W, 0);
        // Use a set for occupied cells
        unordered_set<long long> occ;
        occ.reserve(totalCells*2);
        auto key=[&](int x,int y)->long long{ return (long long)x*200001+y; };
        
        vector<tuple<int,int,int,int>> place(n);
        int curH=0;
        
        for(int idx=0;idx<n;idx++){
            int i=order[idx];
            long long bsc=LLONG_MAX; int bx=-1,by=-1,boi=-1;
            
            for(int oi=0;oi<(int)allOri[i].size();oi++){
                auto&p=allOri[i][oi];
                if(p.w>W) continue;
                for(int x=0;x<=W-p.w;x++){
                    int miny=0;
                    for(auto&[cx,cy]:p.cells) miny=max(miny, hmap[x+cx]-cy);
                    if(miny<0) miny=0;
                    for(int y=miny; y<=miny+30 && y+p.h<=maxH; y++){
                        bool ok=true;
                        for(auto&[cx,cy]:p.cells) if(occ.count(key(x+cx,y+cy))){ok=false;break;}
                        if(!ok) continue;
                        int nh=max(curH, y+p.h);
                        long long sc=(long long)nh*1000000LL+(long long)(y+p.h)*1000LL+x;
                        if(sc<bsc){bsc=sc;bx=x;by=y;boi=oi;}
                        break;
                    }
                }
            }
            if(boi<0) return false;
            auto&p=allOri[i][boi];
            for(auto&[cx,cy]:p.cells){
                occ.insert(key(bx+cx,by+cy));
                hmap[bx+cx]=max(hmap[bx+cx], by+cy+1);
            }
            curH=max(curH, by+p.h);
            place[i]={bx,by,p.r,p.f};
        }
        long long A=(long long)W*curH;
        if(A<bestA||(A==bestA&&(curH<bestH||(curH==bestH&&W<bestW)))){
            bestA=A;bestH=curH;bestW=W;bestPlace=place;
        }
        return true;
    };
    
    int sq=max(minW,(int)ceil(sqrt((double)totalCells)));
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&]()->int{
        return (int)chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-t0).count();
    };
    
    tryWidth(sq);
    for(int d=1;d<=100 && elapsed()<8000;d++){
        if(sq+d>=minW && elapsed()<8000) tryWidth(sq+d);
        if(sq-d>=minW && elapsed()<8000) tryWidth(sq-d);
    }
    
    if(bestA==LLONG_MAX){
        for(int w=minW;w<=totalCells&&elapsed()<9000;w++) tryWidth(w);
    }
    
    cout<<bestW<<" "<<bestH<<"\n";
    for(int i=0;i<n;i++){
        auto[x,y,r,f]=bestPlace[i];
        cout<<x<<" "<<y<<" "<<r<<" "<<f<<"\n";
    }
}
