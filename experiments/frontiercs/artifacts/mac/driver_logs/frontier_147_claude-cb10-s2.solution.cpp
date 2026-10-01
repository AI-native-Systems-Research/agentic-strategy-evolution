#include<bits/stdc++.h>
using namespace std;

int n;
int X[200],Y[200];
long long R[200];
int A[200],B[200],C[200],D[200];

double calcScore(int i){
    if(A[i]>=C[i]||B[i]>=D[i])return 0;
    if(X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i])return 0;
    double s=(double)(C[i]-A[i])*(double)(D[i]-B[i]);
    double r=(double)R[i];
    double ratio=min(r,s)/max(r,s);
    return 1.0-(1.0-ratio)*(1.0-ratio);
}

void bsp(vector<int>&ids,int x0,int y0,int x1,int y1){
    if(ids.empty())return;
    if(ids.size()==1){
        A[ids[0]]=x0;B[ids[0]]=y0;C[ids[0]]=x1;D[ids[0]]=y1;
        return;
    }
    int w=x1-x0,h=y1-y0;
    if(w<=0||h<=0){
        for(int i:ids){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
        return;
    }
    long long totalR=0;
    for(int i:ids)totalR+=R[i];
    
    double bestCost=1e18;
    int bestK=-1,bestSp=-1;
    bool bestHoriz=true;
    vector<int> bestOrder;
    
    for(int dir=0;dir<2;dir++){
        bool horiz=(dir==0);
        if(horiz&&w<2)continue;
        if(!horiz&&h<2)continue;
        
        vector<int>sorted_ids=ids;
        if(horiz)sort(sorted_ids.begin(),sorted_ids.end(),[](int a,int b){return X[a]<X[b]||(X[a]==X[b]&&Y[a]<Y[b]);});
        else sort(sorted_ids.begin(),sorted_ids.end(),[](int a,int b){return Y[a]<Y[b]||(Y[a]==Y[b]&&X[a]<X[b]);});
        
        long long cumR=0;
        for(int k=0;k<(int)sorted_ids.size()-1;k++){
            cumR+=R[sorted_ids[k]];
            double frac=(double)cumR/totalR;
            if(horiz){
                int lo=X[sorted_ids[k]]+1;
                int hi=X[sorted_ids[k+1]]+1;
                int ideal=x0+(int)(frac*w+0.5);
                int sp=max(lo,min(hi,ideal));
                sp=max(x0+1,min(x1-1,sp));
                if(sp<=X[sorted_ids[k]]||sp>X[sorted_ids[k+1]])continue;
                double leftA=(double)(sp-x0)*h, rightA=(double)(x1-sp)*h;
                double cost=abs(leftA/cumR-1.0)+abs(rightA/(totalR-cumR)-1.0);
                if(cost<bestCost){bestCost=cost;bestK=k;bestSp=sp;bestHoriz=true;bestOrder=sorted_ids;}
            } else {
                int lo=Y[sorted_ids[k]]+1;
                int hi=Y[sorted_ids[k+1]]+1;
                int ideal=y0+(int)(frac*h+0.5);
                int sp=max(lo,min(hi,ideal));
                sp=max(y0+1,min(y1-1,sp));
                if(sp<=Y[sorted_ids[k]]||sp>Y[sorted_ids[k+1]])continue;
                double leftA=(double)w*(sp-y0), rightA=(double)w*(y1-sp);
                double cost=abs(leftA/cumR-1.0)+abs(rightA/(totalR-cumR)-1.0);
                if(cost<bestCost){bestCost=cost;bestK=k;bestSp=sp;bestHoriz=false;bestOrder=sorted_ids;}
            }
        }
    }
    if(bestK<0){
        for(int i:ids){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
        return;
    }
    vector<int>L(bestOrder.begin(),bestOrder.begin()+bestK+1),Ri2(bestOrder.begin()+bestK+1,bestOrder.end());
    if(bestHoriz){bsp(L,x0,y0,bestSp,y1);bsp(Ri2,bestSp,y0,x1,y1);}
    else{bsp(L,x0,y0,x1,bestSp);bsp(Ri2,x0,bestSp,x1,y1);}
}

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    auto t0=chrono::steady_clock::now();
    auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    cin>>n;
    for(int i=0;i<n;i++)cin>>X[i]>>Y[i]>>R[i];
    vector<int>all(n);iota(all.begin(),all.end(),0);
    bsp(all,0,0,10000,10000);
    
    int sA[200],sB[200],sC[200],sD[200];
    mt19937 rng(42);
    double T0=0.05,T1=0.0001;
    int iter=0;
    while(elapsed()<4.7){
        double t=elapsed()/4.7;
        double T=T0*pow(T1/T0,t);
        int i=rng()%n;
        int side=rng()%4;
        int range=max(1,(int)(300*(1-t)+2));
        int delta=(int)(rng()%((unsigned)(2*range+1)))-range;
        if(delta==0)continue;
        
        // Save all
        memcpy(sA,A,sizeof(int)*n);memcpy(sB,B,sizeof(int)*n);memcpy(sC,C,sizeof(int)*n);memcpy(sD,D,sizeof(int)*n);
        double oldTotal=0;for(int j=0;j<n;j++)oldTotal+=calcScore(j);
        
        if(side==0)A[i]+=delta;else if(side==1)B[i]+=delta;else if(side==2)C[i]+=delta;else D[i]+=delta;
        A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
        if(A[i]>=C[i]||B[i]>=D[i]||X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){
            memcpy(A,sA,sizeof(int)*n);memcpy(B,sB,sizeof(int)*n);memcpy(C,sC,sizeof(int)*n);memcpy(D,sD,sizeof(int)*n);
            continue;
        }
        bool ok=true;
        for(int j=0;j<n&&ok;j++)if(j!=i){
            if(max(A[i],A[j])<min(C[i],C[j])&&max(B[i],B[j])<min(D[i],D[j])){
                int dx1=C[i]-A[j],dx2=C[j]-A[i],dy1=D[i]-B[j],dy2=D[j]-B[i];
                int mn=min({dx1,dx2,dy1,dy2});
                if(mn==dx1)A[j]=C[i];else if(mn==dx2)C[j]=A[i];else if(mn==dy1)B[j]=D[i];else D[j]=B[i];
                if(A[j]>=C[j]||B[j]>=D[j]||X[j]<A[j]||X[j]>=C[j]||Y[j]<B[j]||Y[j]>=D[j])ok=false;
            }
        }
        if(!ok){memcpy(A,sA,sizeof(int)*n);memcpy(B,sB,sizeof(int)*n);memcpy(C,sC,sizeof(int)*n);memcpy(D,sD,sizeof(int)*n);continue;}
        double newTotal=0;for(int j=0;j<n;j++)newTotal+=calcScore(j);
        double dS=newTotal-oldTotal;
        if(dS>0||exp(dS/T)>(rng()%10000)/10000.0){
            // accept
        }else{
            memcpy(A,sA,sizeof(int)*n);memcpy(B,sB,sizeof(int)*n);memcpy(C,sC,sizeof(int)*n);memcpy(D,sD,sizeof(int)*n);
        }
        iter++;
    }
    for(int i=0;i<n;i++)cout<<A[i]<<" "<<B[i]<<" "<<C[i]<<" "<<D[i]<<"\n";
}
