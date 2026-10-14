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

## Instrument checks (required), written to `{{instrument_path}}`

1. Worst case: max CPU seconds of the current solution on the largest allowed inputs, and the time
   limit from the statement (`null` if it gives none). `speed_first` is true when max CPU is over 50%
   of the limit: judge machines may be slower than this one.
2. Noise: run the official measure command 3 times on the unchanged solution.
3. Knobs (optional, cheap): for each exposed knob, score at a low and a high value, one at a time.
   `matters` is true when the score moves by more than the noise spread.

```json
{"max_cpu_s": <s>, "time_limit_s": <s or null>, "speed_first": <bool>,
 "noise": {"runs": [<score>, <score>, <score>], "min": <score>, "max": <score>, "spread": <max - min>},
 "knobs": [{"name": "<knob>", "low": <value>, "high": <value>, "delta": <score change>, "matters": <bool>}]}
```

Write `{{evaluator_dir}}/README.md` last: the command, the size groups, the time limit used, and the
current solution's per-group summary. Later sessions only read the README, so keep it short and exact.
