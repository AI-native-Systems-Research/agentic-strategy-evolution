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

    vector<bool> is_prime(N,false);
    {
        vector<bool> sv(N,true);
        if(N>0)sv[0]=false;if(N>1)sv[1]=false;
        for(int i=2;i<N;i++){
            if(sv[i]){is_prime[i]=true;
                for(long long j=(long long)i*i;j<N;j+=i)sv[j]=false;}
        }
    }

    auto eucl=[&](int a,int b)->double{
        double dx=x[a]-x[b],dy=y[a]-y[b];return sqrt(dx*dx+dy*dy);
    };
    auto sc=[&](int t,int from,int to)->double{
        double d=eucl(from,to);
        if(t%10==0&&!is_prime[from])d*=1.1;
        return d;
    };

    // Grid NN construction
    double minx=x[0],maxx=x[N-1];
    double miny=*min_element(y.begin(),y.end()),maxy=*max_element(y.begin(),y.end());
    int G=max(1,(int)sqrt((double)N/4.0));
    double cw=(maxx-minx+1.0)/G,ch=(maxy-miny+1.0)/G;
    auto cl=[&](int i)->pair<int,int>{return{min(G-1,(int)((x[i]-minx)/cw)),min(G-1,(int)((y[i]-miny)/ch))};};
    vector<vector<vector<int>>> grid(G,vector<vector<int>>(G));
    for(int i=0;i<N;i++){auto[a,b]=cl(i);grid[a][b].push_back(i);}

    vector<bool> used(N,false);
    vector<int> tour={0}; tour.reserve(N+1); used[0]=true;
    for(int s=1;s<N;s++){
        int cur=tour.back();auto[cx,cy]=cl(cur);
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

    // 2-opt ONLY for small N to avoid TLE
    if(N<=10000){
        double budget=1500.0;
        bool improved=true;
        while(improved&&ms()<budget){
            improved=false;
            for(int i=0;i<N-1&&ms()<budget;i++)
            for(int j=i+2;j<min(i+200,N);j++){
                double old_c=0;
                for(int s=i+1;s<=min(j+1,N);s++)old_c+=sc(s,tour[s-1],tour[s]);
                reverse(tour.begin()+i+1,tour.begin()+j+1);
                double new_c=0;
                for(int s=i+1;s<=min(j+1,N);s++)new_c+=sc(s,tour[s-1],tour[s]);
                if(new_c<old_c-1e-10)improved=true;
                else reverse(tour.begin()+i+1,tour.begin()+j+1);
            }
        }
    }

    cout<<N+1<<"\n";
    for(int i=0;i<=N;i++)cout<<tour[i]<<"\n";
    return 0;
}
