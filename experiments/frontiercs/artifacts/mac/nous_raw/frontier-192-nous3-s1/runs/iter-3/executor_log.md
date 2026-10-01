Good. Now I have the iter-2 solution as a reference. Let me implement the h-main and h-ablation solutions. Let me set up the workspace.Now let me write the h-main solution (incremental gain + 0.30s SA restarts):Now let me smoke-test this h-main solution:87.58 — good. Now create the h-main patch:Now write the h-ablation version (same code but saBudget=0.03):Good. Now apply h-main patch, change saBudget to 0.03, and create h-ablation patch:Now smoke-test h-ablation:h-ablation at 78.7 on first run (expected to be lower/more variable). Now let me write the experiment plan and run the full experiment — 3 seeds per arm.Now execute the full experiment. h-main runs (already have smoke test score of 87.58):h-main: 87.54, 87.55, 84.82 (the last run hit the slow-machine bimodal mode). Now h-ablation:Interesting results. Let me summarize:

- **h-main** (0.30s SA): 87.54, 87.55, 84.82 → median 87.54
- **h-ablation** (0.03s SA): 87.57, 87.57, 84.69 → median 87.57

Both arms show the same bimodal pattern (2/3 at ~87.5, 1/3 at ~84-85 due to judge machine speed). h-ablation actually scored slightly higher than h-main on the fast-machine runs. The prediction that h-main (deep SA) would beat h-ablation (shallow SA) is REFUTED — short restarts with many random starts perform at least as well.

Let me write the findings:Now validate:Validation passes.

**Summary:** Both arms used incremental gain SA with identical code except restart budget (0.30s vs 0.03s). Results:

- **h-main** (deep, 3 restarts): 87.54, 87.55, 84.82 → **PARTIALLY_CONFIRMED** (matches iter-2 but doesn't exceed it)
- **h-ablation** (shallow, ~30 restarts): 87.57, 87.57, 84.69 → **REFUTED** (predicted lower, observed equal/slightly higher)

Key finding: restart depth vs breadth doesn't matter — the ~87.5 ceiling is robust across all SA configurations tested over 3 iterations. The bimodal variance (84-85 vs 87.5) is judge-machine-speed-dependent, not algorithmic. Breaking through 87.5 would need a fundamentally different approach.