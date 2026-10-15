# Build the local evaluator, iteration {{iteration}} for {{target_system}}

Before any mechanism arm runs, build a local evaluator that every later session will use, and get a
first official score. Aim to finish within about ${{budget_usd}}; the session is stopped at twice that.
{{session_note}}
## Context

- {{design_context}}
- Target: {{system_description}}
- Your `cwd` is a worktree with the current solution.

{{judge_profile}}
## First: a measured baseline

Measure the current solution once with the official measure command. If it scores 0 (a stub), write
the simplest correct solution (no optimization), measure it officially once, keep it in your worktree,
and save it with `git diff > {{baseline_patch}}`. Later arms start from it. Do not optimize here.

## Build in `{{evaluator_dir}}`

Write and run each piece as soon as it exists. Keep each reasoning step short (a few paragraphs). If a
tooling problem (compiler, environment, missing library) is not fixed after 2-3 tries, stop working on
it: measure with the official measure command instead and note the problem in the README.

1. An instance generator from the problem statement, covering small cases and the largest allowed sizes.
2. A per-instance score, computed the way the statement defines it.
3. Per-instance CPU time against the time limit, flagging instances over it. If the statement gives no
   time limit, use {{assumed_time_limit_s}} s.
4. A summary grouped by instance size: count, mean score, worst instances, max CPU time, timeouts.
5. One command that runs all of it on a solution file. Each run appends one JSON line to
   `{{local_log}}`: `{"sha256": "<sha256 of the solution file>", "score": <mean local score>,
   "max_cpu_s": <max CPU s>}`. Run it once on the current solution.

## Instrument checks (required), written to `{{instrument_path}}`

1. Worst case: max CPU seconds of the solution on the largest allowed inputs, and the time limit from
   the statement (`null` if it gives none). `speed_first` is true when max CPU is over 50% of the limit
   (or of {{assumed_time_limit_s}} s when the statement gives none).
2. Noise: run the official measure command 3 times on the baseline (the solution you kept above, never
   a 0-score stub).
3. Knobs (optional, cheap): for each exposed knob, score at a low and a high value, one at a time.
   `matters` is true when the score moves by more than the noise spread.

```json
{"max_cpu_s": <s>, "time_limit_s": <s or null>, "speed_first": <bool>,
 "noise": {"runs": [<score>, <score>, <score>], "min": <score>, "max": <score>, "spread": <max - min>},
 "knobs": [{"name": "<knob>", "low": <value>, "high": <value>, "delta": <score change>, "matters": <bool>}]}
```

As soon as the command runs once, write `{{instrument_path}}` and `{{evaluator_dir}}/README.md` (the
command, the size groups, the time limit used, the baseline's per-group summary), then update both as
you finish the checks. Later sessions only read these two files, so keep them short and exact.
