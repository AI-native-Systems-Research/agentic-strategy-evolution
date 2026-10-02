#include <bits/stdc++.h>
using namespace std;

int n;
int px[201], py[201];
long long pr[201];
int ra[201], rb[201], rc[201], rd[201];

double score_i(int i) {
    double sx = px[i] + 0.5, sy = py[i] + 0.5;
    if (sx > ra[i] && sx < rc[i] && sy > rb[i] && sy < rd[i]) {
        double si = (double)(rc[i]-ra[i])*(double)(rd[i]-rb[i]);
        double ri = (double)pr[i];
        double ratio = min(ri,si)/max(ri,si);
        return 1.0 - (1.0-ratio)*(1.0-ratio);
    }
    return 0.0;
}

void doPartition(vector<int>& ids, int lx, int ly, int rx, int ry) {
    if (ids.empty()) return;
    if (ids.size() == 1) {
        int i = ids[0];
        ra[i]=lx; rb[i]=ly; rc[i]=rx; rd[i]=ry;
        return;
    }
    int sz=ids.size();
    long long total_r=0;
    for(int i:ids) total_r+=pr[i];
    
    double best_score=-1e18;
    int best_sp=-1; bool best_h=false;
    vector<int> best_l, best_r;
    
    for(int horiz=0;horiz<2;horiz++){
        int span=horiz?(ry-ly):(rx-lx);
        if(span<2) continue;
        vector<int> si=ids;
        sort(si.begin(),si.end(),[&](int a,int b){
            return horiz?(py[a]<py[b]||(py[a]==py[b]&&px[a]<px[b]))
                        :(px[a]<px[b]||(px[a]==px[b]&&py[a]<py[b]));
        });
        long long cum=0;
        for(int k=0;k<sz-1;k++){
            cum+=pr[si[k]];
            int ck=horiz?py[si[k]]:px[si[k]];
            int ck1=horiz?py[si[k+1]]:px[si[k+1]];
            int lo=horiz?ly:lx, hi=horiz?ry:rx;
            int slo=max(ck+1,lo+1), shi=min(ck1,hi-1);
            if(slo>shi) continue;
            double ratio=(double)cum/total_r;
            int ideal=lo+(int)round(ratio*span);
            ideal=max(slo,min(shi,ideal));
            
            double la=(double)(ideal-lo)*(horiz?(rx-lx):(ry-ly));
            double ra2=(double)(hi-ideal)*(horiz?(rx-lx):(ry-ly));
            double lw=cum, rw=total_r-cum;
            double sl2=1.0-pow(1.0-min(la,lw)/max(la,lw),2);
            double sr2=1.0-pow(1.0-min(ra2,rw)/max(ra2,rw),2);
            double sc=sl2*(k+1)+sr2*(sz-k-1);
            double bal=min(k+1,sz-k-1)/(double)max(k+1,sz-k-1);
            sc+=bal*0.1;
            if(sc>best_score){
                best_score=sc; best_sp=ideal; best_h=horiz;
                best_l.assign(si.begin(),si.begin()+k+1);
                best_r.assign(si.begin()+k+1,si.end());
            }
        }
    }
    if(best_sp==-1){for(int i:ids){ra[i]=px[i];rb[i]=py[i];rc[i]=px[i]+1;rd[i]=py[i]+1;}return;}
    if(best_h){doPartition(best_l,lx,ly,rx,best_sp);doPartition(best_r,lx,best_sp,rx,ry);}
    else{doPartition(best_l,lx,ly,best_sp,ry);doPartition(best_r,best_sp,ly,rx,ry);}
}

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    cin>>n;
    for(int i=0;i<n;i++) cin>>px[i]>>py[i]>>pr[i];
    vector<int> ids(n); iota(ids.begin(),ids.end(),0);
    doPartition(ids,0,0,10000,10000);
    
    auto start=chrono::steady_clock::now();
    mt19937 rng(12345);
    double cur=0; for(int i=0;i<n;i++) cur+=score_i(i);
    
    int bra[201],brb[201],brc[201],brd[201];
    memcpy(bra,ra,sizeof(ra));memcpy(brb,rb,sizeof(rb));memcpy(brc,rc,sizeof(rc));memcpy(brd,rd,sizeof(rd));
    double best=cur;
    
    while(true){
        double el=chrono::duration<double>(chrono::steady_clock::now()-start).count();
        if(el>4.7) break;
        double T=0.05*(1.0-el/4.7);
        int i=rng()%n;
        int side=rng()%4;
        int maxd=max(1,(int)(100*(1.0-el/4.7)));
        int delta=(int)(rng()%(2*maxd+1))-maxd;
        if(!delta) continue;
        int oa=ra[i],ob=rb[i],oc=rc[i],od=rd[i];
        double old_si=score_i(i);
        if(side==0)ra[i]+=delta;else if(side==1)rb[i]+=delta;else if(side==2)rc[i]+=delta;else rd[i]+=delta;
        bool ok=ra[i]>=0&&rb[i]>=0&&rc[i]<=10000&&rd[i]<=10000&&ra[i]<rc[i]&&rb[i]<rd[i];
        if(ok){double sx=px[i]+0.5,sy=py[i]+0.5;ok=sx>ra[i]&&sx<rc[i]&&sy>rb[i]&&sy<rd[i];}
        if(ok)for(int j=0;j<n&&ok;j++)if(j!=i){
            if(ra[i]<rc[j]&&rc[i]>ra[j]&&rb[i]<rd[j]&&rd[i]>rb[j])ok=false;
        }
        if(ok){
            double new_si=score_i(i);
            double diff=new_si-old_si;
            if(diff>0||((double)(rng()%10000)/10000.0<exp(diff/max(T,1e-9)))){
                cur+=diff;
                if(cur>best){best=cur;memcpy(bra,ra,sizeof(ra));memcpy(brb,rb,sizeof(rb));memcpy(brc,rc,sizeof(rc));memcpy(brd,rd,sizeof(rd));}
            } else {ra[i]=oa;rb[i]=ob;rc[i]=oc;rd[i]=od;}
        } else {ra[i]=oa;rb[i]=ob;rc[i]=oc;rd[i]=od;}
    }
    memcpy(ra,bra,sizeof(ra));memcpy(rb,brb,sizeof(rb));memcpy(rc,brc,sizeof(rc));memcpy(rd,brd,sizeof(rd));
    for(int i=0;i<n;i++) cout<<ra[i]<<" "<<rb[i]<<" "<<rc[i]<<" "<<rd[i]<<"\n";
}
