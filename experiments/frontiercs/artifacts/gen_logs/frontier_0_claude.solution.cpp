#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n; cin>>n;
    vector<vector<pair<int,int>>> pieces(n);
    int totalCells=0;
    for(int i=0;i<n;i++){
        int k; cin>>k;
        pieces[i].resize(k);
        for(int j=0;j<k;j++) cin>>pieces[i][j].first>>pieces[i][j].second;
        totalCells+=k;
    }
    
    auto normalize=[](vector<pair<int,int>>& p){
        int mx=INT_MAX,my=INT_MAX;
        for(auto&c:p){mx=min(mx,c.first);my=min(my,c.second);}
        for(auto&c:p){c.first-=mx;c.second-=my;}
        sort(p.begin(),p.end());
    };
    
    struct Orient{ vector<pair<int,int>> cells; int f,r,w,h; };
    vector<vector<Orient>> orients(n);
    for(int i=0;i<n;i++){
        set<vector<pair<int,int>>> seen;
        for(int f=0;f<2;f++) for(int r=0;r<4;r++){
            vector<pair<int,int>> t=pieces[i];
            if(f) for(auto&c:t) c.first=-c.first;
            for(int rr=0;rr<r;rr++) for(auto&c:t){int x=c.first,y=c.second;c.first=y;c.second=-x;}
            normalize(t);
            if(!seen.count(t)){seen.insert(t);orients[i].push_back({t,f,r,0,0});}
        }
        for(auto&o:orients[i]){int mw=0,mh=0;for(auto&c:o.cells){mw=max(mw,c.first);mh=max(mh,c.second);}o.w=mw+1;o.h=mh+1;}
    }
    
    vector<int> idx(n); iota(idx.begin(),idx.end(),0);
    sort(idx.begin(),idx.end(),[&](int a,int b){
        int ha=0,hb=0;
        for(auto&o:orients[a]) ha=max(ha,(int)o.cells.size());
        for(auto&o:orients[b]) hb=max(hb,(int)o.cells.size());
        if(ha!=hb) return ha>hb;
        return a<b;
    });
    
    long long bestArea=LLONG_MAX; int bestW=0,bestH=0;
    vector<tuple<int,int,int,int>> bestPlace(n);
    
    int side=(int)ceil(sqrt(totalCells*1.05));
    
    auto tryWidth=[&](int W){
        int maxH=(bestArea==LLONG_MAX)?(totalCells/W+10):((int)((bestArea-1)/W));
        if(maxH<1) return;
        maxH=min(maxH, totalCells);
        vector<int> colH(W,0);
        vector<vector<bool>> grid(maxH+11, vector<bool>(W,false));
        vector<tuple<int,int,int,int>> place(n);
        int usedH=0; bool ok=true;
        for(int ii=0;ii<n&&ok;ii++){
            int i=idx[ii]; int bscore=INT_MAX; int bx=-1,by=-1,bo=-1;
            for(int oi=0;oi<(int)orients[i].size();oi++){
                auto&o=orients[i][oi];
                if(o.w>W) continue;
                for(int x=0;x<=W-o.w;x++){
                    int minY=0;
                    for(auto&c:o.cells) minY=max(minY,colH[x+c.first]-c.second);
                    if(minY+o.h>maxH) continue;
                    bool fit=true;
                    for(auto&c:o.cells){if(grid[minY+c.second][x+c.first]){fit=false;break;}}
                    if(!fit) continue;
                    int nH=max(usedH,minY+o.h);
                    int sc=nH*10000+minY*100+x;
                    if(sc<bscore){bscore=sc;bx=x;by=minY;bo=oi;}
                }
            }
            if(bo<0){ok=false;break;}
            auto&o=orients[i][bo];
            for(auto&c:o.cells){grid[by+c.second][bx+c.first]=true;colH[bx+c.first]=max(colH[bx+c.first],by+c.second+1);}
            place[i]={bx,by,o.r,o.f};
            usedH=max(usedH,by+o.h);
        }
        if(ok&&(long long)W*usedH<bestArea){bestArea=(long long)W*usedH;bestW=W;bestH=usedH;bestPlace=place;}
    };
    
    for(int W=max(1,side-20);W<=side+40&&W<=totalCells;W++) tryWidth(W);
    
    if(bestArea==LLONG_MAX){
        bestW=totalCells; bestH=1;
        // fallback: place in a line
        int cx=0;
        for(int i=0;i<n;i++){
            auto&o=orients[i][0];
            bestPlace[i]={cx,0,o.r,o.f};
            cx+=o.w;
        }
        bestW=cx; bestH=1;
        for(int i=0;i<n;i++){auto&o=orients[i][0]; for(auto&c:o.cells) bestH=max(bestH,c.second+1);}
        // Actually just do it properly
        bestH=11; bestW=totalCells;
        int x2=0;
        for(int ii=0;ii<n;ii++){
            int i=idx[ii];
            bestPlace[i]={x2,0,orients[i][0].r,orients[i][0].f};
            x2+=orients[i][0].w;
        }
        bestW=x2;
    }
    
    cout<<bestW<<" "<<bestH<<"\n";
    for(int i=0;i<n;i++){auto[x,y,r,f]=bestPlace[i];cout<<x<<" "<<y<<" "<<r<<" "<<f<<"\n";}
}
