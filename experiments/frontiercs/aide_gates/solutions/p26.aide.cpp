#include <iostream>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <cmath>
#include <cassert>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    cin >> n;
    vector<int> v(n);
    for(int i=0;i<n;i++) cin >> v[i];

    if(n==1){ cout<<"1 0\n"; return 0; }
    bool sorted_flag=true;
    for(int i=0;i<n;i++) if(v[i]!=i+1){sorted_flag=false;break;}
    if(sorted_flag){ cout<<"1 0\n"; return 0; }

    long long total_sum=(long long)n*(n+1)/2;
    vector<int> pos_of(n+1);
    for(int i=0;i<n;i++) pos_of[v[i]]=i;

    // max_hi[lo]: maximum hi such that values lo..hi appear in increasing position order
    vector<int> max_hi(n+2, 0);
    max_hi[n] = n;
    for(int val=n-1; val>=1; val--){
        if(pos_of[val] < pos_of[val+1]) max_hi[val] = max_hi[val+1];
        else max_hi[val] = val;
    }

    vector<long long> prefix(n+2, 0);
    for(int i=1;i<=n;i++) prefix[i] = prefix[i-1] + i;
    auto range_sum = [&](int lo, int hi) -> long long {
        return prefix[hi] - prefix[lo-1];
    };
    auto eval_cost = [&](int s, long long T) -> long long {
        int k = n - s;
        long long tc = total_sum - T - (long long)k*(k-1)/2;
        return (tc + 1) * ((long long)k + 1);
    };
    auto eval_range = [&](int lo, int hi) -> long long {
        if(lo > hi) return (long long)(n+1)*(n+1);
        return eval_cost(hi-lo+1, range_sum(lo,hi));
    };

    long long best_cost = (long long)(n+1)*(n+1);
    int best_type = 0; // 0=keep nothing, 1=contiguous range, 2=LIS
    int best_lo = 1, best_hi = 0;
    vector<int> best_lis_elems;

    // Try contiguous ranges
    for(int lo=1; lo<=n; lo++){
        int mh = max_hi[lo];
        // For small ranges, try all hi
        if(mh - lo + 1 <= 200){
            for(int hi=lo; hi<=mh; hi++){
                long long c = eval_range(lo, hi);
                if(c < best_cost){ best_cost=c; best_type=1; best_lo=lo; best_hi=hi; }
            }
        } else {
            // Try endpoints and ternary search
            for(int hi : {lo, mh}){
                long long c = eval_range(lo, hi);
                if(c < best_cost){ best_cost=c; best_type=1; best_lo=lo; best_hi=hi; }
            }
            int tlo=lo, thi=mh;
            for(int iter=0; iter<200 && tlo<=thi; iter++){
                int m1 = tlo + (thi-tlo)/3;
                int m2 = thi - (thi-tlo)/3;
                long long c1 = eval_range(lo, m1);
                long long c2 = eval_range(lo, m2);
                if(c1 < best_cost){ best_cost=c1; best_type=1; best_lo=lo; best_hi=m1; }
                if(c2 < best_cost){ best_cost=c2; best_type=1; best_lo=lo; best_hi=m2; }
                if(c1 < c2) thi=m2-1; else tlo=m1+1;
            }
            for(int d=-3;d<=3;d++){
                int hi2=tlo+d;
                if(hi2>=lo && hi2<=mh){
                    long long c=eval_range(lo,hi2);
                    if(c<best_cost){best_cost=c;best_type=1;best_lo=lo;best_hi=hi2;}
                }
            }
        }
    }

    // LIS
    {
        vector<int> tails, tail_idx, lis_pred(n,-1);
        for(int i=0;i<n;i++){
            int lo2=0,hi2=(int)tails.size();
            while(lo2<hi2){int m=(lo2+hi2)/2; if(tails[m]<v[i])lo2=m+1;else hi2=m;}
            if(lo2>0) lis_pred[i]=tail_idx[lo2-1];
            if(lo2==(int)tails.size()){tails.push_back(v[i]);tail_idx.push_back(i);}
            else{tails[lo2]=v[i];tail_idx[lo2]=i;}
        }
        int L=(int)tails.size();
        vector<int> lis_elems;
        {int idx=tail_idx[L-1]; while(idx!=-1){lis_elems.push_back(v[idx]);idx=lis_pred[idx];} reverse(lis_elems.begin(),lis_elems.end());}
        long long lis_sum=0; for(int x:lis_elems) lis_sum+=x;
        long long fc=eval_cost(L, lis_sum);
        if(fc<best_cost){best_cost=fc;best_type=2;best_lis_elems=lis_elems;}
    }

    // Build kept set
    vector<bool> keep(n+1, false);
    if(best_type==1 && best_lo>=1 && best_hi>=best_lo){
        for(int val=best_lo;val<=best_hi;val++) keep[val]=true;
    } else if(best_type==2){
        for(int x:best_lis_elems) keep[x]=true;
    }

    vector<int> moved_vals;
    for(int t=n;t>=1;t--) if(!keep[t]) moved_vals.push_back(t);
    int k=(int)moved_vals.size();

    int bs=max(1,(int)sqrt((double)n));
    vector<vector<int>> blocks;
    for(int i=0;i<n;i+=bs){
        blocks.emplace_back();
        for(int j=i;j<min(n,i+bs);j++) blocks.back().push_back(v[j]);
    }
    // val_to_block map
    vector<int> vtb(n+1);
    for(int b=0;b<(int)blocks.size();b++) for(int x:blocks[b]) vtb[x]=b;

    auto gpos=[&](int b,int idx)->int{int p=0;for(int i=0;i<b;i++)p+=(int)blocks[i].size();return p+idx;};

    vector<pair<int,int>> moves; long long tc2=0;
    for(int i=0;i<k;i++){
        int t=moved_vals[i]; int r=k-1-i; int y=t-r;
        int bl=vtb[t]; int idx=-1;
        for(int j=0;j<(int)blocks[bl].size();j++) if(blocks[bl][j]==t){idx=j;break;}
        int x=gpos(bl,idx)+1;
        blocks[bl].erase(blocks[bl].begin()+idx);
        if(blocks[bl].empty()){
            for(int b2=bl+1;b2<(int)blocks.size();b2++) for(int xx:blocks[b2]) vtb[xx]=b2-1;
            blocks.erase(blocks.begin()+bl);
        }
        int gp=y-1,pos=0,ib=-1,id2=-1;
        for(int b=0;b<(int)blocks.size();b++){
            if(pos+(int)blocks[b].size()>gp||b==(int)blocks.size()-1){
                id2=gp-pos; id2=max(0,min(id2,(int)blocks[b].size()));
                ib=b; break;
            }
            pos+=(int)blocks[b].size();
        }
        blocks[ib].insert(blocks[ib].begin()+id2,t);
        vtb[t]=ib;
        if((int)blocks[ib].size()>2*bs){
            vector<int> nb3(blocks[ib].begin()+bs,blocks[ib].end());
            blocks[ib].resize(bs);
            blocks.insert(blocks.begin()+ib+1,nb3);
            for(int xx:blocks[ib]) vtb[xx]=ib;
            for(int xx:blocks[ib+1]) vtb[xx]=ib+1;
            for(int b2=ib+2;b2<(int)blocks.size();b2++) for(int xx:blocks[b2]) vtb[xx]=b2;
        }
        moves.push_back({x,y}); tc2+=y;
    }
    long long fc2=(tc2+1)*((long long)k+1);
    cout<<fc2<<" "<<k<<"\n";
    for(auto&[x,y]:moves) cout<<x<<" "<<y<<"\n";
    return 0;
}