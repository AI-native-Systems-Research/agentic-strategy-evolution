# Build the local evaluator, iteration {{iteration}} for {{target_system}}

Before any mechanism arm runs, build a local evaluator that every later session will use. Do not
work on the solution itself. This session stops at about ${{budget_usd}}.

## Context

- Problem framing: `{{iter_dir}}/problem.md`. Design: `{{iter_dir}}/bundle.yaml`.
- Target: {{system_description}}
- Your `cwd` is a worktree with the current solution; use it only to test the evaluator.

## Build in `{{evaluator_dir}}`

1. An instance generator from the problem statement, covering small cases and the largest allowed sizes.
2. A per-instance score, computed the way the statement defines it.
3. Per-instance CPU time of the solution against the time limit, flagging instances over the limit.
4. A summary grouped by instance size: count, mean score, worst instances, max CPU time, timeouts.
5. One command that runs all of it on a solution file. Run it once on the current solution.

Write `{{evaluator_dir}}/README.md` last: the command, the size groups, the time limit used, and the
current solution's per-group summary. Later sessions only read the README, so keep it short and exact.
