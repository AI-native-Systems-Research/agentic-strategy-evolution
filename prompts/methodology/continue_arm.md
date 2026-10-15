# Arm `{{arm_key}}` won the screening: keep improving it

Your arm scored best among the screened mechanisms (results below). Continue in this worktree with
about ${{budget_usd}} more. Same rules as before: short steps, measure after each change, keep the best
version, never special-case specific inputs or test cases.
{{session_note}}
{{screening_results}}

{{judge_profile}}
After each official measure, re-read `{{judge_profile_path}}`.

Deepen the arm: sweeps of its tunable values, speedups where the judge profile shows time pressure,
refinements of the mechanism. Whenever the kept version improves:

1. `git diff > {{patch_path}}`
2. Update `{{result_path}}` (same format, with `next_step`).

Before you stop, write `{{iter_dir}}/handoff_update.md` (at most 40 lines): the best score and its patch,
what changed and what the measurements showed, where score is still lost per size group (largest
first), and the next step. Do not write `findings.json`, `principle_updates.json`, or
`experiment_plan.yaml`; the orchestrator writes them from your result file.
