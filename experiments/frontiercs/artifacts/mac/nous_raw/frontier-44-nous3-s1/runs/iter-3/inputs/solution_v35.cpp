#include <bits/stdc++.h>
using namespace std;

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);

    auto t0=chrono::steady_clock::now();
    auto ms=[&]()->double{return chrono::duration<double,milli>(chrono::steady_clock::now()-t0).count();};

    int N;
    cin >> N;
    vector<double> x(N), y(N);
    for(int i=0;i<N;i++) cin>>x[i]>>y[i];

    if(N<=2){
        cout<<N+1<<"\n";
        for(int i=0;i<=N;i++)cout<<(i<N?i:0)<<"\n";
        return 0;
    }

    auto eucl=[&](int a,int b)->double{
        double dx=x[a]-x[b],dy=y[a]-y[b];return sqrt(dx*dx+dy*dy);
    };
    auto dist2=[&](int a,int b)->double{
        double dx=x[a]-x[b],dy=y[a]-y[b];return dx*dx+dy*dy;
    };

    double minx=x[0],maxx=x[N-1];
    double miny=*min_element(y.begin(),y.end()),maxy=*max_element(y.begin(),y.end());
    int G=max(1,(int)sqrt((double)N/2.5));
    double cw=(maxx-minx+1.0)/G,ch=(maxy-miny+1.0)/G;
    auto cell=[&](int i)->pair<int,int>{return{min(G-1,(int)((x[i]-minx)/cw)),min(G-1,(int)((y[i]-miny)/ch))};};
    vector<vector<vector<int>>> grid(G,vector<vector<int>>(G));
    for(int i=0;i<N;i++){auto[a,b]=cell(i);grid[a][b].push_back(i);}

    const int K = 15;
    vector<int> knn(N*K, -1);
    for(int i=0;i<N;i++){
        auto [cx,cy]=cell(i);
        double best[K]; int bidx[K];
        for(int k=0;k<K;k++){best[k]=1e30;bidx[k]=-1;}
        for(int r=0;r<=G;r++){
            for(int dx=-r;dx<=r;dx++)for(int dy=-r;dy<=r;dy++){
                if(r>0&&abs(dx)!=r&&abs(dy)!=r)continue;
                int nx=cx+dx,ny=cy+dy;
                if(nx<0||nx>=G||ny<0||ny>=G)continue;
                for(int c:grid[nx][ny]){
                    if(c==i)continue;
                    double d=dist2(i,c);
                    if(d<best[K-1]){
                        best[K-1]=d;bidx[K-1]=c;
                        for(int k=K-2;k>=0;k--){
                            if(best[k+1]<best[k]){swap(best[k],best[k+1]);swap(bidx[k],bidx[k+1]);}
                            else break;
                        }
                    }
                }
            }
            if(bidx[K-1]!=-1&&r>=1)break;
        }
        for(int k=0;k<K;k++) knn[i*K+k]=bidx[k];
    }

    vector<bool> used(N,false);
    vector<int> tour; tour.reserve(N+1); tour.push_back(0); used[0]=true;
    for(int s=1;s<N;s++){
        int cur=tour.back();auto[cx,cy]=cell(cur);
        int best=-1;double bd=1e18;
        for(int r=0;r<=G;r++){
            if(best!=-1){double md=max(0.0,(double)(r-1))*min(cw,ch);if(md>bd)break;}
            for(int dx=-r;dx<=r;dx++)for(int dy=-r;dy<=r;dy++){
                if(abs(dx)!=r&&abs(dy)!=r)continue;
                int nx=cx+dx,ny=cy+dy;
                if(nx<0||nx>=G||ny<0||ny>=G)continue;
                for(int c:grid[nx][ny])if(!used[c]){double d=eucl(cur,c);if(d<bd){bd=d;best=c;}}
            }
            if(best!=-1&&r>=1)break;
        }
        used[best]=true;tour.push_back(best);
    }
    tour.push_back(0);

    vector<int> pos(N+1);
    for(int i=0;i<=N;i++) pos[tour[i]]=i;
    vector<double> ed(N+1);
    for(int i=0;i<N;i++) ed[i]=eucl(tour[i],tour[i+1]);

    double budget_ms = 1900.0;
    vector<bool> dlb(N+1, false);

    auto do_2opt_candidate=[&](double tl)->bool{
        fill(dlb.begin(),dlb.end(),false);
        bool any=false;
        for(int pass=0; pass<500 && ms()<tl; pass++){
            bool improved=false;
            for(int idx=0; idx<N && ms()<tl; idx++){
                if(dlb[idx]) continue;
                int a = tour[idx];
                bool found=false;
                const int* nn = &knn[a*K];
                for(int ki=0; ki<K; ki++){
                    int c = nn[ki];
                    if(c<0) continue;
                    int j = pos[c];
                    int ii=idx, jj=j;
                    if(ii>jj) swap(ii,jj);
                    if(jj<=ii+1||jj>=N) continue;
                    double threshold = ed[ii]+ed[jj];
                    if(dist2(tour[ii],tour[jj]) >= threshold*threshold) continue;
                    double new_ac = eucl(tour[ii],tour[jj]);
                    if(new_ac >= threshold) continue;
                    double new_bd = eucl(tour[ii+1],tour[jj+1]);
                    double delta = new_ac + new_bd - threshold;
                    if(delta < -1e-9){
                        reverse(tour.begin()+ii+1,tour.begin()+jj+1);
                        for(int p=ii+1;p<=jj;p++) pos[tour[p]]=p;
                        ed[ii]=new_ac;
                        if(jj-ii>2) reverse(ed.begin()+ii+1,ed.begin()+jj);
                        ed[jj]=new_bd;
                        if(ii>0)dlb[ii-1]=false;
                        dlb[ii]=false; dlb[jj]=false;
                        if(jj+1<=N)dlb[jj+1]=false;
                        improved=true; found=true; any=true; break;
                    }
                }
                if(!found) dlb[idx]=true;
            }
            if(!improved) break;
        }
        return any;
    };

    auto do_2opt_window=[&](double tl){
        int window = min(N-1, max(20, min(300, (int)(4000000.0/N))));
        for(int pass=0; pass<10 && ms()<tl; pass++){
            bool improved=false;
            for(int i=0;i<N-1 && ms()<tl;i++){
                double di=ed[i];
                for(int j=i+2;j<min(i+window,N);j++){
                    double threshold=di+ed[j];
                    if(dist2(tour[i],tour[j])>=threshold*threshold)continue;
                    double new_ac=eucl(tour[i],tour[j]);
                    if(new_ac>=threshold)continue;
                    double new_bd=eucl(tour[i+1],tour[j+1]);
                    double delta=new_ac+new_bd-threshold;
                    if(delta<-1e-9){
                        reverse(tour.begin()+i+1,tour.begin()+j+1);
                        for(int p=i+1;p<=j;p++) pos[tour[p]]=p;
                        ed[i]=new_ac;
                        if(j-i>2)reverse(ed.begin()+i+1,ed.begin()+j);
                        ed[j]=new_bd;
                        di=ed[i];
                        improved=true;
                    }
                }
            }
            if(!improved)break;
        }
    };

    // Or-opt1: relocate single city
    auto do_oropt1=[&](double tl)->bool{
        bool any=false;
        for(int pass=0; pass<200 && ms()<tl; pass++){
            bool improved=false;
            for(int idx=1; idx<N && ms()<tl; idx++){
                int c = tour[idx];
                double removal_gain = ed[idx-1] + ed[idx] - eucl(tour[idx-1], tour[idx+1]);
                if(removal_gain < 1e-9) continue;
                const int* nn = &knn[c*K];
                bool found = false;
                for(int ki=0; ki<K; ki++){
                    int nb = nn[ki];
                    if(nb<0) continue;
                    int j = pos[nb];
                    for(int ins : {j, j-1}){
                        if(ins < 0 || ins >= N || ins==idx-1 || ins==idx) continue;
                        double ic = eucl(tour[ins], c) + eucl(c, tour[ins+1]) - ed[ins];
                        if(ic - removal_gain < -1e-9){
                            if(idx < ins){
                                memmove(&tour[idx], &tour[idx+1], (ins-idx)*sizeof(int));
                                tour[ins] = c;
                                if(ins-idx>=2) memmove(&ed[idx], &ed[idx+1], (ins-idx-1)*sizeof(double));
                                if(idx>0) ed[idx-1]=eucl(tour[idx-1],tour[idx]);
                                ed[ins-1]=eucl(tour[ins-1],c); ed[ins]=eucl(c,tour[ins+1]);
                                for(int p=idx;p<=ins;p++) pos[tour[p]]=p;
                            } else {
                                int np=ins+1;
                                memmove(&tour[np+1],&tour[np],(idx-np)*sizeof(int));
                                tour[np]=c;
                                if(idx-np>=2) memmove(&ed[np+1],&ed[np],(idx-np-1)*sizeof(double));
                                ed[ins]=eucl(tour[ins],c); ed[np]=eucl(c,tour[np+1]);
                                ed[idx]=eucl(tour[idx],tour[idx+1]);
                                for(int p=np;p<=idx;p++) pos[tour[p]]=p;
                            }
                            improved=true; found=true; any=true; break;
                        }
                    }
                    if(found) break;
                }
            }
            if(!improved) break;
        }
        return any;
    };

    // Or-opt2: relocate pair with optional reversal, efficient memmove updates
    auto do_oropt2=[&](double tl)->bool{
        bool any=false;
        for(int pass=0; pass<100 && ms()<tl; pass++){
            bool improved=false;
            for(int idx=1; idx<N-1 && ms()<tl; idx++){
                int c1=tour[idx], c2=tour[idx+1];
                double bridge=eucl(tour[idx-1],tour[idx+2]);
                double rg=ed[idx-1]+ed[idx+1]-bridge;
                if(rg<1e-9) continue;
                const int* nn=&knn[c1*K];
                bool found=false;
                for(int ki=0;ki<K;ki++){
                    int nb=nn[ki]; if(nb<0) continue;
                    int j=pos[nb];
                    if(j>=idx-1 && j<=idx+2) continue;
                    if(j<0||j>=N) continue;
                    // Normal: (c1,c2)
                    double dn=eucl(tour[j],c1)+eucl(c2,tour[j+1])-ed[j]-rg;
                    // Reversed: (c2,c1)
                    double dr=eucl(tour[j],c2)+eucl(c1,tour[j+1])-ed[j]-rg;
                    int bo=0; double bd=dn;
                    if(dr<bd){bd=dr;bo=1;}
                    if(bd < -1e-9){
                        int s1=bo==0?c1:c2, s2=bo==0?c2:c1;
                        double pe=bo==0?ed[idx]:eucl(c2,c1);
                        if(idx<j){
                            memmove(&tour[idx],&tour[idx+2],(j-idx-1)*sizeof(int));
                            tour[j-1]=s1; tour[j]=s2;
                            if(j-idx-2>0) memmove(&ed[idx],&ed[idx+2],(j-idx-2)*sizeof(double));
                            if(idx>0) ed[idx-1]=eucl(tour[idx-1],tour[idx]);
                            ed[j-2]=eucl(tour[j-2],s1); ed[j-1]=pe; ed[j]=eucl(s2,tour[j+1]);
                            for(int p=idx;p<=j;p++) pos[tour[p]]=p;
                        } else {
                            memmove(&tour[j+3],&tour[j+1],(idx-j-1)*sizeof(int));
                            tour[j+1]=s1; tour[j+2]=s2;
                            if(idx-j-2>0) memmove(&ed[j+3],&ed[j+1],(idx-j-2)*sizeof(double));
                            ed[j]=eucl(tour[j],s1); ed[j+1]=pe; ed[j+2]=eucl(s2,tour[j+3]);
                            ed[idx+1]=eucl(tour[idx+1],tour[idx+2]);
                            for(int p=j+1;p<=idx+1;p++) pos[tour[p]]=p;
                        }
                        improved=true; found=true; any=true; break;
                    }
                }
            }
            if(!improved) break;
        }
        return any;
    };

    // Or-opt3: relocate triple with optional reversal
    auto do_oropt3=[&](double tl)->bool{
        bool any=false;
        for(int pass=0; pass<50 && ms()<tl; pass++){
            bool improved=false;
            for(int idx=1; idx<N-2 && ms()<tl; idx++){
                int c1=tour[idx],c2=tour[idx+1],c3=tour[idx+2];
                double bridge=eucl(tour[idx-1],tour[idx+3]);
                double rg=ed[idx-1]+ed[idx+2]-bridge;
                if(rg<1e-9) continue;
                const int* nn=&knn[c1*K];
                bool found=false;
                for(int ki=0;ki<K;ki++){
                    int nb=nn[ki]; if(nb<0) continue;
                    int j=pos[nb];
                    if(j>=idx-1&&j<=idx+3) continue;
                    if(j<0||j>=N) continue;
                    // Normal order
                    double dn=eucl(tour[j],c1)+eucl(c3,tour[j+1])-ed[j]-rg;
                    // Reversed
                    double dr=eucl(tour[j],c3)+eucl(c1,tour[j+1])-ed[j]-rg;
                    int bo=0; double bd=dn;
                    if(dr<bd){bd=dr;bo=1;}
                    if(bd < -1e-9){
                        int s1,s2,s3; double pe1,pe2;
                        if(bo==0){s1=c1;s2=c2;s3=c3;pe1=ed[idx];pe2=ed[idx+1];}
                        else{s1=c3;s2=c2;s3=c1;pe1=ed[idx+1];pe2=ed[idx];}
                        if(idx<j){
                            memmove(&tour[idx],&tour[idx+3],(j-idx-2)*sizeof(int));
                            tour[j-2]=s1;tour[j-1]=s2;tour[j]=s3;
                            if(j-idx-3>0) memmove(&ed[idx],&ed[idx+3],(j-idx-3)*sizeof(double));
                            if(idx>0) ed[idx-1]=eucl(tour[idx-1],tour[idx]);
                            ed[j-3]=eucl(tour[j-3],s1); ed[j-2]=pe1; ed[j-1]=pe2;
                            ed[j]=eucl(s3,tour[j+1]);
                            for(int p=idx;p<=j;p++) pos[tour[p]]=p;
                        } else {
                            memmove(&tour[j+4],&tour[j+1],(idx-j-1)*sizeof(int));
                            tour[j+1]=s1;tour[j+2]=s2;tour[j+3]=s3;
                            if(idx-j-2>0) memmove(&ed[j+4],&ed[j+1],(idx-j-2)*sizeof(double));
                            ed[j]=eucl(tour[j],s1); ed[j+1]=pe1; ed[j+2]=pe2;
                            ed[j+3]=eucl(s3,tour[j+4]);
                            ed[idx+2]=eucl(tour[idx+2],tour[idx+3]);
                            for(int p=j+1;p<=idx+2;p++) pos[tour[p]]=p;
                        }
                        improved=true; found=true; any=true; break;
                    }
                }
            }
            if(!improved) break;
        }
        return any;
    };

    auto eucl_cost=[&]()->double{
        double c=0;for(int i=0;i<N;i++) c+=ed[i];return c;
    };

    // Phase 1: 2-opt candidate
    do_2opt_candidate(budget_ms * 0.52);
    // Phase 2: Or-opt (1,2,3) — strict time budgets
    do_oropt1(budget_ms * 0.57);
    do_oropt2(budget_ms * 0.61);
    do_oropt3(budget_ms * 0.64);
    // Phase 3: Window 2-opt
    do_2opt_window(budget_ms * 0.75);

    // Phase 4: ILS
    double best_eucl = eucl_cost();
    vector<int> best_tour = tour;
    vector<double> best_ed = ed;
    vector<int> best_pos = pos;
    mt19937 rng(42);
    vector<int> newtour(N+1);

    while(ms() < budget_ms - 130 && N >= 8){
        double time_left = budget_ms - ms() - 80;
        if(time_left < 100) break;

        int cuts[3]; int att=0, nc=0;
        while(nc<3 && att<100){
            int c=1+rng()%(N-2);
            bool ok=true;
            for(int k=0;k<nc;k++)if(abs(cuts[k]-c)<2)ok=false;
            if(ok)cuts[nc++]=c; att++;
        }
        if(nc<3)break;
        if(cuts[0]>cuts[1])swap(cuts[0],cuts[1]);
        if(cuts[1]>cuts[2])swap(cuts[1],cuts[2]);
        if(cuts[0]>cuts[1])swap(cuts[0],cuts[1]);

        newtour[0]=0; int p=1;
        memcpy(&newtour[p],&tour[1],cuts[0]*sizeof(int)); p+=cuts[0];
        memcpy(&newtour[p],&tour[cuts[1]+1],(cuts[2]-cuts[1])*sizeof(int)); p+=cuts[2]-cuts[1];
        memcpy(&newtour[p],&tour[cuts[0]+1],(cuts[1]-cuts[0])*sizeof(int)); p+=cuts[1]-cuts[0];
        memcpy(&newtour[p],&tour[cuts[2]+1],(N-1-cuts[2])*sizeof(int)); p+=N-1-cuts[2];
        newtour[N]=0;
        memcpy(tour.data(),newtour.data(),(N+1)*sizeof(int));
        for(int i=0;i<=N;i++) pos[tour[i]]=i;
        for(int i=0;i<N;i++) ed[i]=eucl(tour[i],tour[i+1]);

        double per_iter = max(80.0, time_left * 0.4);
        double deadline = ms() + per_iter;
        do_2opt_candidate(deadline * 0.75);
        do_oropt1(deadline);

        double cost = eucl_cost();
        if(cost < best_eucl - 1e-9){
            best_eucl=cost; best_tour=tour; best_ed=ed; best_pos=pos;
        } else {
            tour=best_tour; ed=best_ed; pos=best_pos;
        }
    }

    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++)cout<<best_tour[i]<<"\n";
    return 0;
}
