# Optimization campaign guide (`kind: optimization`)

This guide is the authoring interface for `kind: optimization` campaigns.
It exists alongside [`docs/campaign-authoring-guide.md`](campaign-authoring-guide.md)
(the reflective kind's guide) but is not a variant of it: the two kinds
answer different questions. Reflective campaigns build causal claims about
*why* a system behaves as it does, one designed iteration at a time.
Optimization campaigns fit a *response surface* over knobs the author
already controls, in a design fixed before any result is seen.

**This kind is not about servers.** The machinery is a factorial design over
declared levels, a predicate that each lever engaged, a native test that the
mechanism is correct, and a bound on how much better the unknown best
configuration could be. Any field where all four exist is in scope — solver
tolerances and mesh resolutions, compiler flags, training hyperparameters,
aligner sensitivity settings, process set points — and §3 opens with the mapping
from the abstractions to four different domains, then works examples in each. If
an example in this guide is phrased in serving terms, that is provenance (the
corpus it was measured on), not a scope statement.

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

**Before you launch anything, read §7 (pre-flight), and run its §7.9
checklist.** Static validation and `--smoke` catch a campaign that cannot
execute; §7 covers the apparatus properties that only show up across a *range*
of configurations — a timeout sized from the wrong corner, a per-row limit that
binds harder on one factor level and deletes its evidence, a design that stops
being fittable when rows fail, a factor that moves nothing, a noise floor
measured in the wrong regime, an objective that is not fittable, an adapter that
records too little to debug itself. Each item there is a defect a real campaign
shipped — several of them *after* the paragraph warning against it was already in
this guide, which is why §7.9 is a checklist to execute rather than advice to
absorb.

**And once an epoch is measuring, the apparatus is frozen.** Not the campaign
YAML, not the adapter, not the workload, not the resource limits. Changing any
of them is an epoch boundary and never an edit — see "An apparatus change is an
epoch boundary, not an edit" in the compiled-policy section for the procedure and
for what a ninety-second "improvement" actually costs.

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

A worked instance, measured on a discrete-event scheduling simulator: six
two-level policy and capacity factors over a fully-loaded workload, the
objective spanning 23.45 to 117.85 (a 5x range). The surface has three real
interactions and one factor showing the textbook sign flip — one knob at
-43.82 alone and +81.03 in the best context — and greedy *still* reached
the optimum from all 64 starting points. Real interactions and a
sign-flipping factor are **not sufficient** for a trap; that is exactly why
this is worth checking rather than assuming.

The check is domain-agnostic — `traps_greedy` above takes a dict of
configurations to responses and knows nothing about what the configurations
are. Run it on a solver's tolerance/preconditioner grid, a compiler's flag
combinations, or a hyperparameter cube exactly as written; the only cost is
being able to evaluate a modest space exhaustively once.

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
- **`self_check`** — invariants the row's **own response** must satisfy for its
  reported objective to *be* the objective. Same `{observable | metric, op,
  value}` shape as `constraints`, and a different question: a constraint asks
  *is this configuration admissible?* (violation → `infeasible`, real data about
  the space, retained), while a self-check asks *does this row contradict
  itself?* (violation → `failed`, excluded from the fit). Declare one whenever
  the objective is defined by a **predicate over a diagnostic** — "the largest
  rate that was sustained", "the smallest setting that still converges", "the
  highest load meeting a bound". See §7.7 and the "Guarding the adapter"
  section below.
- **`constant_fields`** — response fields that legitimately never vary across
  rows (a schema version, a host name, a build tag). Excluded from the
  output-freshness guard's byte-identity comparison, which makes that check
  *stricter* on what remains. See "Guarding the adapter" below.
- **`noise_estimate_pct`** — rough expected measurement noise as a percent
  of the primary metric, used to size replicate counts.

### Guarding the adapter: the three checks Nous applies to your `run_command`

`policy.json` is content-hashed and a mid-epoch edit hard-aborts, because a
pre-registered policy that changed inside an epoch is not a pre-registration. A
pre-registered design makes the same assumption about the **measurement
instrument** — your adapter — and until these three guards nothing enforced it.
Each closes a defect observed on a real campaign, where the adapter produced
plausible-but-wrong numbers Nous had no way to question.

| Guard | Fires when | Consequence | Turn it off by |
|---|---|---|---|
| **Contract drift** | this row's response has a key the epoch's first successful row did not, is missing one it had, or reports one at a different **type** (including `null`) | campaign **abort** | nothing — it is always on |
| **Output freshness** | this row's response object is byte-identical to the immediately preceding row's while the factor levels differ | **row failure** (excluded from the fit) | declaring `response.constant_fields`, or reporting a diagnostic alongside the objective |
| **Declared self-check** | a `response.self_check` predicate fails on this row's own response | **row failure** | declaring no `self_check` (the default) |

**Contract drift** — at the first *successful* row of an epoch, Nous
fingerprints the adapter's output contract (every top-level key name and its
value's type, never the values themselves, which legitimately change per row)
and writes it to `adapter_contract.json` + `adapter_contract.sha256` at the
work-dir root, beside `policy.json`. Every later row is checked against it. The
fingerprint is epoch-scoped, so the contract captured at `screen` is the one
`refine` and `confirm` are checked against — an adapter edited *between* two
iterations of one epoch is exactly the interval the real defect occupied.

An added key aborts just as a removed one does, and that is deliberate. The
tempting answer is a warning: an extra key is additive and nothing downstream
reads it. That is right about the row and wrong about the epoch — the only way an
adapter grows a key between two rows of one pre-registered design is that the
adapter was edited mid-epoch, and in the real defect the added key was the
*carrier* of the damage: the rows measured **before** the edit are the ones that
end up `null`, and they are already on disk and unfixable by the time the new key
appears. The real consequence was a `None` reaching a `float()` coerce and a `>=`
against a float — an entire iteration killed at fit time, after ~2 hours of
measurement.

**An apparatus change is an epoch boundary, not an edit.** If you improve your
adapter mid-campaign, end the epoch and let the next one capture the new
contract (see "Semantic exceptions, and how to start epoch 2"). Do not edit
`adapter_contract.json`; its hash sidecar is checked, exactly as `policy.json`'s
is.

**Output freshness** — Nous cannot police your adapter's internals, but it can
assert what it observes. A response whose *entire* object is byte-identical to
the immediately preceding row's, while the levels differ, is the signature of a
cached or stale read. The real defect: an adapter reused a stale metrics file
whenever the target exited non-zero, so a factor level that **panicked** was
recorded as "no effect, identical to baseline" — and three factors were briefly
believed live on that basis.

Two different level combinations *can* legitimately produce the identical
objective value (`arc` and `lru` both measured exactly 1.3125 on a live
campaign), so the check compares the **full response object**, not the objective,
and only against the **immediately preceding** row. It has one honest limit: an
adapter that echoes its own configuration back emits a response that differs on
every row by construction, so the guard cannot fire for it even when every metric
is stale. That is the case `self_check` and `--liveness`'s effect-size
measurement cover instead — a factor whose objective never moves reads as a dead
axis.

**Declared self-check** — Nous cannot know your objective's semantics, so it
cannot detect a self-contradictory row itself. You state the invariant; Nous
enforces it, per row, and on the configurations `--smoke` and `--liveness` run:

```yaml
response:
  primary: {metric: max_sustained_rate, direction: maximize}
  self_check:
    # the reported optimum must satisfy the predicate that DEFINES it
    - {metric: backlog_slope, op: "<=", value: 0.060}
```

On a real campaign that one line would have failed **8 of 12 rows** at the
moment each was measured. Without it, every one reported a flattering
`max_sustained_rate` whose own recorded `backlog_slope` said the rate was
growing — exit codes clean, file present and parseable, manipulation predicates
passing, schema validating — and the epoch's fit was believed.

A violation fails only its own row, never the campaign: in the real defect 4 of
12 rows were sound, and aborting would have discarded them. The verdicts are
recorded in `runs.jsonl`'s `self_check` field on **passing** rows too, so a
reader can tell "the invariant held" from "no invariant was declared" (§7.7's
"record enough to adjudicate a flag you raise").

Two things the validator rejects: a **trivially true** self-check (it certifies
nothing while making the campaign look checked, and an author who declares one
reasonably stops looking by hand), and a self-check **over the primary metric
itself** — a bound on the objective is `response.constraints` (violation →
`infeasible`, retained) or `response.ceiling` (violation → the instrumentation is
lying), and as a self-check it would throw away a measurement that is merely
unattractive.

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

Structured prose in two named slots. The two are read very differently, and the
difference matters:

- **`factor_nomination`** — **passed verbatim to the `build` stage's prompt**
  when `build` is declared (as "AUTHOR'S GUIDANCE ON THE MECHANISM"), and
  otherwise unread. Domain knowledge about which axes matter, which mechanisms
  already exist in the target, which plumbing path to use, and which failure mode
  to avoid belongs here. **This is the channel for anything the agent writing the
  mechanism needs to know.** Without `build` in `stages`, nothing consumes it —
  the tokenless stages have no prompt to put it in.
- **`interpretation`** — **reserved, not read by any stage.** Scope limitations
  and "report X as a lead, not a result" belong here. It is deliberately NOT
  passed to `build`: it steers how *results* are read, and `build` makes no
  correctness judgement (`verify` is the gate), so handing it the interpretation
  rules would invite it to pre-judge a measurement it is not allowed to make.

**Why `factor_nomination` reaching `build` is load-bearing.** It did not, until a
two-arm field test was confounded by the gap. The author had written the target's
known crash mode — *"naively skipping this call raises IndexError because the
shared buffer's per-frame claim goes unmade"* — into `factor_nomination`,
reasonably assuming a field named *guidance* reaches the agent being guided. It
reached nobody: `build_prompt` read only `research_question` and
`target_system.description`. The build then shipped the exact defect the author
had already diagnosed, while the reflective arm of the same comparison — which
carries the same facts in its `research_question`, and that *is* its prompt —
avoided it. A 10x optimality gap between the two kinds was therefore partly an
artifact of which YAML field the author happened to choose.

**So: if `build` needs to know it, put it in `factor_nomination` or in
`target_system.description`. Those two are the only prose that reaches it.**

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

**Declare it.** Every campaign this repo has run left it at the default, and at
least one of them then spent its entire `confirm` stage running one row at a
time on a many-core machine — not because sequential execution was the right
call, but because nobody had written the field down anywhere an author would
copy it from. The default is 1 for backward compatibility, not because 1 is the
right value for your machine. So here is the arithmetic worked all the way
through, for a `confirm` stage that a real campaign's `design` block would
produce:

```yaml
optimization:
  # Machine: 16 physical cores. One run_command needs ~4 cores (the target
  # spawns 3 workers plus the harness), so 4 concurrent rows saturate the
  # machine without time-slicing. Measured: one row is ~9 min.
  max_parallel: 4
  design:
    confirm: {replicates: 5, shortlist_size: 3}
```

`shortlist_size: 3` × `replicates: 5` = **15 rows** at `confirm`. Blocks are a
barrier, so with `max_parallel: 4` the execution is:

| Replicate block | Rows in flight | Wall clock |
|---|---|---|
| 1 | 3 (all three finalists, concurrently) | ~9 min |
| 2 | 3 | ~9 min |
| ... | ... | ... |
| 5 | 3 | ~9 min |
| **total** | **15 rows in 5 rounds** | **~45 min** (vs ~135 min sequential) |

Note what the bound is *not* doing. It is `4`, but only 3 rows are ever in
flight, because a block holds 3 finalists and the block boundary is a barrier:
replicate *i* of every finalist completes before replicate *i+1* starts. So
`max_parallel` here is a ceiling that the block size, not the ceiling, actually
binds — and that is the normal case. **Size it from cores anyway**, because the
effective concurrency is `min(max_parallel, shortlist_size)` and you want the
ceiling to be the thing protecting the machine, not an accident of the shortlist
size. Setting it to `16` on this machine would let a `shortlist_size: 16`
campaign (or a future round with a wider shortlist) time-slice 16 runs across 16
cores with 4 cores of demand each.

The saving is real (3x here) and it comes with no statistical cost, for the
reason developed below — which is the same reason it is not available at `screen`.

It applies to **`confirm` replicate blocks** unconditionally, and to the
spending stages — `screen`, `foldover`, `refine` — **only when the campaign
licenses them** via the `optimization.concurrency` block documented below.
On `max_parallel` alone the spending stages stay sequential, and the reason is the
same one that makes the design worth running at all.

**Why screen rows are excluded by default.** A spending stage fits a response surface over
*distinct* configurations. Co-scheduled rows contend for machine resources, so a
row's measured response comes to depend on which *other* rows happened to run
beside it — and contention spread unevenly across a design is absorbed by the
fitted coefficients as though it were a factor effect. This is not the same
problem as drift, which the pre-registered randomized run order already handles:
a permutation spreads a *time* trend across the levels, but it can do nothing
about a *neighbour* effect, because permuting the rows permutes the neighbours
too. Randomization is a defence against confounds that vary with *time*; a
neighbour effect varies with *the permutation itself*, so no permutation removes
it. That distinction is the whole argument, and it is why "we randomized the run
order" is not an answer here.

Whether contention is first-order or a rounding error depends on the target, and
the honest split is not systems-versus-not:

| Contention is the measurement | Contention is closer to noise |
|---|---|
| an objective defined by where the system saturates (a queue, a cache, an autoscaler) | a fixed-work computation whose answer does not depend on how fast it ran |
| any wall-clock or throughput objective on shared cores | an objective that is a *count* or a *tolerance* (iterations to converge, coarsest feasible mesh, accuracy at a fixed epoch count) |
| anything memory-bandwidth-bound or cache-resident | anything that mostly waits on a remote service and holds no core |

The right-hand column is real — a solver's iteration count to a residual (§3.5)
does not care who else is on the machine, and a compiler's *output* does not
either. But the objective in both of those examples is guarded by a wall-clock
`constraint`, and *that* is contention-sensitive: co-scheduling would push rows
over a `wall_sec` budget and mark them infeasible for a reason that has nothing
to do with their levels — which is the level-correlated-limit bias of §7.1a
arriving through the back door. The bound is unconditional for that reason: even
where the primary metric is safe, the constraints usually are not.

Parallelizing an 18-row screen would turn a 3-hour campaign into a 45-minute one
and hand back coefficients that partly describe your machine's scheduler.

**One qualification, landing as this is written.** A concurrent change adds an
opt-in `optimization.concurrency` block that *licenses* concurrency at the
spending stages — via either `load_independent: true` (your asserted claim that
the objective is not a function of machine load: an iteration count, an output
size, a discrete-event simulated time) or `contention_probe_levels` (Nous
measures a contention floor at the design's **heaviest** corner and certifies a
width only if the objective moves less than 2x that floor). Read the two
paragraphs above as the reason that license has to be *explicit and defended*
rather than a flag you flip: the confound is real, the randomized run order does
not remove it, and the right-hand column of the table above is exactly the set of
targets for which `load_independent` is an honest claim.

#### Licensing the spending stages: `optimization.concurrency`

`max_parallel` alone never widens a spending stage; this block is what does. It
exists because the confound above is real, so a width there has to rest on a
**recorded basis** rather than on the campaign asking for one. Declare exactly one
of two fields:

```yaml
optimization:
  max_parallel: 4
  concurrency:
    load_independent: true      # (A) your claim, no measurement
    # contention_probe_levels:  # (B) Nous measures a floor instead
    #   {LOAD: 4096, WORKERS: 64}
```

**(A) `load_independent: true`** asserts that the objective is not a function of
machine load — an iteration count, an allocation count, an output size, a
bit-identical checksum, a discrete-event simulator's *simulated* time. That is the
right-hand column of the table above. It is recorded as your claim, not as
something Nous measured, and it is falsified for free afterwards: if two rows with
identical levels and the same workload seed report different objectives, the stage
says so. Do **not** declare it for a throughput, a queue depth, or a latency
percentile measured under real load.

**(B) `contention_probe_levels`** has Nous measure a **contention floor** before
the first spending stage writes its matrix: it runs that corner serially several
times to get the target's own noise floor, then runs it at the declared width, and
certifies the width only if the objective moved **less than 2x** that floor.

**Name the heaviest corner, never the baseline.** This is the one place the obvious
choice is unsound, and the numbers are worth internalising. Take a soft-knee
throughput and let co-scheduling cost 10% of machine capacity, against a 2% noise
floor (so a 2x gate admits inflation under 4%):

| Probe corner | Inflation at width N | Verdict under a 4% gate |
|---|---|---|
| light load (`known_valid_baseline`) | 1.0% | **passes** |
| mid load | 5.3% | fails |
| saturating load | 9.2% | fails |

A floor measured at the baseline would therefore **certify the very design whose
interesting corners it gets wrong by 9%** — contention inflation grows with load,
and a response-surface campaign cares about the loaded corners. That is why the
field is explicit and is never defaulted to `known_valid_baseline`.

Either way the width is capped at `os.cpu_count()`. Under this block that cap is a
**hard error** rather than the advisory warning it is for `confirm`: the
I/O-bound-run exception cannot rescue a spending stage, where the confound is
first-order instead of cancelling.

**Defaults.** Declaring a basis with **no** `max_parallel` resolves the width to
`min(4, cpu_count - 2)` rather than 1 — a declared basis should buy wall clock
without also making you pick a thread count. The cap of 4 is deliberately modest
because **your adapter's own internal fan-out multiplies it**: a real campaign
whose `run_command` itself spawned 4 concurrent probes per row would have put 16
processes on a 10-CPU box at width 4. Nous cannot see that fan-out; you can.

**Declaring `max_parallel > 1` with no `concurrency` block** at a spending stage
resolves to **1**, and the artifact records that. This is deliberate rather than
silent: a pre-registration must describe the runs it registered, so
`design_matrix.json` records the *effective* width and the reason. An
**incoherent** block *is* refused at validation time — an empty block, both
fields at once, or a width above the CPU count — because "silently ran at 1"
wastes a day and explains nothing, while "silently ran wide" corrupts the surface.

**Verify it from the artifact, not from prose.** Every iteration's
`design_matrix.json` carries three fields you can read back:

| Field | Meaning |
|---|---|
| `max_parallel` | the **effective** width the rows actually ran at |
| `concurrency_basis` | `serial` \| `confirm_block` \| `load_independent` \| `contention_floor` |
| `concurrency_certified_width` | for `contention_floor`, the width the evidence covers — `max_parallel` may be narrower, never wider |
| `concurrency_detail` | the measured numbers, or whose claim it was |

`jq '.max_parallel, .concurrency_basis' runs/iter-2/design_matrix.json` tells you
in one line whether a screen ran as a sequence or a schedule, and on what grounds.

#### Isolation is separate, portable, and unconditional

Contention is a *statistical* property; **clobbering is a correctness one**, and
the two are handled differently. At every width including 1, Nous exports into
each run's environment:

| Variable | Meaning |
|---|---|
| `NOUS_RUN_DIR` | a private, existing, writable directory for this row |
| `NOUS_ROW_INDEX` | the row's index |
| `NOUS_RUN_SLOT` | the concurrency slot, or `0` |

**Write your build output, metrics file, and temp data under `NOUS_RUN_DIR`.** Two
rows sharing one `go build -o` path is a real defect that produced plausible
numbers from the wrong binary, with nothing in any artifact to show it. Factors
using `apply.kind: config_patch` are already isolated on the input side (each run
gets its own patched copy), so this closes the output side. It is exported at width
1 as well so that the same adapter code path runs serially and concurrently — a
variable that only appeared above width 1 would make concurrency the first thing
to exercise it. See `docs/targets.md` for the adapter contract.

**CPU pinning is deliberately not offered.** A disjoint CPU set partitions CPU
time slices and per-core L1/L2, and leaves shared: L3/LLC, memory bandwidth and
controllers, disk queue depth, page cache, NIC queues, thermal budget, and the
GPU. Two channels closed, seven open — so for a throughput or tail-latency
objective it isolates almost nothing the objective reads, while a per-row CPU set
in the artifact would testify to an isolation the measurement never had. That is
declined on the merits, independently of `os.sched_setaffinity` being Linux-only.

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

Row-level concurrency at the spending stages is reachable only by *closing* the
confound rather than ignoring it — which is what `optimization.concurrency` above
does, by either an explicit load-independence claim or a measured contention
floor. Raising `max_parallel` alone will never make a screen run rows side by
side.

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

**The build is told to make the mechanism CHEAP, not merely correct.** The prompt
carries the campaign's own objective (metric and direction) and requires the agent
to weigh the asymptotic cost of *deciding* to take its fast path against the cost
of the work that path avoids — the cost of deciding must be strictly lower. This
requirement exists because a build shipped the opposite: a dirty-tracking skip
that removed **70 %** of the per-item work and ran **23.7 % slower**, because its
per-frame decision rebuilt a state tuple over every one of the same N items it was
trying to skip. Correct, well-tested, and a regression the campaign then correctly
recommended disabling. A skip whose check is O(N) over the same N cannot pay for
itself; the decision has to be hoisted to something readable in O(1) — a counter
or epoch bumped at the few places that genuinely invalidate it.

The corollary for authors: **a `correctness` relation cannot catch a slow
mechanism.** All four oracles and every `native_test` check that the mechanism is
*right*. Nothing in the gate checks that it is *fast* — that only shows up at
`screen`, as a main effect with the wrong sign, by which point the build call is
spent. If your mechanism's cost model is the hard part, say so in
`guidance.factor_nomination`, which the build now reads.

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
| how many declared levels the probe did **not** exercise | a level that aborts the target, reported as a clean null result identical to baseline |

The last row is a *count*, not a check: the probe runs ONE corner, so every other
declared level is unexercised at that point. `--liveness` (below) closes it.

The predicate check builds its scope the way `run_stage` does — the target's own
`applied` echo wins over the requested levels — because using the requested
levels would make `applied.X == "{level}"` trivially true and hide the exact
mismatch worth finding.

It costs one test run plus one configuration, and each of those failures
otherwise costs a full campaign to discover. Make it the last thing you do
before launching.

#### `--liveness`: is each level runnable, and does each factor matter?

    nous validate campaign campaign.yaml --smoke --liveness

Opt-in, because it is the only part of `--smoke` whose cost scales with the
design: **`sum(len(levels)) + --liveness-repeats` runs** — linear in the design,
never `prod(len(levels))`. Everything else `--smoke` does costs one run total,
which is why plain `--smoke` stays cheap enough to be unconditional.

It runs every declared level of every factor once, holding the other factors at
`known_valid_baseline`, and reads that one sweep two ways:

| Reading | Verdict |
|---|---|
| a level whose run exits non-zero, times out, or emits unparseable output | **smoke FAILURE**, naming the factor *and* the level |
| each factor's effect — the objective's **range across all its measured levels**, a superset of the extreme-levels difference — against the noise floor from `--liveness-repeats` baseline runs varying only the workload seed | **reported**, and flagged `not demonstrably live` under `2 x` the noise CV |

The asymmetry is deliberate. A level the target cannot execute is a hole in the
design matrix, and (if a harness reuses a stale metrics file on non-zero exit) it
reads downstream as a measurement *identical to baseline* — that is a hard
failure. A small effect, by contrast, may be small and real; the number is what
was missing, so the flag informs the author's call rather than overriding it.

Both readings share the same runs on purpose: a level that aborts cannot produce
an effect size. `--liveness` requires `known_valid_baseline`, since it is both
what the other factors are held at and what the noise floor is measured on.

This automates §7.2 and §7.3's manual probe recipes; run it instead of doing
them by hand.

Run `nous validate campaign FILE` before starting: it warns when a declared
`native_test` cannot be found in the target and no `build` stage exists to author
it — the combination that is otherwise guaranteed to abort at `verify`, but only
after a real run. Three locator styles are checked, matching what the result
parsers actually support:

| Locator | Checked by |
|---|---|
| `sim/kv/offload_test.go`, `tests/test_x.py::test_foo` | the file's existence under the target |
| `TestOffloadCPUTier_ARCRespectsCapacity`, `test_foo` | a definition (`func TestFoo` / `def test_foo`) anywhere under the target |
| `go test ./sim/kv/ -run TestFoo`, `pytest -k test_foo` | the identifier behind the selector flag, then as above |

Anything else gets its own warning saying the locator **could not be checked**,
and why. That is deliberate: silence used to cover a bare Go test name — exactly
what `--- PASS: TestName` output is parsed into — so a campaign declaring bare Go
identifiers with no `build` stage validated at 0 errors / 0 warnings and aborted
at `verify` after a full run. An author must be able to tell "checked and fine"
from "could not check".

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
Welch-combining two independent variances. On any noisy target that is
the difference between certifying inside the run budget and not. On a
**deterministic** target there is nothing to pair and this block should be
omitted — see the compiler example in §3.6 of this guide, which does.

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
| `adapter_contract.json` + `adapter_contract.sha256` | the first **successful** row of the epoch's first measuring stage | the adapter's output contract (every top-level key and its value's *type*) and its content hash — every later row is checked against it |

Per iteration, under `runs/iter-N/`:

| File | Written by | Contains |
|---|---|---|
| `design_matrix.json` | before execution | the pre-registered rows, generator, randomized run order, RNG seed, `workload_seeds` |
| `runs.jsonl` | each run, append-only | levels, response metrics, replicate index, manipulation/constraint/**`self_check`** verdicts, status, duration |
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

### An apparatus change is an epoch boundary, not an edit

This is a **workflow rule**, and it is the one most likely to be broken by
someone who knows it. It follows from everything above, it is enforced by the
contract-drift guard in §2, and it is worth stating as a procedure because the
moment you want to break it is the moment you are least inclined to read a rule.

> **While an epoch is measuring, the adapter is frozen. If you want to change
> the adapter, the campaign, the workload generator, or anything else the
> measurement passes through, end the epoch first and start a new one.**

"Anything the measurement passes through" is broader than `policy.json`:

| Under the freeze | Why |
|---|---|
| `run_command` and everything it invokes | it *is* the instrument |
| the target's benchmark harness / probe scripts | same |
| the workload generator and its data | a row measured on a different workload is not comparable to its neighbours |
| the target's own build, if rows are not rebuilt per row | otherwise half the design measures one binary and half another |
| `run_timeout_sec`, `max_parallel`, and any external resource limit | changing a limit mid-epoch is the level-correlated-bias mechanism of §7.1a, applied by hand |
| the machine the rows run on | the same argument as `max_parallel`'s: rows must be comparable to each other |

**A ninety-second edit is still an epoch boundary.** This has been done, on this
repo's own campaign, by the person who wrote the guard: an adapter improvement
was applied while an epoch was mid-measurement, on the reasoning that it would
take about a minute and only made the adapter *better*. Both halves of that
reasoning are irrelevant. The damage is not proportional to the edit's duration
or to its quality — it is that the epoch now contains rows measured on two
different instruments, and the pre-registration covers only one of them. Nothing
downstream can tell which row got which, and a fitted coefficient over a mixed
instrument is not an estimate of anything. An improvement is *especially*
dangerous, because a better instrument shifts the measurements in a
non-random direction, which is precisely the shape a fit reads as a factor
effect.

The contract-drift guard (§2) catches the subset of these that changes the
adapter's *output contract* — a key appearing, disappearing, or changing type —
and aborts. It cannot catch an edit that changes what the numbers *mean* while
keeping the same key set, which is most edits. So the guard is a backstop, not
the rule. The rule is the freeze.

**The procedure, when you find something you want to change mid-epoch:**

1. **Stop.** Do not edit the live adapter. Write the change down instead.
2. **Let the epoch finish, or end it deliberately.** A finished epoch's
   `report.json` still names an action on whatever rung its evidence supports,
   and the rows it did measure are all on one instrument, so they are worth
   something.
3. **Make the change**, to the adapter and to the campaign YAML together.
4. **Re-run the pre-flight** — `nous validate campaign FILE --smoke`, plus
   `--liveness` if the change touched what a level does.
5. **Start epoch 2** (the four steps in the previous subsection). The next
   pre-registration is then a registration of the instrument it will actually
   measure with — which is the whole content of the claim a policy hash makes.

The asymmetry to hold on to: **an epoch is cheap relative to a campaign, and a
mixed-instrument epoch is worth zero.** Ending an epoch early costs you the
remaining rows of one design. Editing mid-epoch costs you every row already
measured, and you find out later, if at all.

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

## 3. Seven worked end-to-end examples

Each of the following is a complete, valid `kind: optimization` campaign —
schema-valid, cross-field-valid, drawn from the real campaign corpus
(restated as this kind), from the motivating benchmark case, or from a domain
chosen to exercise a part of the machinery the others leave untested.

**Read these for the structure, not the subject matter.** Nothing in this
campaign kind is about servers, queues, or throughput. The machinery is a
factorial design over declared levels, a predicate that the lever engaged, a
native test that the mechanism is correct, and a bound on how much better the
unknown best configuration could be. Any field where all four of those exist
is in scope: a PDE solver's tolerances, a compiler's optimization flags, a
training run's hyperparameters, an aligner's sensitivity settings, a
manufacturing process's set points. The table below is the mapping — read down
your own domain's column before reading any example.

| The abstraction | Serving/systems reading | Numerical-computing reading | Compiler/build reading | ML-training reading |
|---|---|---|---|---|
| `factors` | scheduler policy, batch cap, cache size | preconditioner, mesh coarseness, solver tolerance | `-O` level, inlining threshold, LTO on/off | optimizer, LR schedule, batch size, precision |
| `response.primary` | throughput, tail latency | coarsest mesh that converges, wall time to a fixed residual | benchmark score, binary size | validation metric |
| `response.constraints` | an SLA the winner must meet | a residual floor, a memory cap | output must stay bit-identical | wall-clock or peak-memory budget |
| `response.self_check` | "the reported rate really was sustained" | "the run the answer came from really did converge" | "the timed binary really is the one we built" | "the reported epoch really did finish" |
| `relations: correctness` | off-level is byte-identical to baseline | the discretization is consistent at any mesh | `-O0` and `-O3` outputs agree bit-for-bit | seed-fixed training is reproducible |
| `design_space.invariants` | transfer path is peer-to-peer | the mesh actually refined (cell count rose) | the flag reached the compiler, not just the driver | the run used the precision it claimed |
| `held_out` | a second workload trace | a second geometry | a second benchmark suite | the true test split |
| The composition barrier | a lever that regresses alone but wins in compound | a preconditioner that only pays off at a tolerance you would not pick alone | a flag that costs time alone but enables a later pass | a schedule that underperforms except at one batch size |

The last row is the one to take seriously. The composition barrier (§1) is a
property of *search*, not of servers — a domain where knobs interact has it
whether or not anything in that domain is called a queue.

The examples below are ordered so the first four are the systems-flavored ones
(§3.1–§3.4, drawn from the corpus) and the last three deliberately are not
(§3.5 numerical, §3.6 compiler, §3.7 ML training). Each of the last three
exists because it exercises structure the first four never do — the note under
each says which.

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
  cooldown_bars: 0
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
      apply: "--severity-boundary={level}"
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

### 3.5 An objective that is the extremum of a feasible set — a PDE solver

Nothing in the four examples above has an objective whose *validity* is a
property of the run that produced it. All four measure a quantity (throughput,
latency, detection rate, bandwidth) that exists whether or not the run went
well. This example is the other shape, and it is common outside serving:

> **The coarsest mesh on which the solver still converges to the required
> residual.**

That is not a number the target measures; it is the **extremum of a feasible
set**. The adapter has to decide membership — "did this mesh converge?" — and
therefore the adapter can be wrong in the one direction that flatters it. A
solver that stops at its iteration cap and reports the last residual it reached
looks exactly like a solver that converged, and the coarser the mesh the more
attractive the wrong answer. This is the same defect shape that cost a real
campaign 8 of 12 rows (§7.7), reached from a different domain — which is the
point of putting it here rather than only in the systems example.

Three structural features this campaign has and §3.1–§3.4 do not:

1. **`response.self_check` re-checks the objective against the diagnostic that
   defines it.** `residual_norm <= 1e-8` beside `primary: coarsest_mesh` is the
   convergence criterion restated where Nous evaluates it, per row, on the
   adapter's own reported response. A row whose reported coarsest mesh came from
   a run that did not converge fails, is excluded from the fit, and the sound
   rows are untouched.
2. **A `config_patch` apply, because the target is configured by file, not by
   flag.** Solvers are frequently driven by an input deck. Note the precondition
   the validator enforces: `solver.json` appears as an argument value in
   `run_command`, because the patch is applied to a per-run *copy* whose path is
   substituted textually into the assembled command.
3. **A correctness relation that is a discretization property, not a
   no-op check.** "The computed solution converges to the analytic solution at
   the discretization's design order" is a real property test over a whole input
   space, and it is the relation that makes the measurement mean anything: a
   mesh that "converges" to the wrong answer fast is not a win.

```yaml
kind: optimization
run_id: elliptic-solver-coarsest-mesh
research_question: >
  What is the coarsest mesh, preconditioner, and Krylov tolerance combination
  on which the elliptic solver still reaches a 1e-8 residual on the reference
  geometry, and can that configuration be certified within 5% of the coarsest
  feasible one in 70 runs?

target_system:
  name: elliptic-solver
  description: >
    Finite-volume elliptic solver. bench/nous_bench.py writes the requested
    solver settings into a copy of solver.json, runs the reference geometry to
    convergence or to the iteration cap, and prints one JSON object:
    {cells, residual_norm, converged, wall_sec, peak_mem_mb, order_estimate,
    cfg:{...}}. `cells` is the realized cell count (coarser mesh -> fewer
    cells), so maximizing it is wrong and maximizing the mesh spacing is what
    the campaign wants; the adapter reports `mesh_h` for that purpose.
  controllable_knobs: [mesh_h, preconditioner, krylov_tol, smoother_sweeps, cfl]

locked_parameters:
  geometry: reference-cube-3d
  boundary_conditions: dirichlet-analytic
  iteration_cap: 20000
  residual_target: 1.0e-8
  precision: float64
  cfl: 0.45

prompts:
  methodology_layer: prompts/methodology

optimization:
  run_command: "python bench/nous_bench.py --config solver.json --geometry reference-cube-3d --json"
  test_command: "python -m pytest tests/test_solver_props.py -q --json-report --json-report-file=/dev/stdout"
  run_timeout_sec: 2700     # see the sizing note below this block

  known_valid_baseline: {H: 0.005, PC: jacobi, TOL: 1.0e-10, SW: 2}

  policy:
    epsilon: {pct: 5.0}
    delta_screen: 0.05
    delta_terminal: 0.05
    confirm_max_rounds: 2

  response:
    # Coarser mesh = larger spacing = cheaper. Maximize the spacing.
    primary: {metric: mesh_h, direction: maximize}
    constraints:
      # Admissibility, not self-consistency: a run that converged but blew the
      # memory envelope is real data about the space and is retained.
      - {metric: peak_mem_mb, op: "<=", value: 32000}
      - {metric: wall_sec, op: "<=", value: 2400}
    self_check:
      # The predicate that DEFINES the objective. Without these two lines a
      # solver that stalls at its iteration cap reports the coarsest mesh of
      # all and wins.
      - {metric: converged, op: "==", value: true}
      - {metric: residual_norm, op: "<=", value: 1.0e-8}
    held_out: [held_out_geometry_wedge_mesh_h]
    noise_estimate_pct: 1.5

  factors:
    - id: H
      name: mesh_h
      type: numeric
      levels: [0.005, 0.010, 0.020, 0.040]
      grid: 0.005
      apply: {kind: config_patch, path: solver.json, pointer: /mesh/h, value: "{level}"}
      manipulation: {observable: applied_patches.H.value, op: "==", value: "{level}"}
      relations:
        - {id: R_H, kind: correctness,
           statement: "the computed solution converges to the analytic solution at second order in h (halving h quarters the L2 error, within 15%)",
           native_test: "tests/test_solver_props.py::test_second_order_convergence"}
        - {id: B_H, kind: behavioral,
           statement: "iteration count to a fixed residual is non-decreasing as h coarsens at fixed preconditioner",
           native_test: "tests/test_solver_props.py::test_iterations_monotone_in_h"}

    - id: PC
      name: preconditioner
      type: choice
      levels: [jacobi, ilu0, amg]
      apply: {kind: config_patch, path: solver.json, pointer: /krylov/preconditioner, value: "{level}"}
      manipulation: {observable: cfg.preconditioner, op: "==", value: "{level}"}
      relations:
        - {id: R_PC, kind: correctness,
           statement: "every preconditioner reaches the same solution to within 10x the residual target (a preconditioner changes the path, never the fixed point)",
           native_test: "tests/test_solver_props.py::test_preconditioner_agnostic_solution"}

    - id: TOL
      name: krylov_tol
      type: numeric
      levels: [1.0e-10, 1.0e-9, 1.0e-8, 1.0e-7]
      apply: {kind: config_patch, path: solver.json, pointer: /krylov/rtol, value: "{level}"}
      manipulation: {observable: cfg.krylov_rtol, op: "==", value: "{level}"}
      relations:
        - {id: R_TOL, kind: correctness,
           statement: "the reported residual_norm is the true residual ||b - Ax|| recomputed from scratch, not the Krylov method's own recurrence estimate",
           native_test: "tests/test_solver_props.py::test_reported_residual_is_recomputed"}

    - id: SW
      name: smoother_sweeps
      type: numeric
      levels: [1, 2, 4, 8]
      grid: 1
      apply: {kind: config_patch, path: solver.json, pointer: /smoother/sweeps, value: "{level}"}
      manipulation: {observable: cfg.smoother_sweeps, op: "==", value: "{level}"}
      relations:
        - {id: R_SW, kind: correctness,
           statement: "sweeps has no effect on the converged solution, only on the iteration count",
           native_test: "tests/test_solver_props.py::test_sweeps_inert_at_convergence"}

  design:
    screen: {resolution: 5, center_points: 4}
    refine: {kind: central_composite, center_points: 4}
    confirm: {replicates: 4, shortlist_size: 3}
    max_runs: 70

  design_space:
    invariants:
      # The mesh actually refined. A deck that silently clamps h to a
      # geometry-imposed minimum would otherwise report every coarse level as
      # the baseline mesh, and the H main effect would be a flat line the fit
      # would happily report as "no effect".
      - id: I_CELLS
        statement: "the realized cell count is at least the reference geometry's coarsest legal mesh, so the deck did not silently clamp h"
        observable: cells
        op: ">="
        value: 4096
      - id: I_ORDER
        statement: "the run's own order estimate is consistent with a second-order scheme"
        observable: order_estimate
        op: ">="
        value: 1.8

  build_checks:
    mechanism_paths: ["bench/nous_bench.py", "tests/test_solver_props.py"]

  guidance:
    interpretation: >
      Expect an H x PC interaction and treat it as the object of interest: AMG's
      setup cost is amortized over more iterations on a coarse mesh, so the
      preconditioner that wins at h=0.005 is not necessarily the one that wins
      at h=0.040 — and a main-effects summary that reports "AMG helps" would be
      the composition barrier in numerical clothing. TOL is expected to be
      nearly inert above the residual target and sharply consequential below it;
      if its main effect is within noise, that is a real finding (the solve is
      mesh-limited, not tolerance-limited), not a failed factor.
      Certification arithmetic: noise_estimate_pct is 1.5, so with 4 paired
      replicates over 2 challengers the terminal bound clears the 5% epsilon
      whenever the winner's margin is more than about one mesh level. Two
      adjacent mesh levels tying should come back `terminal_best` — read that as
      "these two meshes are indistinguishable in feasibility at this residual
      target", which is a real answer to the research question.
```

**Why `run_timeout_sec: 2700`, and why a per-level probe could not have told
you.** The expensive corner here is `H` at its *finest* level combined with
`PC: jacobi` (the weakest preconditioner, so the most iterations) and `TOL` at
its *tightest* — three costly levels at once. A `--liveness` sweep visits each
level once with the others at `known_valid_baseline`, so it measures `H=0.005`
against `PC: jacobi` and `TOL: 1e-10` *because those happen to be the
baseline's values* — but it would never measure `PC: amg`'s setup cost at the
finest mesh, and on a target whose baseline used a strong preconditioner it
would never visit the fatal corner at all. Size the ceiling from that corner
explicitly (§7.1), which for this target is one extra run.

That matters more here than in a serving campaign, because of the perverse
direction: **the coarser the mesh, the cheaper the run, and the coarser mesh is
what wins.** So the rows at risk of the ceiling are the fine-mesh rows — the
*losers*. A timeout that deletes losers biases the surface toward reporting a
larger feasible mesh than the solver actually supports, which is the flattering
direction. Compare the serving case in §7.1, where the timeout deletes the
*winners*: the direction of the bias depends on whether cost and objective move
together or oppose, and you have to work it out per campaign rather than assume
the sign.

### 3.6 Correctness as a hard constraint — compiler optimization flags

Every example so far has a `correctness` relation that is *about the
apparatus*: "the off level is a no-op", "the baseline reproduces". This one is
different in kind, and it is the shape most build/compiler/codegen campaigns
have: **correctness is the thing the optimization can most plausibly break.**
An aggressive flag combination that reorders floating-point arithmetic or
assumes strict aliasing will make the benchmark faster and the answers wrong,
and it will do so silently — the binary runs, the benchmark reports a number,
the number is better.

So this campaign states the same property in **two places, deliberately**, and
the two are not redundant:

- as a **`correctness` relation** (`native_test` in the target's own suite,
  differential: `-O0` output versus the flagged output, bit-for-bit), which
  hard-fails the *campaign* — a compiler that miscompiles under a declared flag
  means every measurement is meaningless;
- as a **`response.constraints` entry** (`outputs_bit_identical == true`, read
  off the row's own response), which marks the *configuration* infeasible and
  retains the row as real data about the space.

The relation guards the apparatus; the constraint guards the recommendation.
A campaign that declared only the relation would abort the whole run on the
first row where a fast-math flag combination diverged — throwing away the
finding "this combination is fast and wrong", which is exactly what the campaign
should report. A campaign that declared only the constraint would fit a surface
over a compiler it never checked.

```yaml
kind: optimization
run_id: numerics-kernel-flags
research_question: >
  Which combination of optimization level, inlining threshold, LTO, and
  vectorization width maximizes the numerics kernel benchmark score while
  keeping the computed output bit-identical to the -O0 reference?

target_system:
  name: numerics-kernel
  description: >
    C++ numerical kernel with a bit-reproducible reference mode.
    bench/nous_bench.py rebuilds the kernel with the requested flags, runs the
    fixed benchmark suite, diffs the computed output against the checked-in -O0
    reference, and prints one JSON object:
    {bench_score, build_sec, text_bytes, outputs_bit_identical, max_abs_diff,
     compiler_version, cfg:{...}}.
  controllable_knobs: [opt_level, inline_threshold, lto, vector_width]

locked_parameters:
  compiler: clang-19
  target_arch: x86-64-v3
  benchmark_suite: kernels-v3
  reference_build: O0-strict-fp

prompts:
  methodology_layer: prompts/methodology

optimization:
  run_command: "python bench/nous_bench.py --suite kernels-v3 --reference O0-strict-fp --json"
  test_command: "python -m pytest tests/test_codegen_props.py -q --json-report --json-report-file=/dev/stdout"
  # A full rebuild plus the suite; the LTO corner is the expensive one.
  run_timeout_sec: 3000

  known_valid_baseline: {O: "O2", INL: 225, LTO: "off", VW: 128}

  policy:
    epsilon: {pct: 2.0}
    delta_screen: 0.05
    delta_terminal: 0.05

  response:
    primary: {metric: bench_score, direction: maximize}
    constraints:
      # Correctness as ADMISSIBILITY: a fast-and-wrong configuration is a
      # finding worth keeping in runs.jsonl, not a campaign abort.
      - {metric: outputs_bit_identical, op: "==", value: true}
      - {metric: build_sec, op: "<=", value: 1200}
    self_check:
      # The score must have come from the binary this row actually built. A
      # stale artifact in the build tree is the domain's version of the
      # stale-metrics-file defect (§7.7).
      - {metric: max_abs_diff, op: "<=", value: 0.0}
    held_out: [held_out_suite_spec2017_score]
    noise_estimate_pct: 1.0

  factors:
    - id: O
      name: opt_level
      type: choice
      levels: ["O1", "O2", "O3"]
      apply: "--opt-level={level}"
      manipulation: {observable: cfg.opt_level, op: "==", value: "{level}"}
      relations:
        - {id: R_O, kind: correctness,
           statement: "at every optimization level the kernel's output is bit-identical to the -O0 reference on the full input corpus"
           , native_test: "tests/test_codegen_props.py::test_output_bit_identical_across_opt_levels"}

    - id: INL
      name: inline_threshold
      type: numeric
      levels: [75, 225, 600, 1200]
      grid: 25
      apply: "--inline-threshold={level}"
      manipulation: {observable: cfg.inline_threshold, op: "==", value: "{level}"}
      relations:
        - {id: R_INL, kind: correctness,
           statement: "inlining changes no observable result: output is bit-identical at every threshold"
           , native_test: "tests/test_codegen_props.py::test_inlining_is_semantics_preserving"}
        - {id: B_INL, kind: behavioral,
           statement: "text segment size is non-decreasing in the inline threshold"
           , native_test: "tests/test_codegen_props.py::test_text_size_monotone_in_inlining"}

    - id: LTO
      name: lto
      type: choice
      levels: ["off", "thin", "full"]
      apply: "--lto={level}"
      manipulation: {observable: cfg.lto, op: "==", value: "{level}"}
      relations:
        - {id: R_LTO, kind: correctness,
           statement: "lto=off produces a binary byte-identical to the recorded baseline build"
           , native_test: "tests/test_codegen_props.py::test_lto_off_is_baseline_binary"}

    - id: VW
      name: vector_width
      type: numeric
      levels: [128, 256, 512]
      grid: 128
      apply: "--vector-width={level}"
      manipulation: {observable: cfg.vector_width, op: "==", value: "{level}"}
      relations:
        - {id: R_VW, kind: correctness,
           statement: "vectorized reductions use the same association order as the scalar reference, so sums are bit-identical at any width"
           , native_test: "tests/test_codegen_props.py::test_reduction_association_order_fixed"}

  design:
    screen: {resolution: 5, center_points: 3}
    refine: {kind: central_composite, center_points: 3}
    confirm: {replicates: 5, shortlist_size: 3}

  design_space:
    invariants:
      # The flag reached the COMPILER, not merely the build driver. A driver
      # that silently drops an unknown flag turns a typo into a fabricated
      # null result -- the loud-failure case the build section describes.
      - id: I_ARCH
        statement: "every build targets the locked architecture, so no row is measuring a different ISA"
        observable: cfg.target_arch
        op: "=="
        value: x86-64-v3
      - id: I_CC
        statement: "every build used the locked compiler version"
        observable: compiler_version
        op: "=="
        value: clang-19

  guidance:
    interpretation: >
      LTO x INL is the interaction to watch and the reason this is a factorial:
      thin LTO makes cross-module inlining possible, so a threshold that is
      useless at lto=off can be decisive at lto=thin. A main-effects reading
      would report "inlining threshold does not matter" and be wrong for
      exactly the configuration worth shipping. Read any row with
      outputs_bit_identical=false as a compiler finding to file upstream, not
      as a campaign failure — it is retained as infeasible precisely so it
      stays visible. noise_estimate_pct is 1.0 because a rebuilt-and-rerun
      benchmark on fixed hardware is among the least noisy targets this kind
      sees; that is what makes a 2% epsilon reachable at 5 replicates.
```

Note there is no `workload` block: the benchmark is deterministic, so there is
no seed to pair on and `confirm`'s terminal bound will be computed with the
unpaired (Welch) method. That is correct rather than a shortcoming — declaring
`workload.seed_env` on a target that has no stochasticity to control would
record a paired method for an experiment that paired nothing (§2, `workload`).
Deterministic targets are the one case where a small `noise_estimate_pct` and a
tight epsilon are both honest.

### 3.7 A budgeted objective and a real held-out split — ML training

> Also shipped standalone as
> [`examples/optimization/finetune-hyperparams.yaml`](../examples/optimization/finetune-hyperparams.yaml),
> with the reasoning inline as comments. Copy that file rather than this block if
> you are starting a campaign in this domain.

This is the domain where `held_out` finally means what its name suggests. In
§3.1–§3.4 `held_out` is a second workload or a second trace: useful, but a
generalization check by analogy. Here it is the actual test split, and the
distinction the field encodes — *recorded at `confirm`, never an input to
fitting* — is the ordinary discipline of the field, stated where Nous enforces
it. An optimizer that fit its response surface on the test metric would be
doing exactly what a decade of ML methodology exists to prevent, and the
validator's rule 2 makes that particular mistake unwriteable.

Two more structural features worth copying:

1. **The objective is budgeted, and the budget is a `constraint`, not a
   penalty.** "Best validation accuracy" with no budget is won by whichever
   configuration was allowed to train longest, so the interesting question is
   always accuracy *subject to* a wall-clock and a memory envelope. Stating the
   budget as `response.constraints` makes an over-budget configuration
   `infeasible` — retained in `runs.jsonl` as real data about the trade — rather
   than folding it into the score with a hand-chosen penalty weight nobody can
   later justify. See `docs/targets.md` §4 on why validity beats penalty.
2. **The objective is censorable, and the campaign says so.** A run that
   diverges reports whatever accuracy it had when it stopped, and a run killed
   at the wall-clock ceiling reports the last epoch it finished. Both are
   censored observations that look like measurements (§7.4). The `self_check`
   below is what separates them: a row whose reported accuracy did not come
   from a completed evaluation at the declared epoch count fails, and is
   excluded from the fit rather than fitted as a low point on the surface.

```yaml
kind: optimization
run_id: finetune-budgeted-accuracy
research_question: >
  Which combination of optimizer, learning-rate schedule, batch size, and
  precision maximizes validation accuracy on the fine-tuning task within a
  90-minute wall-clock and 40 GiB memory budget, and does the winner hold up on
  the untouched test split?

target_system:
  name: finetune-harness
  description: >
    Fine-tuning harness over a fixed dataset and a fixed model checkpoint.
    bench/nous_bench.py trains for the locked epoch count with the requested
    hyperparameters using a seeded data order (NOUS_WORKLOAD_SEED), evaluates on
    the validation split, and prints one JSON object:
    {val_accuracy, test_accuracy, epochs_completed, train_wall_sec,
     peak_gpu_mem_gib, grad_norm_final, diverged, cfg:{...}}.
    test_accuracy is computed but NEVER read by any fitting stage -- it is
    declared held_out below.
  controllable_knobs: [optimizer, lr_schedule, batch_size, precision, warmup_pct]

locked_parameters:
  dataset: task-mix-v2
  base_checkpoint: base-7b-r3
  epochs: 3
  max_seq_len: 2048
  val_split: val-frozen-5k
  test_split: test-frozen-5k
  warmup_pct: 3

prompts:
  methodology_layer: prompts/methodology

optimization:
  run_command: "python bench/nous_bench.py --dataset task-mix-v2 --checkpoint base-7b-r3 --epochs 3 --json"
  test_command: "python -m pytest tests/test_train_props.py -q --json-report --json-report-file=/dev/stdout"
  run_timeout_sec: 6600     # 90 min budget + margin; see the note below

  known_valid_baseline: {OPT: adamw, SCH: cosine, BS: 16, PREC: bf16}

  workload:
    seed_env: NOUS_WORKLOAD_SEED
    seeds: [7, 17, 27, 37, 47]

  policy:
    epsilon: {abs: 0.004}     # 0.4 accuracy points: below this we would not reship
    delta_screen: 0.05
    delta_terminal: 0.05
    confirm_max_rounds: 2

  response:
    primary: {metric: val_accuracy, direction: maximize}
    constraints:
      # The budget is admissibility, not a penalty term.
      - {metric: train_wall_sec, op: "<=", value: 5400}
      - {metric: peak_gpu_mem_gib, op: "<=", value: 40}
      - {metric: diverged, op: "==", value: false}
    self_check:
      # A censored run is not a measurement of this objective. Without this,
      # a run killed at epoch 2 reports a real-looking accuracy and the fit
      # treats it as "this configuration is mediocre" rather than "this row
      # measured something else".
      - {metric: epochs_completed, op: ">=", value: 3}
      - {metric: grad_norm_final, op: "<=", value: 100.0}
    held_out: [test_accuracy]
    noise_estimate_pct: 1.2

  factors:
    - id: OPT
      name: optimizer
      type: choice
      levels: [adamw, adafactor, lion]
      apply: "--optimizer={level}"
      manipulation: {observable: cfg.optimizer, op: "==", value: "{level}"}
      relations:
        - {id: R_OPT, kind: correctness,
           statement: "at a fixed seed, two runs of the same optimizer produce identical loss curves (the harness is reproducible, so a measured difference is the factor and not the run)"
           , native_test: "tests/test_train_props.py::test_seeded_run_is_reproducible"}

    - id: SCH
      name: lr_schedule
      type: choice
      levels: [constant, cosine, linear_decay]
      apply: "--lr-schedule={level}"
      manipulation: {observable: cfg.lr_schedule, op: "==", value: "{level}"}
      relations:
        - {id: R_SCH, kind: correctness,
           statement: "every schedule starts at the configured peak LR after warmup and ends at or below it -- no schedule silently rescales the peak"
           , native_test: "tests/test_train_props.py::test_schedule_endpoints"}

    - id: BS
      name: batch_size
      type: numeric
      levels: [8, 16, 32, 64]
      grid: 8
      apply: "--batch-size={level}"
      manipulation: {observable: cfg.batch_size, op: "==", value: "{level}"}
      relations:
        - {id: R_BS, kind: correctness,
           statement: "gradient accumulation makes the effective batch exact: the summed gradient at batch 8 with 2 accumulation steps equals the gradient at batch 16 to float tolerance"
           , native_test: "tests/test_train_props.py::test_accumulation_matches_larger_batch"}

    - id: PREC
      name: precision
      type: choice
      levels: [fp32, bf16, fp8]
      apply: "--precision={level}"
      manipulation: {observable: cfg.precision, op: "==", value: "{level}"}
      relations:
        - {id: R_PREC, kind: correctness,
           statement: "the master weights and the optimizer state stay fp32 at every compute precision, so a precision change is a compute change and not a silently different algorithm"
           , native_test: "tests/test_train_props.py::test_master_weights_are_fp32"}

  design:
    screen: {resolution: 5, center_points: 3}
    # No `refine`: BS is the only numeric factor with more than two levels, and
    # a central-composite design needs >= 2 to have a surface with curvature.
    # The validator hard-fails a `refine` block here rather than running one
    # that could only fit a line -- see the note after this block.
    confirm: {replicates: 4, shortlist_size: 3}
    max_runs: 60

  stages: [verify, screen, confirm]

  design_space:
    invariants:
      # The precision the row CLAIMS is the precision the row USED. A harness
      # that silently falls back to bf16 on hardware without fp8 support would
      # otherwise report the fp8 rows as a duplicate of the bf16 rows, and the
      # PREC main effect would be a fabricated null.
      - id: I_PREC
        statement: "the executed compute precision matches the requested one"
        observable: cfg.effective_precision
        op: "=="
        value: "{level}"
      - id: I_SPLIT
        statement: "every run evaluates the frozen validation split, so no row scores itself on different data"
        observable: cfg.val_split
        op: "=="
        value: val-frozen-5k

  guidance:
    interpretation: >
      BS x SCH is the expected interaction and the reason for a factorial: a
      constant LR is defensible at batch 8 and badly wrong at batch 64, so the
      schedule's main effect averaged over batch sizes is close to meaningless.
      Expect PREC x BS too, through memory: fp8 makes batch 64 fit, and batch 64
      may be where the winner lives, which is precisely the compound a
      one-factor-at-a-time sweep cannot reach. Read `test_accuracy` at confirm as
      a check, never as a tiebreak: if the shortlist's val ordering and test
      ordering disagree, the campaign has found overfitting to the validation
      split and that is the result to report, not an excuse to pick the config
      that won on test. epsilon is 0.4 accuracy points absolute rather than a
      percent, because a percentage of an accuracy is a quantity nobody in this
      field reasons about.
```

**Why no `refine`, and why that is the common case outside systems work.**
`refine` fits curvature, which needs at least two `numeric` factors with more
than two levels — the validator hard-fails a `refine` block that does not have
them, rather than running a central-composite design that could only fit a line.
Hyperparameter spaces are frequently mostly `choice` (optimizer, schedule,
precision are names, not magnitudes), so one numeric factor is typical and
`stages: [verify, screen, confirm]` is the right schedule. That is not a
degraded campaign: screening still estimates every two-factor interaction, and
`confirm` still does terminal discrimination over a shortlist, so the final
claim still does not rest on the fitted surface. Compare §3.2, which reaches the
same schedule from an all-`choice` factor set.

**Expect one warning from `nous validate campaign` on this campaign, and read
it.** A 6600-second per-row ceiling against `max_runs: 60` is ~110 hours of
worst-case wall clock, and the validator says so. That warning is correct and
this campaign keeps the ceiling anyway, because the measurement really is
compound (a full fine-tuning run) and shortening it would change the
experiment rather than the schedule. The warning exists so that decision is
made explicitly. A campaign where the same warning is *not* justified — a
short measurement under a generous ceiling — should lower the ceiling so a hang
fails fast instead of quietly eating the budget.

**On the `I_PREC` invariant.** It uses `value: "{level}"`, which is the same
level interpolation `manipulation` uses. That is legal in an invariant and is
the right tool when the property you want checked is "what ran matches what was
asked" for a factor with more than two levels. Reach for it whenever a target
has a *fallback path*: a harness that quietly downgrades an unsupported setting
is the single most common way a factor becomes a dead axis while every check
passes (§7.2).

**Why `run_timeout_sec` is above the wall-clock constraint.** `train_wall_sec <=
5400` is a *constraint*, evaluated after the row completes: an over-budget
configuration must be allowed to finish so it can be recorded as infeasible.
`run_timeout_sec: 6600` gives it room to do that. Setting the ceiling *at* the
budget would convert every over-budget configuration from an infeasible row
(retained, informative) into a timed-out row (excluded, indistinguishable from a
target that hung) — and it would do so systematically, on exactly the large-batch
fp32 corner, which is the level-correlated failure §7.1 warns about.

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

### 4.1 Choosing levels: the region is part of the claim

A factor's `levels` do two jobs, and authors reliably notice only the first.
They say **which settings the design will run**; they also say **which region of
the space the campaign's answer is about.** A campaign that declares
`CPU: [1, 4, 16]` GiB and one that declares `CPU: [40, 80, 160]` GiB are not the
same experiment at different budgets — they are experiments about two different
regimes, and a mechanism can be decisive in one and inert in the other for
entirely legitimate reasons.

That is not a defect. Choosing the region is a real part of the strategy: you
tune where you intend to operate. The defect is leaving the choice **implicit**,
because a `report.json` states its recommendation and its bound without stating
which regime the levels put it in, and a reader — including you, later — will
read it as a claim about the factor rather than a claim about the factor *in that
region*.

Two things follow.

**Say the region in the campaign.** `guidance.interpretation` is the slot for it,
and one sentence is enough: "these levels bracket the memory-constrained regime
we deploy in; a result here says nothing about the large-cache regime." It costs
nothing and it is the only place that fact will be written down.

**If two campaigns will be compared, they must share levels — or the comparison
must be stated per-region.** This is where the implicit choice turns into a wrong
number. Two campaigns on a real target were compared on "best objective found",
as a single ratio, and one factor's levels were `1/4/16 GiB` in one and
`40/80/160 GiB` in the other. **No shared level at all.** The ratio was real
arithmetic over two different regimes, and it read as a comparison of the two
*strategies* — which is what it was reported as, and it was not that.

The failure has three honest fixes, in decreasing order of preference:

1. **Fix the levels globally.** Put the shared factor's levels in one place both
   campaigns reference — a YAML anchor in a shared fragment, a generator script,
   or simply an explicit convention recorded next to both campaigns. Then the
   comparison is a comparison.
2. **Overlap deliberately.** Where a full match is not possible (two targets
   genuinely have different feasible ranges), give the factor at least two levels
   in common and report the comparison **restricted to the shared levels**. A
   ratio over the overlap is a real number; a ratio over the union is not.
3. **Compare per-region and say so.** If the ranges cannot overlap, the campaigns
   are answering different questions and the deliverable is two answers, each
   labelled with its region — not one ratio. "Strategy A found 1.4x in the
   memory-constrained regime; strategy B found 1.1x in the large-cache regime" is
   a defensible pair of sentences. Their quotient is not a defensible one.

The rule of thumb: **before you write a single comparative number across two
campaigns, diff their factor levels.** If any factor whose effect could plausibly
depend on regime has no level in common, the comparison is between regimes and not
between whatever you meant to compare. This applies to arms of the same campaign
too, and to a campaign compared against a previously published result — that
last case is the easiest to get wrong, because the published levels are often not
stated at all.

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
  held_out: [held_out_scoer]   # typo: "scoer"
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

### 6.9 Non-overlapping levels on a factor two campaigns will be compared on

**Wrong** — two campaigns whose deliverable is a single comparative ratio, with
one shared factor declared over disjoint ranges:

```yaml
# campaign A
factors:
  - {id: CPU, name: cache_bytes_gib, type: numeric, levels: [1, 4, 16],
     apply: "--cache-gib={level}",
     manipulation: {observable: cfg.cache_gib, op: "==", value: "{level}"},
     relations: [{id: R, kind: correctness, statement: "...",
                  native_test: "tests/prop.py::test_cache_sizing"}]}
```

```yaml
# campaign B — same factor, no level in common
factors:
  - {id: CPU, name: cache_bytes_gib, type: numeric, levels: [40, 80, 160],
     apply: "--cache-gib={level}",
     manipulation: {observable: cfg.cache_gib, op: "==", value: "{level}"},
     relations: [{id: R, kind: correctness, statement: "...",
                  native_test: "tests/prop.py::test_cache_sizing"}]}
```

Nothing here is invalid, and that is the problem — the validator sees two
well-formed campaigns and has no way to know they will be quotiented. This
shipped: two campaigns on a real target were compared on "best objective found",
one factor ranged `1/4/16 GiB` against `40/80/160 GiB`, and the resulting ratio
was read as a comparison of the two *strategies* when it was a comparison of two
*regimes*. A mechanism that pays off under memory pressure and one that pays off
with a large cache are different findings, and their quotient is not a finding at
all.

**Right:** give the shared factor at least two levels in common, or state the
region and report per-region. §4.1 has the three ordered fixes. The cheapest
version is one sentence in `guidance.interpretation` on both campaigns naming the
regime, plus a diff of the two factor lists before any comparative number is
written.

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

The sign is not fixed, though, and you have to work it out for your own
campaign rather than assume it. When cost and objective move *together* — a
better configuration is a more expensive one, as in a saturation search — the
timeout deletes winners and the surface reads pessimistic. When they *oppose* —
a better configuration is a cheaper one, as in §3.5's coarsest-mesh objective,
where the winning row is the coarse mesh and the fine meshes are what run long —
the timeout deletes losers and the surface reads *optimistic*, which is worse
because nothing about it looks wrong. Ask which direction your objective
correlates with cost before you size the ceiling.

#### This advice did not hold as prose. Make it a check.

The paragraphs above are the third revision of this item, and the author of the
first two **violated them three times on the very next campaign**, each time by
sizing the ceiling from the cheap corner they happened to have timed. That is
the most useful thing this section can tell you: an authoring rule that lives
only as prose in a guide loses to the convenience of the number already on
screen. It loses even when the person reading the prose *wrote* it.

So convert the rule into an artifact before you launch:

1. **Write the measured worst-corner duration into the YAML as a comment**,
   next to `run_timeout_sec`, naming the configuration it came from — as the
   `run_timeout_sec` example above does. A ceiling with no provenance comment is
   a ceiling nobody can audit, including you in a week.
2. **Run the worst corner as a run, not as an estimate.** One run. If you find
   yourself reasoning about it instead of measuring it, that is the failure mode
   reproducing.
3. **Treat every timed-out row as a design defect until proven otherwise**, and
   go look at *which* rows timed out before re-running anything (next
   subsection).

**Steps 2 and 3 are now partly mechanical, and only partly.** Two of the three
have code behind them:

- `--liveness` prints the **observed wall clock of every run it makes** (each
  declared level, plus each noise-floor repeat) against the resolved
  `run_timeout_sec`, and **FAILS** `--smoke` when the ceiling leaves under `2x`
  headroom over the slowest *completed* run. Plain `--smoke` applies the same
  rule to its single corner. It is a failure rather than a flag — unlike the
  dead-axis report beside it — because insufficient headroom is not a judgement
  call the author has to make: rows will die at the ceiling, each after
  consuming the whole ceiling, and at `--smoke` time the repair is one integer.
- Every row of `runs.jsonl` now carries a real `duration_ms` (total across
  attempts), `last_attempt_ms`, `attempts`, and a machine-readable
  `failure_kind` — so step 3's "go look at which rows timed out" is a filter on
  `failure_kind == "timeout"` rather than a walk through
  `failed_runs/*.log`. Before this, `duration_ms` was structurally always `0`
  and every failure read as an undifferentiated `failed`, which is why the
  campaign that motivated this section could not be diagnosed from its own
  artifacts.

**What the check does not do is close the gap in the next subsection**: it
bounds *levels*, and the fatal corner combines several. A passing headroom
verdict means "the ceiling clears every configuration this sweep actually
measured by 2x", never "the ceiling clears the design". The message says so, and
step 2's one corner run is still yours to make.

#### What a per-level sweep can and cannot bound

`--liveness` is the closest thing to an automatic timeout probe, and it is worth
being precise about its reach, because it is easy to over-trust:

| Question | Can a single-level sweep answer it? |
|---|---|
| Is each declared level runnable at all? | **Yes** — that is exactly what it checks. |
| Does each factor move the objective more than noise? | **Yes**, at the baseline operating point. |
| How long does the slowest *single level* take? | **Yes**, with the other factors at `known_valid_baseline`. |
| How long does the slowest *corner* take? | **No.** It never runs one. |

The sweep visits `sum(len(levels))` configurations, each varying **one** factor
with the rest at baseline. The design matrix visits **corners**, where several
factors sit at costly levels simultaneously. Those are different sets, and the
gap between them is exactly where a mis-sized ceiling lives.

The gap is not a small correction, because cost interacts. On the real campaign
this section is drawn from, the fatal corner combined **three** costly levels —
an expensive eviction policy, a slow device class, and a small memory tier — and
the per-level measurements of each one individually were all comfortably inside
the ceiling. Cost superadditivity is the normal case rather than the exception:
a policy that does more bookkeeping per operation costs more when there are more
operations, which is what a smaller cache and a slower device each independently
cause. Adding three individually-fine level costs and expecting the corner to be
fine is the same arithmetic mistake as adding three main effects and expecting
to have described the surface — and it is being made by someone who is running a
factorial design *specifically because* that arithmetic does not hold.

**So: `--liveness` bounds levels; only a corner run bounds corners.** Budget
from `max(measured corners)`, not from `max(measured levels)`, and if you can
afford exactly one extra pre-flight run, spend it on the corner where every
factor's most expensive level meets.

### 7.1a A resource limit that correlates with a factor level biases the surface

This is the failure the timeout sizing above is trying to prevent, stated in its
general form, because **the timeout is only one instance of it** and the others
have no `run_timeout_sec` field to warn you about.

Any **per-row resource limit** — a wall-clock timeout, a memory cap, a disk
quota, an API rate limit, a retry budget, a per-row cost ceiling, a container
OOM killer — binds *harder* on some levels of some factors than others. When it
does, the rows it kills are not a random sample of the design: they are exactly
the region where that factor's expensive level does the most work. The fit then
never sees that region, and the coefficient it reports for that factor is
computed over the part of the space where the mechanism was *cheap*, which is
usually the part where it was also least useful.

The real case, and the reason this has its own subsection: on a live campaign,
every row at `EV=arc, DEV=sata_ssd, CPU=40GiB` timed out, and every row at
`EV=lru` at that **identical** corner completed. A perfect 2x2 separation on the
`EV` factor at one corner of the other two. `arc` is the policy that does more
bookkeeping, so it is the policy the ceiling bound harder — and the resulting
surface would have reported `arc` as no better than `lru` while having no
measurement of `arc` anywhere it might have paid off. The timeout did not add
noise to the estimate of `EV`; it **deleted the evidence for one level of it**
and left the fit looking healthy.

Generalize away from that specific target, because the shape recurs wherever the
limit and the mechanism are related:

| Limit | Binds harder on | Deletes evidence for |
|---|---|---|
| wall-clock timeout | policies that do more work per operation; finer discretizations; larger models | exactly the settings whose cost you were trying to justify |
| memory cap / OOM kill | larger batch, larger cache, higher precision, wider vector width | the high end of every capacity factor |
| disk or artifact quota | higher logging verbosity, larger intermediate dumps, LTO/debug builds | the settings that produce the most evidence |
| API rate limit or token budget | higher sampling counts, more retries, larger contexts | the configurations that query the most |
| retry budget | flakier-but-better configurations | anything whose variance is higher, regardless of its mean |

Two things to do about it, and they are both cheap:

1. **Budget every per-row limit from the worst corner, not the typical row.**
   The same rule as the timeout, applied to memory, quota, and rate. If a limit
   cannot be raised (a real hardware ceiling, a hard API quota), then narrow the
   factor's levels so the design stays inside it — a level you cannot measure is
   not a level, and declaring it anyway pre-registers a hole.
2. **Treat clustered failures as a finding, not as noise.** When rows fail, the
   first question is *which* rows, before any question about re-running them.
   Cross-tabulate the failures against the factor levels. If the failures are
   spread across the design, you have a flaky apparatus. If they cluster on one
   level of one factor — or on one corner — you have a **level-correlated
   limit**, and the honest responses are to raise the limit and re-run the epoch,
   or to narrow that factor's levels and start a new epoch, *not* to fit the
   surviving rows and report a coefficient for a factor whose expensive level was
   never measured.

**What `runs.jsonl` records, and how to read it for this.** Every row carries
four instrumentation fields, so the budget-versus-defect split above is a filter
rather than a substring match on prose:

| Field | What it answers |
|---|---|
| `failure_kind` | *Why* the row failed, from a closed vocabulary: `timeout`, `exit_nonzero`, `unparseable_output`, `adapter_exception`, plus the rejection kinds (`ceiling_exceeded`, `constraint_violated`, `invariant_violated`, `manipulation_failed`, `integrity_failed`, `adapter_guard`). `timeout` is a **budget** question about your design; the next three are **defects** that will recur on any row reaching the same branch. |
| `duration_ms` | Total wall clock the row consumed, **across attempts**. This is what makes "budget from the worst corner" auditable after the fact, and it lets the NEXT epoch's ceiling be sized from your own measured data instead of a fresh probe. |
| `last_attempt_ms` | The single slowest attempt. **This is what a per-row ceiling applies to** — size `run_timeout_sec` against this, not against `duration_ms`. |
| `attempts` | How many tries the row took, which is what tells you whether the two numbers above should differ. |

Recording only the total would make a two-attempt row indistinguishable from a
target that got twice as slow, and an author would then raise a ceiling that was
never the constraint.

To test whether failures cluster on a level, cross-tabulate `failure_kind` against
`levels` — a `timeout` concentrated on one level of one factor is the bias this
subsection is about, and it is now a group-by rather than a reading exercise.
`duration_ms` is reserved so that `0` means "did not run": a field that exists,
validates, and is always zero reads as "measured, instantaneous", which is how one
real campaign hid a total instrumentation failure across all eighteen rows.

**And the `--liveness` headroom check.** `nous validate campaign FILE --smoke
--liveness` now reports each level's observed wall clock and FAILS when
`run_timeout_sec` lacks 2x headroom over the slowest level that completed. That
moves §7.1's advice from prose into a check — which matters, because prose did not
hold: this section's own author sized a ceiling from the cheap corner three times
in a row. The load-bearing limit is unchanged and the check says so itself: it
bounds **levels**, and it still cannot bound **corners**. A failed run's duration
is printed but never sets the bound, since its duration is bounded *by* the ceiling
and feeding it back would compare the ceiling against itself.


### 7.1b Design so the surface survives losing rows

Some rows will fail. A target crashes on one combination, a limit binds, a node
is preempted, a flaky dependency times out. A design that is only fittable when
every row succeeds is a design that will not be fitted.

Nous already does the right thing per row: an incomplete or self-contradictory
row is excluded from the fit and recorded in `fit_exclusions.json`, and the
remaining complete rows are fitted (spec §4 D2 — this exists because one
infeasible row once NaN-poisoned every coefficient in an epoch). But excluding
rows correctly is not the same as the design still answering the question, and
that part is the author's job at authoring time.

**The consequence is not graded.** It is tempting to read a lost row as "a
slightly weaker fit", and for a scattered loss that is roughly true — you lose
degrees of freedom and the bounds widen. But a factor that loses **all** of its
rows at one of its levels does not have a weaker coefficient; it has **no
identifiable coefficient at all**. There is no contrast left to estimate it
from. The two outcomes look similar in a log full of failed rows and are
completely different scientifically:

| What was lost | Consequence |
|---|---|
| a few rows, scattered across levels | wider bounds, same claims — the design degraded gracefully |
| every row at one level of one factor | that factor's effect is **unestimable**; the fit either drops the factor or reports a number computed from something else |
| every row in one corner | the interactions involving that corner are unestimable, and an alias class may become unresolvable |

Three authoring moves that keep the design fittable:

- **Prefer more levels on fewer factors over the reverse, when rows are at
  risk.** A four-level factor that loses one level still has three contrasts;
  a two-level factor that loses one level has none.
- **Put `center_points` in every stage's design.** They are the pure-error
  estimate the lack-of-fit test needs, they are measured at a mid configuration
  that is rarely the one that fails, and they are the cheapest insurance in the
  schema. Every worked example in §3 declares them.
- **Leave budget headroom for a re-measurement.** `max_runs` sized to the exact
  design leaves no room to re-run a corner you lost. The screen block plus
  center points plus `shortlist_size * replicates` is the floor, not the budget.

And one thing to check *before* the policy hash: for each factor, ask what
fraction of that factor's rows would have to fail before its coefficient became
unestimable. If the answer for any factor is "the rows in one corner", that
factor's levels or the design's resolution is the thing to revise — not the
analysis afterwards.

**What the fitter now detects for you, and what stays your job.** A stage that
loses rows writes `fit_exclusions.json`, and its fields map onto the three rows of
the "what was lost" table above:

| Field | Meaning |
|---|---|
| `excluded_by_reason` | Which rows went, split by cause — `failed_to_measure` / `no_metric` versus `infeasible` / `rejected`. Only the first two count as bias evidence; a constraint boundary concentrates on one level **by construction**, so counting `infeasible` would false-flag every constrained campaign. |
| `non_identifiable_factors` | Factors that lost every row at one of their levels. Their coefficient is not weaker — it is **not estimable**, so the factor is dropped from the fit and named here. |
| `interactions_dropped` | Set when the surviving rows cannot support the interaction block (six corners cannot fit seven terms). Main effects are kept. |

`effects.json` carries `exclusion_balance`, the per-factor and per-cell
concentration verdict, and a level-correlated exclusion **withholds global
certification** — it is evidence against `delta_screen`'s premise that screening
did not exclude the true optimum.

Two of the three rows in that table are therefore now detected automatically: an
unestimable coefficient is structurally visible from the surviving design matrix,
and a concentrated loss is visible from the exclusion pattern. The **third stays
your pre-flight judgement** — whether the region that went missing was the one you
cared about is a question about your system, not about the matrix.

One distinction worth keeping straight when you read the artifacts, because the
names are similar and the findings are opposite: `effects.json`'s `dropped_factors`
means **measured null** (the confidence interval contains zero — a result), while
`fit_exclusions.json`'s `non_identifiable_factors` means **never estimable** (the
design lost the contrast — a hole). Reading a hole as a result would report "this
factor does not matter" about a factor you never measured.


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

**`nous validate campaign FILE --smoke --liveness` runs this recipe for you** —
noise floor, per-factor effect, and the `2 x` comparison — and additionally fails
on any declared level the target cannot execute. Prefer it to doing the below by
hand; the manual recipe remains here because it is the reasoning the flag
implements, and because a target whose noise structure needs a different floor
(more seeds, a different operating point) is still the author's to measure.

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
were briefly believed live on that basis. Nous now fails a row whose
response object is byte-identical to the immediately preceding row's while the
levels differ (see "Guarding the adapter", §2) — but only for a target that does
not echo its configuration back, so the fail-loud wrapper above is still the
primary defence, not a redundant one. The same class of defect as this
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

This shape is not a systems phenomenon and it is worth recognizing it in your own
field before it costs you an epoch. "The coarsest mesh on which the solver
converges" (§3.5), "the largest batch that fits in memory", "the lowest bitrate
that stays above the quality bar", "the loosest tolerance that still passes the
regression suite", "the fewest samples that still detect the effect" are all the
same object: an **extremum of a feasible set**, where the adapter decided
membership and can be wrong in the flattering direction. §3.5 is the worked
version — its `self_check` is two lines (`converged == true`,
`residual_norm <= 1e-8`) and without them a solver that stalls at its iteration
cap reports the coarsest mesh of all and wins the campaign.

**And declare it, so Nous enforces it too.** The assertion above lives inside
*your* adapter, which is the right place for it — but it is also the code that
was wrong in the first place, so an adapter asserting its own correctness is a
single point of failure. `response.self_check` is the same predicate stated where
Nous can evaluate it, against the response the adapter actually returned:

```yaml
response:
  primary: {metric: max_sustained_rate, direction: maximize}
  self_check:
    - {metric: backlog_slope, op: "<=", value: 0.060}
```

That one line fails each offending row at the moment it is measured (excluded
from the fit, reason recorded, the sound rows untouched), and `--smoke` /
`--liveness` evaluate it on the configurations they run — so a violated invariant
surfaces *before* the policy hash is written rather than after the epoch. See
"Guarding the adapter" in §2 for the other two guards, which need no declaration
at all.


**Record enough to adjudicate a flag you raise, not just to raise it.** A check
that reports a problem you then cannot diagnose has done half its job, and the
missing half is usually the expensive half.

A campaign's adapter validated that its search produced a well-ordered result and
recorded the outcome as counts:

    n_sustained: 7      n_growing: 4      monotone: false

The flag is correct and the record is useless. "Monotone: false" over those counts
is consistent with two situations that call for opposite responses:

* one point straddles the boundary — noise near the decision threshold, and the
  reported extremum is broadly fine;
* the response is genuinely not ordered in the swept variable — in which case the
  reported extremum is not the quantity it claims to be, and no amount of
  replication fixes that.

Distinguishing them needs **which** points fell in each bin, which the artifact did
not carry. The row had to be re-run to be judged — at full cost, after the fact,
and only because someone noticed.

The rule generalizes past monotonicity: whenever you add a validity flag, ask what
a reader would need to *act* on it, and record that alongside. A boolean is a
smoke alarm; the diagnosis needs the floor plan.


**Emit the diagnostics you would need to debug a failure, before you need
them.** This is the same rule pointed at the *next* campaign rather than at the
current row, and it is the cheapest item in this whole section.

A row's response object is the only durable record of what happened in that
measurement. Whatever your adapter did not print is gone: the run is over, the
target's temporary state is cleaned up, and re-measuring it costs a full row and
does not reproduce the conditions anyway. So the question to ask while writing
the adapter is not "what does the campaign need to score this row?" — it is
**"what would I want to know if this row came back wrong?"**

The concrete failure, and it is embarrassing in its simplicity: a campaign's
rows recorded no **duration**. Rows then timed out, and sizing the next epoch's
`run_timeout_sec` correctly required knowing how long the surviving rows had
taken — a number nobody had, from runs nobody could re-do cheaply. The campaign
could not size its own next ceiling from its own data. The fix would have been
one field.

Nous now records the row's own total duration, so the crudest version of that
gap is closed on the Nous side. It does not close the adapter side: a row that
took 4,900 s tells you the row was slow, and only your adapter can say whether
that was the build, the warmup, the measurement pass, or an inner probe that
climbed higher than expected. For a **compound** objective (§7.1) the breakdown is
the number the next ceiling is computed from, and nothing but the adapter can
emit it.

A durable minimum for any adapter, on **every** row including the failing ones:

| Emit | Because |
|---|---|
| the objective and every metric named in `constraints` / `regimes` / `self_check` | the campaign cannot score the row otherwise |
| **wall-clock duration** of the measurement, and of each inner phase | Nous records the row's total separately; what only *you* can report is the breakdown — which phase of a compound measurement ran long, which is what actually sizes the next ceiling and identifies the expensive corner |
| the diagnostic each `self_check` predicate reads | a self-check you cannot see the input to is a boolean again |
| the **effective** configuration, not the requested one | catches the silent-fallback dead axis (§7.2); this is what `manipulation` should assert against |
| a one-metric proof the mechanism was active (§7.5) | distinguishes "no effect" from "never ran" |
| the workload seed **as the target received it** | proves the seed contract actually took effect, rather than assuming it |
| for a compound objective: the number of inner probes and the values probed | the §7.1 worst-probe arithmetic needs them; without them the ceiling is guesswork |
| the target's own version / build identifier | the cheapest possible detector for an apparatus that changed under you |

Two constraints on how you emit them, both from the guards in §2. Keep the key
set and the value **types** identical on every row — a diagnostic that is a
number on good rows and `null` on interesting ones will abort the epoch on
contract drift, which is the guard working correctly and still not what you
wanted. And list under `response.constant_fields` any of these that legitimately
never varies (a build tag, a host name), which keeps the output-freshness check
strict on the fields that should have moved.

A cheap way to test the whole set: take one row's JSON, imagine it is the only
evidence you have, and ask whether you could tell a mis-set lever, a stale
result, a censored measurement, and an idle mechanism apart from each other. If
you cannot, add fields until you can. This costs nothing per row and it is the
difference between one bad epoch and two.

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
| 1 | `nous validate campaign FILE --smoke` | 1 run | predicates unsatisfiable, tests unmatched, `run_command` cannot exec, a declared `response.self_check` violated at the probe corner |
| 2 | Mechanism is active (§7.5) | 1 run | the mechanism's own metric is zero |
| 3+4 | `nous validate campaign FILE --smoke --liveness` (§7.2, §7.3) | `sum(len(levels)) + N` runs | any declared level the target cannot execute, or one whose row violates a declared `response.self_check` — and it *reports* every factor under 2x the noise CV |
| 5 | Objective is monotone and uncensored (§7.4) | 4–6 runs | orders-of-magnitude swings, or values pinned at a deadline |
| 6 | Observation window has settled (§7.6) | 2 runs | the verdict or fitted value changes between a window and 1.5x it |
| 7 | Worst-*probe* timing (§7.1) | 2 runs | `run_timeout_sec` under ~2x the most expensive probe the search can reach |
| 8 | Worst-**corner** timing (§7.1) | 1 run | the ceiling was sized from levels or from the baseline rather than from the corner where several costly levels meet — `--liveness` cannot bound this, because it never runs a corner |
| 9 | Every per-row limit budgeted from that corner (§7.1a) | 0 runs (reuse #8's row) | a timeout, memory cap, quota, or rate limit that binds harder on one level of one factor — it deletes that level's evidence rather than adding noise |
| 10 | The design survives losing rows (§7.1b) | 0 runs | any factor whose coefficient becomes **unestimable** if one corner's rows fail; no `center_points`; `max_runs` with no headroom to re-measure |
| 11 | The adapter emits its own diagnostics (§7.7) | 0 runs (read #1's JSON) | one row's response cannot distinguish a mis-set lever, a stale result, a censored measurement, and an idle mechanism — notably, no per-row **duration**, so the next epoch cannot size its ceiling from data |
| 12 | Levels state their region, and match any campaign this will be compared against (§4.1) | 0 runs | a shared factor with no level in common across the two campaigns, while a single comparative ratio is the deliverable |

Checks 8–12 cost nothing but one run between them, and each is a defect a real
campaign shipped **after** the prose advising against it was already in this
guide. That is the argument for running them as a list rather than trusting that
you remember them: the author of §7.1 mis-sized a ceiling from the cheap corner
three times in a row on the campaign immediately following.

If a check fails, revise the campaign — **not** the check. A pre-registration
whose apparatus was not verified first is a hash over an assumption. And once the
epoch is running, **the apparatus is frozen** — see "An apparatus change is an
epoch boundary, not an edit" in the compiled-policy section: anything you discover
after check 12 is a reason to start a new epoch, never a reason to edit the
instrument mid-flight.

## See also

- `examples/optimization/*.yaml` — standalone, schema-valid campaigns you
  can copy: [`vllm-batching.yaml`](../examples/optimization/vllm-batching.yaml),
  [`qdrant-hnsw.yaml`](../examples/optimization/qdrant-hnsw.yaml),
  [`knative-autoscale.yaml`](../examples/optimization/knative-autoscale.yaml)
  (online systems), and
  [`finetune-hyperparams.yaml`](../examples/optimization/finetune-hyperparams.yaml)
  (an **offline batch** target: a real held-out test split, a budget as a
  constraint rather than a penalty, a censorable objective guarded by
  `self_check`, no `refine`, and a `run_timeout_sec` deliberately above the
  wall-clock constraint). §3.5 and §3.6 of this guide carry a PDE solver and a
  compiler flag set as in-guide examples.
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
