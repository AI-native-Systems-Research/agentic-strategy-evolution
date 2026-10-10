#include <bits/stdc++.h>
using namespace std;
int main(){
    long long k;
    scanf("%lld",&k);
    if(k==1){
        printf("1\nHALT PUSH 1 GOTO 1\n");
        return 0;
    }
    long long m=(k-1)/2;
    vector<int> bits;
    {long long t=m; while(t>0){bits.push_back(t&1);t>>=1;} reverse(bits.begin(),bits.end());}
    // bits[0]=1 (MSB)
    // For each bit after MSB we need 3 instructions (doubling loop), +1 if bit=1
    // Plus 1 instruction to push initial element, plus 2 instructions for final pop loop + halt
    // Each level i uses value (i+1)
    vector<string> prog;
    int val=1;
    // Instruction 1: push first element (value 1), goto next
    // We'll build instructions, then fix GOTO targets
    // Phase 1: push one element of value val=1
    // Use HALT instruction that pushes (since stack is empty, it halts... no wait, we need it to NOT halt first)
    // Actually instruction format: HALT PUSH b GOTO y -> if stack empty, halt; else push b, goto y
    // So first instruction must be HALT PUSH 1 GOTO 2 -> stack is empty, so it halts after 1 step. That's only for k=1.
    // For k>1, first instruction should push something. Use POP with a value that's not on stack (stack is empty -> push)
    prog.push_back("POP 1024 GOTO 999 PUSH 1 GOTO 999"); // placeholder, fix gotos later
    // This pushes 1, goes to next instruction
    int cur=1; // current level value
    for(int i=1;i<(int)bits.size();i++){
        int nv=cur+1;
        // Doubling loop: POP cur -> GOTO (after loop) PUSH nv GOTO (this instr)
        // which pops one cur, pushes two nv? No, that's net +1 per pop.
        // Need: POP cur GOTO X PUSH nv GOTO self  (this replaces each cur with two nv? No, one pop -> one push of nv, net 0 change... 
        // Let me just use: pop cur, push nv, push nv pattern with 2 instructions
        int base=prog.size();
        prog.push_back("POP "+to_string(cur)+" GOTO 999 PUSH "+to_string(nv)+" GOTO 999");
        prog.push_back("POP 1024 GOTO 999 PUSH "+to_string(nv)+" GOTO "+to_string(base+1));
        if(bits[i]) prog.push_back("POP 1024 GOTO 999 PUSH "+to_string(nv)+" GOTO 999");
        cur=nv;
    }
    // Pop all and halt
    int popinst=prog.size();
    prog.push_back("POP "+to_string(cur)+" GOTO "+to_string(popinst+1)+" PUSH 1024 GOTO 999");
    prog.push_back("HALT PUSH 1 GOTO "+to_string(prog.size()+1));
    // TODO: fix goto targets properly
    printf("%d\n",(int)prog.size());
    for(auto&s:prog) printf("%s\n",s.c_str());
}
