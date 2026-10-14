# Screen arm `{{arm_key}}`, iteration {{iteration}} for {{target_system}}

You are one of several fresh executor sessions, one per competing mechanism. Build and measure only this
arm. Your `cwd` is a worktree holding the current best solution; change it there. This session stops at
about ${{budget_usd}}, so write the result file early and update it as you improve.

## Arm

```yaml
{{arm_yaml}}
```

## Context

- Problem framing: `{{iter_dir}}/problem.md`. Design handoff: `{{iter_dir}}/handoff_snapshot.md`.
- Target: {{system_description}}
- Local evaluator: `{{evaluator_dir}}` (read its README.md). Use it for the validity check and for
  per-instance, per-size-group measurement; report the score from the sanctioned measure command.

## Steps

1. Implement the mechanism minimally, then run the arm's `validity_check` on a tiny case. If it fails,
   stop building: record `validity_check.passed: false` with what failed.
2. Measure. Refine within this arm's hypothesis while the budget allows, keeping the best version in the
   worktree. Do not re-measure the unchanged incumbent; the winner session does that.
3. Save the kept version as a patch: `git diff > {{patch_path}}`.
4. Write `{{result_path}}` after the first measurement and again whenever the kept version improves:

```json
{"arm_key": "{{arm_key}}", "arm_type": "<h-main or h-alternative>", "mechanism_family": "<family>",
 "validity_check": {"passed": true, "detail": "<what the tiny case showed>"},
 "metrics": {<keys {{metric_keys}} with the kept values>},
 "predicted": "<the arm's prediction>", "observed": "<what you measured>",
 "status": "CONFIRMED | REFUTED | PARTIALLY_CONFIRMED", "error_type": "direction | magnitude | regime | null",
 "per_group": [{"group": "<size group>", "n": 0, "mean_score": 0, "max_cpu_s": 0, "timeouts": 0}]}
```

Do not write `findings.json`, `principle_updates.json`, or `experiment_plan.yaml`.
