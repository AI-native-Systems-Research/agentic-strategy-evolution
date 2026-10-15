# Authoring a `kind: optimization` campaign (for humans and for Claude)

This is the short path from "I have a target and some knobs" to a campaign that
launches correctly the first time. The full reference is
[`optimization-campaign-guide.md`](optimization-campaign-guide.md), and the
target-side contract is [`targets.md`](targets.md). Read this first and follow
the loop. Go to the guide when a message sends you there.

## Which kind?

| Question you are asking | Kind |
|---|---|
| *Which* setting of knobs I already know about is best, and how sure am I? | `optimization` |
| *Why* does the system behave this way? What mechanism explains it? | `reflective` (default) |

Choose `optimization` only when you can list the factors, their levels, and
one numeric objective **before** any result is seen. Factors are
**declared by you**. No model proposes them. With the default stages the
campaign makes **zero model calls**. The opt-in `plan` and `build` stages
(one agent call each) design and author a mechanism that does not exist yet.
`report.md`, the gate summaries and the deployment verdict are all rendered
from artifacts with zero tokens.

## The loop

Go round each step until it is clean. Every `nous validate` run ends with one
`next:` line that tells you exactly what to run next.

```bash
# 1. Scaffold. Every value only you can know is a TODO- placeholder.
nous create-campaign --kind optimization --to campaign.yaml \
    --target-repo-path /abs/path/to/target --adapter-stub /abs/path/to/target/bench/adapter.py

# 2. Fill. Edit campaign.yaml and the adapter until no TODO- remains.

# 3. Static check: 0 runs. Lists EVERY problem in one pass: schema errors,
#    leftover placeholders by field path, and the cross-field rules.
nous validate campaign campaign.yaml

# 4. Contract check: the test command plus ONE configuration (and the generated
#    centre point).
nous validate campaign campaign.yaml --smoke

# 5. Liveness: every declared level once, plus a measured noise floor. Ends with
#    a zero-token DESIGN PREVIEW (runs per stage, wall clock, the screen's
#    minimum detectable effect vs epsilon, whether levels bracket the baseline).
nous validate campaign campaign.yaml --liveness

# 6. Launch, with artifacts kept OUT of the target repo.
NOUS_CAMPAIGN_PARENT=~/nous-campaigns nous run campaign.yaml
```

`nous run` refuses a file that still contains a `TODO-` placeholder.
`--liveness` implies `--smoke`. Its cost is `sum(len(levels)) + 3` runs, which
grows linearly with the design, so it is affordable on almost every target.

## The traps that have cost real campaigns

Every item below is a defect that shipped on a real campaign. The trailing tag
says which step catches it. **[static]** = `nous validate campaign`,
**[smoke]** = `--smoke`, **[live]** = `--liveness`, **[you]** = no tool sees it.

### Commands and tests

- **`run_command` / `test_command` are argv, not a shell line.** Each is split
  with `shlex` and run with `cwd = target_system.repo_path`. A `cd`, `&&`,
  pipe, redirect, glob, or a leading `VAR=value` reaches the program as a
  literal argument. Use `env VAR=value prog ...`. [static]
- **The interpreter you name must have the test runner and the target's
  dependencies installed.** Name the target's own venv
  (`.venv/bin/python -m pytest ...`), not whatever `python` resolves to. [smoke]
- **The target's own pytest config applies to `test_command` too.** `addopts`
  in `pytest.ini`, `tox.ini` or `pyproject.toml` (e.g. `-n auto --cov
  --cov-fail-under=98`) still runs. Either install those plugins in this
  interpreter or override them (`--no-cov -n 0 -p no:cacheprovider`). Read the
  `--smoke` output for `unrecognized arguments`. [smoke]
- **`native_test` ids must match what the runner prints.** Write paths
  relative to `repo_path` (`tests/test_x.py::test_y`), use per-test output
  (`pytest -v`, `go test -v`), and expand no globs. A declared test that never
  ran counts as a **failed** relation, so verify aborts. [static warns, smoke proves]
- **Use the target's own fast relation tests.** A relation proves that a
  lever engages and stays correct, not by how much, so run it at the cheapest
  operating point. `test_timeout_sec` defaults to 900. [smoke times it]
- **With `build` declared,** the tests build will author need not exist yet.
  `--smoke` names them ("expected to be authored by build") and leaves them
  out of its own test run. **Keep them in `test_command`**, because verify
  requires them after build. Under build, a correctness test that already
  PASSES before the build aborts verify (oracle 2(b)), unless you set
  `build_checks.allow_preexisting_tests: true`. [smoke]

### The adapter (`run_command`)

- **Print one JSON object last on stdout, and exit non-zero on any failed
  measurement.** Never emit `0` or `null` for a number you did not measure.
  [smoke]
- **Echo every factor's EFFECTIVE value on every row**, under `cfg.*`. Never
  omit a field at some corners. The output contract is fingerprinted at row 1,
  and a key that appears or disappears later aborts the epoch. [smoke, epoch]
- **Types matter.** A numeric observable must be a number (`256`, not
  `"256"`). A choice observable must be the exact level string (`"on"`, not
  `true`). [smoke]
- **Read `NOUS_WORKLOAD_SEED`** when `workload.seed_env` is declared, and
  **write files only under `NOUS_RUN_DIR`.** [you; see targets.md §3, §4a]

### Factors and levels

- **Integer levels need `grid: 1`**, or refine and the centre points can ask
  for `2.5`. [static warns]
- **`known_valid_baseline` must use declared levels for every factor**, and a
  numeric baseline should sit *inside* its levels. The preview says whether it
  brackets them. [static, live]
- **`refine` needs ≥ 2 numeric factors with > 2 levels.** Otherwise leave it
  out: `stages: [verify, screen, confirm]`. [static]
- **Screen at `resolution: 5`**, so no main effect or two-factor interaction
  is aliased. Lower resolutions depend on a foldover to untangle what they
  confounded. [static warns]
- **A factor that moves the objective by less than 2× the noise is a dead
  axis.** Widen its levels or drop it before pre-registering. [live]

### Locks, responses, noise

- **`locked_parameters` are only enforced through
  `optimization.locked_observables`**, which says where the adapter reports
  the value it actually used. A lock without an observable is a comment.
  [static warns, smoke checks]
- **SLA and budget limits go in `response.constraints`.** A violating row is
  infeasible: kept as data, but never the winner. **Invariants of the
  measurement itself** (the run completed, nothing was censored) go in
  `response.self_check`. [static, smoke]
- **`held_out` is reported, never optimized.** It is recorded on every row,
  split off the response so nothing fits or ranks on it, and summarised in
  `report.json`'s `held_out` block. [static rejects leakage]
- **On a shared machine, measure CPU time, not wall clock, for a CPU-bound
  in-process target.** Co-scheduled work (another test suite, a build) inflates
  wall-clock throughput noise by an order of magnitude — measured 0.5% → 12% CV
  on one laptop — while `time.process_time()` (user + system time of the
  adapter's own process, SQLite syscalls included) barely moves. Report wall
  clock too, as a diagnostic. A target that waits on I/O, a network or another
  process needs wall clock — then run on a quiet machine. [you; liveness shows
  the CV]
- **Measure the noise, then size epsilon.** `--liveness` prints the
  baseline's CV (put it in `noise_estimate_pct`) and the screen's minimum
  detectable effect, `MDE = t(0.975, df) · 2·sd / √corners`, where
  `df = center_points − 1`. If `epsilon < MDE` it warns that certification
  will rest on confirm's paired replicates. In that case add confirm
  replicates, declare `workload.seed_env`, or add centre points. [live]
- **Size `run_timeout_sec` from the slowest corner** (≥ 2× its wall clock), not
  from the baseline. `--liveness` fails a ceiling with under 2× headroom over
  the slowest level it ran. [live, then you for corners]

### Where artifacts go

- **Export `NOUS_CAMPAIGN_PARENT`** so the state, ledger and reports land
  outside the target repo. Without it they go to `<repo>/.nous/<run_id>/`.
  [you]

## When the static check fails

Messages are tagged `[schema]` (shape), `[placeholder]` (a `TODO-` still
present) and `[rules]` (cross-field). When the shape is invalid the rules
still run, tagged `[rules, provisional]`: some of them may be consequences of
the schema errors, so fix those first. Every rule message names its own
repair.

## Further reading

- [`optimization-campaign-guide.md`](optimization-campaign-guide.md) §2: every
  field. §7.9: the full pre-flight checklist (corner timing, row-loss
  robustness, objective fittability).
- [`targets.md`](targets.md): the adapter contract, the seed verification
  recipe, and choosing an epsilon that can certify.
- `examples/optimization/*.yaml`: complete campaigns you can copy.
