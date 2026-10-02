#include <bits/stdc++.h>
using namespace std;

int main(){
    long long k;
    scanf("%lld",&k);
    if(k==1){
        printf("1\nHALT PUSH 1 GOTO 1\n");
        return 0;
    }
    // We'll build instructions. Strategy: binary representation of k.
    // k is odd, k>=3.
    // We decompose k. Let's use the approach of building a program
    // that simulates a binary counter.
    
    // Represent k in binary, build from MSB to LSB.
    vector<int> bits;
    long long tmp=k;
    while(tmp>0){bits.push_back(tmp&1);tmp>>=1;}
    reverse(bits.begin(),bits.end()); // MSB first
    
    // We'll use a construction with ~5 instructions per bit
    // Using values 1..31 for different bit levels
    int n_instr = 0;
    vector<string> instrs;
    auto add=[&](string s)->int{ instrs.push_back(s); return ++n_instr;};
    
    // First bit is always 1 (MSB)
    // Start: instruction 1 is HALT PUSH 1 GOTO 2
    // This gives us 1 step if stack empty.
    // For subsequent bits, we double and optionally add 1.
    
    add("HALT PUSH 1 GOTO 2"); // instr 1: 1 step if done, else push 1 goto 2
    for(int i=1;i<(int)bits.size();i++){
        int base=n_instr;
        // Double: push then pop cycle
        int pop_instr=base+1; // will be added next
        int next_halt=base+3;
        add("POP 1 GOTO "+to_string(base+3)+" PUSH 1 GOTO "+to_string(base+1));
        add("HALT PUSH 1 GOTO "+to_string(base+2));
        if(bits[i]==1){
            // add one extra step
            add("HALT PUSH 1 GOTO "+to_string(base+4));
            add("POP 1 GOTO "+to_string(base+5)+" PUSH 1 GOTO "+to_string(base+1));
            add("HALT PUSH 1 GOTO "+to_string(base+4));
        }
    }
    printf("%d\n",n_instr);
    for(auto&s:instrs) printf("%s\n",s.c_str());
}
