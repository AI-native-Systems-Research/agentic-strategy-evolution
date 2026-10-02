Let me read the campaign context and bundle files first.The solution.cpp is a stub. I need the BnB-only code from iter-2. Let me get it.Good. I have the BnB-only code from iter-2's h-ablation patch. Now let me execute the experiment.Let me set up variables and create the h-main solution, then create the patches.Now apply the h-ablation patch from iter-2 (which is the BnB-only solution with 1950ms) and create the h-main patch:Now create h-robustness patch (same code, 1000ms instead of 1950ms):Now write the experiment plan and execute:Now execute h-main:Both arms scored 100. Now write findings and principle updates.Now also apply the winning solution as a cumulative patch:Now validate:Validation passes. 

**Summary:** Both arms CONFIRMED.
- **h-main**: BnB-only with degeneracy ordering, 1950ms budget → SCORE: 100
- **h-robustness**: Same algorithm, 1000ms budget → SCORE: 100

The solution has a comfortable ≥2x timing margin. RP-1 updated to reflect the 1000ms sufficiency finding.