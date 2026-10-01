#include <bits/stdc++.h>
using namespace std;

static int n;
static int x_[200], y_[200];
static long long r_[200];
static int a_[200], b_[200], c_[200], d_[200];

static inline long long area(int i){ return (long long)(c_[i]-a_[i])*(d_[i]-b_[i]); }

static inline double score_i(int i){
    long long si = area(i);
    if(si<=0) return 0;
    if(x_[i]<a_[i]||x_[i]>=c_[i]||y_[i]<b_[i]||y_[i]>=d_[i]) return 0;
    double mn = min((double)r_[i],(double)si);
    double mx = max((double)r_[i],(double)si);
    double ratio = 1.0 - mn/mx;
    return 1.0 - ratio*ratio;
}

// Spatial grid for fast overlap queries
static const int GCELL = 100; // 100x100 grid cells
static const int GN = 10000/GCELL; // 100 cells per side
static vector<int> grid[GN][GN];

static void gridClear(){
    for(int gx=0;gx<GN;gx++) for(int gy=0;gy<GN;gy++) grid[gx][gy].clear();
}

static void gridAdd(int i){
    int gx1 = a_[i]/GCELL, gy1 = b_[i]/GCELL;
    int gx2 = (c_[i]-1)/GCELL, gy2 = (d_[i]-1)/GCELL;
    gx1=max(0,min(gx1,GN-1)); gy1=max(0,min(gy1,GN-1));
    gx2=max(0,min(gx2,GN-1)); gy2=max(0,min(gy2,GN-1));
    for(int gx=gx1;gx<=gx2;gx++)
        for(int gy=gy1;gy<=gy2;gy++)
            grid[gx][gy].push_back(i);
}

static void gridRemove(int i){
    int gx1 = a_[i]/GCELL, gy1 = b_[i]/GCELL;
    int gx2 = (c_[i]-1)/GCELL, gy2 = (d_[i]-1)/GCELL;
    gx1=max(0,min(gx1,GN-1)); gy1=max(0,min(gy1,GN-1));
    gx2=max(0,min(gx2,GN-1)); gy2=max(0,min(gy2,GN-1));
    for(int gx=gx1;gx<=gx2;gx++)
        for(int gy=gy1;gy<=gy2;gy++){
            auto &v = grid[gx][gy];
            v.erase(remove(v.begin(),v.end(),i),v.end());
        }
}

// Get candidates that might overlap with a given rect
static void getCandidates(int ra, int rb, int rc, int rd, int exclude, vector<int>& out){
    out.clear();
    int gx1=ra/GCELL, gy1=rb/GCELL;
    int gx2=(rc-1)/GCELL, gy2=(rd-1)/GCELL;
    gx1=max(0,min(gx1,GN-1)); gy1=max(0,min(gy1,GN-1));
    gx2=max(0,min(gx2,GN-1)); gy2=max(0,min(gy2,GN-1));
    static bool seen[200];
    // We'll use a generation counter instead
    for(int gx=gx1;gx<=gx2;gx++)
        for(int gy=gy1;gy<=gy2;gy++)
            for(int j:grid[gx][gy])
                if(j!=exclude) out.push_back(j);
    // deduplicate
    sort(out.begin(),out.end());
    out.erase(unique(out.begin(),out.end()),out.end());
}

static bool overlapsAny(int ra, int rb, int rc, int rd, int exclude){
    static vector<int> cands;
    getCandidates(ra,rb,rc,rd,exclude,cands);
    for(int j:cands){
        if(ra<c_[j]&&rc>a_[j]&&rb<d_[j]&&rd>b_[j]) return true;
    }
    return false;
}

// Max expand in direction dir without overlap
// dir: 0=left(a-), 1=up(b-), 2=right(c+), 3=down(d+)
static int maxExpand(int i, int dir){
    int limit;
    if(dir==0) limit=a_[i];
    else if(dir==1) limit=b_[i];
    else if(dir==2) limit=10000-c_[i];
    else limit=10000-d_[i];
    if(limit<=0) return 0;
    
    // Check neighbors
    static vector<int> cands;
    int ra,rb,rc,rd;
    if(dir==0){ ra=0; rb=b_[i]; rc=a_[i]; rd=d_[i]; }
    else if(dir==1){ ra=a_[i]; rb=0; rc=c_[i]; rd=b_[i]; }
    else if(dir==2){ ra=c_[i]; rb=b_[i]; rc=10000; rd=d_[i]; }
    else { ra=a_[i]; rb=d_[i]; rc=c_[i]; rd=10000; }
    
    getCandidates(ra,rb,rc,rd,i,cands);
    
    int hi=limit;
    for(int j:cands){
        if(dir==0||dir==2){
            if(b_[i]>=d_[j]||d_[i]<=b_[j]) continue;
            if(dir==0){
                if(c_[j]<=a_[i]) hi=min(hi,a_[i]-c_[j]);
            } else {
                if(a_[j]>=c_[i]) hi=min(hi,a_[j]-c_[i]);
            }
        } else {
            if(a_[i]>=c_[j]||c_[i]<=a_[j]) continue;
            if(dir==1){
                if(d_[j]<=b_[i]) hi=min(hi,b_[i]-d_[j]);
            } else {
                if(b_[j]>=d_[i]) hi=min(hi,b_[j]-d_[i]);
            }
        }
    }
    return max(hi,0);
}

// Find the neighbor rectangle in a given direction that is closest
// Returns -1 if none found; also returns the gap distance
static int findNeighbor(int i, int dir, int &gap){
    static vector<int> cands;
    int ra,rb,rc,rd;
    if(dir==0){ ra=max(0,a_[i]-500); rb=b_[i]; rc=a_[i]; rd=d_[i]; }
    else if(dir==1){ ra=a_[i]; rb=max(0,b_[i]-500); rc=c_[i]; rd=b_[i]; }
    else if(dir==2){ ra=c_[i]; rb=b_[i]; rc=min(10000,c_[i]+500); rd=d_[i]; }
    else { ra=a_[i]; rb=d_[i]; rc=c_[i]; rd=min(10000,d_[i]+500); }
    
    getCandidates(ra,rb,rc,rd,i,cands);
    
    int bestJ=-1, bestDist=INT_MAX;
    for(int j:cands){
        if(dir==0||dir==2){
            if(b_[i]>=d_[j]||d_[i]<=b_[j]) continue;
            int dist;
            if(dir==0){
                dist=a_[i]-c_[j]; if(dist<0) continue;
            } else {
                dist=a_[j]-c_[i]; if(dist<0) continue;
            }
            if(dist<bestDist){ bestDist=dist; bestJ=j; }
        } else {
            if(a_[i]>=c_[j]||c_[i]<=a_[j]) continue;
            int dist;
            if(dir==1){
                dist=b_[i]-d_[j]; if(dist<0) continue;
            } else {
                dist=b_[j]-d_[i]; if(dist<0) continue;
            }
            if(dist<bestDist){ bestDist=dist; bestJ=j; }
        }
    }
    gap=bestDist;
    return bestJ;
}

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    
    cin>>n;
    for(int i=0;i<n;i++) cin>>x_[i]>>y_[i]>>r_[i];
    
    // Guillotine-cut initialization
    struct Rect { int x1,y1,x2,y2; };
    
    function<void(vector<int>&, Rect)> partition = [&](vector<int>& ids, Rect bound){
        if(ids.size()==1){
            int i=ids[0];
            a_[i]=bound.x1; b_[i]=bound.y1; c_[i]=bound.x2; d_[i]=bound.y2;
            return;
        }
        if(ids.empty()) return;
        
        int W=bound.x2-bound.x1, H=bound.y2-bound.y1;
        long long totalR=0;
        for(int i:ids) totalR+=r_[i];
        
        auto trySplit=[&](bool horiz)->tuple<double,int,vector<int>,vector<int>>{
            vector<int> sorted_ids=ids;
            if(horiz) sort(sorted_ids.begin(),sorted_ids.end(),[&](int a,int b){return y_[a]<y_[b];});
            else sort(sorted_ids.begin(),sorted_ids.end(),[&](int a,int b){return x_[a]<x_[b];});
            
            double bestCost=1e18; int bestK=-1;
            long long cumR=0;
            
            for(int k=0;k<(int)sorted_ids.size()-1;k++){
                cumR+=r_[sorted_ids[k]];
                double frac=(double)cumR/totalR;
                int splitPos;
                if(horiz){
                    int lo=y_[sorted_ids[k]]+1, hi=y_[sorted_ids[k+1]];
                    if(lo>hi) continue;
                    splitPos=bound.y1+max(1,min((int)round(frac*H),H-1));
                    splitPos=max(splitPos,lo); splitPos=min(splitPos,hi);
                    if(splitPos<=bound.y1||splitPos>=bound.y2) continue;
                } else {
                    int lo=x_[sorted_ids[k]]+1, hi=x_[sorted_ids[k+1]];
                    if(lo>hi) continue;
                    splitPos=bound.x1+max(1,min((int)round(frac*W),W-1));
                    splitPos=max(splitPos,lo); splitPos=min(splitPos,hi);
                    if(splitPos<=bound.x1||splitPos>=bound.x2) continue;
                }
                double actualFrac;
                if(horiz) actualFrac=(double)(splitPos-bound.y1)/H;
                else actualFrac=(double)(splitPos-bound.x1)/W;
                double cost=(actualFrac-frac)*(actualFrac-frac);
                if(horiz){
                    double ar1=(double)W/max(1,splitPos-bound.y1);
                    double ar2=(double)W/max(1,bound.y2-splitPos);
                    cost+=0.001*(max(ar1,1.0/ar1)+max(ar2,1.0/ar2));
                } else {
                    double ar1=(double)(splitPos-bound.x1)/max(1,H);
                    double ar2=(double)(bound.x2-splitPos)/max(1,H);
                    cost+=0.001*(max(ar1,1.0/ar1)+max(ar2,1.0/ar2));
                }
                if(cost<bestCost){ bestCost=cost; bestK=k; }
            }
            if(bestK<0) return {1e18,0,{},{}};
            
            cumR=0;
            for(int k=0;k<=bestK;k++) cumR+=r_[sorted_ids[k]];
            double frac=(double)cumR/totalR;
            int splitPos;
            if(horiz){
                int lo=y_[sorted_ids[bestK]]+1, hi=y_[sorted_ids[bestK+1]];
                splitPos=bound.y1+max(1,min((int)round(frac*H),H-1));
                splitPos=max(splitPos,lo); splitPos=min(splitPos,hi);
            } else {
                int lo=x_[sorted_ids[bestK]]+1, hi=x_[sorted_ids[bestK+1]];
                splitPos=bound.x1+max(1,min((int)round(frac*W),W-1));
                splitPos=max(splitPos,lo); splitPos=min(splitPos,hi);
            }
            vector<int> left(sorted_ids.begin(),sorted_ids.begin()+bestK+1);
            vector<int> right(sorted_ids.begin()+bestK+1,sorted_ids.end());
            return {bestCost,splitPos,left,right};
        };
        
        auto [costH,splitH,leftH,rightH]=trySplit(true);
        auto [costV,splitV,leftV,rightV]=trySplit(false);
        
        if(costH>=1e17&&costV>=1e17){
            for(int i:ids){ a_[i]=x_[i]; b_[i]=y_[i]; c_[i]=x_[i]+1; d_[i]=y_[i]+1; }
            return;
        }
        if(costH<costV&&costH<1e17){
            Rect top={bound.x1,bound.y1,bound.x2,splitH};
            Rect bot={bound.x1,splitH,bound.x2,bound.y2};
            partition(leftH,top); partition(rightH,bot);
        } else {
            Rect lft={bound.x1,bound.y1,splitV,bound.y2};
            Rect rgt={splitV,bound.y1,bound.x2,bound.y2};
            partition(leftV,lft); partition(rightV,rgt);
        }
    };
    
    vector<int> allIds(n);
    iota(allIds.begin(),allIds.end(),0);
    partition(allIds,{0,0,10000,10000});
    
    // Fix containment
    for(int i=0;i<n;i++){
        if(x_[i]<a_[i]||x_[i]>=c_[i]||y_[i]<b_[i]||y_[i]>=d_[i]){
            a_[i]=x_[i]; b_[i]=y_[i]; c_[i]=x_[i]+1; d_[i]=y_[i]+1;
        }
    }
    
    auto startTime=chrono::steady_clock::now();
    auto elapsed=[&]()->double{
        return chrono::duration<double>(chrono::steady_clock::now()-startTime).count();
    };
    
    // Build grid
    gridClear();
    for(int i=0;i<n;i++) gridAdd(i);
    
    // Phase 1: Greedy expansion (multiple passes)
    for(int pass=0;pass<500&&elapsed()<1.5;pass++){
        vector<int> order(n);
        iota(order.begin(),order.end(),0);
        sort(order.begin(),order.end(),[&](int i,int j){ return score_i(i)<score_i(j); });
        
        bool changed=false;
        for(int idx=0;idx<n;idx++){
            int i=order[idx];
            long long target=r_[i];
            
            // Try all 4 directions, pick the best expansion
            for(int dir=0;dir<4;dir++){
                if(area(i)>=target) break;
                gridRemove(i);
                int mx=maxExpand(i,dir);
                if(mx<=0){ gridAdd(i); continue; }
                int perpLen=(dir==0||dir==2)?(d_[i]-b_[i]):(c_[i]-a_[i]);
                if(perpLen<=0){ gridAdd(i); continue; }
                long long need=target-area(i);
                int wantDelta=(int)min((long long)mx,(need+perpLen-1)/perpLen);
                wantDelta=max(1,min(wantDelta,mx));
                if(dir==0) a_[i]-=wantDelta;
                else if(dir==1) b_[i]-=wantDelta;
                else if(dir==2) c_[i]+=wantDelta;
                else d_[i]+=wantDelta;
                changed=true;
                gridAdd(i);
            }
        }
        if(!changed) break;
    }
    
    // Phase 2: Simulated Annealing with grid-based overlap checking
    mt19937 rng(12345);
    double timeLimit=4.7;
    double T0=0.05, Tend=0.0001;
    double saStart=elapsed();
    
    auto totalScore=[&]()->double{
        double s=0;
        for(int i=0;i<n;i++) s+=score_i(i);
        return s;
    };
    
    int accepted=0, tried=0;
    
    while(elapsed()<timeLimit){
        double t=elapsed();
        double frac=(t-saStart)/(timeLimit-saStart);
        frac=max(0.0,min(1.0,frac));
        double T=T0*pow(Tend/T0,frac);
        
        int moveType=rng()%100;
        
        if(moveType<60){
            // Single rectangle edge move
            int i=rng()%n;
            int dir=rng()%4;
            double oldS=score_i(i);
            int oa=a_[i],ob=b_[i],oc=c_[i],od=d_[i];
            
            bool expand=(area(i)<r_[i])?(rng()%100<80):(rng()%100<20);
            
            gridRemove(i);
            
            if(expand){
                int mx=maxExpand(i,dir);
                if(mx<=0){ gridAdd(i); tried++; continue; }
                int maxD=max(1,(int)(mx*(0.1+0.9*(1.0-frac))));
                int delta=1+rng()%maxD;
                if(dir==0) a_[i]-=delta; else if(dir==1) b_[i]-=delta;
                else if(dir==2) c_[i]+=delta; else d_[i]+=delta;
            } else {
                int maxShrink;
                if(dir==0) maxShrink=x_[i]-a_[i];
                else if(dir==1) maxShrink=y_[i]-b_[i];
                else if(dir==2) maxShrink=c_[i]-x_[i]-1;
                else maxShrink=d_[i]-y_[i]-1;
                if(maxShrink<=0){ gridAdd(i); tried++; continue; }
                int maxD=max(1,(int)(maxShrink*(0.1+0.9*(1.0-frac))));
                int delta=1+rng()%maxD;
                if(dir==0) a_[i]+=delta; else if(dir==1) b_[i]+=delta;
                else if(dir==2) c_[i]-=delta; else d_[i]-=delta;
            }
            
            if(a_[i]<0||b_[i]<0||c_[i]>10000||d_[i]>10000||a_[i]>=c_[i]||b_[i]>=d_[i]||
               x_[i]<a_[i]||x_[i]>=c_[i]||y_[i]<b_[i]||y_[i]>=d_[i]){
                a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;
                gridAdd(i); tried++; continue;
            }
            
            double newS=score_i(i);
            double diff=newS-oldS;
            tried++;
            if(diff>=0||(rng()%10000)/10000.0<exp(diff/T)){
                accepted++;
                gridAdd(i);
            } else {
                a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;
                gridAdd(i);
            }
        } else {
            // Coordinated boundary shift: shrink i on one side, expand neighbor j on same side
            int i=rng()%n;
            int dir=rng()%4; // direction to shrink i
            
            int maxShrink;
            if(dir==0) maxShrink=x_[i]-a_[i];
            else if(dir==1) maxShrink=y_[i]-b_[i];
            else if(dir==2) maxShrink=c_[i]-x_[i]-1;
            else maxShrink=d_[i]-y_[i]-1;
            if(maxShrink<=0){ tried++; continue; }
            
            // Find neighbor in opposite direction
            int oppDir=(dir<2)?dir+2:dir-2;
            int gap;
            int j=findNeighbor(i,dir,gap);
            if(j<0||gap>0){ tried++; continue; } // no adjacent neighbor
            
            double oldSi=score_i(i), oldSj=score_i(j);
            int oa=a_[i],ob=b_[i],oc=c_[i],od=d_[i];
            int oja=a_[j],ojb=b_[j],ojc=c_[j],ojd=d_[j];
            
            int maxD=max(1,(int)(maxShrink*(0.1+0.9*(1.0-frac))));
            int delta=1+rng()%maxD;
            
            // Also check j can expand by delta
            int jMaxExpand;
            if(dir==0){ // shrink i left -> i.a increases, j can expand right (j.c increases)
                // but we need j.c == a_[i] and j.c+delta <= new a_[i]
                // Actually: i shrinks from left: a_[i] += delta
                // j expands from right: c_[j] += delta (if j is to the left of i)
                // Check: c_[j] should equal a_[i]
                if(c_[j]!=a_[i]){ tried++; continue; }
                a_[i]+=delta; c_[j]+=delta;
            } else if(dir==1){
                if(d_[j]!=b_[i]){ tried++; continue; }
                b_[i]+=delta; d_[j]+=delta;
            } else if(dir==2){
                if(a_[j]!=c_[i]){ tried++; continue; }
                c_[i]-=delta; a_[j]-=delta;
            } else {
                if(b_[j]!=d_[i]){ tried++; continue; }
                d_[i]-=delta; b_[j]-=delta;
            }
            
            // Validate both
            bool valid=true;
            if(a_[i]>=c_[i]||b_[i]>=d_[i]) valid=false;
            if(a_[j]>=c_[j]||b_[j]>=d_[j]) valid=false;
            if(valid&&(x_[i]<a_[i]||x_[i]>=c_[i]||y_[i]<b_[i]||y_[i]>=d_[i])) valid=false;
            if(valid&&(x_[j]<a_[j]||x_[j]>=c_[j]||y_[j]<b_[j]||y_[j]>=d_[j])) valid=false;
            
            if(!valid){
                a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;
                a_[j]=oja;b_[j]=ojb;c_[j]=ojc;d_[j]=ojd;
                tried++; continue;
            }
            
            double newSi=score_i(i), newSj=score_i(j);
            double diff=(newSi+newSj)-(oldSi+oldSj);
            tried++;
            if(diff>=0||(rng()%10000)/10000.0<exp(diff/T)){
                accepted++;
                gridRemove(i); // remove old
                gridRemove(j);
                // Actually we need to remove before changing... let's rebuild
                // We already changed the coordinates, so we need to update grid
                // Remove entries with old coords - but we already changed them
                // Simplest: just rebuild grid periodically
                gridAdd(i);
                gridAdd(j);
            } else {
                a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;
                a_[j]=oja;b_[j]=ojb;c_[j]=ojc;d_[j]=ojd;
            }
        }
        
        // Rebuild grid periodically to fix stale entries
        if(tried%5000==0){
            gridClear();
            for(int i=0;i<n;i++) gridAdd(i);
        }
    }
    
    // Final greedy expansion pass
    gridClear();
    for(int i=0;i<n;i++) gridAdd(i);
    for(int pass=0;pass<100&&elapsed()<4.9;pass++){
        vector<int> order(n);
        iota(order.begin(),order.end(),0);
        sort(order.begin(),order.end(),[&](int i,int j){ return score_i(i)<score_i(j); });
        bool changed=false;
        for(int idx=0;idx<n;idx++){
            int i=order[idx];
            long long target=r_[i];
            if(area(i)>=target) continue;
            for(int dir=0;dir<4;dir++){
                if(area(i)>=target) break;
                gridRemove(i);
                int mx=maxExpand(i,dir);
                if(mx<=0){ gridAdd(i); continue; }
                int perpLen=(dir==0||dir==2)?(d_[i]-b_[i]):(c_[i]-a_[i]);
                if(perpLen<=0){ gridAdd(i); continue; }
                long long need=target-area(i);
                int wantDelta=(int)min((long long)mx,(need+perpLen-1)/perpLen);
                wantDelta=max(1,min(wantDelta,mx));
                if(dir==0) a_[i]-=wantDelta;
                else if(dir==1) b_[i]-=wantDelta;
                else if(dir==2) c_[i]+=wantDelta;
                else d_[i]+=wantDelta;
                changed=true;
                gridAdd(i);
            }
        }
        if(!changed) break;
    }
    
    for(int i=0;i<n;i++){
        printf("%d %d %d %d\n",a_[i],b_[i],c_[i],d_[i]);
    }
}
