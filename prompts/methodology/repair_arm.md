# Repair arm `{{arm_key}}` before it is ranked

The screening of this arm ended with: {{repair_reason}}. That usually means an implementation bug, not
a refuted mechanism. You have about ${{budget_usd}} for one fix.
{{session_note}}
Arm (do not change the mechanism):

```yaml
{{arm_yaml}}
```

{{judge_profile}}
Earlier iterations' patches and results are in `{{iter_dir}}/../iter-*/` if working code there helps.

1. Find the cause (crash, invalid output, timeout, or a 0 from the judge) on a tiny case with the local
   evaluator in `{{evaluator_dir}}`.
2. Fix it in your worktree, run the arm's validity check, and measure once with the official measure
   command.
3. `git diff > {{patch_path}}` and update `{{result_path}}` (same format as before).

If you cannot fix it within the budget, record what failed in `{{result_path}}` and stop.
