# Build the local evaluator, iteration {{iteration}} for {{target_system}}

Before any mechanism arm runs, get an official score for a correct baseline. Aim to finish within about
${{budget_usd}}; the session is stopped at twice that. The orchestrator measures your baseline
officially afterwards and writes the instrument checks, so you do not.
{{session_note}}
## Context

- {{design_context}}
- Target: {{system_description}}
- Your `cwd` is a worktree with the current solution.

{{judge_profile}}
## Steps

1. Measure the current solution once with the official measure command.
2. If it scores above 0, keep it unchanged and stop.
3. If it scores 0 (a stub), write the simplest correct solution: no optimization, no tuning. Measure it
   officially once. Keep it in your worktree and save it with `git diff > {{baseline_patch}}`. Later arms
   start from it.

Use the official measure command for every score. Do not debug the compiler or the environment: if a
local build fails, measure officially instead and never try to fix the toolchain.

## Optional local helper

Only if compiling and running locally works within one or two tries, you may write a small helper in
`{{evaluator_dir}}`: an instance generator from the statement and a per size group breakdown of score
and CPU time. Each run appends one JSON line to `{{local_log}}`: `{"sha256": "<sha256 of the solution
file>", "score": <mean local score>, "max_cpu_s": <max CPU s>}`. Describe its one command in
`{{evaluator_dir}}/README.md` in a few lines. Skip this section otherwise.

Do not write `instrument.json`.
