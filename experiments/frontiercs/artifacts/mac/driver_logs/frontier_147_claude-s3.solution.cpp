#include<bits/stdc++.h>
using namespace std;
int n;
int X[205],Y[205];
long long R[205];
int A[205],B[205],C[205],D[205];

double calc_score(int i){
    if(A[i]>=C[i]||B[i]>=D[i])return 0;
    if(X[i]<A[i]||X[i]>=C[i]||Y[i]<B[i]||Y[i]>=D[i])return 0;
    double s=(double)(C[i]-A[i])*(double)(D[i]-B[i]);
    double r=(double)R[i];
    double ratio=min(r,s)/max(r,s);
    return 1.0-(1.0-ratio)*(1.0-ratio);
}

bool overlaps(int i,int j){
    return A[i]<C[j]&&A[j]<C[i]&&B[i]<D[j]&&B[j]<D[i];
}

bool valid(int i){
    return A[i]<C[i]&&B[i]<D[i]&&A[i]>=0&&B[i]>=0&&C[i]<=10000&&D[i]<=10000&&X[i]>=A[i]&&X[i]<C[i]&&Y[i]>=B[i]&&Y[i]<D[i];
}

int main(){
    scanf("%d",&n);
    for(int i=0;i<n;i++)scanf("%d%d%lld",&X[i],&Y[i],&R[i]);
    for(int i=0;i<n;i++){A[i]=X[i];B[i]=Y[i];C[i]=X[i]+1;D[i]=Y[i]+1;}
    
    auto no_overlap=[&](int i)->bool{
        for(int j=0;j<n;j++)if(j!=i&&overlaps(i,j))return false;
        return true;
    };
    
    mt19937 rng(42);
    double best_total=0;
    for(int i=0;i<n;i++)best_total+=calc_score(i);
    
    for(int iter=0;iter<800;iter++){
        for(int i=0;i<n;i++){
            double s=(double)(C[i]-A[i])*(double)(D[i]-B[i]);
            double r=(double)R[i];
            int dirs[]={0,1,2,3};
            shuffle(dirs,dirs+4,rng);
            for(int d:dirs){
                int oa=A[i],ob=B[i],oc=C[i],od=D[i];
                int delta=(s<r)?1:-1;
                if(d==0)A[i]-=delta;
                else if(d==1)B[i]-=delta;
                else if(d==2)C[i]+=delta;
                else D[i]+=delta;
                if(!valid(i)||!no_overlap(i)){
                    A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
                }
            }
        }
    }
    
    // More iterations with finer control
    for(int iter=0;iter<200;iter++){
        for(int i=0;i<n;i++){
            double old_sc=calc_score(i);
            double s=(double)(C[i]-A[i])*(double)(D[i]-B[i]);
            double r=(double)R[i];
            for(int d=0;d<4;d++){
                for(int delta:{-1,1}){
                    int oa=A[i],ob=B[i],oc=C[i],od=D[i];
                    if(d==0)A[i]+=delta;
                    else if(d==1)B[i]+=delta;
                    else if(d==2)C[i]+=delta;
                    else D[i]+=delta;
                    if(valid(i)&&no_overlap(i)&&calc_score(i)>old_sc){
                        old_sc=calc_score(i);
                    } else {
                        A[i]=oa;B[i]=ob;C[i]=oc;D[i]=od;
                    }
                }
            }
        }
    }
    
    for(int i=0;i<n;i++)printf("%d %d %d %d\n",A[i],B[i],C[i],D[i]);
}
