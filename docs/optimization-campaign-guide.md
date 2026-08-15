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
| 1 | `verify` | 1 design call + mechanism code & native tests | ~2/factor | Levers exist, engage, pass native property tests |
| 2 | `screen` | 0 | 16-64 | Which factors matter + all two-factor interactions |
| 3 | `refine` | 0 | 15-25 | Curvature on surviving `numeric` factors; a stationary point |
| 4 | `confirm` | 1 analyze call | ~3-5 x replicates | Predicted optimum reproduces; `held_out` evaluated |

`screen` and `refine` make **zero** model calls. Once the model proposes
factors at `verify`, Python drives the pre-registered design matrix straight
through to a fitted surface with no further model involvement — build,
run, parse, replicate, fit is deterministic. This is why `design_space`
exists as a separate mechanism from prose (§5): there is no phase reading
prompts during the two stages that spend most of the run budget.

### Where the tokens go

Substantive model calls per campaign: **about 3** — one design call at
`verify` to propose factors and write mechanism code with native tests, and
one analyze call at `confirm` to interpret the fitted surface (plus a
lightweight gate-summary call per iteration, existing machinery, which
costs little). Against that: 60-90 benchmark runs, all of them tokenless.

The cost curve inverts relative to a reflective campaign: **iter-1 (verify)
carries nearly all the token cost**, because that is where mechanism code
and its native property tests get written per lever. Iterations 2 and 3
are effectively free in tokens — pure compute. This is also, not
coincidentally, the stage whose output is most durable: mechanism code and
tests land in the target repo and outlive the campaign, where a reflective
campaign's prose findings do not.

## 2. Field-by-field walkthrough of the `optimization` block

The block is required when `kind: optimization`, and forbidden otherwise
(the validator's rule 1). Its three required top-level keys are `response`,
`factors`, and `design`; everything else — `design_space`, `guidance`,
`test_command`, `integrity_command`, `stages` — is optional but load-
bearing when present.

### `response`

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

Structured prose for the two model-facing stages, in exactly two named
slots because they're read at different times and blending them wastes
tokens in both.

- **`factor_nomination`** — read at `verify`, when the model proposes
  factors and levels. Domain knowledge about which axes matter, which
  mechanisms already exist in the target, and what's out of scope belongs
  here.
- **`interpretation`** — read at `confirm`, when the model interprets the
  fitted surface. Scope limitations and "report X as a lead, not a result"
  belong here.

### `test_command` / `integrity_command`

- **`test_command`** — shell command that runs every declared relation's
  `native_test` and exits clean iff all pass.
- **`integrity_command`** — optional, independent of any single relation
  (a checksum or reconciliation script).

### `stages`

Optional override of the default iteration -> stage mapping
(`[verify, screen, refine, confirm]`). Use to skip `refine` explicitly for
an all-`choice` campaign, e.g. `[verify, screen, confirm]`. An iteration
index beyond the list resolves to `confirm`, never a fresh screen (which
would re-spend the screening budget).

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
  to prevent.
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
| `guidance.factor_nomination` / `guidance.interpretation` | The model | `verify` (nomination) / `confirm` (interpretation) | What the model **proposes** or concludes |
| `design_space.invariants` | Python | Every run, every stage, including `screen` and `refine` | What Python **executes** |
| `target_system.description` | The model | Both model-facing stages | Narrative framing, domain context |

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

## See also

- [`docs/campaign-authoring-guide.md`](campaign-authoring-guide.md) — the
  reflective kind's authoring guide (locked parameters, rehearsal
  discipline, spec fidelity).
- [`docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md`](superpowers/specs/2026-08-13-optimization-campaign-kind-design.md) —
  the full design spec this guide implements, including the architecture,
  execution/control-flow, and failure-taxonomy rationale behind every rule
  cited above.
- `orchestrator/schemas/campaign.schema.yaml`, the `optimization` block —
  the schema-level source of truth for every field in §2.
- `orchestrator/validate.py`, `_rule1`..`_rule10` — the cross-field rules
  this guide is written to never contradict.
