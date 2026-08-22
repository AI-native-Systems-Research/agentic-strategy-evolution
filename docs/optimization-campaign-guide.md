# Optimization campaign guide (`kind: optimization`)

This guide is the authoring interface for `kind: optimization` campaigns.
It exists alongside [`docs/campaign-authoring-guide.md`](campaign-authoring-guide.md)
(the reflective kind's guide) but is not a variant of it: the two kinds
answer different questions. Reflective campaigns build causal claims about
*why* a system behaves as it does, one designed iteration at a time.
Optimization campaigns fit a *response surface* over knobs the author
already controls, in a design fixed before any result is seen.

**These campaigns are authored by AI.** There is no human in the loop who
notices an ambiguous field and asks a clarifying question — an ambiguity
here becomes an invalid campaign, or worse, a campaign that validates and
then leaks or misclassifies something. Every field below is written to be
unambiguous to the model reading it at authoring time, and every worked
example in this guide is executable truth: a test
(`tests/test_optimize_guide_examples.py`) extracts every YAML block from
this file and holds it to the same validator a real campaign author faces.
If you are editing this guide, fix the **example**, never the test, when
one fails — an example that would fail its own validator is the single
most damaging thing a doc for AI authors can contain.

**Before you launch anything, read §7 (pre-flight).** Static validation and
`--smoke` catch a campaign that cannot execute; §7 covers the apparatus
properties that only show up across a *range* of configurations — a timeout
sized from the wrong corner, a factor that moves nothing, a noise floor
measured in the wrong regime, an objective that is not fittable. Each item
there is a defect a real campaign shipped.

## 1. Mental model

### Why factorial beats one-factor-at-a-time

The traditional way to tune N knobs is to vary one at a time, holding the
rest fixed, and keep whichever direction helps. This is one-factor-at-a-time
(OFAT) search, and it has a structural blind spot: it can only see
**increments**, never **interactions**. If a lever is harmful alone but
required in combination with another, OFAT prunes it in round one and never
finds the combination — regardless of how much compute you throw at it.

This is not hypothetical. The motivating case for this campaign kind (see
the design spec) measured eight interacting throughput levers on a
cold-read benchmark. One lever, batching, reduced throughput 9.5% in
isolation but was *required* for the best-performing compound of four
levers together. Seven different LLM-driven optimizers were run against
this problem; five stalled well below the hardware ceiling because their
search strategies — population methods sidelining regressing candidates,
diversity-weighted selection pulling away from the best scorer, reverting
levers to seed values while keeping others — all shared the same root
cause: they searched by increment, so a negative increment looked like a
dead end instead of a clue.

A factorial design does not have this blind spot, because it never
decomposes the space into increments in the first place. Every
configuration in the design matrix is chosen in advance, screening covers
the *combinations* of levels, and effects — including interactions — are
estimated from the whole matrix at once, not from a sequence of "keep or
discard" decisions. A resolution-V design over 8 binary factors (32 runs)
estimates all 8 main effects and all 28 two-factor interactions
unconfounded. The lever that looks harmful alone and the interaction that
redeems it show up in the *same* fitted table.

### The composition barrier

Call this the **composition barrier**: an artifact of OFAT search, not an
inherent property of the underlying system. It is not that composed wins
are rare or hard to find in principle — it is that a search procedure
which throws away regressing candidates cannot reach them, no matter how
much budget it has. The fix is architectural (fit a design, don't decide
increment-by-increment), not a matter of trying harder within the OFAT
frame.

### Does your surface actually have the barrier?

The barrier is a property of the search, but whether it *bites* is a
property of your system — so it is worth five minutes to find out which
case you are in, because the answer changes what the optimization kind buys
you.

The cheap test: pick a modest factor set, evaluate the full space if you
can afford it, then run greedy steepest-ascent from **every** starting
point and count how many reach the global optimum.

```python
# Over a dict of {frozen config -> response}, ascend one factor at a time.
def traps_greedy(space, ids, levels):
    best = max(space.values())
    for start in space:                     # every corner, not just one
        cur = dict(start)
        while True:
            nxt = None
            for f in ids:
                alt = dict(cur)
                alt[f] = levels[f][1] if cur[f] == levels[f][0] else levels[f][0]
                key = tuple(sorted(alt.items()))
                if space[key] > space[tuple(sorted(cur.items()))] + 1e-9:
                    if nxt is None or space[key] > space[tuple(sorted(nxt.items()))]:
                        nxt = alt
            if nxt is None:
                break
            cur = nxt
        if space[tuple(sorted(cur.items()))] < best - 1e-9:
            return True                     # a trap exists: factorial pays off twice
    return False                            # unimodal: factorial pays off on tokens only
```

Two outcomes, both actionable:

* **Traps exist.** Sequential search can land on a local optimum and stay
  there. This is the case the kind was designed for, and the factorial
  design buys you both a better answer *and* a smaller token bill.
* **Unimodal — no starting point traps greedy.** Sequential search will
  find the same optimum you will. The factorial design still wins on
  tokens (`screen` and `refine` are structurally tokenless, so the saving
  is architectural rather than incidental), and it still gives you the
  fitted effect table, the interaction estimates, and the pre-registered
  audit trail that a hill-climb never produces. But do not claim a
  better-optimum result you did not get.

A worked instance, measured on `inference-sim`'s `blis`: six two-level
policy and capacity factors over a saturated three-SLO-class workload,
goodput spanning 23.45 to 117.85 (a 5x range). The surface has three real
interactions and one factor showing the textbook sign flip — `MAXRUN` at
-43.82 alone and +81.03 in the best context — and greedy *still* reached
the optimum from all 64 starting points. Real interactions and a
sign-flipping factor are **not sufficient** for a trap; that is exactly why
this is worth checking rather than assuming.

### Screen → refine → confirm

Each optimization campaign runs four stages, each a normal Nous iteration
with its own gates and artifacts:

| Iter | Stage | LLM calls | Runs | Establishes |
|---|---|---|---|---|
| 1 | `verify` | 0 | ~2/factor | pure Python: certifies levers, reconciles relations, compiles the policy |
| 2 | `screen` | 0 | 16-64 | Which factors matter + all two-factor interactions |
| 3 | `refine` | 0 | 15-25 | Curvature on surviving `numeric` factors; a stationary point |
| 4 | `confirm` | 0 | ~3-5 x replicates | Predicted optimum reproduces; `held_out` evaluated |

`screen` and `refine` make **zero** model calls. The author declares factors;
`verify` certifies them and compiles the policy, and Python drives the
pre-registered design matrix straight through to a fitted surface with no
model involvement — build, run, parse, replicate, fit is deterministic. This
is why `design_space` exists as a separate mechanism from prose (§5): there
is no phase reading prompts during the two stages that spend most of the run
budget.

### Where the tokens go

Substantive model calls per campaign: **0** when every factor maps to a knob
the target already exposes, and **1** when the campaign must author the
mechanism first — the only substantive model call in the kind is `build`.
Gate summaries and the end-of-campaign report use the existing shared
machinery and are not part of the epoch. Against either: 60-90 benchmark
runs, all of them tokenless.

| Stage | Model calls | What it costs |
|---|---|---|
| `build` (opt-in) | 1 | authors the mechanism + its native tests in the target repo |
| `verify` | 0 | runs the target's test command; pure Python reconciliation |
| `screen` | 0 | pre-registered design matrix; tokenless |
| `refine` | 0 | tokenless |
| `confirm` | 0 | tokenless |
| `report` state (Tasks 4+) | 0 | pure Python: recommendation + certificate |
| gate summaries | 1 per iteration | existing machinery, small |

**Model.** Every phase of a `kind: optimization` campaign resolves to
`claude-opus-5` (`orchestrator.campaign.OPTIMIZATION_MODEL`), not to the
per-phase `defaults.yaml` entries the reflective kind uses. The reasoning is
that this kind makes only a handful of model calls while the tokenless stages
carry the bulk of the work, so the marginal cost of the strongest model is
small — and the downside of a weaker model on the `build` call is that every
downstream measurement describes worse code. An explicit
`campaign.models.<phase>` still wins, so pin a cheaper model per phase when you
want one.

**Do not add a `build` stage you do not need.** It is the only stage that
spends an agent call on the target repo, so a campaign varying existing
flags should omit it and stay at zero *substantive* model calls. Add it only
when the mechanism under study does not exist yet.

The cost curve inverts relative to a reflective campaign: nearly all token
cost sits in the one authoring call at the front, and every measurement
iteration after it is free — pure compute. That front-loaded call is also
the one whose output is most durable: mechanism code and native tests land
in the target repo and outlive the campaign, where a reflective campaign's
prose findings do not.

## 2. Field-by-field walkthrough of the `optimization` block

The block is required when `kind: optimization`, and forbidden otherwise
(the validator's rule 1). Its three required top-level keys are `response`,
`factors`, and `design`; everything else — `design_space`, `guidance`,
`test_command`, `integrity_command`, `run_timeout_sec`, `stages` — is
optional but load-bearing when present.

### `response`

> `noise_estimate_pct` should be **measured, not guessed** — at the operating
> point the campaign will actually run. See §7.3, and §7.4 on checking that the
> metric you chose is a fittable response at all.


What the campaign is optimizing, and the guardrails that keep a winning
candidate honest.

- **`primary`** (required) — `{metric, direction}`. The single response
  the design matrix fits. `direction` is `maximize` or `minimize`.
  Example: `{metric: throughput_gbps, direction: maximize}`.
- **`constraints`** — admissibility filters over the same observation every
  config produces. A config that violates any constraint is marked
  infeasible: excluded from fitting, but *retained* in `runs.jsonl` as real
  data about the space (it is not thrown away — a config that turns a
  feature off entirely and thereby "wins" trivially is exactly the case
  this catches). Example: `{metric: trigger_rate_pct, op: ">", value: 0.0}`.
- **`regimes`** — a conjunction that must hold in *every* named regime, for
  responses that are a constrained trade-off rather than a scalar. A
  scalar objective lets a config win on the average while failing one
  regime outright; `regimes` makes that failure visible instead of averaged
  away. Example: `{id: burst, metric: improvement_burst_pct, op: ">",
  value: 0}` alongside a matching `steady` entry.
- **`held_out`** — metric name(s) reserved purely as a generalization
  check, recorded only at `confirm`, never an input to fitting. The
  validator hard-fails if a `held_out` metric collides (case/whitespace-
  insensitively) with `primary`, any `constraints` entry, or any `regimes`
  entry. See the held-out anti-patterns in §6 for the failure mode this
  does *not* catch.
- **`ceiling`** — an optional physical bound on the primary metric (a
  hardware limit, a theoretical maximum). A response above ceiling
  hard-fails that config: exceeding a physical ceiling means the
  instrumentation is lying, not that the campaign found a miracle.
- **`noise_estimate_pct`** — rough expected measurement noise as a percent
  of the primary metric, used to size replicate counts.

### `factors`

The knobs the campaign varies. Each becomes one column of the design
matrix, and the schema requires `id`, `name`, `type`, `levels`, `apply`,
one `manipulation`, and at least one `correctness` relation — everything
else has a default.

- **`type`** is `numeric` or `choice` — a domain question, not a statistics
  question. The only thing you decide is *whether values between the
  declared levels are runnable*. `numeric`: interpolation is meaningful
  (`escalate_low` in a threshold sweep, `queue_count` in `{2,4,8,16}`).
  `choice`: nothing lives between the levels (`scheduler` in
  `{fcfs, sjf, priority}`, `batching` in `{off, on}`). The retired
  `continuous` / `ordinal` / `categorical` vocabulary is not accepted —
  see anti-pattern §6.7.
- **`levels`** — every runnable setting, as a flat list, `>= 2` entries.
  Screening uses the pair from `screen_levels` (default: `levels[0]` and
  `levels[-1]`); interior levels are explored only in `refine`.
- **`grid`** (numeric only) — snaps a fitted interior optimum to the
  nearest multiple of this step, so `confirm` never has to run a value the
  target can't actually take (`K = 4.7` becomes `K = 5` with `grid: 1`).
  Omit when any real value ships (thresholds, ratios).
- **`screen_levels`** — the two `levels` members the 2-level screen uses for
  this factor. Declare only when the extremes are known-pathological and
  the screen should bracket a narrower span; otherwise omit and take the
  default.
- **`apply`** — the seam that removes the LLM from the inner loop: how a
  level becomes a runnable configuration, mechanically, with zero model
  involvement. A bare string is CLI-flag shorthand
  (`apply: "--queues={level}"`); the long forms are
  `{kind: cli_flag, template: ...}`, `{kind: env_var, name: ..., value: ...}`,
  and `{kind: config_patch, path: ..., pointer: ..., value: ...}`.
  `{level}` is the *only* interpolation token in the entire spec. This is
  the single most load-bearing field in the schema — get it wrong and
  Python is applying the wrong configuration on every one of 60-90 runs
  with nobody watching.

  **`config_patch` has one precondition, and the validator enforces it.**
  A patch is applied to a per-run COPY of `path` (your file is never
  mutated — rows run concurrently in principle, and a mutated shared file
  is both a race and a cross-row contamination channel), and the copy's
  path is substituted for every occurrence of `path` in the assembled
  command. So `path` **must appear as an argument value in
  `run_command`** — `run_command: "bench --config engine.json --json"` for
  `path: engine.json`. A path the command never names is a hard validation
  error, because there would be nothing to substitute and the run would
  read your unpatched file while the design matrix recorded the requested
  level. `pointer` is an RFC 6901 JSON pointer (`/cache/policy`,
  `/tiers/0/bytes`, with `~0` for a literal `~` and `~1` for a literal
  `/`) and must address a field that already exists — a patch replaces a
  value the target reads, it never invents structure. The two spellings must
  match **literally**: `path: ./engine.json` against
  `run_command: "... engine.json"` is a hard error, because the substitution is
  textual over the assembled argv and nothing normalises either side. The match
  is anchored to an argument boundary, so `other/engine.json` in the command
  does *not* satisfy `path: engine.json` (and `--config=engine.json` does). `.json`, `.yaml`,
  and `.yml` are supported; anything else is an error rather than a guess
  at a format Nous cannot round-trip. The level's TYPE is preserved
  exactly: `42949672960` lands as an integer, `true` as the format's
  native boolean, `arc` as a string. What actually happened is recorded
  per run as `applied_patches` (next to `applied_args` and `applied_env`),
  keyed by factor id and including the copy's path and the command that
  consumed it — so a target that echoes nothing back can still write a
  truthful check: `{observable: applied_patches.P1.value, op: "==", value:
  "{level}"}`. The copy itself is preserved only when the run FAILED, under
  `runs/iter-N/patched_configs/row-<index>/`; a successful row's
  configuration is reproducible from the pre-registered matrix.
- **`manipulation`** (required, exactly one) — Family A: did the lever
  actually engage? Checked on every run of this factor. Uses the shared
  comparison shape `{observable | metric, op, value}`, with `value:
  "{level}"` substituting the level under test. The validator rejects
  trivially-true predicates (`> 0`, `!= null`, bare truthiness) — see
  anti-pattern §6.1.
- **`relations`** (required, `>= 1`, and at least one must be
  `kind: correctness`) — Family B: is the mechanism correct?
  `correctness`: a violation hard-fails the whole campaign (the apparatus
  is broken; every measurement is meaningless). `behavioral`: a violation
  is recorded as a finding and the campaign continues. **Monotonicity
  claims must be `behavioral`, never `correctness`** — see anti-pattern
  §6.4. Each relation names a `native_test` identifier living in the
  *target's own* test tree, run under its own idiom (`hypothesis`,
  `proptest`, `rapid`, whatever the target already uses) — Nous's role is
  a contract check: the declared `test_command` ran and exited clean.
- Both `manipulation` and any `relations` check, plus `design_space`
  invariants and `response` constraints, share optional `when: <level(s)>`
  / `when_not: <level(s)>` guards, because a check is often meaningless at
  one level (a batch-size assertion holds only when `batching: on`).
  Supplying both on one check is a validation error.

### `design`

How the design matrix is sized and staged. Run counts are **derived**,
not chosen freely.

- **`screen`** (required) — `{resolution, center_points}`. Default target
  resolution is **V** (estimates every two-factor interaction unconfounded
  with any main effect or other interaction). The validator warns (not
  blocks) at `resolution < 5` with more than one factor — see anti-pattern
  §6.3. `center_points` are replicated runs at the center of the design,
  giving the pure-error estimate the lack-of-fit test needs.
- **`refine`** — `{kind: central_composite, center_points}`. Runs only
  when at least two `numeric` factors with more than 2 levels survive
  screening (the validator's rule 4). Omit this key entirely when your
  factors are all `choice`, or all binary numeric — there is no curvature
  to fit, and refine would have nothing to do.
- **`confirm`** (required) — `{replicates}`. Replicates the predicted
  optimum (snapped to each factor's `grid`) and evaluates `held_out`
  metrics.
- **`max_runs`** — your run budget. The validator fails with the two
  honest options — raise the budget, or accept a lower resolution and its
  named aliasing — rather than silently downgrading resolution to fit. If
  your factor count has no tabulated design at the resolution you asked
  for, the validator says so explicitly rather than fabricating a run-count
  comparison; omit `max_runs` if you have not first checked that your
  `(factor count, resolution)` pair is one Nous has a published generator
  for.

### `design_space`

Properties Python enforces on **every** configuration in every stage —
see §5 for the full rationale and the decision test for what belongs here.

- **`invariants`** (required, `>= 1`) — `{id, statement, observable, op,
  value}`. Where a violation is statically determinable from the matrix
  row, the row is rejected before it runs; otherwise the config hard-fails
  after running. Either way, the guarantee holds across all 60-90 runs,
  not just the two the model sees.

### `guidance`

Structured prose in two named slots. Both are **reserved, not read by any
stage** — `verify` and `confirm` are pure Python, so nothing consumes these
fields today. Keep them accurate: they document author intent for a human
reader, and they are the slots a future model-facing stage would read.

- **`factor_nomination`** — **reserved, not read by any stage.** Domain
  knowledge about which axes matter, which mechanisms already exist in the
  target, and what's out of scope belongs here.
- **`interpretation`** — **reserved, not read by any stage.** Scope
  limitations and "report X as a lead, not a result" belong here.

### `test_command` / `integrity_command`

- **`test_command`** — shell command that runs every declared relation's
  `native_test` and exits clean iff all pass.
- **`integrity_command`** — optional, independent of any single relation
  (a checksum or reconciliation script).

### `run_timeout_sec`

Wall-clock ceiling, in seconds, on **one** invocation of `run_command` — one
row of the design matrix, one measurement. Defaults to **600**, which is what
every campaign authored before this field existed ran at.

Raise it when the target's single *legitimate* measurement is a **compound**
one: an objective evaluation that is itself a bisection, a sweep to saturation,
or a multi-replicate average inside the target's own harness. A live campaign
whose one objective evaluation was a capacity bisection over ~5 simulator runs
died on its first row at the old fixed ceiling, and every workaround available
at that point bought the schedule with the science — a shorter simulation
horizon means a noisier slope statistic, a looser bisection tolerance means a
coarser objective value, and caching results across invocations would open a
covert channel between arms the design registered as independent. Declaring the
real ceiling is the only option that leaves the measurement alone.

```yaml
optimization:
  run_command: "./sim capacity-bisect --tol 0.01 --json"
  run_timeout_sec: 5400          # ~5 simulator runs per objective evaluation
```

Two things it is not. It is **not a budget**: a run that exceeds the ceiling
records a `failed` row naming the timeout, that row is excluded from the fit
(the complete-row subset rule, spec §4 D2), and the epoch continues — you never
get a partial measurement, because a partial measurement of a compound
objective is indistinguishable from a complete measurement of a different one.
And it is **not free to over-size**: the ceiling is per row, so
`run_timeout_sec × runs` is the campaign's worst-case wall clock, and that worst
case is reachable rather than hypothetical — a target that hangs consumes the
whole ceiling on every affected row before failing it. `nous validate campaign`
warns above 3600 and quantifies the exposure against your declared `max_runs`.

The resolved value — declared or defaulted — is echoed into every iteration's
`design_matrix.json` as `run_timeout_sec`, beside `workload_seeds` and
`policy_hash`. A reader of a timed-out row can then tell which ceiling produced
it without knowing which campaign revision was on disk at the time.

`--smoke` prints the probe configuration's real duration next to this ceiling,
and flags a probe that used more than half of it. That check matters most when
the probe *passes*: the first design corner is not the design's slowest, so a
corner finishing at 570s under a 600s ceiling clears smoke and still kills the
epoch on the first slower row.

### `max_parallel`

Ceiling on **simultaneous in-flight `run_command` invocations**. Defaults to
**1** — strictly sequential, exactly what every campaign authored before this
field existed ran at.

```yaml
optimization:
  max_parallel: 4                # confirm replicate blocks only; see below
```

It applies to **`confirm` replicate blocks and nothing else.** The spending
stages — `screen`, `foldover`, `refine` — stay strictly sequential no matter
what you declare, and the reason is the same one that makes the design worth
running at all.

**Why screen rows are excluded.** A spending stage fits a response surface over
*distinct* configurations. Co-scheduled rows contend for machine resources, so a
row's measured response comes to depend on which *other* rows happened to run
beside it — and contention spread unevenly across a design is absorbed by the
fitted coefficients as though it were a factor effect. This is not the same
problem as drift, which the pre-registered randomized run order already handles:
a permutation spreads a *time* trend across the levels, but it can do nothing
about a *neighbour* effect, because permuting the rows permutes the neighbours
too. For a target whose objective is where the system saturates — a queue, a
cache, an autoscaler, which is every target this kind exists for — contention is
the measurement, not noise around it. Parallelizing an 18-row screen would turn
a 3-hour campaign into a 45-minute one and hand back coefficients that partly
describe your machine's scheduler.

**Why a confirm block is different in kind.** Confirm's rows are emitted one
complete replicate block at a time, and within a block *every finalist is
measured exactly once*. So whatever contention the block creates is symmetric
across exactly the things being compared: it shifts all the finalists together
and cancels out of the finalist-to-finalist difference, which is the only
quantity terminal discrimination reads. That is the same argument that puts
confirm's run-order shuffle *inside* a block rather than across the whole
matrix, and the bound is scoped to be its exact counterpart. Blocks stay a
barrier — replicate *i* of every finalist completes before replicate *i+1*
starts — so "every finalist measured once before any is measured twice" still
holds. A shortlist of 3 finalists × 5 replicates at `max_parallel: 3` is five
sequential rounds of three concurrent runs, not fifteen runs in a free-for-all.

**Size it from cores, not from rows.** More in-flight runs than the machine has
CPUs means the runs time-slice against each other, and a finalist's response
starts depending on the scheduler — which injects variance into the very
differences the terminal bound is computed from, so a wider bound buys wall
clock with a *wider* residual-regret certificate. `nous validate campaign` warns
above `os.cpu_count()`. It is a warning rather than an error because there is one
legitimate case it cannot see: a `run_command` that mostly *waits* — on a remote
inference endpoint, a managed database, a cluster it only submits to — holds no
core while waiting, and a bound well above the core count is correct there. Only
you know which your target is.

The **effective** value is echoed into every iteration's `design_matrix.json` as
`max_parallel`, beside `run_order_seed` — and note it is the effective one, so a
screen matrix records `1` even under a campaign declaring `4`. The two fields are
meant to be read together: a `run_order` permutation looks identical whether it
described a sequence or a schedule, so a pre-registration claiming a randomized
run order while executing rows concurrently would be asserting a guarantee it
did not provide.

**Look here first, though.** The field bounds concurrency *between* rows, and on
most targets that is not where the wall clock actually is. A single objective
evaluation is frequently several *sequential* target invocations behind one
`run_command` — a warmup pass, then a measurement pass, then a verification
pass; or a bisection stepping through candidate loads one at a time; observed on
a real campaign at up to five sequential invocations per row. Those probes are
usually **independent of each other**, and parallelizing them is entirely
target-side: it needs no field here, it speeds up *every* stage rather than only
`confirm`, and it introduces no cross-row confound at all, because the
contention it creates is inside one measurement and therefore identical for
every row of the design. Before reaching for `max_parallel`, check whether your
`run_command` is really one measurement or five in a row.

Row-level concurrency at the spending stages is not simply unimplemented — it is
reachable only by *closing* the confound rather than ignoring it: each concurrent
row pinned to a disjoint CPU set, with the pinning recorded in the artifact so a
reader can check it. This field deliberately does not enable that, and raising it
will never make a screen run rows side by side.

### `stages`

Optional override of the default iteration -> stage mapping
(`[verify, screen, refine, confirm]`). Use to skip `refine` explicitly for
an all-`choice` campaign, e.g. `[verify, screen, confirm]`. An iteration
index beyond the list resolves to `confirm`, never a fresh screen (which
would re-spend the screening budget).

#### `build` — when the mechanism does not exist yet

`build` is **opt-in and absent from the default order**, so every campaign
written before it existed behaves identically. Declare it first when the
campaign has to *extend the target* before it can measure anything:

```yaml
stages: [build, verify, screen, confirm]
max_turns:
  build: 160        # optional; defaults to 120
```

It spends exactly one agent call in the target repo to write the mechanism
and the native tests your `relations` declare, then hands control back to
the tokenless stages. Use it when a factor's `apply` names a flag, policy,
or algorithm the target does not have yet. Omit it when every factor maps
to an existing knob.

Three properties are worth understanding before you use it:

1. **`build` makes no correctness judgement.** `verify` is still the gate,
   and it runs the real `test_command` against the real repo. The stage that
   writes the mechanism is never the stage that certifies it — otherwise the
   model would be grading its own work.
2. **It runs once, first.** The validator rejects `build` anywhere but
   position 1. Behind `verify` it guarantees an abort (verify would gate
   tests for code that does not exist yet); behind `screen` it is worse than
   an abort, because the screen measured the *old* mechanism and the effect
   table then describes a system the campaign replaced.
3. **It does not iterate to green.** One call, then the gate. A build-fix
   loop would both burn tokens and let the model negotiate with its own
   gate. If `verify` fails, the campaign aborts with the failing relation
   IDs — fix the spec or the tests and re-run.

Because `verify` is fail-closed — a declared `native_test` that does not
execute counts as a **failure**, not as "skipped" — the tests you declare in
`relations` are the actual contract for the build. Write them as the precise
thing you want guaranteed:

- a **backward-compatibility** test, when the specification says an existing
  default must not change;
- a **property-based** test for invariants that must hold across a whole
  input space, not at two or three sampled points;
- a **metamorphic** test when changing one input should move the output in a
  known direction — this catches a mechanism wired to the wrong formula even
  when each variant independently satisfies every invariant. **Do the algebra
  before you write the direction down, and put a worked numeric example in the
  `statement`.** A metamorphic relation pointing the wrong way is worse than
  no test at all: it fails a correct implementation, or passes a broken one,
  and it does so with the authority of a declared correctness relation. This
  is the single easiest thing to get wrong in a campaign, because the wrong
  direction is often the intuitive one. Real example from this repo's own
  campaign corpus — an author declared that interior interpolation ceilings
  satisfy `step <= linear <= exponential`, reasoning that "exponential decays
  slower so it must sit higher". The truth is the reverse: for a threshold `T`
  in (0,1), `T^f <= 1 - f*(1 - T)` because the exponential is concave in `f`.
  At `T=0.6` with three bands the interior ceilings are step `0.600`,
  exponential `0.775`, linear `0.800`, so the correct relation is
  `step <= exponential <= linear`. Benchmark numbers taken *before* authoring
  already contradicted the declared direction and were misread as confirming
  it — so check the inequality symbolically, then verify it numerically at two
  or three concrete points, and never infer it from an end-to-end metric;
- a **loud-failure** test, so an unrecognized value cannot silently fall back
  to the default and turn a typo into a fabricated null result.

Those tests are native to the target's language and live in the target repo,
using its own tooling. Nous never grows a property-testing dependency for
this; `hypothesis`, `rapid`, and `proptest` belong to target repos.

### `build_checks` — and `mechanism_paths`, which every campaign should declare

`build_checks` tunes the oracles that keep a mechanism honest. Three of its
fields only matter when you declare `build`; the fourth matters always.

```yaml
optimization:
  build_checks:
    mechanism_paths: ["src/batching.py", "tests/prop_batch.py"]
    # the three below apply only when `build` is in `stages`:
    allow_preexisting_tests: false   # oracle 2(b)
    baseline_replicates: 3           # oracle 2(c)
    baseline_tolerance_pct: 4.0      # oracle 2(c)
```

**Oracle 2(b) — the tests must have been red before the build.** A declared
`correctness` relation whose `native_test` *already passed* against a tree
without the mechanism is green for some other reason, and it stays green if the
build wires the mechanism to nothing. `verify` aborts on that. Set
`allow_preexisting_tests: true` only when the relation genuinely covers
pre-existing behaviour — a backward-compatibility test asserting an existing
default did not change is the legitimate case.

**Oracle 2(c) — the control must be unchanged by the build.** Your
`known_valid_baseline` is measured `baseline_replicates` times before the build
and again at `verify`; a mean shift past `baseline_tolerance_pct` (relative, as a
percent) hard-fails. A mechanism that moves the metric *at its own OFF level*
changed something outside its scope and confounds every treatment effect while
looking clean. This is why `known_valid_baseline` is **required** whenever `build`
is declared: without a control there is nothing to measure, and a silently absent
oracle on the one stage that writes code is the worst place to have one. On a
noisy target, raise `baseline_replicates` rather than widening the tolerance.

#### `mechanism_paths`: declare it, `build` stage or not

**This one field is not limited to `build` campaigns.** Every epoch iteration
re-hashes the target tree and hard-aborts if it no longer matches the recorded
`mechanism.sha256`. That oracle is armed by the *presence* of that hash — which a
campaign may also write by hand — not by the `build` stage.
`mechanism_paths` is what that hash covers.

Omit it and the hash covers the **entire working tree**: every tracked edit plus
every untracked file git does not ignore. Nous runs the target's own
`test_command` and `run_command` **with the target repo as the working
directory**, so anything they leave behind that is not gitignored — a
`.pytest_cache/`, a `run.log`, a `.coverage` file — changes that hash, and the
next iteration aborts with:

    mechanism drifted since compile

That is a false positive wearing the costume of the worst available true
positive. It has happened on a real campaign, with zero `build` stage involved.
Naming the mechanism's files removes the whole class of failure.

The whole-tree default is kept only for backward compatibility — an existing
campaign's recorded hash stays valid across the change — not because it is the
better setting.

**Entries are literal paths, not globs.** The matching rule is a plain
path-component prefix:

| Entry | Means |
|---|---|
| `src/batching.py` | that file, exactly |
| `src/` (or `src`) | everything under that directory |
| `src/batch` | **nothing** — a partial component never matches |
| `src/*`, `*.py`, `mech?.py`, `src/[ab].py`, `.` | **rejected by the validator** |

Globs are refused rather than supported, because the hash has two halves scoped
by the same entries through two different matchers: tracked edits go through
`git diff HEAD -- <entries>`, whose pathspec *does* expand `*`, while untracked
files go through Nous's literal prefix match, which does not. A `["src/*"]` that
was merely accepted would be honoured for tracked edits and match nothing among
untracked files — and an untracked new module is the common shape of a mechanism.
Half the oracle would be silently disarmed. `nous validate campaign` hard-fails
these entries so you find out while you can still read the message.

`--smoke` goes one step further and reports an entry that resolves to nothing
under the target — a typo'd path is not a loud failure, it just quietly narrows
the oracle. (That check is skipped when `build` is declared, since `build` is the
stage that authors the file in the first place.)

#### Reference numbers in a spec: verify them, or leave them out

If your mechanism description quotes expected values for the build stage to
check against, **reproduce every one of them yourself first, with the exact
code path the build stage will use.** An unverifiable number is the most
expensive thing you can put in a spec: the agent cannot tell "the author
mislabelled this" from "my implementation is wrong", so it does the diligent
thing and searches for a variant that matches — burning the one call the
campaign has on probes that produce no mechanism and no measurement.

Observed for real, and it cost three aborted build stages. A spec described its
baseline leg in terms of the *deployed system's* behaviour and quoted an exact
figure for it. The figure was correct; the **label** was not — one of the
behaviours named in the label was not modelled by the target's evaluator at all,
so it could not have contributed. The build agent spent twenty-plus shell probes
grid-searching variants trying to close a sub-percentage-point gap that was
unclosable by construction, and never got as far as writing the mechanism.

Two rules follow:

1. **Name the leg by the code path that produces it**, not by what the
   production system does. "Function `f` called per item with these arguments,
   results combined this way" is checkable; "production's strategy" is an
   invitation to go looking for behaviour the evaluator may not model.
2. **Say what to do on a mismatch.** State explicitly that a divergence should
   be recorded and the build continued, rather than chased. The build prompt
   says this too, but a spec that also says it removes the ambiguity.

#### Always finish with `--smoke`

`nous validate campaign FILE` is **static**: it checks structure and cross-field
rules, and it will pass a campaign that cannot execute a single configuration.
That is not a hypothetical — a campaign passed static validation cleanly and
then failed every one of its screen runs, because its manipulation predicate
compared a level (a *string*) against a value the target emits as a *bool*. The
target was correct; the contract between campaign and target was not, and
nothing was executing that contract.

    nous validate campaign campaign.yaml --smoke

`--smoke` runs the test command and **one** configuration at every factor's
first level, then reports six things static checks cannot see:

| Check | Failure it prevents |
|---|---|
| declared `native_test` identifiers appear in the runner's output | fail-closed abort at `verify` for tests that exist and pass |
| `run_command` execs and emits parseable JSON | every run dies on a usage error |
| `response.primary.metric` is present in the output | every run parses and scores NaN, poisoning the fit |
| manipulation predicates hold at the first level | every run rejected while the target is fine |
| each declared `build_checks.mechanism_paths` entry resolves under the target | a typo'd entry silently narrows the drift oracle to less than declared — to nothing, if every entry is wrong |
| the probe's real duration against the effective `run_timeout_sec` | a ceiling the first corner clears and a slower corner does not — the probe passes, then row *k* of the epoch dies on the ceiling |

The predicate check builds its scope the way `run_stage` does — the target's own
`applied` echo wins over the requested levels — because using the requested
levels would make `applied.X == "{level}"` trivially true and hide the exact
mismatch worth finding.

It costs one test run plus one configuration, and each of those failures
otherwise costs a full campaign to discover. Make it the last thing you do
before launching.

Run `nous validate campaign FILE` before starting: it warns when declared
`native_test` files are absent from the target and no `build` stage exists to
author them — the combination that is otherwise guaranteed to abort at
`verify`, but only after a real run.

## The compiled policy

Everything in §2 describes what you *declare*. This section describes what
Nous *compiles that into*, and what it writes to disk while executing it —
because the artifacts, not the YAML, are what you read when the campaign
comes back.

The binding design authority is
[`docs/superpowers/specs/2026-08-16-compiled-policy-design.md`](superpowers/specs/2026-08-16-compiled-policy-design.md).
Where that spec and this section disagree, the spec wins and this section is
the bug — except on artifact **names**, where the code is the authority and
two names are called out below.

### `policy.json` — the pre-registration, compiled at `verify`

At the end of `verify`, `orchestrator.optimize.policy.compile_policy` turns
your `optimization` block into a **compiled epoch**: a state machine written
to `policy.json` at the work-dir root, with its content hash in
`policy.sha256`. Compilation is **pure Python — zero model tokens**, and it
reads no measurement.

That hash is the whole point. A policy hash written *before the first
benchmark run* means every branch the campaign could take was fixed before
any result was seen. There is nothing to p-hack: the adaptivity is real
(a screen result genuinely changes which state runs next), but the *set of
possible adaptations* was registered in advance.

Three consequences you will feel as an author:

1. **Never edit `policy.json`.** The next stage compares it against
   `policy.sha256` and aborts with *"policy.json was edited after
   compilation… a pre-registered policy cannot change inside an epoch."*
   To change the design, change the campaign YAML and start a new epoch
   (below).
2. **The observation vocabulary is closed.** A `when` guard may read only the
   keys in `policy.OBSERVATION_KEYS` and compare them with `>`, `>=`, `<`,
   `<=` (`policy.COMPARISON_OPS`). There is no free-form expression form, so
   a measurement outside the vocabulary cannot become a new branch —
   it becomes a **semantic exception** instead.
3. **Every conditional transition names an inferential accounting rule.**
   `check_policy` rejects a policy whose conditional branch has no
   `accounting` string. An adaptive branch with no named accounting rule does
   not ship — that is a stated non-goal of the design, not an oversight.

### The `policy` block: the numbers that decide when to stop

```yaml
optimization:
  policy:
    epsilon: {pct: 2.0}       # indifference width; declare exactly one of abs/pct
    delta_screen: 0.05        # error budget for the MODEL bound
    delta_terminal: 0.05      # error budget for the TERMINAL bound
    confirm_max_rounds: 1     # rounds of terminal discrimination before reporting uncertified
```

Every field is optional and has the default shown. All four are compiled
verbatim into `policy.json`'s `objective` block and covered by the policy
hash, which is what makes them pre-registered rather than chosen after the
fact.

`epsilon` is the width below which you would not bother changing production.
Certification is `R_δ(x̂) ≤ ε`, so `epsilon: {abs: 0}` can never be met and
an epsilon wider than the whole response range certifies immediately.
`docs/targets.md` §5 gives the arithmetic for picking one that is reachable
at your replicate count — it is **not** simply "above the noise floor."

`delta_screen` and `delta_terminal` are separate because the two bounds they
size rest on different assumptions; `Pr(wrong global decision) ≤ δ_s + δ_t`.

### `known_valid_baseline`: the bottom rung

```yaml
optimization:
  known_valid_baseline: {MNS: 256, MBT: 8192, CP: "off", POL: fcfs}
```

One configuration you know works today, with the mechanism under study at its
OFF/control level — normally your production setting. Every id must name a
declared factor and every level must be one of that factor's `levels`; the
validator hard-fails otherwise, because a baseline outside the declared space
is not a configuration the campaign is allowed to run.

It does three jobs: it is the report's last-resort answer when nothing
measured survives the correctness gates, it is the shortlist's last-resort
finalist, and it is the control that build oracle 2(c) measures before and
after a `build`. It is **required** whenever `build` is declared.

### `workload`: seeds, and why `confirm` pairs them

```yaml
optimization:
  workload:
    seed_env: NOUS_WORKLOAD_SEED    # required; must match ^[A-Z_][A-Z0-9_]*$
    seeds: [11, 22, 33, 44]         # optional explicit set, taken modulo the index
```

Declare this whenever the target is stochastic — a queue, a cache, an
autoscaler, a sampler, anything whose run-to-run variance is comparable to
the effect under study. Two things follow.

Every measurement row gets a deterministic seed exported into the run
subprocess's environment under `seed_env` and recorded in that iteration's
`design_matrix.json` as `workload_seeds`, so a surprising row can be
re-measured exactly rather than argued about.

And the terminal comparison uses **common random numbers**: replicate *i* of
every finalist runs the *same* seed, so the seed's contribution cancels out
of the finalist-to-finalist difference and the terminal bound is computed on
paired differences (`bonferroni_one_sided_t_paired`) instead of
Welch-combining two independent variances. On a noisy systems target that is
the difference between certifying inside the run budget and not.

**Nous exports the variable; it cannot make your benchmark read it.** A
target that ignores `seed_env` still gets a recorded seed and a bound
computed over differences whose shared term never cancelled. That bound is
still *valid* — its variance is estimated from the observed differences — but
it buys nothing, and the certificate on disk will record a paired method for
an experiment that paired nothing. Wire the variable into the workload
generator's seed, and verify it with the two-run recipe in
[`docs/targets.md`](targets.md) §3 before you trust any paired bound.

### `design.confirm.shortlist_size`: terminal discrimination, not replication

```yaml
optimization:
  design:
    confirm: {replicates: 4, shortlist_size: 3}
```

`confirm` is this branch's name for the paper's **`discriminate`** stage
(design spec §3.3's naming note — same behaviour, older token). It is
**terminal discrimination**, not replication: it takes a shortlist
`S ⊆ X_valid` of `shortlist_size` finalists and measures each of them
`replicates` times *freshly*, then compares them **against each other**. The
final claim therefore does not rest on the fitted response surface at all.
The only global claim left is that screening did not exclude the winner.

`shortlist_size` defaults to 3. Setting it to `1` reproduces the old
single-point confirmation, which measures how *repeatable* one configuration
is and leaves "is it the best?" as a claim about the fitted model. Total runs
at this stage are `shortlist_size * replicates`, out of the same `max_runs`
budget as everything else.

### States and registered branches

`build` and `verify` are **pre-epoch** — `verify` is what compiles the
policy, so it cannot be a state inside it. The epoch begins at `screen`.

| State | Spends benchmark? | Registered branches out |
|---|---|---|
| `screen` | yes | `foldover`, `refine`, `confirm`, `exception` |
| `foldover` | yes | `refine`, `confirm`, `exception` |
| `refine` | yes | `confirm`, `exception` |
| `confirm` | yes | `confirm` (further round), `report`, `exception` |
| `report` | no | terminal |
| `exception` | no | terminal; **ends the epoch** |

`step(policy, state, observations) -> (next_state, rule)` is the *only* thing
that decides what runs next. It is pure, total, and deterministic, and every
call appends a row to `transitions.jsonl` carrying the state, the full
observation dict, the rule that fired (including its `accounting` string),
and the `policy_hash` it ran under. That file — not the log — is the audit
trail; `report.json`'s `path` is read back from it.

The registered branches worth understanding as an author:

- **`foldover`** — a **registered foldover**, spent only when the screen's
  aliasing is *consequential* (an alias class could change which
  configuration wins) **and** the remaining budget covers the fold block.
  Aliasing is a resource question, not a blanket warning: at resolution IV
  the design confounds two-factor interactions, and the campaign resolves
  that confounding only when resolving it can change the answer. One
  coefficient is fitted per **alias class**, and the classes are recorded
  (see the artifacts below) whatever the verdict — "the design confounds AB
  with CD and it does not matter for the winner" is a claim you should be
  able to check, not an absence you have to trust. There is nothing to
  declare: the state is registered whenever `screen` exists and gated at
  **runtime**, deliberately *not* on `design.screen.resolution` — a
  resolution-V screen aliases nothing, so the branch simply never fires,
  and making the state's existence depend on the resolution would put the
  same fact in two places and let them drift.
- **`refine`** — entered when at least one refinable factor survives
  screening (numeric, more than two levels). All-`choice` or all-binary
  campaigns skip it, which is why `stages: [verify, screen, confirm]` is a
  legitimate schedule rather than a shortcut.
- **`confirm` → `confirm`** — a further round of terminal discrimination,
  capped by `confirm_max_rounds`, re-measuring the winner plus every finalist
  whose bound still exceeded epsilon.

### Reading `report.json`

`report.json` lands at the work-dir root and always names an action. The
fallback ladder (design spec §3.6) is recorded as
`recommendation.basis`, so you can tell a certificate from a fallback without
reading a single log line:

| `recommendation.basis` | What it means |
|---|---|
| `certified` | terminal discrimination ran and `R_δ^term ≤ ε`. The strongest claim the kind makes. |
| `terminal_best` | terminal discrimination ran, bound too wide to certify. The winner is still a *measured* configuration compared against measured rivals. |
| `model` | no terminal stage ran; the fitted argmax stands with its model bound. **The one rung that rests on the fitted surface** — suppressed when a semantic exception ended the epoch, or when the exact levels were already measured infeasible. |
| `measured` | the model's answer is unusable; the best measured *valid* configuration is returned. Never the largest noisy observation — only `complete` rows are eligible. |
| `baseline` | nothing above survived; your `known_valid_baseline` is returned. |
| `none` | not a rung. No baseline was declared, so there is genuinely nothing legal to return, and saying so beats inventing an origin. |

The spec's §3.6 states four rungs; the artifact has six values because the
spec's rung 2 ("model adequate, bound too wide") and rung 3 ("model
inadequate, remeasure") are two distinct `basis` values on disk
(`terminal_best`, `measured`), plus `none` for the no-baseline case that is
not a rung at all.

**Two bounds, reported separately, never collapsed:**

- `residual_regret_model` — the **model bound**, a simultaneous one-sided
  upper bound on how much better any challenger could still be *under the
  registered response class*, at `delta_screen`. Method
  `bonferroni_one_sided_t`. It carries the response-model assumption.
- `residual_regret_terminal` — the **terminal bound**, computed from the
  fresh finalist measurements only, at `delta_terminal`. Method
  `bonferroni_one_sided_t_paired` under common random numbers, else
  `bonferroni_one_sided_welch_t`. It does not depend on the fitted model at
  all.

They rest on different assumptions, so a single "regret" number would
advertise the assumption-light guarantee while delivering the
model-dependent one. `Pr(wrong global decision) ≤ delta_screen +
delta_terminal` is only meaningful while the two stay apart.

`report.json` carries each bound's *value*; the full record — `challenger`,
`delta`, `method`, `detail` — is in `recommendation.json` (model) and
`confirmation.json` / `shortlist.json` (terminal). A `null` bound means the
variance was not estimable (fewer than two replicates per finalist, or no
pure-error degrees of freedom), and an unknown is not a zero: treat `null`
as "cannot certify."

Also in `report.json`: `certified`, `epsilon`, `delta_screen`,
`delta_terminal`, `finalists` (each with its levels, samples, mean, and
*why* it made the shortlist), `known_valid_baseline`, `path`, `epoch`,
`policy_hash`, and — only when a semantic exception ended the epoch —
`epoch_ended`.

### Artifacts the epoch writes

Work-dir root:

| File | Written by | Contains |
|---|---|---|
| `policy.json` + `policy.sha256` | end of `verify` | the compiled policy and its content hash |
| `transitions.jsonl` | every `step()` | `epoch`, `iteration`, `from`, `to`, full `observations`, the `rule` that fired, `policy_hash` |
| `report.json` | `report` | recommendation + `basis`, both bounds, both deltas, finalists, `path`, `certified` |
| `epoch_end-<epoch>.json` | `exception` | why the epoch ended and what a new one would need |
| `mechanism.patch` + `mechanism.sha256` | `build` (or written by hand) | the mechanism snapshot the drift oracle compares the tree against |
| `pre_build_tests.json` | before `build` | oracle 2(b): each declared `native_test`'s verdict *before* the mechanism existed |
| `baseline_equivalence.json` | `verify`, when `build` ran | oracle 2(c): the baseline's replicate vectors before and after the build |

Per iteration, under `runs/iter-N/`:

| File | Written by | Contains |
|---|---|---|
| `design_matrix.json` | before execution | the pre-registered rows, generator, randomized run order, RNG seed, `workload_seeds` |
| `runs.jsonl` | each run, append-only | levels, response metrics, replicate index, manipulation/constraint verdicts, status, duration |
| `effects.json` | fitting states | fitted effects and interactions, pure error, lack-of-fit, **`aliases`** (the alias classes), dropped factors |
| `recommendation.json` | fitting states | `levels`, `predicted`, `top_candidates`, `stationary_point`, `residual_regret_model`, `aliases`, **`alias_consequential`** |
| `fit_exclusions.json` | fitting states, only when rows were excluded | which row indices were left out of the fit, and why |
| `confirmation.json` | `confirm` | the finalists, their fresh samples, the winner, `residual_regret_terminal`, `epsilon`, `certified` |
| `shortlist.json` | `confirm` | `S` and why each member is in it, plus a pointer to `confirmation.json` |
| `relations.json` | every stage | per-relation verdicts from the native test run |
| `findings.json`, `principle_updates.json` | every stage | projected deterministically from the fit — zero tokens |

Two name notes, because the spec and the code differ and the code is what
you will find on disk:

- Design spec §3.9's table calls the epoch-ending artifact **`epoch.json`**;
  the code writes **`epoch_end-<epoch>.json`** (one per epoch, at the
  work-dir root, so the epoch counter is a glob rather than a directory
  walk). Same artifact, and the spec's name is the idealized one.
- Design spec §3.9's table names an **`alias_map.json`**; there is no such
  file. The same content is carried by `effects.json`'s `aliases` (what is
  aliased with what, one coefficient per alias class) and
  `recommendation.json`'s `alias_consequential` (whether it could change the
  winner) — recorded at *every* fitting state, including `foldover`, where
  an empty list is how you verify the fold actually resolved the alias it
  was spent on.

### Semantic exceptions, and how to start epoch 2

A **semantic exception** is a measurement the compiled policy has no
registered branch for: a `correctness` relation failed, the primary metric
came back NaN, or the fitted stationary point landed outside the declared
hull. No further measurement *inside* the epoch can repair it — the epoch's
own vocabulary does not describe the situation — so the epoch **ends**.

What does *not* happen: a model call to interpret the result. That is the
single most important invariant in the kind, and it is what makes the
token-call table in §1 true. A semantic exception ends the epoch instead of
improvising a branch.

What *does* happen: the campaign still returns an action.
`epoch_end-<epoch>.json` records the state, the guard that fired, the full
observation dict, and a `next_epoch_requires` string mapping the observation
to the revision it calls for (a lookup over the closed vocabulary, not
prose a model wrote). Then `report.json` is written on the strongest rung
that does *not* rest on the fitted surface — `measured` or `baseline` — with
`epoch_ended` set. Uncertainty weakens the claim; it should not prevent a
decision.

To start epoch 2:

1. Read `epoch_end-<epoch>.json`'s `next_epoch_requires`.
2. **Revise the campaign YAML** — widen a range whose optimum sat outside
   the hull, fix the objective metric or the target's instrumentation for a
   NaN response, repair the mechanism (or the relation, if the asserted
   algebra was wrong) for a correctness failure.
3. Re-run `nous validate campaign FILE --smoke`.
4. `nous run --resume`. The presence of `epoch_end-1.json` is what tells
   Nous the next run is epoch 2, so it **recompiles** from the revised
   campaign rather than interpreting the stale policy.

That recompilation is not an escape from the hash check. The hash check
refuses a policy edited *inside* an epoch; recompiling *across* an epoch
boundary is the opposite operation — a new pre-registration, freshly hashed,
whose `epoch` field says which execution it registers. The previous epoch's
registration survives in `transitions.jsonl`, whose rows carry the
`policy_hash` they ran under, so "which policy scheduled this design?" stays
answerable for every epoch.

Two related aborts are *not* semantic exceptions, and their fixes differ:
tree drift (`mechanism drifted since compile` — restore the tree, or scope
the oracle with `build_checks.mechanism_paths`, above) and a re-snapshotted
mechanism whose hash the policy never registered (recompile: a revised
mechanism is a new experiment).

### A complete example using every field in this section

```yaml
kind: optimization
run_id: qdrant-hnsw-epoch
research_question: >
  Which HNSW build and search parameters maximize query throughput at a fixed
  recall floor, and can the winner be certified 2%-optimal within 80 runs?
prompts:
  methodology_layer: prompts/methodology
  domain_adapter_layer: null
target_system:
  name: qdrant
  repo_path: /path/to/qdrant
  description: >
    bench/nous_bench.py builds a collection with the given HNSW parameters,
    replays a seeded query stream (NOUS_WORKLOAD_SEED) against a held-fixed
    corpus, and prints one JSON object:
    {qps, recall_at_10, p99_ms, peak_rss_mb, cfg:{...}}.
  controllable_knobs: [m, ef_construct, ef_search, quantization]
locked_parameters:
  corpus: sift-1m
  vectors: 1000000
  query_count: 10000
  threads: 8
optimization:
  run_command: "python bench/nous_bench.py --corpus sift-1m --queries 10000"
  test_command: "python -m pytest bench/test_nous_props.py -q --json-report --json-report-file=/dev/stdout"

  # The bottom rung of the fallback ladder: production's own settings, with the
  # mechanism under study at its control level.
  known_valid_baseline: {M: 16, EFC: 128, EFS: 64, Q: "none"}

  # Stochastic target -> declare the seed contract, so confirm can pair.
  workload:
    seed_env: NOUS_WORKLOAD_SEED
    seeds: [101, 202, 303, 404, 505]

  # The registered decision parameters, hashed into policy.json.
  policy:
    epsilon: {pct: 2.0}
    delta_screen: 0.05
    delta_terminal: 0.05
    confirm_max_rounds: 2

  response:
    primary: {metric: qps, direction: maximize}
    constraints:
      - {metric: recall_at_10, op: ">=", value: 0.95}
      - {metric: p99_ms, op: "<=", value: 25}
    noise_estimate_pct: 3.0
  factors:
    - id: M
      name: hnsw_m
      type: numeric
      levels: [8, 16, 32, 64]
      grid: 4
      apply: "--hnsw-m={level}"
      manipulation: {observable: cfg.m, op: "==", value: "{level}"}
      relations:
        - id: R_M
          kind: correctness
          statement: "every indexed vector is reachable from the entry point at any m"
          native_test: "bench/test_nous_props.py::test_graph_fully_reachable"
    - id: EFC
      name: ef_construct
      type: numeric
      levels: [64, 128, 256, 512]
      grid: 8
      apply: "--ef-construct={level}"
      manipulation: {observable: cfg.ef_construct, op: "==", value: "{level}"}
      relations:
        - id: R_EFC
          kind: correctness
          statement: "the built collection reports exactly the corpus vector count at any ef_construct"
          native_test: "bench/test_nous_props.py::test_all_vectors_indexed"
    - id: EFS
      name: ef_search
      type: numeric
      levels: [32, 64, 128, 256]
      grid: 8
      apply: "--ef-search={level}"
      manipulation: {observable: cfg.ef_search, op: "==", value: "{level}"}
      relations:
        - id: R_EFS
          kind: correctness
          statement: "ef_search >= k, so every query returns exactly k results"
          native_test: "bench/test_nous_props.py::test_k_results_returned"
        - id: B_EFS
          kind: behavioral
          statement: "recall@10 is non-decreasing in ef_search at fixed m and ef_construct"
          native_test: "bench/test_nous_props.py::test_recall_monotone_in_ef_search"
    - id: Q
      name: quantization
      type: choice
      levels: ["none", "scalar"]
      apply: {kind: cli_flag, template: "--quantization={level}"}
      manipulation: {observable: cfg.quantization, op: "==", value: "{level}"}
      relations:
        - id: R_Q
          kind: correctness
          statement: "quantization none returns byte-identical result ids to the unquantized reference"
          native_test: "bench/test_nous_props.py::test_quantization_none_is_reference"
  design:
    screen: {resolution: 5, center_points: 4}
    refine: {kind: central_composite, center_points: 4}
    # Terminal discrimination: 3 finalists x 5 fresh replicates = 15 runs.
    confirm: {replicates: 5, shortlist_size: 3}
    max_runs: 80
  design_space:
    invariants:
      - id: I_RSS
        statement: "peak resident memory stays under the container limit"
        observable: peak_rss_mb
        op: "<="
        value: 12000
  build_checks:
    mechanism_paths: ["bench/nous_bench.py", "bench/test_nous_props.py"]
  guidance:
    interpretation: >
      Expect an M x EFS interaction: a sparse graph needs a wide search
      beam to reach the recall floor, and a dense one does not. Certification
      arithmetic at these settings: noise_estimate_pct is 3.0, so with 5
      paired replicates the terminal Bonferroni-t bound over 2 challengers
      clears the 2% epsilon only when the winner's true margin is a few
      percent or more. A near-tie among finalists should come back
      `terminal_best`, not `certified` — that is the instrument working, not
      failing. Report a `measured` or `baseline` basis as a null result about
      the factor set, not as a recommendation.
```

Note what is *not* in that campaign: no stage anywhere in the epoch consults
a model. `build` is absent because every factor maps to a knob Qdrant
already exposes, so this campaign's substantive model-call count is **zero**.

## 3. Four worked end-to-end examples

Each of the following is a complete, valid `kind: optimization` campaign —
schema-valid, cross-field-valid, drawn from the real campaign corpus
(restated as this kind) or from the motivating benchmark case.

### 3.1 Multi-level grid — `alert-threshold-robustness`

The corpus campaign that hand-rolled a 5x6x3x5x3 = **1350-cell grid** by
enumerating every combination of five threshold knobs by hand. Restated as
a factorial design: resolution V over 5 factors is 16 runs; with 4 center
points at screen, 4 at refine, and 3 replicates at confirm, the whole
campaign is **~40 runs against 1350** — and it gains interaction estimates
the original grid never computed at all.

```yaml
kind: optimization
run_id: alert-threshold-robustness-opt
research_question: >
  Is there an escalation-threshold configuration that robustly beats the
  recorded baseline out-of-sample across both the bursty and the steady
  stretches of the held-out window?

target_system:
  name: event-replay
  description: Threshold-based alert classifier replayed over recorded event streams.

prompts:
  methodology_layer: prompts/methodology

locked_parameters:
  arming_threshold: 0.40
  score_floor: 0.0
  cd: 0
  weighting: equal_per_window
  is_start: "2025-03-20"
  oos_start: "2026-02-01"

optimization:
  response:
    primary: {metric: improvement_steady_pct, direction: maximize}
    constraints:
      - {metric: trigger_rate_pct, op: ">", value: 0.0}   # not turned off
    regimes:                  # the robustness conjunction, made explicit
      - {id: burst,      metric: improvement_burst_pct,      op: ">",  value: 0}
      - {id: drift, metric: improvement_drift_pct, op: ">",  value: 0}
      - {id: steady,       metric: improvement_steady_pct,       op: ">=", value: -5}
    held_out: [held_out_blocks_robust]
    noise_estimate_pct: 4.0

  design_space:
    invariants:
      - id: I1
        statement: "every config trades the same instrument set (no survivorship drift)"
        observable: telemetry.event_stream_hash
        op: "=="
        value: "baseline"
      - id: I2
        statement: "no config peeks past the OOS boundary"
        observable: telemetry.max_bar_date
        op: "<="
        value: "2026-06-18"

  guidance:
    factor_nomination: >
      escalate_low and escalate_high interact through the category boundary; treat their
      interaction as the primary object of interest rather than either main
      effect. Trailing-stop factors are secondary -- screen them, but do not
      spend refinement budget on them unless the screen says they matter.
    interpretation: >
      A config that wins only in the steady regime is not a result for this
      campaign; the robustness conjunction across all three regimes is the
      claim. Report steady-only winners as leads.

  factors:
    - id: F1
      name: escalate_low
      type: numeric
      levels: [0.015, 0.020, 0.025, 0.030, 0.040]
      apply: "--escalate-low={level}"
      manipulation: {observable: config.escalate_low, op: "==", value: "{level}"}
      relations:
        - {id: R1, kind: correctness,
           statement: "escalate_low at 0.015 reproduces the recorded baseline run",
           native_test: "tests/prop_thresholds.py::test_baseline_reproduces"}

    - id: F2
      name: escalate_high
      type: numeric
      levels: [0.030, 0.040, 0.050, 0.060, 0.080, 0.120]
      apply: "--escalate-high={level}"
      manipulation: {observable: config.escalate_high, op: "==", value: "{level}"}
      relations:
        - {id: R2, kind: correctness,
           statement: "escalate_high >= escalate_low invariant holds for every accepted config",
           native_test: "tests/prop_thresholds.py::test_ordering_invariant"}

    - id: F3
      name: severity_boundary
      type: numeric
      levels: [0.75, 0.85, 0.95]
      apply: "--severity_boundary={level}"
      manipulation: {observable: config.severity_boundary, op: "==", value: "{level}"}
      relations:
        - {id: R3a, kind: correctness,
           statement: "severity_boundary partitions every bar into exactly one category",
           native_test: "tests/prop_thresholds.py::test_partition_is_total"}
        - {id: R3b, kind: behavioral,
           statement: "trigger_rate is monotone non-increasing in severity_boundary",
           native_test: "tests/prop_thresholds.py::test_trigger_rate_monotone"}

    - id: F4
      name: decay_guard_threshold
      type: choice              # "off" is not a number; no interpolation
      # QUOTE "off". Unquoted `off` is a YAML 1.1 boolean and parses as False,
      # so the level list would become [False, 0.004, ...] and `when_not: off`
      # would guard on the boolean instead of the sentinel string.
      levels: ["off", 0.004, 0.005, 0.007, 0.010]
      apply: "--decay-guard={level}"
      # The predicate compares against the interpolated level, not a bare
      # `> 0`. `decay_guard_events > 0` would be trivially true -- it
      # passes whenever the stop fires at all, so it cannot distinguish
      # 0.004 from 0.010 and would report a mis-set lever as verified.
      manipulation: {observable: config.decay_guard_threshold, op: "==",
                     value: "{level}", when_not: "off"}
      relations:
        - {id: R4, kind: correctness,
           statement: "decay_guard=off is byte-identical to the no-stop path",
           native_test: "tests/prop_stops.py::test_off_is_noop"}

    - id: F5
      name: decay_guard_min_peak
      type: numeric
      levels: [0.006, 0.008, 0.012]
      apply: "--min-peak={level}"
      manipulation: {observable: config.min_peak, op: "==", value: "{level}"}
      relations:
        - {id: R5, kind: correctness,
           statement: "min_peak has no effect when decay_guard=off",
           native_test: "tests/prop_stops.py::test_min_peak_inert_when_off"}

  design:
    screen:  {resolution: 5, center_points: 4}
    refine:  {kind: central_composite, center_points: 4}
    confirm: {replicates: 3}
    max_runs: 60

  test_command: "pytest -q tests/prop_*.py --json-report"
```

Two things this example demonstrates that prose does not:

- **`decay_guard` is `choice`, not `numeric`**, because `off` sits in a
  list of numbers. Reaching for `numeric` here would ask the fitter to
  interpolate between `off` and `0.004`. The `type` question ("is anything
  between these runnable?") makes the right answer obvious without knowing
  anything about regression — and the `off` sentinel must be quoted, or it
  parses as the YAML boolean `False` (§6.3).
- **R5 encodes a cross-factor inertness relation** — `min_peak` must do
  nothing when `decay_guard=off`. That is a real bug class in threshold
  code, invisible to any single-factor test, and would otherwise show up
  as unexplained noise in the F5 main effect.

### 3.2 Categorical mechanism factorial — `ordering-theorem`

Three control surfaces — routing, preemption, scheduling — each a
`choice` factor over mechanism names, not numbers. The corpus campaign's
recorded headline finding: *"Preemption is actively HARMFUL when paired
with FIFO scheduling: largest-kappa preemption + FIFO produces 7.3x WORSE
critical TTFT P95 than dumb-tail preemption + FIFO."* A main-effects-only
screen reports "preemption helps" on average and misses this inversion
entirely — it is a genuine interaction, not a subtlety of averaging.
Estimating the two-factor interaction is the entire point of running this
as a factorial rather than three independent A/B tests.

Because all three factors are `choice`, there is no curvature to fit —
`design.refine` is omitted, and `stages` explicitly skips straight from
`screen` to `confirm`.

```yaml
kind: optimization
run_id: ordering-theorem-opt
research_question: >
  Do routing, preemption, and scheduling policy interact to change critical-
  request tail latency, or does each mechanism's effect hold independently
  of the others?

target_system:
  name: llm-serving-sim
  description: >
    Simulated LLM inference server with configurable request routing,
    preemption policy, and scheduling discipline.

prompts:
  methodology_layer: prompts/methodology

optimization:
  response:
    primary: {metric: critical_ttft_p95_ms, direction: minimize}
    constraints:
      - {metric: throughput_tokens_per_sec, op: ">", value: 0.0}
    held_out: [held_out_workload_ttft_p95_ms]
    noise_estimate_pct: 5.0

  design_space:
    invariants:
      - id: I1
        statement: "every config serves the same request mix (no workload drift)"
        observable: telemetry.workload_hash
        op: "=="
        value: "baseline"

  guidance:
    factor_nomination: >
      All three mechanisms already exist in the target's scheduler module --
      do not write new mechanism code, only the wiring to select among the
      existing implementations. Preemption and scheduling are suspected to
      interact through the wrong-consumer-preempted pathway; treat that
      interaction as the object of interest, not either main effect alone.
    interpretation: >
      If preemption's main effect and its interaction with scheduling
      disagree in sign, report the interaction as the finding -- a
      main-effects summary that omits it would be actively misleading.

  factors:
    - id: F1
      name: routing
      type: choice
      levels: [round_robin, least_loaded, kappa_weighted]
      apply: "--routing={level}"
      manipulation: {observable: telemetry.routing_policy, op: "==", value: "{level}"}
      relations:
        - {id: R1, kind: correctness,
           statement: "round_robin routing reproduces the recorded baseline run",
           native_test: "tests/prop_routing.py::test_baseline_is_round_robin"}

    - id: F2
      name: preemption
      type: choice
      levels: [none, dumb_tail, largest_kappa]
      apply: "--preemption={level}"
      manipulation: {observable: telemetry.preemption_policy, op: "==", value: "{level}",
                     when_not: none}
      relations:
        - {id: R2, kind: correctness,
           statement: "preemption=none never preempts a request",
           native_test: "tests/prop_preempt.py::test_none_is_noop"}
        - {id: R3, kind: behavioral,
           statement: "critical TTFT P95 is monotone non-increasing as preemption gets more selective"
           # behavioral, not correctness: a monotonicity break here IS the
           # 7.3x interaction this campaign exists to find. Classifying it
           # correctness would hard-fail the campaign on its own headline
           # discovery -- see anti-pattern 6.4.
           , native_test: "tests/prop_preempt.py::test_monotone_selectivity"}

    - id: F3
      name: scheduling
      type: choice
      levels: [fifo, ea_wfq, priority_fcfs]
      apply: "--scheduler={level}"
      manipulation: {observable: telemetry.scheduler_policy, op: "==", value: "{level}"}
      relations:
        - {id: R4, kind: correctness,
           statement: "fifo scheduling reproduces the recorded baseline run",
           native_test: "tests/prop_sched.py::test_baseline_is_fifo"}

  design:
    screen: {resolution: 5, center_points: 2}
    confirm: {replicates: 4}

  stages: [verify, screen, confirm]   # all-choice factors: no curvature to refine

  test_command: "pytest -q tests/prop_*.py --json-report"
```

Note `design.max_runs` is deliberately omitted here: with only 3 factors
there is no tabulated fractional design in Nous's generator table at any
resolution (the smallest tabulated resolution-V design starts at 5
factors), so the screen runs the full 2^3 = 8-run factorial — already
small enough that no budget ceiling is needed, and declaring one against
an untabulated combination would only produce a validator error asking you
to remove it or add factors.

### 3.3 Constrained multi-regime response — `composite-sensitivity-boundary`

The corpus campaign whose recorded finding is a genuine trade, not a
scalar win: *"Removing LT from the composite eliminates 100% of false
positives at rho < 1, with no detection loss at rho >= 1.05."* A single
`maximize(detection_rate)` objective would hide this: an optimizer could
win on average detection while quietly regressing the false-positive rate
in the low-rho regime, which is exactly the overfitting this design exists
to prevent. `regimes` makes the trade a first-class, checkable object
instead of something you discover by manually slicing the data afterward.

```yaml
kind: optimization
run_id: composite-sensitivity-boundary-opt
research_question: >
  Which composite-score component weighting maximizes detection rate at
  high rho while keeping the false-positive rate acceptable at low rho?

target_system:
  name: composite-detector
  description: >
    Composite anomaly-detection score combining several component signals
    (including a long-term "LT" component) evaluated across a sweep of the
    rho separation parameter.

prompts:
  methodology_layer: prompts/methodology

optimization:
  response:
    primary: {metric: detection_rate_high_rho, direction: maximize}
    constraints:
      - {metric: false_positive_rate_low_rho, op: "<=", value: 0.05}
    regimes:                  # the trade the campaign exists to characterize
      - {id: low_rho,  metric: false_positive_rate_low_rho, op: "<=", value: 0.05}
      - {id: high_rho, metric: detection_rate_high_rho,      op: ">=", value: 0.90}
    held_out: [held_out_rho_sweep_detection_rate]
    noise_estimate_pct: 3.0

  design_space:
    invariants:
      - id: I1
        statement: "every config sweeps the identical rho grid (no grid drift across configs)"
        observable: telemetry.rho_grid_hash
        op: "=="
        value: "baseline"

  guidance:
    factor_nomination: >
      lt_weight is the component under suspicion of causing low-rho false
      positives; treat its interaction with st_weight (the short-term
      component) as the primary object of interest. Report whichever
      configuration wins the low-rho/high-rho conjunction, not whichever
      wins detection rate alone.
    interpretation: >
      A config that improves high-rho detection at the cost of low-rho
      false positives is not a win for this campaign -- report it as a
      lead (a possible two-regime-specific scoring scheme), not a result.

  factors:
    - id: F1
      name: lt_weight
      type: numeric
      levels: [0.0, 0.25, 0.5, 0.75, 1.0]
      apply: "--lt-weight={level}"
      manipulation: {observable: config.lt_weight, op: "==", value: "{level}"}
      relations:
        - {id: R1, kind: correctness,
           statement: "lt_weight=0.0 reproduces the no-LT baseline run",
           native_test: "tests/prop_composite.py::test_lt_zero_is_noop"}

    - id: F2
      name: st_weight
      type: numeric
      levels: [0.0, 0.25, 0.5, 0.75, 1.0]
      apply: "--st-weight={level}"
      manipulation: {observable: config.st_weight, op: "==", value: "{level}"}
      relations:
        - {id: R2, kind: correctness,
           statement: "st_weight=0.0 reproduces the no-ST baseline run",
           native_test: "tests/prop_composite.py::test_st_zero_is_noop"}
        - {id: R3, kind: behavioral,
           statement: "detection_rate_high_rho is monotone non-decreasing in st_weight",
           native_test: "tests/prop_composite.py::test_st_weight_monotone"}

  design:
    screen:  {resolution: 5, center_points: 3}
    refine:  {kind: central_composite, center_points: 3}
    confirm: {replicates: 4}

  test_command: "pytest -q tests/prop_composite.py --json-report"
```

`design.max_runs` is omitted for the same reason as §3.2: 2 factors has no
tabulated fractional generator either (the design runs the full 2^2 = 4-run
screen), so there is no budget ceiling worth declaring. What this example
demonstrates that a scalar objective cannot: the low-rho and high-rho
regime checks are declared as a conjunction the fitted surface must
satisfy in *both* places, not a single number averaged across rho — a
config can post an excellent mean detection rate while failing exactly the
trade the campaign was built to characterize.

### 3.4 Binary throughput levers — the Certus cold-read case

The motivating benchmark itself, restated as the design that would have
found the compound directly: eight binary levers (L1-L8) on a cold-read
data-transfer path, including **L5 (batching)**, which measured **-9.5%
throughput alone** yet was required for the winning four-lever compound.
Resolution V over 8 binary factors is 64 runs — small next to the
composition barrier it removes.

```yaml
kind: optimization
run_id: certus-coldread-opt
research_question: >
  Do the eight cold-read throughput levers (L1-L8) interact such that a
  jointly-optimal compound exceeds every individually-tuned configuration,
  and does any lever with a negative main effect still belong in the winner?

target_system:
  name: certus
  description: Peer-to-peer cold-read data transfer path over RDMA fabric.

prompts:
  methodology_layer: prompts/methodology

optimization:
  response:
    primary: {metric: achieved_bandwidth_gbps, direction: maximize}
    constraints:
      - {metric: integrity_checksum_ok, op: "==", value: true}
    ceiling: {metric: achieved_bandwidth_gbps, value: 21.1}
    held_out: [held_out_workload_bandwidth_gbps]
    noise_estimate_pct: 2.0

  design_space:
    invariants:
      - id: I1
        statement: "connector is peer-to-peer, never staged through host memory"
        observable: telemetry.transfer_path
        op: "=="
        value: p2p

  guidance:
    factor_nomination: >
      L5 (batching) is known to be harmful in isolation from prior manual
      tuning; do not let a negative single-factor result cause you to drop
      it from the design -- the whole point of this campaign is to measure
      its interaction with the other seven levers, not to re-litigate its
      main effect.
    interpretation: >
      If any lever's main effect and its interaction terms disagree in
      sign, report the interaction as the primary finding. A compound that
      depends on a lever with a negative main effect is the headline result
      this campaign is designed to surface, not an anomaly to explain away.

  factors:
    - id: L1
      name: connection_count
      type: choice
      levels: [1, 4]
      apply: "--connections={level}"
      manipulation: {observable: telemetry.connection_count, op: "==", value: "{level}"}
      relations:
        - {id: R1, kind: correctness,
           statement: "connection_count=1 reproduces the recorded baseline run",
           native_test: "tests/prop_certus.py::test_single_connection_is_baseline"}

    - id: L2
      name: request_pipelining
      type: choice
      levels: ["off", "on"]
      apply: {kind: env_var, name: CERTUS_PIPELINE, value: "{level}"}
      manipulation: {observable: telemetry.pipeline_depth, op: ">", value: 1, when: "on"}
      relations:
        - {id: R2, kind: correctness,
           statement: "pipelining=off is byte-identical to baseline",
           native_test: "tests/prop_certus.py::test_pipeline_off_is_noop"}

    - id: L3
      name: window_scaling
      type: choice
      levels: ["off", "on"]
      apply: {kind: env_var, name: CERTUS_WINDOW_SCALE, value: "{level}"}
      manipulation: {observable: telemetry.window_bytes, op: ">", value: 65536, when: "on"}
      relations:
        - {id: R3, kind: correctness,
           statement: "window_scaling=off is byte-identical to baseline",
           native_test: "tests/prop_certus.py::test_window_off_is_noop"}

    - id: L4
      name: checksum_offload
      type: choice
      levels: ["off", "on"]
      apply: {kind: env_var, name: CERTUS_CKSUM_OFFLOAD, value: "{level}"}
      manipulation: {observable: telemetry.checksum_in_hw, op: "==", value: true, when: "on"}
      relations:
        - {id: R4, kind: correctness,
           statement: "checksum results are identical whether computed in hw or sw",
           native_test: "tests/prop_certus.py::test_offload_checksum_matches_sw"}

    - id: L5
      name: batching
      type: choice
      levels: ["off", "on"]
      apply: {kind: env_var, name: CERTUS_BATCHING, value: "{level}"}
      manipulation: {observable: telemetry.mean_batch_size, op: ">", value: 1, when: "on"}
      relations:
        - {id: R5, kind: correctness,
           statement: "batching=off is byte-identical to baseline",
           native_test: "tests/prop_batch.py::test_off_is_noop"}
        - {id: R6, kind: behavioral,
           # behavioral, NOT correctness -- see anti-pattern 6.4. A naive
           # monotonicity classification here would hard-fail the campaign
           # on its own single most important discovery (L5 is negative
           # alone, positive in the winning compound).
           statement: "throughput is monotone non-decreasing in batch_size when batching=on",
           native_test: "tests/prop_batch.py::test_monotone_when_on"}

    - id: L6
      name: numa_pinning
      type: choice
      levels: ["off", "on"]
      apply: {kind: env_var, name: CERTUS_NUMA_PIN, value: "{level}"}
      manipulation: {observable: telemetry.numa_local_pct, op: ">", value: 90, when: "on"}
      relations:
        - {id: R7, kind: correctness,
           statement: "numa_pinning=off is byte-identical to baseline",
           native_test: "tests/prop_certus.py::test_numa_off_is_noop"}

    - id: L7
      name: completion_polling
      type: choice
      levels: [interrupt, poll]
      apply: "--completion-mode={level}"
      manipulation: {observable: telemetry.completion_mode, op: "==", value: "{level}"}
      relations:
        - {id: R8, kind: correctness,
           statement: "completion_mode=interrupt reproduces the recorded baseline run",
           native_test: "tests/prop_certus.py::test_interrupt_is_baseline"}

    - id: L8
      name: prefetch_depth
      type: choice
      levels: [1, 8]
      apply: "--prefetch-depth={level}"
      manipulation: {observable: telemetry.prefetch_depth, op: "==", value: "{level}"}
      relations:
        - {id: R9, kind: correctness,
           statement: "prefetch_depth=1 reproduces the recorded baseline run",
           native_test: "tests/prop_certus.py::test_prefetch_1_is_baseline"}

  design:
    screen: {resolution: 5, center_points: 4}
    confirm: {replicates: 5}
    max_runs: 90

  stages: [verify, screen, confirm]   # all binary/choice factors: no curvature to refine

  test_command: "pytest -q tests/prop_*.py --json-report"
  integrity_command: "./scripts/verify_integrity.sh"
```

Three things this example demonstrates that the earlier ones don't:

- **`guidance.factor_nomination` explicitly pre-empts the OFAT reflex.**
  Without that line, a model proposing factors from its own judgment might
  quietly drop L5 because prior tuning showed it was harmful alone — which
  would silently reintroduce the exact composition barrier this campaign
  kind exists to remove. Naming the risk in `guidance` is not required by
  the schema, but leaving it out invites the failure the design is built
  to prevent. Nothing reads this field today; it documents the author intent
  a future model-facing stage would honor.
- **R6 is `behavioral`, not `correctness`, precisely at the lever whose
  main effect is negative.** This is the single highest-stakes
  classification decision in the whole spec — see anti-pattern §6.4.
- **8 factors at resolution V is exactly the tabulated case (64 runs, no
  aliasing)**, so unlike §3.2 and §3.3, `design.max_runs: 90` is safe to
  declare here: the validator can certify the design against the budget
  because the (8, 5) generator is published.

## 4. Declare as factor, lock, or assert as invariant

Mirrors the existing "what to lock" inventory in the reflective guide
(#245), adapted for the three-way choice this kind actually offers. Every
knob that could plausibly affect the outcome lands in exactly one of:

| Mechanism | Question it answers | Who checks it | Violation means |
|---|---|---|---|
| `optimization.factors` | Should the campaign learn this knob's effect? | Python fits it | (not a violation — it's the thing being measured) |
| `locked_parameters` | Is this input pinned so it can never drift? | Validator, every bundle | The spec was silently rewritten (#246) |
| `design_space.invariants` | Does a *property of the resulting system* hold on every config? | Python, on every run in every stage | The campaign left its declared design space |

**The decision test: would you be upset to discover this was violated
after 60 runs?**

- If the answer is "yes, and I want the campaign to actively explore its
  effect" — it's a **factor**.
- If the answer is "yes, and it should simply never change" — it's a
  **locked parameter**.
- If the answer is "yes, and it's a property that should hold regardless
  of which combination of factors is running" — it's an **invariant**.
- If the answer is "no, I wouldn't mind" — it doesn't need any of the
  three; leave it alone.

A parameter that shows up in `target_system.controllable_knobs` but lands
in none of `factors` / `locked_parameters` trips the validator's rule 10
warning — the "what did you forget to control" check. It is advisory, not
a hard failure, but it exists because a knob nobody decided about is a
silent confound.

**"The connector is peer-to-peer" is an invariant, not a locked
parameter**, because it may be an *emergent* consequence of several
settings together rather than one flag you set directly — asserting the
observed transfer path is stronger evidence than pinning the flags you
merely believe produce it. If your invariant is really just "this one flag
has this one value," it should probably be a `locked_parameter` instead;
reach for `design_space.invariants` when the property is a downstream
consequence you want checked at the system-behavior level, not the
input-flag level.

## 5. Steering: the three channels

Three mechanisms carry author intent into an optimization campaign, and
they are not interchangeable — they are consumed by different code at
different times, and treating them as interchangeable is the single most
consequential mistake an author can make (anti-pattern §6.6).

| Channel | Consumed by | When | Shapes |
|---|---|---|---|
| `guidance.factor_nomination` / `guidance.interpretation` | Nothing — **reserved, not read by any stage** | never | Author intent, for human readers |
| `design_space.invariants` | Python | Every run, every stage, including `screen` and `refine` | What Python **executes** |
| `target_system.description` | The model | `build`, when present | Narrative framing, domain context |

The reason this split exists — rather than one big prose field, as in the
reflective kind's `target_system.description` — is structural, not
stylistic: **`screen` and `refine` make zero model calls.** Any directive
written only as prose is unenforceable during precisely the two stages
that spend the benchmark budget. "Single-tier workload only" written into
a description cannot stop a matrix row from being generated with two
tiers, because nothing reads that description while the matrix is
executing.

**The rule for authors:** anything you would be upset to discover was
violated after 60 runs belongs in `design_space.invariants`. `guidance`
shapes what the model *proposes*; `invariants` bound what Python will
*execute*. If you find yourself writing "must always," "never," or "only
if" in `guidance` or `target_system.description`, stop and ask whether
that sentence is describing a property Python could check mechanically —
if so, it belongs in `invariants` instead.

## 6. Anti-patterns

Each of these is a wrong/right pair. Several are defects this campaign
kind's own design and worked examples actually shipped during development
— a documented near-miss teaches better than an abstract warning, so they
are named here rather than smoothed over.

These are mistakes in what you **wrote**. For mistakes in what you
**assumed** about the target — a mis-sized timeout, an inert factor, a noise
floor from the wrong regime — see §7.

### 6.1 Trivially-true manipulation predicates

**Wrong:**

```yaml
manipulation: {observable: telemetry.decay_guard_events, op: ">", value: 0}
```

This passes whenever the stop fires *at all* — it cannot distinguish a
threshold of `0.004` from `0.010`, so it would report a mis-set lever as
"verified." The validator rejects this exact shape (`> 0`, `!= null`, bare
truthiness) as trivially true. **This is not hypothetical: the design
spec's own first-draft worked example shipped this predicate**, and the
guide's own test suite (`predicates.is_trivial`) is what caught it during
review.

**Right:**

```yaml
manipulation: {observable: config.decay_guard_threshold, op: "==",
               value: "{level}", when_not: "off"}
```

Compares against the interpolated level under test. A broken lever that
silently applied the wrong threshold, or none at all, actually fails this
check.

### 6.2 Held-out leakage — including the kind the validator cannot catch

**Wrong (caught by the validator):**

```yaml
response:
  primary: {metric: train_score, direction: maximize}
  held_out: [train_score]     # same metric, hard rejected
```

The validator's rule 2 rejects `held_out` colliding with `primary` /
`constraints` / `regimes` (case/whitespace-insensitively) — this is the
`holdout-selection` leakage class, where a held-out generalization check
was declared but nothing stopped fitting from using it too.

**Wrong (the validator CANNOT catch this one):**

```yaml
response:
  held_out: [held_out_scoer]   # typo: "retrun"
```

A typo in a `held_out` entry makes it **inert**, not leaked. The author
believes the metric is protected; nothing protects it; and because the
misspelled name never resolves against anything the target actually
emits, nothing complains at authoring time either — the validator has no
way to know which metric names the target will produce at runtime, so a
name that simply doesn't match anything looks identical to a name that
does. This has the *same consequence* as leakage (the generalization
check silently does nothing) reached from the opposite direction (nothing
was ever there to leak). Verify every `held_out` name against the
target's actual emitted metric names before running, and watch for it at
`confirm` — the confirm stage reads held-out values from the observation,
so a `held_out` metric that never appears in any recorded observation
across the whole campaign is detectable after the fact, even though the
validator cannot detect it before the fact.

**Right:**

```yaml
response:
  primary: {metric: train_score, direction: maximize}
  held_out: [held_out_score]   # spelled to match the target's actual field
```

### 6.3 Main-effects-only screening when interactions are expected

**Wrong:**

```yaml
design:
  screen: {resolution: 3, center_points: 2}   # 3+ factors, unstated aliasing
```

Resolution III with more than one factor aliases two-factor interactions
onto main effects. The validator's rule 7 warns (does not block) at
`resolution < 5` with more than one factor, because this is the
one-factor-at-a-time failure mode wearing a factorial-design costume — and
the real corpus's headline finding (`ordering-theorem`'s 7.3x interaction,
§3.2) is exactly the kind of result a low-resolution screen would invert
or hide.

**Right:**

```yaml
design:
  screen: {resolution: 5, center_points: 2}
```

Resolution V is the schema's documented default rationale for a reason:
estimate every two-factor interaction unconfounded, and only accept a
lower resolution deliberately, with the aliased pairs named and understood.

### 6.4 Monotonicity misclassified as `correctness`

**Wrong:**

```yaml
relations:
  - {id: R6, kind: correctness,
     statement: "throughput is monotone non-decreasing in batch_size",
     native_test: "tests/prop_batch.py::test_monotone"}
```

A `correctness` violation hard-fails the entire campaign. If batching's
main effect really is negative — as it was in the motivating benchmark,
where L5 measured -9.5% alone yet was required for the best four-lever
compound — this classification would hard-fail the campaign on its own
single most important discovery, on the theory that "the code is wrong"
when the truth is "the system is surprising." Conflating those two would
make the campaign kind structurally blind to exactly the non-monotonic
compounds it exists to find.

**Right:**

```yaml
relations:
  - {id: R6, kind: behavioral,
     statement: "throughput is monotone non-decreasing in batch_size",
     native_test: "tests/prop_batch.py::test_monotone"}
```

A `behavioral` violation is recorded as a finding — often the campaign's
best finding — and the campaign continues. Reserve `correctness` for
claims whose failure really does mean the apparatus is broken (a no-op
baseline that isn't actually a no-op, a conservation law that doesn't
balance), never for a directional claim about how the system *should*
behave when part of the point of running the campaign is to find out
whether it does.

### 6.5 Treating a constrained multi-regime conjunction as a scalar objective

**Wrong:**

```yaml
response:
  primary: {metric: detection_rate_avg_across_rho, direction: maximize}
```

Averaging across regimes lets a config win on the mean while failing one
regime outright — precisely the overfitting `composite-sensitivity-
boundary`'s real trade (§3.3) was built to characterize and prevent. A
scalar objective cannot even represent "good here, bad there" as a
distinguishable outcome from "mediocre everywhere."

**Right:**

```yaml
response:
  primary: {metric: detection_rate_high_rho, direction: maximize}
  regimes:
    - {id: low_rho,  metric: false_positive_rate_low_rho, op: "<=", value: 0.05}
    - {id: high_rho, metric: detection_rate_high_rho,      op: ">=", value: 0.90}
```

`regimes` makes the conjunction mechanical: a config is only admissible if
it holds in *every* named regime, and the per-regime effect fits show
directly whether a factor helps everywhere or trades one leg against
another.

### 6.6 An enforceable directive in `guidance` instead of `design_space.invariants`

**Wrong:**

```yaml
guidance:
  factor_nomination: >
    Only propose single-tier workload configurations; never generate a
    multi-tier matrix row.
```

`screen` and `refine` make zero model calls (§1, §5). This sentence is
never read during either stage — Python is the one generating and
executing matrix rows, and Python does not consult `guidance`. This is the
exact failure mode a prior reflective-campaign bug (#221) hit from the
other direction: a directive honored by the phase that reads prompts and
silently ignored by the phase that does the actual work.

**Right:**

```yaml
design_space:
  invariants:
    - id: I2
      statement: "workload is single-tier"
      observable: config.tier_count
      op: "=="
      value: 1
```

Checked mechanically on every one of the 60-90 runs, in the stages where
no model is watching. Use `guidance` for what you want the model to
*propose*; use `invariants` for what must hold regardless of what gets
proposed.

### 6.7 `type: numeric` on a factor with a non-numeric sentinel level

**Wrong:**

```yaml
- id: F4
  name: decay_guard_threshold
  type: numeric
  levels: [off, 0.004, 0.005, 0.007, 0.010]
```

Two defects stack here. First, `numeric` tells the fitter that values
*between* the declared levels are meaningful and interpolable — but
nothing lives between the sentinel `off` and `0.004`; there is no
"half-off" trailing stop. Second, and more dangerous: **unquoted `off` in
a YAML list is a YAML 1.1 boolean**, not the string `"off"`. This parses
as `levels: [False, 0.004, 0.005, 0.007, 0.010]`, and any `when_not: off`
guard elsewhere in the same factor then compares against the boolean
`False` instead of the sentinel string — silently changing which levels
the guard excludes. **This exact mistake shipped in the design spec's own
first-draft worked example.**

**Right:**

```yaml
- id: F4
  name: decay_guard_threshold
  type: choice
  levels: ["off", 0.004, 0.005, 0.007, 0.010]
```

`choice`, because nothing lives between `off` and `0.004` — and `"off"`
quoted, so it survives as the string it's meant to be.

### 6.8 `complexity_tier` under `kind: optimization`

**Wrong:**

```yaml
kind: optimization
complexity_tier: 1
tier_justification: "single mechanism, single knob screen"
```

or, equally wrong, nested under `metadata`:

```yaml
metadata:
  complexity_tier: 1
```

The #159 graded-complexity tier ladder — "iteration N may use any tier
`<= N`," designed to stop a campaign from asserting a sophisticated causal
mechanism claim before simpler ones are ruled out — is scoped to
`kind: reflective` only (see `CLAUDE.md` and the design spec's §7.2). It
does not apply here, and the validator (rule 9) rejects `complexity_tier`
/ `tier_justification` wherever it appears: top level, under `metadata`,
or under `optimization`. The reason is not "the ladder is inconvenient" —
it's that a pre-registered design matrix already gives a *stronger*
anti-p-hacking guarantee than the ladder protects (every configuration is
fixed before any result is seen, so there is no way to choose the next
factor after seeing which way the data broke), and half-adopting both
disciplines on the same campaign would be incoherent.

**Right:** simply don't declare a tier field anywhere on an
`kind: optimization` campaign. If you want to reason about how
sophisticated the factor structure is, that's what `design.screen.resolution`
and the factor count already express.

## 7. Pre-flight: measure the apparatus before you pre-register a design

Everything in §6 is a mistake in what you *wrote*. This section is about
mistakes in what you *assumed* — and they are more expensive, because a
campaign whose design is sound but whose apparatus is mis-sized still burns
its whole run budget before saying so.

The rule that ties this section together:

> **A pre-registration is a promise about an experiment that can execute.
> Probe first, then compile.**

`nous validate campaign FILE --smoke` is the first line of defence and should
always be run. But `--smoke` executes **one** configuration; several apparatus
properties only show up across a *range* of configurations, and those are what
this section covers. Every item below is a defect a real campaign shipped.

### 7.1 Size `run_timeout_sec` from a measured worst case, not a typical one

**Wrong:** leave `optimization.run_timeout_sec` at its default, having timed
one run.

**Right:** time the *slowest plausible* configuration, then set the ceiling
with headroom.

```yaml
optimization:
  # Measured: baseline (LRU, large tier) bisects in ~330 s. The slow corner
  # (ARC, small tier) takes materially longer -- ARC's bookkeeping on a
  # smaller tier does more work per step. 1800 s covers the slow corner with
  # ~2x headroom.
  run_timeout_sec: 1800
```

This is worth its own item because of *how* the failure presents. The
campaign does not warn you; the row simply dies:

```
RuntimeError: config run failed: Command '[...]' timed out after 600 seconds
```

A real campaign hit this twice. The first timing pass measured the **baseline**
configuration (~330 s, comfortably inside the ceiling) and concluded the
budget was fine. The screen then died on its first row, which the randomized
run order happened to make the *slow corner* of the space. Note the ordering
is the point: a pre-registered design deliberately randomizes run order, so
you cannot assume the cheap corners run first and warn you gently.

Two properties make an objective especially prone to this:

- **A compound response.** If one objective evaluation is itself a search — a
  bisection, a ramp, a convergence loop — its cost is a multiple of a single
  run's. Time the *evaluation*, not the run.
- **Factors that change the cost of measuring.** A factor that alters how much
  work the target does per unit of measurement (cache size, policy complexity,
  concurrency) makes cost vary *across the design matrix*, so the mean is the
  wrong statistic. Take the max.

**Probe recipe:** measure the two extreme corners of your factor space (all
factors at their cheapest levels, all at their most expensive), take the
larger, and set `run_timeout_sec` to roughly twice it. Cheap: two runs.

**For a compound objective, corners are not enough — size from the slowest
PROBE the search can reach.** This is the subtler half, and getting it wrong
cost a row in a real campaign even after the ceiling had already been raised
once from the corner measurement.

When the objective is a search (a bisection over a load level, a ramp, a
convergence loop), each probe's cost depends on the *value being probed*, not
only on the configuration. If the target does work proportional to the probed
value — a load level `v` sustained over an observation window `T` does `v x T`
work — then a probe at 16x the baseline value costs roughly 16x as much. The
bracket's reachable ceiling therefore sets the worst-case row:

    worst row  ~=  (max reachable probe / baseline probe) x baseline row cost

with `max reachable probe = hi x 2^(expansion steps)` for a doubling search.
Concretely, from a real campaign: a bracket of `[0.75, 3.0]` with 5 evaluations
can double `hi` three times to 24 — 16x the baseline probe — so a 330 s baseline
row implies a ~5,300 s worst row. A ceiling of 2,400 s looked generous against
the measured corners and was still 2x short; two rows died on it.

**The perverse consequence, which is what makes this a trap:** a *better*
configuration costs *more* to measure, because the search must climb higher
before it finds a failing point. So the rows most likely to time out are the
ones carrying your best candidates — and losing them biases the surface toward
mediocre configurations while every diagnostic looks healthy. Bound the search
explicitly (cap the bracket, or cap the probe value) rather than relying on the
timeout to do it.

### 7.2 Verify each factor actually moves the response, at the operating point

**Wrong:** declare eight factors because the target documents eight knobs.

**Right:** measure each factor's effect against the noise floor first, and
declare only the ones that clear it.

`--smoke` checks that manipulation predicates **hold** — that the lever
engaged. It does not check that the lever **matters**. A factor whose levels
move the response by less than run-to-run noise passes every static and smoke
check, consumes its share of a resolution-V design, and contributes only
variance to the fit. A policy hash computed over such factors is a
pre-registration of nothing.

**Probe recipe**, and note both halves are required:

1. **Noise floor.** Run the baseline configuration at ≥5 workload seeds.
   Compute the coefficient of variation of your objective. That is your floor.
2. **Per-factor effect.** For each candidate factor, run its extreme levels
   with everything else at baseline. Effect size is the difference in the
   objective.
3. **Keep a factor only if `|effect| > 2 x noise CV`.** Report the ones you
   dropped; a factor that does not move the response is a finding about the
   target, not a failure of the campaign.

A real campaign began with eight candidate factors and found that **three
were unusable** — two levels caused the target to abort outright, and two more
produced byte-identical output because the knob was captured in config but not
yet consumed by any mechanism. Discovering that after pre-registration would
have spent the run budget on dead axes.

### 7.3 Measure the noise floor at the operating point you will actually run

**Wrong:** measure noise once, anywhere, and reuse the number.

**Right:** measure noise at, or near, the configuration the campaign will
spend most of its budget on — and re-measure if you change the operating
point.

Noise is not a property of the target; it is a property of the target *at a
load*. The same system measured below capacity, near capacity, and past
capacity gives three different variances, and the ordering is not always
intuitive. In one measured case a tail percentile was *less* noisy than a
lower percentile at the same load, which inverted the obvious choice of
objective.

Worse, effect sizes measured in the wrong regime can be **actively
misleading** rather than merely imprecise. The same campaign measured
apparent factor effects of −6.8% while the system was queue-bound; at a
healthy operating point the same factors moved the objective by 0.3–3.3%
against a 4.8% noise floor — i.e. nothing. The large effects were queueing
dynamics that happened to correlate with the config change.

`response.noise_estimate_pct` should be a number you measured, not a guess.

### 7.4 Check that your objective is a fittable response

**Wrong:** pick the metric your stakeholders quote.

**Right:** pick a metric that (a) responds monotonically to the thing you are
varying, and (b) does not swing by orders of magnitude on a single factor
change.

Symptoms that a metric is unfittable, all observed:

- **Extreme tail sensitivity.** In one campaign a single factor change moved an
  extreme tail statistic (a 99th percentile) by +268% while a less extreme one
  (90th) moved +9%. A surface fitted to the extreme tail is fitting a handful of
  unlucky observations, not the system. Prefer the least extreme statistic that
  still answers the question you were asked.
- **Censoring.** A default request timeout pinned the objective at the deadline
  for every overloaded configuration (three configurations all reporting
  ~300,000 ms — the timeout, not a latency). The surface goes flat exactly
  where the search operates. If your target has a deadline, either raise it
  beyond any plausible measurement or exclude censored rows explicitly.
- **Degeneracy.** An objective can be pinned by something you held fixed — a
  throughput metric under a fixed offered load is largely determined by that
  load, not by the factors. Sweep one factor and confirm the objective actually
  moves before you optimize it.

**Probe recipe:** sweep one factor across its full range and plot the
objective. If it is monotone and its dynamic range comfortably exceeds the
noise floor, it is fittable.

### 7.5 Confirm the workload exercises the mechanism under study

**Wrong:** use the target's default workload.

**Right:** confirm the subsystem you are tuning is actually active, by reading
a metric that proves it.

A campaign tuning a caching subsystem ran the target's default workload and
measured a hit rate of **exactly 0.000** — that workload had no reuse at all, so
every cache factor was inert for a reason that had nothing to do with the
factors. The tell was in the target's own metrics output the whole time, unread.

Pick one metric that is **zero when the mechanism is idle** and assert it is
non-zero before you launch. For a cache: hit rate. For an eviction policy:
eviction count. For an admission controller: rejection count. Then put it in
`design_space.invariants` so a configuration that silently disables the
mechanism is recorded as infeasible rather than fitted as a data point.

### 7.6 The observation window is part of the objective's definition, not a speed knob

**Wrong:** shorten the measurement window to make rows cheaper.

**Right:** treat the window length as fixed by the objective's semantics, and
validate it against a configuration whose answer you already know.

Many objectives are computed over a window of observed behaviour — a trend, a
rate, a steady-state level, anything fitted over time. Such a metric has a
*settling* requirement: the window must be long enough for start-up behaviour to
stop dominating it. Trim the window for speed and you do not get a noisier
version of the same measurement, you get a **different and biased** one.

Measured, from a real campaign whose objective was the largest load a system
sustains without its backlog growing:

| window | wall per run | samples | fitted trend, two seeds | verdict |
|---|---|---|---|---|
| short (2/3 length) | 38-44 s | ~2,540 | +0.1643, +0.0625 | **growing** |
| full | 70-74 s | ~3,875 | +0.0553, -0.0247 | **sustained** |

Same configuration, same load, same seeds, **opposite verdicts** — and the short
window is 1.8x faster, which is exactly what makes it tempting. The cause is that
the short window still contains the cold-start ramp (the system filling from
empty), and a trend fitted across a ramp reads as growth. The longer window lets
the ramp amortise so the real trend shows.

The consequence is not symmetric noise: a too-short window declares saturation
too early on **every** configuration, so every reported optimum shifts in the same
direction. A 1.8x speedup that moves every number one way is not a speedup, it is
a different experiment.

**Validation recipe.** Pick a configuration you are confident is comfortably
inside capacity. Measure it at your candidate window and at 1.5x that window. If
the verdict or the fitted quantity changes, your window is too short — the metric
has not settled. Repeat until two adjacent window lengths agree, then lock the
longer one into `locked_parameters` so a later iteration cannot quietly trim it.

This is the same failure mode as computing the statistic over the wrong *region*
of a run rather than the wrong *length* — in the same campaign, a trend computed
over a window that included the post-arrival drain reported "stable" for a system
whose backlog was growing throughout the active phase. Both are cases of a
correct statistic over an incorrect window.

### 7.7 Make your probe harness fail loudly

**Wrong:**

```python
subprocess.run(cmd)                 # exit code ignored
d = json.load(open(metrics_path))   # may be a stale file from the last run
```

**Right:**

```python
if os.path.exists(metrics_path):
    os.unlink(metrics_path)         # never read a stale result
p = subprocess.run(cmd, capture_output=True, text=True)
if p.returncode != 0:
    raise ProbeError(f"exit {p.returncode}: {p.stderr[-400:]}")
if "panic:" in p.stdout + p.stderr:
    raise ProbeError("target panicked")
if not os.path.exists(metrics_path):
    raise ProbeError("no metrics written")
```

This belongs in a guide about *campaigns* because the probes that size your
apparatus are usually throwaway scripts, and a throwaway script that fails
silently produces confident wrong numbers that then get pre-registered.

The concrete failure: a probe harness that ignored exit codes and re-read a
stale metrics file reported a factor level as having **no effect, identical to
baseline** — when in fact that level made the target *abort*. Three factors
were briefly believed live on that basis. The same class of defect as this
kind's two historical fit bugs (a singular `XᵀX` from aliased columns; NaN
poisoning from infeasible rows): **a silent failure that looks like a clean
result.**


**Assert that the reported answer satisfies its own predicate.** This is the
sharpest form of the rule above, and the one that catches the bug a fail-loud
wrapper misses.

A measured campaign shipped rows of the form:

    max_sustained_rate = 2.1562        # "this load was sustained"
    backlog_slope      = 0.1234        # the growing threshold was 0.060

Those two lines contradict each other: the reported answer is a point the run's own
recorded diagnostic classifies as *not* sustained. **8 of 12 rows** had this shape,
every one biased in the flattering direction, and nothing caught it — exit codes
were clean, the file was present and parseable, the manipulation predicates passed,
and the schema validated. The harness was loud about *failures* and silent about a
*self-contradiction*.

No amount of threshold calibration finds this. Only an assertion tying the returned
value back to the evidence does:

```python
lam, diagnostics = search(...)
slope = diagnostics["slope"]
if slope > GROWING_THRESHOLD:
    raise SearchError(
        f"reported {lam} as sustained but its own slope {slope} exceeds "
        f"{GROWING_THRESHOLD} — refusing to report a self-contradictory result")
```

Generalize it: whenever an objective is defined by a **predicate over a
diagnostic** — "the largest input for which the system is stable", "the smallest
setting that still converges", "the highest load meeting a bound" — the returned
extremum must be re-checked against that predicate before it is reported. A search
that returns a point violating its own acceptance test has a bug in the search, not
a measurement worth recording. Make that a hard failure, because as data it is
indistinguishable from a good result.

### 7.8 Point certifying relations at tests that fail without the mechanism

**Wrong:** hang a `correctness` relation on an existing test that already
passes, because it happens to cover the area you are changing.

**Right:** point it at a test that is *new with*, or *strengthened by*, the
mechanism.

`verify` enforces this and will hard-fail:

```
native test(s) TestFoo passed before the mechanism existed — a test that
passes without the mechanism does not test it, so it cannot certify the
apparatus every later measurement rests on.
```

A real campaign hit exactly this. It deliberately pointed three relations at a
guard test that asserted the *unimplemented* state of the mechanism — good
instinct, wrong slot. That test necessarily passed on the pre-build tree, so it
could not certify anything. The right structure is:

- **Certifying relations** → the new tests the mechanism brings with it.
- **A stale guard test** → still required to pass (so the change cannot quietly
  delete it), but checked as a *diff review*, not as a certifying relation.

`optimization.build_checks.allow_preexisting_tests: true` exists for the
legitimate case — a genuine backward-compatibility relation, where "this still
behaves as it did" is exactly the claim.

### 7.9 The pre-flight checklist

Run these before you let a policy hash be written. Total cost is a handful of
runs against a budget of 60–90.

| # | Check | Cost | Fails if |
|---|---|---|---|
| 1 | `nous validate campaign FILE --smoke` | 1 run | predicates unsatisfiable, tests unmatched, `run_command` cannot exec |
| 2 | Mechanism is active (§7.5) | 1 run | the mechanism's own metric is zero |
| 3 | Noise floor at the operating point (§7.3) | ≥5 runs | — (produces `noise_estimate_pct`) |
| 4 | Per-factor effect vs noise (§7.2) | 2 per factor | any factor under 2x the noise CV |
| 5 | Objective is monotone and uncensored (§7.4) | 4–6 runs | orders-of-magnitude swings, or values pinned at a deadline |
| 6 | Observation window has settled (§7.6) | 2 runs | the verdict or fitted value changes between a window and 1.5x it |
| 7 | Worst-*probe* timing (§7.1) | 2 runs | `run_timeout_sec` under ~2x the most expensive probe the search can reach |

If a check fails, revise the campaign — **not** the check. A pre-registration
whose apparatus was not verified first is a hash over an assumption.

## See also

- [`docs/campaign-authoring-guide.md`](campaign-authoring-guide.md) — the
  reflective kind's authoring guide (locked parameters, rehearsal
  discipline, spec fidelity).
- [`docs/targets.md`](targets.md) — the **target adapter contract**: what
  `run_command` and `test_command` must emit, the `NOUS_WORKLOAD_SEED`
  verification recipe, why SLA constraints define validity rather than a
  penalty, and per-target notes for inference servers, vector databases,
  analytical query engines, autoscalers, and eBPF datapaths. Read it before
  writing a campaign against a real system.
- [`docs/superpowers/specs/2026-08-16-compiled-policy-design.md`](superpowers/specs/2026-08-16-compiled-policy-design.md) —
  the binding design authority for the compiled policy: `policy.json`,
  `step()`, the closed observation and operator vocabularies, the two
  residual-regret bounds, the fallback ladder, and the three oracles. This is
  what "The compiled policy" section above documents.
- [`docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md`](superpowers/specs/2026-08-13-optimization-campaign-kind-design.md) —
  the original design spec for the kind, including the architecture and
  failure-taxonomy rationale behind most rules cited above. **Superseded in
  part:** its §5.5 (artifacts) and §6.3 (stage transitions) predate the
  compiled policy — see the note at the top of that file.
- [`docs/data-model.md`](data-model.md) §7 — the per-artifact reference for
  everything the epoch writes.
- `orchestrator/schemas/campaign.schema.yaml`, the `optimization` block —
  the schema-level source of truth for every field in §2.
- `orchestrator/validate.py`, `_rule1`..`_rule10` — the cross-field rules
  this guide is written to never contradict.
