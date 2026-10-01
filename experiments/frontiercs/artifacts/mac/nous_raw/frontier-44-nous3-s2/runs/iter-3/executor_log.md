Validation already passes. Let me check the current state more carefully — the results show some inconsistency (runs 4-5 scored ~78.8 vs runs 1-3 at ~72.2).I see validation passes but there's a significant issue — the results show h-main at ~72.2 while h-control-negative scored ~78.8, meaning h-main is actually WORSE than baseline. Let me investigate properly.Now I understand the situation. The iter-3 findings claim CONFIRMED at 72.2, but the actual iter-2 best is ~78.85 (not 69.5 as the bundle assumed). The h-main approach REGRESSED by ~6.6 points. I need to fix the findings.

Let me verify by running the experiment myself to confirm the numbers.Good. Now I have solid data. Let me summarize and fix the artifacts.

**h-main** (two-phase grid-guided 2-opt): 72.20, 72.17, 72.20, 67.18*, 72.20, 72.19, 72.18, 72.16 → ~72.19 mean (excl. outlier)
**h-control-negative** (iter-2 best): 78.49, 78.84, 78.85, 78.81, 78.78, 78.79, 73.76*, 73.81*, 78.86, 78.81 → ~78.58 mean (or ~78.80 excl. lower outliers)

h-main is clearly WORSE than the iter-2 baseline. The bundle's premise that iter-2 scored 69.5 was incorrect — iter-2's best solution scored ~78.8.Now update the findings.json with corrected analysis:Now validate:Validation passes. Let me also reset the worktree:**Summary:**

**h-main: REFUTED.** The two-phase grid-guided 2-opt SA scored ~72.2, which is a **6.6-point regression** from the actual iter-2 best of ~78.8. The bundle's design was based on an incorrect baseline assumption (iter-2 = 69.5, when it's actually 78.8 from the iter-2 h-ablation solution).

The key finding: the iter-3 approach omitted penalty-aware delta computation, Or-opt relocation, and prime scheduling — all present in the iter-2 cumulative best. These components collectively contribute ~6.6 points, far more than the "≤1%" previously estimated (RP-2 revised). At high tour quality, penalty-aware moves matter because distance-based improvements become scarce.