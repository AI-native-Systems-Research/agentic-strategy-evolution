#include <bits/stdc++.h>
using namespace std;

int main(){
    auto startTime = chrono::steady_clock::now();
    
    string input((istreambuf_iterator<char>(cin)),istreambuf_iterator<char>());
    
    // Parse JSON: {"name": [qty, value, mass, volume], ...}
    struct Item { string name; int q; long long v, m, l; };
    vector<Item> items;
    
    size_t pos = 0;
    while(pos < input.size()){
        pos = input.find('"', pos);
        if(pos == string::npos) break;
        size_t end = input.find('"', pos+1);
        if(end == string::npos) break;
        string key = input.substr(pos+1, end-pos-1);
        pos = end+1;
        size_t br = input.find('[', pos);
        if(br == string::npos) break;
        size_t br2 = input.find(']', br);
        if(br2 == string::npos) break;
        string arr = input.substr(br+1, br2-br-1);
        pos = br2+1;
        
        vector<long long> nums;
        stringstream ss(arr);
        string tok;
        while(getline(ss, tok, ',')){
            // trim and parse integer
            long long v = 0; bool neg = false; bool found = false;
            for(char c : tok){
                if(c=='-') neg=true;
                else if(c>='0'&&c<='9'){ v=v*10+(c-'0'); found=true; }
            }
            if(found) nums.push_back(neg?-v:v);
        }
        if(nums.size()>=4){
            items.push_back({key, (int)nums[0], nums[1], nums[2], nums[3]});
        }
    }
    
    int n = items.size();
    long long CAPM = 20000000LL, CAPL = 25000000LL;
    
    // Branch and bound
    long long bestVal = 0;
    vector<int> bestSol(n, 0), curSol(n, 0);
    bool timeUp = false;
    long long callCount = 0;
    
    // Sort by value density
    sort(items.begin(), items.end(), [](const Item&a, const Item&b){
        double wa = max(1.0, max((double)a.m/20.0, (double)a.l/25.0));
        double wb = max(1.0, max((double)b.m/20.0, (double)b.l/25.0));
        return (double)a.v/wa > (double)b.v/wb;
    });
    
    // Greedy first
    {long long rm=CAPM,rl=CAPL,gv=0;
    for(int i=0;i<n;i++){
        long long mM=(items[i].m>0)?rm/items[i].m:items[i].q;
        long long mL=(items[i].l>0)?rl/items[i].l:items[i].q;
        int t=(int)min({(long long)items[i].q,mM,mL});
        curSol[i]=t;rm-=t*items[i].m;rl-=t*items[i].l;gv+=t*items[i].v;
    }
    if(gv>bestVal){bestVal=gv;bestSol=curSol;}}
    
    function<void(int,long long,long long,long long)> solve=[&](int idx,long long rm,long long rl,long long cv){
        if(timeUp)return;
        if(idx==n){if(cv>bestVal){bestVal=cv;bestSol=curSol;}return;}
        if(++callCount%10000==0){if(chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now()-startTime).count()>900)timeUp=true;}
        if(timeUp)return;
        // Simple UB
        double ub=cv;
        for(int i=idx;i<n;i++) ub+=items[i].v*(double)items[i].q;
        if(ub<=bestVal+0.5)return;
        int mx=items[idx].q;
        if(items[idx].m>0)mx=min(mx,(int)(rm/items[idx].m));
        if(items[idx].l>0)mx=min(mx,(int)(rl/items[idx].l));
        for(int k=mx;k>=0;k--){
            curSol[idx]=k;
            solve(idx+1,rm-k*items[idx].m,rl-k*items[idx].l,cv+k*items[idx].v);
            if(timeUp)break;
        }
        curSol[idx]=0;
    };
    fill(curSol.begin(),curSol.end(),0);
    solve(0,CAPM,CAPL,0);
    
    cout<<"{\n";
    for(int i=0;i<n;i++){
        cout<<"  \""<<items[i].name<<"\": "<<bestSol[i];
        if(i<n-1)cout<<",";
        cout<<"\n";
    }
    cout<<"}\n";
}
