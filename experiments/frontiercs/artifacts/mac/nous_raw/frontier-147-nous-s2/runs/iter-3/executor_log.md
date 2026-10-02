Let me gather the context I need — the bundle, problem framing, handoff, and prior amendments.Now let me look at the code files I need to work with:Now I have the full picture. Let me set up the experiment. The worktree has a stub — I need to write the real baseline, create the h-main patch, and run both arms.Now let me create the h-main patch by writing the v5 version and generating a diff:Good. Now let me set up the result directories and write the experiment plan:Now let me run the experiments. I'll start with the h-ablation arm (baseline):Now the h-main arm (multi-restart SA):All 6 runs complete. Let me analyze:

**h-ablation** (single-run SA): 85.53, 84.76, 86.09 → mean **85.46** (σ=0.66)
**h-main** (multi-restart SA): 85.86, 86.61, 85.75 → mean **86.07** (σ=0.47)

Difference: +0.61 points (predicted ~2.1). Direction correct but magnitude smaller and not significant at p<0.05 with n=3.

Now let me write the findings and principle updates:Now validate:Validation passes.

**Summary:** Ran h-main (3-restart SA) and h-ablation (single-run SA) 3 times each.

- **h-ablation**: mean 85.46 (σ=0.66)
- **h-main**: mean 86.07 (σ=0.47)
- **Difference**: +0.61 points — direction correct but magnitude far below the predicted ~2.1 points and not statistically significant (p≈0.13)

Both arms **PARTIALLY_CONFIRMED**: the restart mechanism produces a small positive effect, but the design probes overestimated the magnitude due to judge variance (~0.6 std dev per run, not 0.02 as previously claimed). Updated RP-2 accordingly and added RP-3 documenting the true judge variance.