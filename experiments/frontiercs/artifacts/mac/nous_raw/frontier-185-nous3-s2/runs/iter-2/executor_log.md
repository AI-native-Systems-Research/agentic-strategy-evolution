Let me read the key artifacts to understand the experiment.Now let me set up directories and create the h-main solution.Good. Now let me write the full BnB+DLS hybrid solution for h-main:Now create the h-main patch and run the judge:h-main scores 100. Save the result and prepare the ablation:Now create the h-ablation solution (BnB only, no DLS, 1950ms time limit):Now create the ablation version — remove DLS, give BnB 1950ms:Interesting — h-ablation also scores 100. BnB alone with 1950ms is sufficient. Let me save the result and write all artifacts.Now write the experiment plan, findings, and principle updates:Now validate:Fix the schema issues:Validation passes.

**Summary:** Both arms executed successfully.

- **h-main** (BnB+DLS hybrid): Score 100 — **CONFIRMED**, reproducing iter-1's result.
- **h-ablation** (BnB only, no DLS, 1950ms): Score 100 — **REFUTED** the prediction that DLS is necessary. BnB alone with degeneracy ordering + coloring bound suffices for this judge's test set.

Key finding: The DLS tabu search fallback is redundant. RP-1's claim that "pure BnB plateaus around 88-90%" was based on BnB *without* degeneracy ordering. With degeneracy ordering and the full 1950ms budget, BnB solves all instances optimally. The simpler BnB-only solution achieves score 100.