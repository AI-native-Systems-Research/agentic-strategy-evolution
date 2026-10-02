Let me check the full iter-1 h-main patch to understand the proven solution, then design iter-2.Now I have everything needed. Iter-1 scored 100 with BnB+DLS. For iter-2 (real mode, tier ≤ 2), I'll design an ablation to understand whether the DLS component is necessary or if refined BnB alone suffices, plus confirm the proven solution.

Let me write the artifacts.Now validate:Validation passes. 

**Summary:** Iter-2 design is a tier-2 ablation study. h-main reproduces the proven BnB+DLS hybrid (score 100 in iter-1). h-ablation removes the DLS tabu search fallback and gives BnB the full 1950ms budget, testing RP-1's claim that pure BnB plateaus at 88-90% on hard dense instances. Two judge calls total.