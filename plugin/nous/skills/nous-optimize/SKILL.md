---
name: nous-optimize
description: Find the best settings of a system's knobs by measurement with a Nous `kind: optimization` campaign — scaffold it, validate it, run it, monitor it, and read the answer. Use when the user wants to tune or optimize configuration (flags, cache/buffer/batch sizes, thread counts, policies, timeouts) of a service, library, simulator or pipeline — including a system composed of several repos — asks "which configuration is fastest / cheapest / best subject to X", or wants an existing Nous optimization campaign monitored, resumed or explained.
---

# `nous-optimize`

Drive a `kind: optimization` campaign end to end. Nous pre-registers a factorial
design, measures it with **zero model calls**, fits the response surface, and
returns an answer with a stated basis (certified, or which fallback rung).
The only token spend is the opt-in `plan`/`build` stages that author a
mechanism the target does not have yet.

Reference docs ship with every install: `nous docs quickstart` (read it first),
`nous docs targets` (adapter contract), `nous docs guide` (every field).

## 1. Is this the right kind?

- **optimization** — the knobs exist (or one mechanism must be written first)
  and the question is *which settings are best, and how sure are we?*
- **reflective** (`nous create-campaign` without `--kind`) — the question is
  *why* the system behaves as it does. Use the `nous-create-campaign` skill.

## 2. Understand the target before writing YAML

1. Find each knob **in the code** and confirm it reaches a mechanism (read the
   function, not the docs). Note its type: numeric (and whether it is
   integer-valued and geometric — sizes, batches, intervals) or choice.
2. Pick ONE primary metric and its direction — or, when the user wants to see
   a trade-off (throughput vs memory, ratio vs speed), two or more
   `objectives` (see "Multi-objective" below). Bound everything else that must
   hold as `constraints` (SLAs, budgets, durability). Pick a different workload
   or metric to hold out as the generalization check.
3. Run the target by hand 2–3 times at a baseline and once per knob extreme.
   Learn magnitudes and run-to-run noise now; it decides epsilon.
   - CPU-bound and in-process on a shared machine? Measure CPU time
     (`time.process_time()`), not wall clock.

## 3. The adapter and its tests (in the target repo)

- `run_command` adapter: takes one `--flag=value` per factor, prints ONE JSON
  object last on stdout: the metrics, plus `cfg` echoing the **effective** value
  of every knob read back from the system (never the requested value, never
  omitted at some corners), reading `NOUS_WORKLOAD_SEED` and writing only under
  `NOUS_RUN_DIR`. `nous create-campaign --kind optimization --adapter-stub PATH`
  writes a skeleton.
- Relation tests in the target's own runner (pytest -v, go test -v):
  one "knob reaches the mechanism" test per factor, and a metamorphic
  "no performance knob changes any answer" test. Keep them fast.
- **Several repos?** Make a small harness repo (`repo_path`) that composes
  them, install each clone editable into the harness interpreter, have the
  adapter report each component's git commit, and pin them with
  `locked_parameters` + `optimization.locked_observables`.

## 4. Scaffold and fill

```bash
nous create-campaign --kind optimization --to campaign.yaml --target-repo-path /abs/path/to/repo
```

Fill every `TODO-`. The rules that have cost real campaigns:

- `run_command`/`test_command` are **argv, not shell** (no `cd`, `&&`, pipes);
  name an interpreter that has the deps (e.g. `.venv/bin/python`); test paths
  relative to `repo_path`; the target's own pytest addopts apply.
- Integer levels need `grid: 1`; geometric knobs need `scale: log`. A knob
  that runs only at listed values (powers of two, a menu of sizes) needs
  `levels_only: true` instead of `grid`: everything run or recommended is then
  a declared level. A `choice` factor may list any number of levels; every
  one is screened (L levels use 2^ceil(log2 L) - 1 contrast df of the screen,
  or the level-space factorial when that is smaller), fitted with
  L-1 df and recommendable -- do not split a multi-level choice into binaries.
- Any number of knobs is fine; the screen is always a fraction. Past about 10
  knobs, screen at `resolution: 4` first (the smallest power of two >= 2k
  runs, i.e. 2k-4k) and refine the live ones next epoch; the `--liveness`
  preview prices each option.
- `known_valid_baseline` uses a declared level of every factor.
- Declare `refine` (and add it to `stages`) whenever ≥ 2 numeric factors have
  > 2 levels — curvature at the screen routes there.
- `locked_parameters` are enforced only with `locked_observables`; a lock with
  neither a path nor an `optimization.unverified_locks: {param: reason}`
  acknowledgement is a validation error.
- `self_check` is an invariant of the measurement itself, never a bound on the
  objective (that is a constraint).

## 5. Validate until clean — act on every message

```bash
nous validate campaign campaign.yaml             # static: every problem, one pass
nous validate campaign campaign.yaml --smoke     # real test command + one config
nous validate campaign campaign.yaml --liveness  # every level + noise floor + DESIGN PREVIEW
```

Each run ends with a `next:` line; follow it. In the preview, check:
- the **run counts and wall clock** are acceptable;
- **epsilon vs the screen's MDE**: if epsilon is below it, certification rests
  on confirm's paired replicates (add confirm replicates / centre points);
- every factor flagged "not demonstrably live": drop it, widen it, or
  replace it (it is dead *at the base configuration*). A factor labelled
  "drives constraint `<m>` only — keep" moves feasibility: keep it.

## 6. Run in the background, then monitor

```bash
NOUS_CAMPAIGN_PARENT=~/nous-campaigns nous run campaign.yaml --auto-approve
```

Start it with the Bash tool's `run_in_background`; do not block on it. Nous
records where the work_dir went, so from any shell:

```bash
nous progress campaign.yaml --line   # one line: stage, rows done/planned, ETA
nous progress campaign.yaml --json   # machine-readable snapshot
nous stop campaign.yaml              # halt cleanly at the next boundary
```

To wait for it to finish, poll for `report.md` or `halt.json` in the work_dir
(`nous progress --json` names the run) rather than sleeping.

## 7. Read the answer and tell the user plainly

Open `report.md` in the work_dir. Lead with: the recommended configuration,
its value, and the **basis**:

| basis | say |
|---|---|
| `certified` | within epsilon of the best configuration in `certificate_scope` (a held-factor slice when `region: slice` — say which), at probability 1 − delta_screen − delta_terminal |
| `terminal_best` | best measured finalist, not certified — give the withheld reasons |
| `model` / `measured` / `baseline` | a fallback rung — say which and why |

Then the held-out check, the cost (`nous cost campaign.yaml`; zero unless
plan/build ran), and anything in **What to do next**. If `halt.json` exists, a
gate stopped the campaign: report its stage and reason verbatim.

## 8. Iterate

If the report shows a **boundary optimum** (the fitted optimum lies past a
declared edge; the answer is the best configuration inside the ranges), the
epoch ended on an exception, or certification was withheld, `report.md`'s
**What to do next** names the change as runnable levels. Do not widen a knob
whose edge is a hard limit (concurrency 1, the core count, a memory budget):
pin it there and spend the next epoch on the others. Edit the campaign, re-run `nous validate`, then:

```bash
nous resume campaign.yaml --auto-approve   # recompiles into a new epoch
```

## Multi-objective: the trade-off front

When the user asks "what does X cost me in Y?" rather than "what is best?",
declare `response.objectives` instead of `primary`:

```bash
nous create-campaign --kind optimization --objectives 2 --to campaign.yaml --target-repo-path /abs/path/to/repo
```

```yaml
response:
  objectives:
    - {metric: ops_per_cpu_s, direction: maximize}
    - {metric: peak_rss_mib,  direction: minimize}
  preference: {method: knee}    # default; or weights (+ weights:) / lexicographic (+ order:)
policy:
  epsilon: {ops_per_cpu_s: {pct: 2}, peak_rss_mib: {abs: 5}}   # per objective, or one spec
```

- A metric with a known acceptable bound is a **constraint**, not an
  objective; never both (validate refuses it). Objectives may not be
  `held_out` or `self_check` metrics.
- `--liveness` prints one effect table per objective and lists **trade-off
  candidates** (a factor whose level change improves one objective while
  worsening another, beyond noise): those knobs shape the front. It warns on
  an objective that is constant (nothing to trade) and prints each
  objective's screen MDE vs its epsilon.
- Reading the answer: `report.md` shows the front as a table sorted by the
  first objective. Tell the user the preferred point (and the `preference`
  that chose it), then the front: which points are `confidently_nondominated`
  vs `possibly_dominated`, the hypervolume, and any `gaps_remaining`. Present
  the trade-off in real units ("+12% throughput costs +40 MiB"); do not
  collapse it to one number.

## When the mechanism does not exist yet

Add `plan` and `build` before `verify` in `stages`, declare the tests the build
must write under each new factor's `relations`, set `known_valid_baseline` and
`build_checks.mechanism_paths`, and put what the authoring agent must know in
`optimization.guidance.factor_nomination`. `plan` prices the design first;
`build` authors it; `verify` gates it (its tests must fail before the build and
pass after, and the control must be unchanged). This is the only token spend.
