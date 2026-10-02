#include<bits/stdc++.h>
using namespace std;

int n;
int X[205],Y[205];
long long R[205];
int A[205],B[205],C[205],D[205];
int BA[205],BB[205],BC[205],BD[205];

double calcScore(int i){
    long long si=(long long)(C[i]-A[i])*(D[i]-B[i]);
    if(si<=0)return 0;
    if(!(A[i]<=X[i]&&X[i]<C[i]&&B[i]<=Y[i]&&Y[i]<D[i]))return 0;
    double ratio=(double)min(R[i],si)/(double)max(R[i],si);
    return 1.0-(1.0-ratio)*(1.0-ratio);
}

void doPartition(vector<int>&pts,int x1,int y1,int x2,int y2){
    if(pts.size()==1){A[pts[0]]=x1;B[pts[0]]=y1;C[pts[0]]=x2;D[pts[0]]=y2;return;}
    if(pts.empty())return;
    long long totalR=0;for(int i:pts)totalR+=R[i];
    int w=x2-x1,h=y2-y1;
    double bestCost=1e18;int bestK=-1;bool bestHoriz=true;vector<int>bestOrder;
    for(int horiz=0;horiz<2;horiz++){
        vector<int>sp=pts;
        if(horiz)sort(sp.begin(),sp.end(),[](int a,int b){return X[a]<X[b];});
        else sort(sp.begin(),sp.end(),[](int a,int b){return Y[a]<Y[b];});
        long long cumR=0;
        for(int k=1;k<(int)sp.size();k++){
            cumR+=R[sp[k-1]];
            double frac=(double)cumR/totalR;
            if(horiz){
                int mx=-1,mn=10001;
                for(int j=0;j<k;j++)mx=max(mx,X[sp[j]]+1);
                for(int j=k;j<(int)sp.size();j++)mn=min(mn,X[sp[j]]);
                if(mx>mn)continue;
                int splitX=x1+(int)(frac*(x2-x1)+0.5);
                splitX=max(splitX,max(x1+1,mx));splitX=min(splitX,min(x2-1,mn));
                if(splitX<=x1||splitX>=x2)continue;
                double af=(double)(splitX-x1)/(x2-x1);
                double cost=abs(frac-af);
                if(cost<bestCost){bestCost=cost;bestK=k;bestHoriz=true;bestOrder=sp;}
            }else{
                int mx=-1,mn=10001;
                for(int j=0;j<k;j++)mx=max(mx,Y[sp[j]]+1);
                for(int j=k;j<(int)sp.size();j++)mn=min(mn,Y[sp[j]]);
                if(mx>mn)continue;
                int splitY=y1+(int)(frac*(y2-y1)+0.5);
                splitY=max(splitY,max(y1+1,mx));splitY=min(splitY,min(y2-1,mn));
                if(splitY<=y1||splitY>=y2)continue;
                double af=(double)(splitY-y1)/(y2-y1);
                double cost=abs(frac-af);
                if(cost<bestCost){bestCost=cost;bestK=k;bestHoriz=false;bestOrder=sp;}
            }
        }
    }
    if(bestK<0){
        bestK=(int)pts.size()/2;bestHoriz=(w>=h);bestOrder=pts;
        if(bestHoriz)sort(bestOrder.begin(),bestOrder.end(),[](int a,int b){return X[a]<X[b];});
        else sort(bestOrder.begin(),bestOrder.end(),[](int a,int b){return Y[a]<Y[b];});
    }
    pts=bestOrder;long long cumR=0;for(int k=0;k<bestK;k++)cumR+=R[pts[k]];
    double frac=(double)cumR/totalR;
    vector<int>le(pts.begin(),pts.begin()+bestK),ri(pts.begin()+bestK,pts.end());
    if(bestHoriz){
        int s=x1+(int)(frac*(x2-x1)+0.5);
        int mx=-1,mn=10001;
        for(int i:le)mx=max(mx,X[i]+1);for(int i:ri)mn=min(mn,X[i]);
        s=max(s,max(x1+1,mx));s=min(s,min(x2-1,mn));s=max(x1+1,min(x2-1,s));
        doPartition(le,x1,y1,s,y2);doPartition(ri,s,y1,x2,y2);
    }else{
        int s=y1+(int)(frac*(y2-y1)+0.5);
        int mx=-1,mn=10001;
        for(int i:le)mx=max(mx,Y[i]+1);for(int i:ri)mn=min(mn,Y[i]);
        s=max(s,max(y1+1,mx));s=min(s,min(y2-1,mn));s=max(y1+1,min(y2-1,s));
        doPartition(le,x1,y1,x2,s);doPartition(ri,x1,s,x2,y2);
    }
}

static const int GS=200;
static const int GN=50;
vector<short> grid[GN][GN];

void gridRemove(int i){
    if(A[i]>=C[i]||B[i]>=D[i])return;
    int gx1=A[i]/GS,gy1=B[i]/GS,gx2=(C[i]-1)/GS,gy2=(D[i]-1)/GS;
    gx1=max(0,gx1);gy1=max(0,gy1);gx2=min(GN-1,gx2);gy2=min(GN-1,gy2);
    for(int gx=gx1;gx<=gx2;gx++)for(int gy=gy1;gy<=gy2;gy++){
        auto&v=grid[gx][gy];
        for(int k=0;k<(int)v.size();k++)if(v[k]==i){v[k]=v.back();v.pop_back();break;}
    }
}

void gridInsert(int i){
    if(A[i]>=C[i]||B[i]>=D[i])return;
    int gx1=A[i]/GS,gy1=B[i]/GS,gx2=(C[i]-1)/GS,gy2=(D[i]-1)/GS;
    gx1=max(0,gx1);gy1=max(0,gy1);gx2=min(GN-1,gx2);gy2=min(GN-1,gy2);
    for(int gx=gx1;gx<=gx2;gx++)for(int gy=gy1;gy<=gy2;gy++) grid[gx][gy].push_back((short)i);
}

bool overlapsAny(int i,int excl1=-1,int excl2=-1){
    if(A[i]>=C[i]||B[i]>=D[i])return true;
    int gx1=A[i]/GS,gy1=B[i]/GS,gx2=(C[i]-1)/GS,gy2=(D[i]-1)/GS;
    gx1=max(0,gx1);gy1=max(0,gy1);gx2=min(GN-1,gx2);gy2=min(GN-1,gy2);
    for(int gx=gx1;gx<=gx2;gx++)for(int gy=gy1;gy<=gy2;gy++){
        for(short j:grid[gx][gy])if(j!=i&&j!=excl1&&j!=excl2){
            if(A[i]<C[j]&&C[i]>A[j]&&B[i]<D[j]&&D[i]>B[j])return true;
        }
    }
    return false;
}

bool overlaps2(int i,int j){
    return A[i]<C[j]&&C[i]>A[j]&&B[i]<D[j]&&D[i]>B[j];
}

void expandDir(int i,int dir){
    if(dir==0){
        int lo=0,hi=A[i],best=A[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=A[i];A[i]=mid;if(!overlapsAny(i)){best=mid;hi=mid-1;}else lo=mid+1;A[i]=old;}
        A[i]=best;
    }else if(dir==1){
        int lo=C[i],hi=10000,best=C[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=C[i];C[i]=mid;if(!overlapsAny(i)){best=mid;lo=mid+1;}else hi=mid-1;C[i]=old;}
        C[i]=best;
    }else if(dir==2){
        int lo=0,hi=B[i],best=B[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=B[i];B[i]=mid;if(!overlapsAny(i)){best=mid;hi=mid-1;}else lo=mid+1;B[i]=old;}
        B[i]=best;
    }else{
        int lo=D[i],hi=10000,best=D[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=D[i];D[i]=mid;if(!overlapsAny(i)){best=mid;lo=mid+1;}else hi=mid-1;D[i]=old;}
        D[i]=best;
    }
}

void expandDirLimited(int i,int dir,long long maxArea){
    if(dir==0){
        int lo=0,hi=A[i],best=A[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=A[i];A[i]=mid;
            long long ar=(long long)(C[i]-A[i])*(D[i]-B[i]);
            if(ar<=maxArea&&!overlapsAny(i)){best=mid;hi=mid-1;}else lo=mid+1;A[i]=old;}
        A[i]=best;
    }else if(dir==1){
        int lo=C[i],hi=10000,best=C[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=C[i];C[i]=mid;
            long long ar=(long long)(C[i]-A[i])*(D[i]-B[i]);
            if(ar<=maxArea&&!overlapsAny(i)){best=mid;lo=mid+1;}else hi=mid-1;C[i]=old;}
        C[i]=best;
    }else if(dir==2){
        int lo=0,hi=B[i],best=B[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=B[i];B[i]=mid;
            long long ar=(long long)(C[i]-A[i])*(D[i]-B[i]);
            if(ar<=maxArea&&!overlapsAny(i)){best=mid;hi=mid-1;}else lo=mid+1;B[i]=old;}
        B[i]=best;
    }else{
        int lo=D[i],hi=10000,best=D[i];
        while(lo<=hi){int mid=(lo+hi)/2;int old=D[i];D[i]=mid;
            long long ar=(long long)(C[i]-A[i])*(D[i]-B[i]);
            if(ar<=maxArea&&!overlapsAny(i)){best=mid;lo=mid+1;}else hi=mid-1;D[i]=old;}
        D[i]=best;
    }
}

void shrinkToTarget(int i){
    long long si=(long long)(C[i]-A[i])*(D[i]-B[i]);
    if(si<=R[i])return;
    for(int iter=0;iter<5000&&(long long)(C[i]-A[i])*(D[i]-B[i])>R[i];iter++){
        int dl=X[i]-A[i],dr=C[i]-X[i]-1,du=Y[i]-B[i],dd=D[i]-Y[i]-1;
        if(max({dl,dr,du,dd})<=0)break;
        if(dl>=dr&&dl>=du&&dl>=dd){A[i]++;}
        else if(dr>=dl&&dr>=du&&dr>=dd){C[i]--;}
        else if(du>=dd){B[i]++;}
        else{D[i]--;}
        if(A[i]>X[i])A[i]=X[i];
        if(C[i]<=X[i])C[i]=X[i]+1;
        if(B[i]>Y[i])B[i]=Y[i];
        if(D[i]<=Y[i])D[i]=Y[i]+1;
    }
}

double scores[205];

void findNeighbors(int i,vector<int>&nbrs){
    nbrs.clear();
    int gx1=max(0,A[i]/GS-1),gy1=max(0,B[i]/GS-1);
    int gx2=min(GN-1,(C[i]-1)/GS+1),gy2=min(GN-1,(D[i]-1)/GS+1);
    static bool seen[205];memset(seen,0,sizeof(seen));seen[i]=true;
    for(int gx=gx1;gx<=gx2;gx++)for(int gy=gy1;gy<=gy2;gy++){
        for(short j:grid[gx][gy])if(!seen[j]){
            seen[j]=true;
            bool xov=A[i]<C[j]&&C[i]>A[j],yov=B[i]<D[j]&&D[i]>B[j];
            bool xtouch=(C[i]==A[j]||A[i]==C[j]),ytouch=(D[i]==B[j]||B[i]==D[j]);
            if((xov&&ytouch)||(yov&&xtouch))nbrs.push_back(j);
        }
    }
}

void greedyExpandAll(double*total){
    for(int rep=0;rep<3;rep++){
        vector<int>order(n);iota(order.begin(),order.end(),0);
        sort(order.begin(),order.end(),[](int a,int b){return scores[a]<scores[b];});
        for(int i:order){
            int oa=A[i],ob=B[i],oc=C[i],od=D[i];
            double os=scores[i];
            gridRemove(i);
            int bestA=A[i],bestB=B[i],bestC=C[i],bestD=D[i];
            double bestS=os;
            static int perms[][4]={{0,1,2,3},{2,3,0,1},{0,2,1,3},{1,3,0,2},{3,2,1,0},{1,0,3,2}};
            for(int p=0;p<6;p++){
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
                for(int d=0;d<4;d++)expandDir(i,perms[p][d]);
                long long si2=(long long)(C[i]-A[i])*(D[i]-B[i]);
                if(si2>R[i])shrinkToTarget(i);
                double ns=calcScore(i);
                if(ns>bestS){bestS=ns;bestA=A[i];bestB=B[i];bestC=C[i];bestD=D[i];}
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
                long long lim=(long long)(R[i]*1.15);
                for(int d=0;d<4;d++)expandDirLimited(i,perms[p][d],lim);
                ns=calcScore(i);
                if(ns>bestS){bestS=ns;bestA=A[i];bestB=B[i];bestC=C[i];bestD=D[i];}
            }
            A[i]=bestA;B[i]=bestB;C[i]=bestC;D[i]=bestD;
            *total+=bestS-os;scores[i]=bestS;
            gridInsert(i);
        }
    }
}

int main(){
    scanf("%d",&n);
    for(int i=0;i<n;i++)scanf("%d%d%lld",&X[i],&Y[i],&R[i]);
    
    vector<int>ids(n);iota(ids.begin(),ids.end(),0);
    doPartition(ids,0,0,10000,10000);
    
    for(int i=0;i<n;i++){
        if(!(A[i]<=X[i]&&X[i]<C[i]&&B[i]<=Y[i]&&Y[i]<D[i])){
            A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;
        }
    }
    
    for(int i=0;i<GN;i++)for(int j=0;j<GN;j++)grid[i][j].clear();
    for(int i=0;i<n;i++)gridInsert(i);
    
    mt19937 rng(42);
    auto clk=chrono::steady_clock::now;
    auto start=clk();
    double tl=4.5;
    
    double total=0;
    for(int i=0;i<n;i++){scores[i]=calcScore(i);total+=scores[i];}
    
    greedyExpandAll(&total);
    
    memcpy(BA,A,sizeof(A));memcpy(BB,B,sizeof(B));memcpy(BC,C,sizeof(C));memcpy(BD,D,sizeof(D));
    double best=total;
    
    int iter_count=0;
    while(true){
        double el=chrono::duration<double>(clk()-start).count();
        if(el>tl)break;
        double prog=el/tl;
        
        if(iter_count%40000==39999&&prog<0.85){
            greedyExpandAll(&total);
            if(total>best){best=total;memcpy(BA,A,sizeof(A));memcpy(BB,B,sizeof(B));memcpy(BC,C,sizeof(C));memcpy(BD,D,sizeof(D));}
        }
        iter_count++;
        
        double T=0.05*(1.0-prog)+1e-10;
        
        int mt2=rng()%100;
        if(mt2<40){
            int i=rng()%n;
            int oa=A[i],ob=B[i],oc=C[i],od=D[i];
            int range=max(1,(int)(400*(1.0-prog*0.9)));
            int mv=rng()%4;
            int delta=(int)(rng()%(2*range+1))-range;if(!delta)delta=(rng()&1)?1:-1;
            if(mv==0)A[i]+=delta;else if(mv==1)B[i]+=delta;else if(mv==2)C[i]+=delta;else D[i]+=delta;
            A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
            if(A[i]>=C[i]||B[i]>=D[i]||A[i]>X[i]||C[i]<=X[i]||B[i]>Y[i]||D[i]<=Y[i]){
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;
            }
            gridRemove(i);
            if(overlapsAny(i)){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;gridInsert(i);continue;}
            double ns=calcScore(i),diff=ns-scores[i];
            if(diff>0||((rng()&0xFFFF)/65536.0)<exp(diff/T)){
                gridInsert(i);total+=diff;scores[i]=ns;
                if(total>best){best=total;memcpy(BA,A,sizeof(A));memcpy(BB,B,sizeof(B));memcpy(BC,C,sizeof(C));memcpy(BD,D,sizeof(D));}
            }else{A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;gridInsert(i);}
        }else if(mt2<80){
            int i=rng()%n;vector<int>nbrs;findNeighbors(i,nbrs);if(nbrs.empty())continue;
            int j=nbrs[rng()%nbrs.size()];
            int oa=A[i],ob=B[i],oc=C[i],od=D[i],ja=A[j],jb=B[j],jc=C[j],jd=D[j];
            int range=max(1,(int)(400*(1.0-prog*0.8)));
            int delta=(int)(rng()%(2*range+1))-range;if(!delta)delta=(rng()&1)?1:-1;
            bool ok=false;
            if(oc==ja&&ob<jd&&od>jb){C[i]+=delta;A[j]+=delta;ok=C[i]>A[i]&&C[j]>A[j]&&C[i]>X[i]&&A[j]<=X[j];}
            else if(oa==jc&&ob<jd&&od>jb){A[i]+=delta;C[j]+=delta;ok=C[i]>A[i]&&C[j]>A[j]&&A[i]<=X[i]&&C[j]>X[j];}
            else if(od==jb&&oa<jc&&oc>ja){D[i]+=delta;B[j]+=delta;ok=D[i]>B[i]&&D[j]>B[j]&&D[i]>Y[i]&&B[j]<=Y[j];}
            else if(ob==jd&&oa<jc&&oc>ja){B[i]+=delta;D[j]+=delta;ok=D[i]>B[i]&&D[j]>B[j]&&B[i]<=Y[i]&&D[j]>Y[j];}
            if(!ok){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;A[j]=ja;B[j]=jb;C[j]=jc;D[j]=jd;continue;}
            A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
            A[j]=max(0,A[j]);B[j]=max(0,B[j]);C[j]=min(10000,C[j]);D[j]=min(10000,D[j]);
            if(A[i]>=C[i]||B[i]>=D[i]||A[j]>=C[j]||B[j]>=D[j]){
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;A[j]=ja;B[j]=jb;C[j]=jc;D[j]=jd;continue;
            }
            gridRemove(i);gridRemove(j);
            if(overlaps2(i,j)||overlapsAny(i,i,j)||overlapsAny(j,i,j)){
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;A[j]=ja;B[j]=jb;C[j]=jc;D[j]=jd;
                gridInsert(i);gridInsert(j);continue;
            }
            double nsi=calcScore(i),nsj=calcScore(j),diff=(nsi-scores[i])+(nsj-scores[j]);
            if(diff>0||((rng()&0xFFFF)/65536.0)<exp(diff/T)){
                gridInsert(i);gridInsert(j);total+=diff;scores[i]=nsi;scores[j]=nsj;
                if(total>best){best=total;memcpy(BA,A,sizeof(A));memcpy(BB,B,sizeof(B));memcpy(BC,C,sizeof(C));memcpy(BD,D,sizeof(D));}
            }else{
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;A[j]=ja;B[j]=jb;C[j]=jc;D[j]=jd;
                gridInsert(i);gridInsert(j);
            }
        }else{
            int i=rng()%n;
            int oa=A[i],ob=B[i],oc=C[i],od=D[i];
            int range=max(1,(int)(400*(1.0-prog*0.9)));
            int d1=(int)(rng()%(2*range+1))-range;if(!d1)d1=1;
            int d2=(int)(rng()%(2*range+1))-range;if(!d2)d2=1;
            int mv=rng()%2;
            if(mv==0){A[i]+=d1;C[i]+=d2;}else{B[i]+=d1;D[i]+=d2;}
            A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
            if(A[i]>=C[i]||B[i]>=D[i]||A[i]>X[i]||C[i]<=X[i]||B[i]>Y[i]||D[i]<=Y[i]){
                A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;continue;
            }
            gridRemove(i);
            if(overlapsAny(i)){A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;gridInsert(i);continue;}
            double ns=calcScore(i),diff=ns-scores[i];
            if(diff>0||((rng()&0xFFFF)/65536.0)<exp(diff/T)){
                gridInsert(i);total+=diff;scores[i]=ns;
                if(total>best){best=total;memcpy(BA,A,sizeof(A));memcpy(BB,B,sizeof(B));memcpy(BC,C,sizeof(C));memcpy(BD,D,sizeof(D));}
            }else{A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;gridInsert(i);}
        }
    }
    
    // Final greedy pass on best
    memcpy(A,BA,sizeof(A));memcpy(B,BB,sizeof(B));memcpy(C,BC,sizeof(C));memcpy(D,BD,sizeof(D));
    for(int i=0;i<GN;i++)for(int j=0;j<GN;j++)grid[i][j].clear();
    for(int i=0;i<n;i++)gridInsert(i);
    total=0;for(int i=0;i<n;i++){scores[i]=calcScore(i);total+=scores[i];}
    greedyExpandAll(&total);
    if(total>best){best=total;memcpy(BA,A,sizeof(A));memcpy(BB,B,sizeof(B));memcpy(BC,C,sizeof(C));memcpy(BD,D,sizeof(D));}
    
    for(int i=0;i<n;i++)printf("%d %d %d %d\n",BA[i],BB[i],BC[i],BD[i]);
    return 0;
}
