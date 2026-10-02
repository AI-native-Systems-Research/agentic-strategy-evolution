#include <iostream>
#include <vector>
#include <algorithm>
#include <cmath>
#include <random>
#include <chrono>
#include <numeric>
#include <cstring>
using namespace std;

static auto t0 = chrono::steady_clock::now();
double elapsed() {
    return chrono::duration<double>(chrono::steady_clock::now() - t0).count();
}

const int W = 10000;
int N;
int px[210], py[210];
long long R[210];

struct Rect { int x1,y1,x2,y2; long long area()const{return(long long)(x2-x1)*(y2-y1);} };
Rect rects[210], best_rects[210];

inline double sat(int i) {
    const Rect& r = rects[i];
    if (!(r.x1<=px[i]&&px[i]<r.x2&&r.y1<=py[i]&&py[i]<r.y2)) return 0.0;
    long long si=r.area(), ri=R[i];
    double ratio=(double)min(si,ri)/(double)max(si,ri);
    return 1.0-(1.0-ratio)*(1.0-ratio);
}

inline bool ov(const Rect& a, const Rect& b) {
    return a.x1<b.x2&&b.x1<a.x2&&a.y1<b.y2&&b.y1<a.y2;
}

bool canPlace(int idx, const Rect& nr) {
    if (nr.x1<0||nr.y1<0||nr.x2>W||nr.y2>W) return false;
    if (nr.x1>=nr.x2||nr.y1>=nr.y2) return false;
    for (int j=0;j<N;j++) {
        if (j==idx) continue;
        if (ov(nr,rects[j])) return false;
    }
    return true;
}

int maxExp(int idx, int d) {
    const Rect& r=rects[idx];
    int lim=(d==0||d==2)?0:W;
    for (int j=0;j<N;j++) {
        if (j==idx) continue;
        const Rect& o=rects[j];
        if (d<=1) {
            if (o.y1>=r.y2||o.y2<=r.y1) continue;
            if (d==0&&o.x2<=r.x1) lim=max(lim,o.x2);
            if (d==1&&o.x1>=r.x2) lim=min(lim,o.x1);
        } else {
            if (o.x1>=r.x2||o.x2<=r.x1) continue;
            if (d==2&&o.y2<=r.y1) lim=max(lim,o.y2);
            if (d==3&&o.y1>=r.y2) lim=min(lim,o.y1);
        }
    }
    return lim;
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    cin>>N;
    for (int i=0;i<N;i++) cin>>px[i]>>py[i]>>R[i];
    for (int i=0;i<N;i++) rects[i]={px[i],py[i],px[i]+1,py[i]+1};

    // Greedy expansion with small steps
    for (int round=0; round<300; round++) {
        if (elapsed()>2.0) break;
        bool any=false;
        for (int idx=0;idx<N;idx++) {
            long long cur=rects[idx].area();
            long long target=R[idx];
            if (cur>=target) continue;
            for (int d=0;d<4;d++) {
                Rect nr=rects[idx];
                double ratio=(double)target/max(1LL,cur);
                int step=max(1,(int)(sqrt(ratio)*3));
                step=min(step,150);
                if (d==0) nr.x1=max(0,nr.x1-step);
                else if (d==1) nr.x2=min(W,nr.x2+step);
                else if (d==2) nr.y1=max(0,nr.y1-step);
                else nr.y2=min(W,nr.y2+step);
                if (canPlace(idx,nr)) {
                    rects[idx]=nr;
                    any=true;
                    cur=rects[idx].area();
                    if (cur>=target) break;
                }
            }
        }
        if (!any) break;
    }

    // SA
    mt19937 rng(42);
    double total=0;
    for (int i=0;i<N;i++) total+=sat(i);
    double best=total;
    memcpy(best_rects,rects,sizeof(Rect)*N);

    double time_limit=9.3;

    while (true) {
        double t=elapsed();
        if (t>time_limit) break;
        double temp=0.01*(1.0-t/time_limit);
        if (temp<1e-9) temp=1e-9;

        int idx=rng()%N;
        Rect old=rects[idx];
        double oldS=sat(idx);
        Rect nr=old;

        int move=rng()%8;
        int delta;
        if (rng()%2==0) delta=(rng()%20)+1;
        else delta=(rng()%200)+1;
        if (rng()%2) delta=-delta;

        switch(move) {
        case 0: nr.x1+=delta; break;
        case 1: nr.x2+=delta; break;
        case 2: nr.y1+=delta; break;
        case 3: nr.y2+=delta; break;
        case 4: nr.x1+=delta; nr.x2+=delta; break;
        case 5: nr.y1+=delta; nr.y2+=delta; break;
        case 6: {
            int d=rng()%4;
            int lim=maxExp(idx,d);
            if (d==0) nr.x1=lim;
            else if (d==1) nr.x2=lim;
            else if (d==2) nr.y1=lim;
            else nr.y2=lim;
            break;
        }
        case 7: {
            long long ca=nr.area(), target=R[idx];
            int d=rng()%4;
            int w=nr.x2-nr.x1, h=nr.y2-nr.y1;
            if (ca<target) {
                int lim=maxExp(idx,d);
                int step;
                if (d<=1) step=max(1,(int)(((double)target/h-w)*((rng()%100+1)/100.0)));
                else step=max(1,(int)(((double)target/w-h)*((rng()%100+1)/100.0)));
                step=min(step,2000);
                if (d==0) nr.x1=max(lim,nr.x1-step);
                else if (d==1) nr.x2=min(lim,nr.x2+step);
                else if (d==2) nr.y1=max(lim,nr.y1-step);
                else nr.y2=min(lim,nr.y2+step);
            } else {
                int step;
                if (d<=1) step=max(1,(int)((w-(double)target/h)*((rng()%100+1)/100.0)));
                else step=max(1,(int)((h-(double)target/w)*((rng()%100+1)/100.0)));
                step=min(step,2000);
                if (d==0) nr.x1=min(px[idx],nr.x1+step);
                else if (d==1) nr.x2=max(px[idx]+1,nr.x2-step);
                else if (d==2) nr.y1=min(py[idx],nr.y1+step);
                else nr.y2=max(py[idx]+1,nr.y2-step);
            }
            break;
        }
        }

        nr.x1=min(nr.x1,px[idx]); nr.x2=max(nr.x2,px[idx]+1);
        nr.y1=min(nr.y1,py[idx]); nr.y2=max(nr.y2,py[idx]+1);
        nr.x1=max(0,nr.x1); nr.x2=min(W,nr.x2);
        nr.y1=max(0,nr.y1); nr.y2=min(W,nr.y2);
        if (nr.x1>=nr.x2||nr.y1>=nr.y2) continue;

        bool ok=true;
        for (int j=0;j<N&&ok;j++) { if (j!=idx&&ov(nr,rects[j])) ok=false; }
        if (!ok) continue;

        rects[idx]=nr;
        double newS=sat(idx);
        double diff=newS-oldS;

        if (diff>=0||(double)(rng()%10000)/10000.0<exp(diff/temp)) {
            total+=diff;
            if (total>best) { best=total; memcpy(best_rects,rects,sizeof(Rect)*N); }
        } else {
            rects[idx]=old;
        }
    }

    for (int i=0;i<N;i++)
        cout<<best_rects[i].x1<<" "<<best_rects[i].y1<<" "<<best_rects[i].x2<<" "<<best_rects[i].y2<<"\n";
    return 0;
}
