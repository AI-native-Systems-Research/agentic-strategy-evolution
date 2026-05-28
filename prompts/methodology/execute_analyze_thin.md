# Execute & Analyze — iteration {{iteration}} for {{target_system}}

> **Methodology lives in `CLAUDE.md`** (auto-loaded). This prompt carries only
> the per-iteration context; consult CLAUDE.md for the experiment-plan
> structure, fast-fail rules, prediction-error taxonomy, and principle-update
> protocol.

## Iteration mode

This iteration's mode is: **{{iteration_mode}}**

{{mode_guidance}}

## Worktree discipline (#228)

Your `cwd` is an experiment worktree, not the target repo. Stay in it.
Parent-repo assets (venvs, data dirs, prior-iter outputs) appear as
symlinks declared in `target_system.worktree_extras` (#229) — reference
them via relative paths, never `cd` to the parent repo. Any file you
write that isn't in a bundle arm's `code_changes[]` gets listed in
`findings.worktree_uncommitted_writes` and lost on cleanup (#230).

## Active principles
{{active_principles}}

## Iteration directory
`{{iter_dir}}` (work_dir-relative).

## Required outputs
- `experiment_plan.yaml` — the deterministic command list per arm × condition.
- `findings.json` — per-arm prediction-vs-outcome with status (CONFIRMED / REFUTED / INCONCLUSIVE).
- `principle_updates.json` — list of principle adds / revisions / retirements (may be empty).
- `patches/<arm>.patch` — when the bundle declares `code_changes` for that arm.
- `results/<arm>/<seed>/...` — raw experimental output files.

## Validation
Run `nous validate execution --dir {{iter_dir}}` before claiming done. The
deterministic Stop hook (`bin/nous-execute-stop`) will block stopping until
validation passes and `principle_updates.json` is present.
