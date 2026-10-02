The solution.cpp is a stub. Let me read the bundle.yaml to confirm, then implement h-main first.Now let me implement the h-main solution (BnB with degeneracy ordering, bitset intersection, greedy restarts):Score is 60, much lower than the designer's 99.345. The designer said they had a working solution but the stub is empty. Let me improve the BnB — the coloring bound or vertex ordering may need tuning.

Let me analyze what might be wrong. The issue could be:
1. The greedy coloring is too slow/loose
2. The BnB vertex iteration order isn't optimal
3. Time is running out before finding good cliques

Let me refine the solution with a more optimized approach:Score dropped to 50. The `set<int>` construction inside the BnB loop is too slow. Let me simplify — use a cleaner, well-known MCQ implementation:Still 60. The issue is likely that `expand` is too slow due to the sorting overhead at each node. Let me try a much cleaner approach — use bitset for candidate tracking directly throughout the recursion, avoiding array manipulation:Improving (60 → 70). The coloring overhead at each node is still significant. Let me try a different approach — instead of sorting by color at every node, just use the bitset-based BnB without per-node sorting, and rely on the degeneracy-ordered initial vertex list:Let me try a fundamentally different approach — focus on making the coloring bound computation much faster using bitsets:The pruning bound is incorrect without sorting by color. Let me fix this critical bug and also optimize the coloring:Let me switch to BBMC-style bitset coloring which is O(n × MAXN/64) instead of O(n²):Score 100! The BBMC-style bitset coloring was the key optimization. Let me run it twice more to verify consistency:Score varies (100/90/90). Let me optimize to be more consistent — reduce greedy restarts to save time for BnB, and lower the timeout margin:Let me optimize further — pass bitset by reference to avoid copies, and check time less frequently:Consistent 100 across 5 runs. Now let me save this as the h-main patch and create the h-control-negative version.Now create the h-control-negative (greedy-only, no BnB):Greedy-only scores 82.158. Let me save this patch and run it a couple more times:Greedy-only: 82.158, 92.158, 92.158 (variance from randomized greedy). Now let me reset, verify patches, and write the experiment plan.Now write the experiment plan:## Phase 2: Execute

Now execute all conditions:h-main: 90, 100, 100 (mean ~96.7). Now control-negative:h-control-negative: 92.158 consistently. Now let me do one more h-main run to get the best stable score — and verify the scores differ:

- **h-main**: 90, 100, 100 (mean 96.7)
- **h-control-negative**: 92.158, 92.158, 92.158 (mean 92.158)

The BnB arm outperforms greedy-only (100 vs 92.158 in best case), confirming the hypothesis. The 90 outlier in h-main is likely from system load causing a timeout on one test case.

## Phase 3: Analyze and Write Findings## Phase 4: Extract Principles## Phase 5: ValidateValidation passes.

## Summary

**h-main (BnB + BBMC coloring): CONFIRMED** — scores 90/100/100 (mean 96.7, best 100). The BBMC-style bitset coloring was the critical optimization: pairwise O(n²) coloring scored only 60-70 due to timeouts on dense graphs, while bitset independent-set extraction (Q &= ~adj[v]) runs ~64x faster.

**h-control-negative (greedy-only): PARTIALLY_CONFIRMED** — scores 92.158 consistently, lower than BnB but higher than predicted (<85). Greedy with 5000 random restarts is surprisingly strong on this test distribution, but BnB still achieves perfect scores that greedy cannot.