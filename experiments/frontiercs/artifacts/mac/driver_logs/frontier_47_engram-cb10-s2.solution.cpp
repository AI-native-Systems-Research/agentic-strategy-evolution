#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    string input((istreambuf_iterator<char>(cin)),istreambuf_iterator<char>());
    int pos=0,len=input.size();
    
    auto ws=[&](){while(pos<len&&isspace((unsigned char)input[pos]))pos++;};
    
    function<void()> skipVal;
    
    auto parseStr=[&]()->string{
        ws();
        if(pos>=len||input[pos]!='"')return"";
        pos++;string r;
        while(pos<len&&input[pos]!='"'){
            if(input[pos]=='\\'){pos++;if(pos<len)r+=input[pos];}
            else r+=input[pos];
            pos++;
        }
        pos++;return r;
    };
    
    auto parseNum=[&]()->double{
        ws();int s=pos;
        if(pos<len&&input[pos]=='-')pos++;
        while(pos<len&&isdigit((unsigned char)input[pos]))pos++;
        if(pos<len&&input[pos]=='.'){pos++;while(pos<len&&isdigit((unsigned char)input[pos]))pos++;}
        if(pos<len&&(input[pos]=='e'||input[pos]=='E')){pos++;if(pos<len&&(input[pos]=='+'||input[pos]=='-'))pos++;while(pos<len&&isdigit((unsigned char)input[pos]))pos++;}
        return stod(input.substr(s,pos-s));
    };
    
    auto parseBool=[&]()->bool{
        ws();
        if(input[pos]=='t'){pos+=4;return true;}
        pos+=5;return false;
    };
    
    skipVal=[&](){
        ws();
        if(pos>=len)return;
        char c=input[pos];
        if(c=='"'){parseStr();}
        else if(c=='{'){
            pos++;ws();
            if(pos<len&&input[pos]=='}'){pos++;return;}
            while(true){
                parseStr();ws();pos++;// :
                skipVal();ws();
                if(pos>=len||input[pos]!=',')break;
                pos++;
            }
            ws();if(pos<len&&input[pos]=='}')pos++;
        }else if(c=='['){
            pos++;ws();
            if(pos<len&&input[pos]==']'){pos++;return;}
            while(true){
                skipVal();ws();
                if(pos>=len||input[pos]!=',')break;
                pos++;
            }
            ws();if(pos<len&&input[pos]==']')pos++;
        }else if(c=='t')pos+=4;
        else if(c=='f')pos+=5;
        else if(c=='n')pos+=4;
        else parseNum();
    };
    
    int W=0,H=0;
    bool allowRotate=false;
    struct Item{string type;int w,h,limit;double v;};
    vector<Item> items;
    
    // Parse top-level object
    ws();pos++;// {
    while(true){
        ws();if(pos>=len||input[pos]=='}'){pos++;break;}
        if(input[pos]==','){pos++;continue;}
        string key=parseStr();ws();pos++;// :
        ws();
        if(key=="bin"){
            pos++;// {
            while(true){
                ws();if(pos>=len||input[pos]=='}'){pos++;break;}
                if(input[pos]==','){pos++;continue;}
                string k=parseStr();ws();pos++;ws();
                if(k=="W"||k=="w"||k=="width"){W=(int)round(parseNum());}
                else if(k=="H"||k=="h"||k=="height"){H=(int)round(parseNum());}
                else if(k=="allow_rotate"||k=="allowRotate"){allowRotate=parseBool();}
                else skipVal();
            }
        }else if(key=="items"){
            pos++;// [
            while(true){
                ws();if(pos>=len||input[pos]==']'){pos++;break;}
                if(input[pos]==','){pos++;continue;}
                pos++;// {
                Item it;it.w=0;it.h=0;it.v=0;it.limit=0;
                while(true){
                    ws();if(pos>=len||input[pos]=='}'){pos++;break;}
                    if(input[pos]==','){pos++;continue;}
                    string k=parseStr();ws();pos++;ws();
                    if(k=="type")it.type=parseStr();
                    else if(k=="w"||k=="width")it.w=(int)round(parseNum());
                    else if(k=="h"||k=="height")it.h=(int)round(parseNum());
                    else if(k=="v"||k=="value")it.v=parseNum();
                    else if(k=="limit"||k=="count")it.limit=(int)round(parseNum());
                    else skipVal();
                }
                items.push_back(it);
            }
        }else skipVal();
    }
    
    int M=items.size();
    struct Rect{int x,y,w,h;};
    struct Placement{string type;int x,y;bool rot;};
    
    struct Bin{
        int bW,bH;
        vector<Rect> fr;
        void init(int W_,int H_){bW=W_;bH=H_;fr.clear();fr.push_back({0,0,W_,H_});}
        void prune(){
            int n=fr.size();
            vector<bool> del(n,false);
            for(int i=0;i<n;i++)if(!del[i])
                for(int j=0;j<n;j++)if(i!=j&&!del[j])
                    if(fr[i].x>=fr[j].x&&fr[i].y>=fr[j].y&&
                       fr[i].x+fr[i].w<=fr[j].x+fr[j].w&&
                       fr[i].y+fr[i].h<=fr[j].y+fr[j].h){del[i]=true;break;}
            vector<Rect>nf;for(int i=0;i<n;i++)if(!del[i])nf.push_back(fr[i]);
            fr=nf;
        }
        bool place(int rw,int rh,int&px,int&py,int m){
            int bs=INT_MAX,bs2=INT_MAX,bi=-1;px=py=0;
            for(int i=0;i<(int)fr.size();i++){
                auto&f=fr[i];
                if(rw<=f.w&&rh<=f.h){
                    int ss=f.w-rw,sl=f.h-rh,s,s2;
                    if(m==0){s=min(ss,sl);s2=max(ss,sl);}
                    else if(m==1){s=max(ss,sl);s2=min(ss,sl);}
                    else if(m==2){s=f.w*f.h-rw*rh;s2=min(ss,sl);}
                    else{s=f.y+rh;s2=f.x+rw;}
                    if(s<bs||(s==bs&&s2<bs2)){bs=s;bs2=s2;bi=i;px=f.x;py=f.y;}
                }
            }
            if(bi==-1)return false;
            Rect pl={px,py,rw,rh};
            vector<Rect>nf;
            for(auto&f:fr){
                if(pl.x>=f.x+f.w||pl.x+pl.w<=f.x||pl.y>=f.y+f.h||pl.y+pl.h<=f.y){nf.push_back(f);continue;}
                if(pl.x>f.x)nf.push_back({f.x,f.y,pl.x-f.x,f.h});
                if(pl.x+pl.w<f.x+f.w)nf.push_back({pl.x+pl.w,f.y,f.x+f.w-pl.x-pl.w,f.h});
                if(pl.y>f.y)nf.push_back({f.x,f.y,f.w,pl.y-f.y});
                if(pl.y+pl.h<f.y+f.h)nf.push_back({f.x,pl.y+pl.h,f.w,f.y+f.h-pl.y-pl.h});
            }
            fr=nf;prune();return true;
        }
    };
    
    double bestProfit=0;
    vector<Placement> bestPl;
    
    auto tryOrder=[&](vector<int>&ord,int method){
        Bin bin;bin.init(W,H);
        vector<int>used(M,0);
        vector<Placement>pls;
        double total=0;
        for(int idx:ord){
            while(used[idx]<items[idx].limit){
                int pw=items[idx].w,ph=items[idx].h;
                int px,py;bool rot=false;bool ok=false;
                // Try normal
                Bin b1=bin;
                int px1,py1;
                bool ok1=(pw<=W&&ph<=H&&b1.place(pw,ph,px1,py1,method));
                // Try rotated
                bool ok2=false;int px2,py2;Bin b2;
                if(allowRotate&&pw!=ph){
                    b2=bin;
                    ok2=(ph<=W&&pw<=H&&b2.place(ph,pw,px2,py2,method));
                }
                if(ok1&&ok2){
                    // pick better fit (lower leftover)
                    bin=b1;px=px1;py=py1;rot=false;ok=true;
                }else if(ok1){bin=b1;px=px1;py=py1;rot=false;ok=true;}
                else if(ok2){bin=b2;px=px2;py=py2;rot=true;ok=true;}
                if(!ok)break;
                pls.push_back({items[idx].type,px,py,rot});
                total+=items[idx].v;
                used[idx]++;
            }
        }
        if(total>bestProfit){bestProfit=total;bestPl=pls;}
    };
    
    auto t0=chrono::steady_clock::now();
    auto ms=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
    
    for(int s=0;s<8&&ms()<2.5;s++){
        vector<int>ord(M);iota(ord.begin(),ord.end(),0);
        sort(ord.begin(),ord.end(),[&](int a,int b){
            double va=items[a].v,vb=items[b].v;
            int aa=items[a].w*items[a].h,ab=items[b].w*items[b].h;
            switch(s){
                case 0:return va/aa>vb/ab;
                case 1:return va>vb;
                case 2:return aa>ab;
                case 3:return max(items[a].w,items[a].h)>max(items[b].w,items[b].h);
                case 4:return items[a].h>items[b].h;
                case 5:return items[a].w>items[b].w;
                case 6:return va*items[a].limit>vb*items[b].limit;
                default:return va*items[a].limit/aa>vb*items[b].limit/ab;
            }
        });
        for(int m=0;m<4;m++)tryOrder(ord,m);
    }
    
    mt19937 rng(42);
    while(ms()<2.5){
        vector<int>ord(M);iota(ord.begin(),ord.end(),0);
        shuffle(ord.begin(),ord.end(),rng);
        tryOrder(ord,rng()%4);
    }
    
    cout<<"{\"placements\":[";
    for(int i=0;i<(int)bestPl.size();i++){
        if(i)cout<<",";
        auto&p=bestPl[i];
        cout<<"{\"type\":\""<<p.type<<"\",\"x\":"<<p.x<<",\"y\":"<<p.y<<",\"rot\":"<<(p.rot?"true":"false")<<"}";
    }
    cout<<"]}"<<endl;
}
