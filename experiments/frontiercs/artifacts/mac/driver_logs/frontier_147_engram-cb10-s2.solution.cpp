#include <bits/stdc++.h>
using namespace std;

int n;
int x_[200], y_[200];
long long r_[200];
int a_[200], b_[200], c_[200], d_[200];

void solve_rec(vector<int>& ids, int ax, int ay, int cx, int cy, int depth) {
    if (ids.empty()) return;
    if (ids.size() == 1) {
        int i = ids[0];
        a_[i] = ax; b_[i] = ay; c_[i] = cx; d_[i] = cy;
        return;
    }
    
    bool horiz = (cx - ax) >= (cy - ay);
    
    if (horiz) sort(ids.begin(), ids.end(), [](int a, int b){ return x_[a] < x_[b] || (x_[a]==x_[b] && y_[a]<y_[b]); });
    else sort(ids.begin(), ids.end(), [](int a, int b){ return y_[a] < y_[b] || (y_[a]==y_[b] && x_[a]<x_[b]); });
    
    long long totalR = 0;
    for (int i : ids) totalR += r_[i];
    
    int bestSplit = -1;
    double bestCost = 1e18;
    long long sumR = 0;
    
    for (int k = 1; k < (int)ids.size(); k++) {
        sumR += r_[ids[k-1]];
        double frac = (double)sumR / totalR;
        
        int prevCoord = horiz ? x_[ids[k-1]] : y_[ids[k-1]];
        int nextCoord = horiz ? x_[ids[k]] : y_[ids[k]];
        
        if (prevCoord == nextCoord) continue;
        
        int range = horiz ? (cx - ax) : (cy - ay);
        int base = horiz ? ax : ay;
        int ideal = base + (int)round(frac * range);
        int lo = prevCoord + 1;
        int hi = nextCoord;
        lo = max(lo, base + 1);
        hi = min(hi, base + range - 1);
        if (lo > hi) continue;
        
        int sp = max(lo, min(hi, ideal));
        double actualFrac = (double)(sp - base) / range;
        double cost = (actualFrac - frac)*(actualFrac - frac);
        if (cost < bestCost) { bestCost = cost; bestSplit = k; }
    }
    
    if (bestSplit < 0) {
        bestSplit = ids.size() / 2;
    }
    
    vector<int> left(ids.begin(), ids.begin()+bestSplit);
    vector<int> right(ids.begin()+bestSplit, ids.end());
    
    long long leftR = 0;
    for (int i : left) leftR += r_[i];
    double frac = (double)leftR / totalR;
    
    if (horiz) {
        int range = cx - ax;
        int sp = ax + max(1, min(range-1, (int)round(frac * range)));
        int lo = ax + 1, hi = cx - 1;
        for (int i : left) lo = max(lo, x_[i]+1);
        for (int i : right) hi = min(hi, x_[i]);
        sp = max(sp, lo); sp = min(sp, hi);
        if (sp < lo) sp = lo;
        if (sp > hi) sp = hi;
        solve_rec(left, ax, ay, sp, cy, depth+1);
        solve_rec(right, sp, ay, cx, cy, depth+1);
    } else {
        int range = cy - ay;
        int sp = ay + max(1, min(range-1, (int)round(frac * range)));
        int lo = ay + 1, hi = cy - 1;
        for (int i : left) lo = max(lo, y_[i]+1);
        for (int i : right) hi = min(hi, y_[i]);
        sp = max(sp, lo); sp = min(sp, hi);
        if (sp < lo) sp = lo;
        if (sp > hi) sp = hi;
        solve_rec(left, ax, ay, cx, sp, depth+1);
        solve_rec(right, ax, sp, cx, cy, depth+1);
    }
}

int main(){
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    cin >> n;
    for(int i=0;i<n;i++) cin >> x_[i] >> y_[i] >> r_[i];
    vector<int> ids(n);
    iota(ids.begin(),ids.end(),0);
    solve_rec(ids,0,0,10000,10000,0);
    for(int i=0;i<n;i++){
        if(a_[i]>=c_[i]||b_[i]>=d_[i]||x_[i]<a_[i]||x_[i]>=c_[i]||y_[i]<b_[i]||y_[i]>=d_[i])
            {a_[i]=x_[i];b_[i]=y_[i];c_[i]=x_[i]+1;d_[i]=y_[i]+1;}
    }
    auto ov=[&](int i,int j)->bool{return a_[i]<c_[j]&&c_[i]>a_[j]&&b_[i]<d_[j]&&d_[i]>b_[j];};
    auto sc=[&](int i)->double{long long s=(long long)(c_[i]-a_[i])*(d_[i]-b_[i]);if(s<=0)return 0.0;double mn=min((double)r_[i],(double)s),mx=max((double)r_[i],(double)s);double ra=1.0-mn/mx;return 1.0-ra*ra;};
    mt19937 rng(42);
    auto t0=chrono::steady_clock::now();
    for(int it=0;;it++){
        if((it&4095)==0){double el=chrono::duration<double>(chrono::steady_clock::now()-t0).count();if(el>4.5)break;}
        double el=chrono::duration<double>(chrono::steady_clock::now()-t0).count();
        double T=5.0*pow(0.0001/5.0,el/4.5);
        int i=rng()%n;
        int dir=rng()%4;
        double os=sc(i);
        int oa=a_[i],ob=b_[i],oc=c_[i],od=d_[i];
        int mag=1+rng()%max(1,(int)(T*10+1));
        int delta=((rng()&1)?1:-1)*mag;
        if(dir==0)a_[i]+=delta;else if(dir==1)b_[i]+=delta;else if(dir==2)c_[i]+=delta;else d_[i]+=delta;
        bool ok=a_[i]>=0&&b_[i]>=0&&c_[i]<=10000&&d_[i]<=10000&&a_[i]<c_[i]&&b_[i]<d_[i]&&x_[i]>=a_[i]&&x_[i]<c_[i]&&y_[i]>=b_[i]&&y_[i]<d_[i];
        if(ok)for(int j=0;j<n;j++)if(j!=i&&ov(i,j)){ok=false;break;}
        if(!ok){a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;continue;}
        double ns=sc(i),diff=ns-os;
        if(diff<0&&(double)(rng()%10000)/10000.0>=exp(diff/max(T,1e-9))){a_[i]=oa;b_[i]=ob;c_[i]=oc;d_[i]=od;}
    }
    for(int i=0;i<n;i++) printf("%d %d %d %d\n",a_[i],b_[i],c_[i],d_[i]);
}
