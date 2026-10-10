#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    int n;
    cin >> n;
    
    struct PieceData {
        int k;
        vector<pair<int,int>> cells;
    };
    vector<PieceData> pieces(n);
    int totalCells = 0;
    for(int i=0;i<n;i++){
        cin >> pieces[i].k;
        pieces[i].cells.resize(pieces[i].k);
        for(int j=0;j<pieces[i].k;j++){
            cin >> pieces[i].cells[j].first >> pieces[i].cells[j].second;
        }
        totalCells += pieces[i].k;
    }
    
    // Precompute orientations for each piece
    struct OriInfo {
        vector<pair<int,int>> cells; // normalized, sorted
        int w, h;
        int f, r;
    };
    
    vector<vector<OriInfo>> allOris(n);
    for(int i=0;i<n;i++){
        set<vector<pair<int,int>>> seen;
        for(int f=0;f<2;f++){
            for(int r=0;r<4;r++){
                vector<pair<int,int>> tc;
                for(auto [x,y]:pieces[i].cells){
                    int nx=x, ny=y;
                    if(f) nx=-nx;
                    for(int q=0;q<r;q++){
                        int tmp=nx; nx=ny; ny=-tmp;
                    }
                    tc.push_back({nx,ny});
                }
                int minx=INT_MAX, miny=INT_MAX;
                for(auto [x,y]:tc){minx=min(minx,x);miny=min(miny,y);}
                for(auto&[x,y]:tc){x-=minx;y-=miny;}
                sort(tc.begin(),tc.end());
                if(seen.insert(tc).second){
                    int w=0,h=0;
                    for(auto[x,y]:tc){w=max(w,x+1);h=max(h,y+1);}
                    allOris[i].push_back({tc,w,h,f,r});
                }
            }
        }
    }
    
    // Sort pieces largest first
    vector<int> order(n);
    iota(order.begin(),order.end(),0);
    sort(order.begin(),order.end(),[&](int a,int b){
        return pieces[a].k > pieces[b].k;
    });
    
    auto startTime = chrono::steady_clock::now();
    auto elapsed = [&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    double sqrtArea = sqrt((double)totalCells*1.2);
    
    // Generate candidate widths
    vector<int> candidateW;
    for(double mult=0.6;mult<=2.5;mult+=0.15){
        int w=max(10,(int)(sqrtArea*mult));
        candidateW.push_back(w);
    }
    sort(candidateW.begin(),candidateW.end());
    candidateW.erase(unique(candidateW.begin(),candidateW.end()),candidateW.end());
    
    long long bestArea = (long long)4e18;
    int bestH=0, bestW=0;
    struct PR { int x,y,r,f; };
    vector<PR> bestPl(n);
    
    for(int W : candidateW){
        if(elapsed()>8.0 && bestArea<(long long)4e18) break;
        
        int maxH = (totalCells+W-1)/W + 20;
        // cap maxH to avoid memory issues
        maxH = min(maxH, totalCells+100);
        
        vector<vector<bool>> grid(W, vector<bool>(maxH, false));
        vector<int> hmap(W, 0);
        vector<PR> placements(n);
        int curMaxY=0;
        bool failed=false;
        
        for(int idx=0;idx<n&&!failed;idx++){
            int pi=order[idx];
            int bestScore=INT_MAX;
            int bx=-1,by=-1,boi=-1;
            
            for(int oi=0;oi<(int)allOris[pi].size();oi++){
                auto&ori=allOris[pi][oi];
                if(ori.w>W) continue;
                
                for(int x=0;x<=W-ori.w;x++){
                    int minY=0;
                    for(auto[cx,cy]:ori.cells){
                        minY=max(minY, hmap[x+cx]-cy);
                    }
                    
                    int topY=0;
                    for(auto[cx,cy]:ori.cells) topY=max(topY,minY+cy+1);
                    if(topY>maxH){continue;}
                    
                    bool ok=true;
                    for(auto[cx,cy]:ori.cells){
                        int py=minY+cy;
                        if(py<0||py>=maxH){ok=false;break;}
                        if(grid[x+cx][py]){ok=false;break;}
                    }
                    
                    if(ok){
                        int score=topY*10000+x;
                        if(score<bestScore){
                            bestScore=score;
                            bx=x;by=minY;boi=oi;
                        }
                        break; // take first valid x for this orientation (bottom-left)
                    }
                }
            }
            
            if(bx==-1){failed=true;break;}
            
            auto&ori=allOris[pi][boi];
            for(auto[cx,cy]:ori.cells){
                grid[bx+cx][by+cy]=true;
                hmap[bx+cx]=max(hmap[bx+cx],by+cy+1);
                curMaxY=max(curMaxY,by+cy+1);
            }
            placements[pi]={bx,by,ori.r,ori.f};
        }
        
        if(failed) continue;
        
        long long area=(long long)W*curMaxY;
        if(area<bestArea||(area==bestArea&&(curMaxY<bestH||(curMaxY==bestH&&W<bestW)))){
            bestArea=area;
            bestH=curMaxY;
            bestW=W;
            bestPl=placements;
        }
    }
    
    // Fallback: wide strip
    if(bestArea>=(long long)4e18){
        int W=totalCells;
        bestW=W; bestH=10;
        // Place each piece in a single row
        int cx=0;
        for(int i=0;i<n;i++){
            auto&ori=allOris[i][0];
            bestPl[i]={cx,0,ori.r,ori.f};
            cx+=ori.w;
        }
        bestW=cx;
        bestH=10; // max piece height
        int mh=0;
        for(int i=0;i<n;i++){
            auto&ori=allOris[i][0];
            mh=max(mh,ori.h);
        }
        bestH=mh;
    }
    
    cout<<bestW<<" "<<bestH<<"\n";
    for(int i=0;i<n;i++){
        cout<<bestPl[i].x<<" "<<bestPl[i].y<<" "<<bestPl[i].r<<" "<<bestPl[i].f<<"\n";
    }
    return 0;
}
