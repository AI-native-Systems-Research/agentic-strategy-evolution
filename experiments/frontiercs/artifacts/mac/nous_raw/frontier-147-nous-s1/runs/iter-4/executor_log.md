The worktree has a stub `solution.cpp`. I need to find the real solution from prior iterations.Good. I have the full solution from iter-3's h-main patch. Let me set up the experiment.Good, the patch applied. Now I have the baseline (2.85s) solution. Let me set up both arms.Now create the h-main patch and save it:Now let me also create the h-control-negative patch (which is the same as iter-3's h-main patch — baseline at 2.85s):Now reset to stub and verify both patches apply:Good. Now let me smoke-test the h-main (4.8s) command:The judge takes more than 2 minutes for 4.8s runs across 50 test cases. Let me wait for it. Meanwhile, let me prepare the experiment plan and result directories.Now let me write the experiment plan while waiting for the smoke test:Smoke test passed: 4.8s arm scores 90.5. Now let me run all 10 experiments. I'll run them sequentially since the judge is CPU-intensive.

First, reset to stub, then run h-main runs:Still running. Let me wait for the notification.

I'll check interim output shortly. The judge runs take about 3-5 minutes for the 4.8s variant. Let me wait for the background task.Still writing. Let me wait for the background task notification and not poll.

The h-main run3 is still executing in the background. I have h-main run1=91.16, run2=91.38 so far. Let me wait for it to complete.It's running. I'll wait for it to finish. Since runs take ~4-5 min at 4.8s, this is expected.

Let me think about how to proceed more efficiently. I need 10 runs total (5 per arm). Each takes ~4-5 min for h-main and ~2-3 min for h-control. Total ~35 minutes.

I'll wait for run3 to complete and then continue sequentially. The background notification will arrive.

While waiting, let me check the iter-3 results for comparison context:Good context. Iter-3 h-main (best-tracking, 2.85s) averaged ~90.9 and h-control (no tracking, 2.85s) ~90.3. The effect was small (~0.65 pts).

Now in iter-4, I'm comparing 4.8s vs 2.85s (both with best-tracking). The h-control-negative here is the same code as iter-3's h-main.

Let me wait for the background task to complete before continuing with more runs.Run3 = 92.45. Now runs 4 and 5 for h-main:h-main done. Now the 5 h-control-negative runs:All 10 runs complete. Let me analyze the results:Strong results. h-main (4.8s) wins convincingly:
- Mean: 91.52 vs 89.24 (+2.28 points)
- h-main stdev dramatically lower (0.53 vs 2.16) — more consistent
- One-sided p=0.025 (significant at α=0.05)
- h-main min (91.16) nearly equals h-ctrl max (91.72)

Now let me write the findings and principle updates.Now validate:Need to remove `description` from arms and `mode` from findings:Validation passes.

**Summary:** Both arms CONFIRMED. Extending SA time budget from 2.85s → 4.8s yields +2.28 points (91.52 vs 89.24, one-sided p=0.025) and reduces score variance by ~4x (stdev 0.53 vs 2.16). New principle RP-6 captured. RP-5 updated with the variance-reduction observation.