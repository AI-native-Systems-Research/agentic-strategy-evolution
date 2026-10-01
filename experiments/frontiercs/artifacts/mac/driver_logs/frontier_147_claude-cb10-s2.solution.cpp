#include<bits/stdc++.h>
using namespace std;

int n;
int X[200],Y[200];
long long R[200];
int A[200],B[200],C[200],D[200];
int bA[200],bB[200],bC[200],bD[200];

double calcScore(int i){
    if(A[i]>=C[i]||B[i]>=D[i])return 0;
    if(X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i])return 0;
    double s=(double)(C[i]-A[i])*(double)(D[i]-B[i]);
    double r=(double)R[i];
    double ratio=min(r,s)/max(r,s);
    return 1.0-(1.0-ratio)*(1.0-ratio);
}

double totalScore(){
    double s=0;
    for(int i=0;i<n;i++)s+=calcScore(i);
    return s;
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
                double lR=cumR,rR=totalR-cumR;
                double cost=0;
                // Use squared ratio error as cost
                double lr=min(leftA,lR)/max(leftA,lR);
                double rr=min(rightA,rR)/max(rightA,rR);
                cost=(1-lr)*(1-lr)+(1-rr)*(1-rr);
                if(cost<bestCost){bestCost=cost;bestK=k;bestSp=sp;bestHoriz=true;bestOrder=sorted_ids;}
            } else {
                int lo=Y[sorted_ids[k]]+1;
                int hi=Y[sorted_ids[k+1]]+1;
                int ideal=y0+(int)(frac*h+0.5);
                int sp=max(lo,min(hi,ideal));
                sp=max(y0+1,min(y1-1,sp));
                if(sp<=Y[sorted_ids[k]]||sp>Y[sorted_ids[k+1]])continue;
                double leftA=(double)w*(sp-y0), rightA=(double)w*(y1-sp);
                double lR=cumR,rR=totalR-cumR;
                double lr=min(leftA,lR)/max(leftA,lR);
                double rr=min(rightA,rR)/max(rightA,rR);
                double cost=(1-lr)*(1-lr)+(1-rr)*(1-rr);
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
    
    double bestTotal=totalScore();
    memcpy(bA,A,sizeof(int)*n);memcpy(bB,B,sizeof(int)*n);memcpy(bC,C,sizeof(int)*n);memcpy(bD,D,sizeof(int)*n);
    
    double scores[200];
    for(int i=0;i<n;i++)scores[i]=calcScore(i);
    double curTotal=bestTotal;
    
    mt19937 rng(42);
    double timeLimit=4.7;
    
    while(elapsed()<timeLimit){
        double t=elapsed()/timeLimit;
        double T=0.05*pow(0.0001/0.05,t);
        int i=rng()%n;
        int side=rng()%4;
        int range=max(1,(int)(500*(1-t)+1));
        int delta=(int)(rng()%((unsigned)(2*range+1)))-range;
        if(delta==0)continue;
        
        int oA=A[i],oB=B[i],oC=C[i],oD=D[i];
        if(side==0)A[i]+=delta;else if(side==1)B[i]+=delta;else if(side==2)C[i]+=delta;else D[i]+=delta;
        A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
        if(A[i]>=C[i]||B[i]>=D[i]||X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){A[i]=oA;B[i]=oB;C[i]=oC;D[i]=oD;continue;}
        
        int saved[200][4];int cnt=0;
        double oldS=scores[i];bool ok=true;
        for(int j=0;j<n&&ok;j++)if(j!=i){
            if(max(A[i],A[j])<min(C[i],C[j])&&max(B[i],B[j])<min(D[i],D[j])){
                saved[cnt][0]=A[j];saved[cnt][1]=B[j];saved[cnt][2]=C[j];saved[cnt][3]=D[j];
                int dx1=C[i]-A[j],dx2=C[j]-A[i],dy1=D[i]-B[j],dy2=D[j]-B[i];
                int mn=min({dx1,dx2,dy1,dy2});
                if(mn==dx1)A[j]=C[i];else if(mn==dx2)C[j]=A[i];else if(mn==dy1)B[j]=D[i];else D[j]=B[i];
                if(A[j]>=C[j]||B[j]>=D[j]||X[j]<A[j]||X[j]>=C[j]||Y[j]<B[j]||Y[j]>=D[j])ok=false;
                else{oldS+=scores[j];saved[cnt][0]|=(j<<16);/* store j */}
                // encode j in saved
                // Actually let me redo
                cnt++;
            }
        }
        // Redo with proper storage
        // Revert and redo properly
        // This got messy, let me simplify
        {
            A[i]=oA;B[i]=oB;C[i]=oC;D[i]=oD;
            // redo
            if(side==0)A[i]=oA+delta;else if(side==1)B[i]=oB+delta;else if(side==2)C[i]=oC+delta;else D[i]=oD+delta;
            A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
        }
        // Just revert all affected
        // Actually the code above already modified neighbors. Let me just use the simple full approach.
        // Revert everything
        for(int cc=cnt-1;cc>=0;cc--){
            // can't recover properly, just use memcpy approach
        }
        // Fall back to simple approach
        A[i]=oA;B[i]=oB;C[i]=oC;D[i]=oD;
        
        // Simple correct version:
        {
            int sA2[200],sB2[200],sC2[200],sD2[200];
            memcpy(sA2,A,4*n);memcpy(sB2,B,4*n);memcpy(sC2,C,4*n);memcpy(sD2,D,4*n);
            if(side==0)A[i]+=delta;else if(side==1)B[i]+=delta;else if(side==2)C[i]+=delta;else D[i]+=delta;
            A[i]=max(0,A[i]);B[i]=max(0,B[i]);C[i]=min(10000,C[i]);D[i]=min(10000,D[i]);
            if(A[i]>=C[i]||B[i]>=D[i]||X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i]){memcpy(A,sA2,4*n);memcpy(B,sB2,4*n);memcpy(C,sC2,4*n);memcpy(D,sD2,4*n);continue;}
            bool ok2=true;
            for(int j=0;j<n&&ok2;j++)if(j!=i){
                if(max(A[i],A[j])<min(C[i],C[j])&&max(B[i],B[j])<min(D[i],D[j])){
                    int dx1=C[i]-A[j],dx2=C[j]-A[i],dy1=D[i]-B[j],dy2=D[j]-B[i];
                    int mn=min({dx1,dx2,dy1,dy2});
                    if(mn==dx1)A[j]=C[i];else if(mn==dx2)C[j]=A[i];else if(mn==dy1)B[j]=D[i];else D[j]=B[i];
                    if(A[j]>=C[j]||B[j]>=D[j]||X[j]<A[j]||X[j]>=C[j]||Y[j]<B[j]||Y[j]>=D[j])ok2=false;
                }
            }
            if(!ok2){memcpy(A,sA2,4*n);memcpy(B,sB2,4*n);memcpy(C,sC2,4*n);memcpy(D,sD2,4*n);continue;}
            double nT=0;for(int j=0;j<n;j++){scores[j]=calcScore(j);nT+=scores[j];}
            double dS=nT-curTotal;
            if(dS>0||exp(dS/T)>(rng()%10000)/10000.0){
                curTotal=nT;
                if(curTotal>bestTotal){bestTotal=curTotal;memcpy(bA,A,4*n);memcpy(bB,B,4*n);memcpy(bC,C,4*n);memcpy(bD,D,4*n);}
            }else{memcpy(A,sA2,4*n);memcpy(B,sB2,4*n);memcpy(C,sC2,4*n);memcpy(D,sD2,4*n);for(int j=0;j<n;j++)scores[j]=calcScore(j);}
        }
    }
    for(int i=0;i<n;i++)cout<<bA[i]<<" "<<bB[i]<<" "<<bC[i]<<" "<<bD[i]<<"\n";
}
