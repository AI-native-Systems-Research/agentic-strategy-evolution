# `kind: optimization` — a factorial/response-surface campaign type for Nous

**Date:** 2026-08-13
**Status:** Design approved, pending implementation plan
**Issue:** not yet filed — file as an epic before the first PR, then replace this
line with the issue number. Related existing issues: #159 (tier discipline),
#165 (adaptive sweeps), #168 (composite objective), #212/#221 (rehearsal scope
and the cost-asymmetry bug), #246 (spec fidelity), #263 (figure pipeline),
#266 (patch inheritance).

## 1. Motivation

### 1.1 The observed failure

The blog post *"Discovery Is Easy, Composition Is Hard"* (AI-native Systems
Research, 2026-08-04) benchmarked seven LLM-driven optimizers on the Certus
cold-read path. Six of seven beat the 8.86 GB/s baseline; five stalled at
10.5–11.6 GB/s against a 21.1 GB/s hardware ceiling. Eight interacting levers
(L1–L8) were in play, and the winning compound required four of them together.

The decisive structural fact: **L5 (batching) reduced throughput 9.5% in
isolation but was required for the compound.** Any search that prunes
regressing candidates cannot reach the optimum. The post's per-framework
autopsies show three different mechanisms producing the same failure —
population methods sidelining regressing candidates, GEPA's diversity-weighted
parent selection pulling away from the best scorer, K-Search reverting L1/L3 to
seed values while keeping L2+L5.

Nous, under the post's $20 budget, completed three experiments and never
reached the compound. In a separate $65 run it did reach 16.3 GB/s — matching
the best result in the study (16.5 GB/s) by a different route, and additionally
producing a reusable principle set.

### 1.2 The diagnosis

The composition barrier is **an artifact of one-factor-at-a-time (OFAT)
search**, not an inherent property of the problem. Sequential OFAT cannot see
interactions; it only sees increments, and non-monotonic landscapes make
increments misleading.

Factorial experimental design does not have a composition barrier, because it
never decomposes the problem into increments. A resolution-IV fractional
factorial in 8 binary factors (2^(8-4), 16 runs) estimates all 8 main effects
clear of two-factor interactions. Resolution V (2^(8-3), 32 runs) additionally
estimates all 28 two-factor interactions unconfounded — including the L1×L3×L5
structure that makes L5's sign flip legible rather than mysterious.

### 1.3 The token-economics consequence

Nous currently costs roughly the same per iteration regardless of what the
iteration learns, because every iteration pays a full DESIGN → EXECUTE →
findings → principle-extraction cycle. On the Certus problem that was
~$6.70/experiment against a coding agent doing 26 mutations in the same
envelope.

The factorial reframe moves the per-configuration decision **out of the model
and into Python**. The model proposes factors once and interprets fitted
effects once; the 16–32 configurations in between are a deterministic sweep —
build, run, parse, replicate, fit. Cost becomes O(factors) in tokens and
O(design) in compute, instead of O(configurations) in tokens.

This is the primary motivation alongside correctness: users consistently report
that Nous is too expensive. The optimization kind is where that is addressed
structurally rather than by trimming prompts.

### 1.4 Non-goals

* Replacing the reflective campaign kind. Mechanism-discovery campaigns that
  make causal claims about *why* a system behaves as it does remain the
  reflective kind's job. This spec adds a second kind; it does not migrate the
  first.
* Bayesian optimization / surrogate-model search. Considered and deferred
  (§3.2). It produces less legible evidence and is the option most likely to
  yield an unfalsifiable "the model says so" finding.
* Refactoring the shared orchestration core. Considered and deferred (§3.3) to
  avoid a risky rewrite of the code path that in-flight campaigns depend on.

## 2. Evidence from the existing corpus

The design was revised after auditing the local campaign corpus
(`$NOUS_CAMPAIGN_PARENT`, `~/Documents/Projects/papers/memorytime`,
`~/Documents/Projects/inference-sim/.nous`). Findings that changed the design:

**`candidate-threshold-robustness` is a hand-rolled full factorial.** Its
`controllable_knobs` enumerate `tp_low ∈ {0.015,0.020,0.025,0.030,0.040}`,
`tp_high ∈ {6 values}`, `ms_boundary ∈ {3}`, `trailing_stop_threshold ∈ {5}`,
`trailing_stop_min_peak ∈ {3}` — a 5×6×3×5×3 = **1350-cell grid**. A
resolution-V fractional design recovers all main effects and two-factor
interactions in ~50 runs. This is the strongest validation of the approach in
the corpus, and it forced **multi-level factor support**: levels are enumerated
discrete sets, not `[low, high]` pairs.

**`ordering-theorem` is a categorical mechanism factorial whose headline
finding is an interaction.** Three control surfaces (routing × preemption ×
scheduling), and the recorded principle is *"Preemption is actively HARMFUL
when paired with FIFO scheduling (wrong consumer): largest-kappa preemption +
FIFO produces 7.3x WORSE critical TTFT P95 than dumb-tail preemption + FIFO."*
A main-effects-only screen would report "preemption helps" and miss this
entirely. Interaction estimation is therefore a core requirement, not an
enhancement — and factors must support categorical mechanism levels, not just
numerics.

**Responses are frequently constrained conjunctions across regimes, not
scalars.** `candidate-threshold-robustness` requires beating buy-and-hold in
down legs AND up legs AND holding across ≥4 of 5 walk-forward blocks.
`composite-sensitivity-boundary`'s recorded principles trade exactly this way:
*"Removing LT from the composite eliminates 100% of false positives at ρ < 1,
with no detection loss at ρ ≥ 1.05"* — a per-regime trade, invisible to a
scalar objective. A single `maximize(metric)` response would let an optimizer
win on the average while failing the conjunction, which is the precise
overfitting these campaigns were built to prevent.

**There is a held-out split that must never be optimized against.**
`symphony-generation` declares `train_annualized_return` as "the selection key"
and `held_out_annualized_return: (generalization check, NOT the selection
key)`. Fitting effects on held-out data voids the campaign scientifically. This
must be enforced mechanically, not by convention.

**Constraints are admissibility filters, not just physical ceilings.**
`max_drawdown <= 60%`, `dd_limit`, and `trigger_rate_pct` trending to 0 ("a
config turning itself off") are all cases where a configuration can post an
excellent primary metric and still be inadmissible.

**`objective:` is unused in practice.** Despite existing since #168, none of
the audited campaigns declare `objective` or `objective_preset`. The composite
score is therefore not a safe assumption as the natural response surface;
`response` is specified independently (and may *optionally* reuse composite
scoring).

**Two historical bugs set hard constraints on the implementation:**

* **#221** — a `rehearsal` iteration had DESIGN honor the reduced scope while
  EXECUTE_ANALYZE fanned out the full 50-arm experiment anyway, defeating the
  entire cost argument for #212. Lesson: **budget discipline must be enforced
  in Python, not requested in a prompt.**
* **#246 / F1** — `paper-memorytime-mirage` iter-1 silently rewrote four locked
  workload parameters. Lesson: **spec fidelity must hard-fail regardless of
  `--auto-approve`.**

## 3. Approaches considered

### 3.1 Division of labor between model and Python

| | Model role | Verdict |
|---|---|---|
| **A (chosen)** | Propose factors once; interpret effects once; re-enter only on Python-detected triggers | Lowest token cost; between-round adaptation is arithmetic on effect sizes, so little is lost |
| B | Re-enter each round to author the next design matrix | One extra design call per round; buys faster recovery from a bad factor nomination |
| C | Model in the loop per configuration batch | Closest to today's flow; most expensive; reintroduces the OFAT cost curve |

**Chosen: A**, with a narrow escape hatch — Python drives the loop and
re-consults the model only when a trigger fires (§6.3). Accepted cost: a bad
initial factor nomination is not discovered until the screen completes.

### 3.2 Design family

| | Approach | Verdict |
|---|---|---|
| **B (chosen)** | Two-stage: 2-level screen → response-surface refine on survivors | Screening shrinks dimensionality cheaply; refinement over 2–4 factors costs ~15–25 runs and can find interior optima |
| A | Two-level screening only | Cheapest; finds interactions; cannot find interior optima or curvature |
| C | Bayesian optimization over the mixed space | Handles curvature natively but needs more runs to identify interactions reliably, and a GP posterior is far weaker as defensible evidence |

**Chosen: B.** A fitted quadratic with a solved stationary point plus
confirmation runs can land *between* tested levels — the difference between
"best corner" and "the optimum." Center points additionally yield a pure-error
estimate and a lack-of-fit test, so the campaign can state whether its own
model form is adequate. C remains available as a future optional refiner.

### 3.3 Code structure

| | Approach | Verdict |
|---|---|---|
| **B (chosen)** | Parallel `orchestrator/optimize/` subpackage, one thin delegation point in `iteration.py` | Reflective path provably unchanged (its code is not touched); new logic in small, independently testable modules |
| A | Branch inside `iteration.py` at each phase seam | Grows the repo's largest file (1668 lines); interleaves two epistemologies in one control flow; breeds #221-class bugs |
| C | Extract a shared orchestration core first, then build both kinds on it | Cleanest end state; requires rewriting the path every in-flight campaign depends on, while guessing the right abstraction from one example |

**Chosen: B.** If duplication between the two loops later becomes painful, C
becomes a better-informed refactor with two working examples to factor against.

## 4. Architecture

`kind` becomes a top-level campaign field:

```yaml
kind: optimization    # enum: [reflective, optimization]; default: reflective
```

Defaulting to `reflective` leaves every existing campaign byte-identical in
behavior. `iteration.py` gains a single early delegation to
`orchestrator.optimize.run_stage(...)`; no existing reflective code path is
modified.

### 4.1 Module layout

```
orchestrator/optimize/
  __init__.py          public API: run_stage(), StageOutcome
  factors.py           Factor/Level parsing, validation, mixed-type handling
  design.py            res IV/V fractional factorial + CCD/Box-Behnken generation
  matrix.py            design matrix -> concrete config expansion; fidelity check
  effects.py           effect fitting, CIs, lack-of-fit, aliasing report
  relations.py         metamorphic/property relation contracts + verdict parsing
  manipulation.py      per-config manipulation predicates
  stage.py             stage decision rule (verify -> screen -> refine -> confirm)
  artifacts.py         design_matrix.json / effects.json / findings.json mapping
```

Every module is pure functions over data. No module in `optimize/` makes an LLM
call; the two model interactions happen through the existing dispatcher seams.

### 4.2 Shared substrate reused (not duplicated)

| Existing | Reused for |
|---|---|
| `Engine`, `state.json`, phase transitions | Stage iterations use the unmodified phase machine |
| `gates.HumanGate` | Per-stage gates (auto-approved by default for this kind, §7.1) |
| `power.required_seeds` | Design-time replication sizing |
| `parallel_arms.run_units` (injected-runner seam) | Tokenless config execution + testability |
| `validate._validate_locked_parameters` | Non-factor spec fidelity, hard-fail under auto-approve |
| `validate._validate_physical_realism` | Ceiling rejection backstop |
| `ledger`, `meta_findings`, `best_found`, `findings.schema` | Durable artifact set, unchanged |
| `work_dir_resolver` | `NOUS_CAMPAIGN_PARENT` placement |
| `derived_from` (#266) | Carries mechanism code *and its native tests* forward |
| `plot_specs` (#263) | Effect plots / interaction plots via the declarative figure pipeline |

### 4.3 Stage decomposition

Four stages, one per iteration, each a normal Nous iteration with its own gates
and artifacts:

| Iter | Stage | LLM calls | Runs | Establishes |
|---|---|---|---|---|
| 1 | `verify` | 1 design + mechanism code & native tests | ~2/factor | Levers exist, engage, pass native property tests |
| 2 | `screen` | 0 | 16–32 | Which factors matter + all 2-factor interactions |
| 3 | `refine` | 0 | 15–25 | Curvature on surviving `numeric` factors; stationary point |
| 4 | `confirm` | 1 analyze | ~5 × replicates | Predicted optimum reproduces; held-out evaluated |

Plus one gate-summary call per iteration (existing machinery). Substantive
model invocations: **~3 per campaign**, against 60–90 benchmark runs.

The cost curve inverts relative to today: iter-1 carries nearly all token cost
(mechanism code + native tests per lever), iters 2–3 are effectively free. The
expensive stage is also the one whose output is most durable — code and tests
land in the target repo and outlive the campaign.

Stage identity is recorded in `state.json` and per-iteration artifacts, so
unattended runs (§7.1) still yield a fully reconstructible provenance chain.

**Run counts are derived, not chosen.** `design.screen.resolution` plus the
factor count determines the size: for k binary factors, resolution V needs the
smallest 2^(k−p) with no two-factor interaction aliased on another, which is 32
runs for k=6..8 and 16 for k=5. Resolution IV halves that but aliases 2-factor
interactions in pairs. Center points and replicates add on top per §6.2.

Because `ordering-theorem` shows that the headline result can *be* an
interaction (§2), the default is **resolution V**, and the validator warns when
an author requests resolution IV or III while declaring more than one factor —
main-effects-only screening is the OFAT failure mode in disguise. Multi-level
Factors with more than two levels are screened at their `screen_levels` pair
(default: first and last); their remaining levels are explored only in `refine`.

When k is large enough that resolution V exceeds the run budget the author
declares, the validator fails with the two honest options (raise the budget, or
accept resolution IV and the named aliased pairs) rather than silently
downgrading resolution.

## 5. Data model

### 5.1 The `optimization` block

```yaml
kind: optimization

optimization:
  response:
    primary:
      metric: train_annualized_return
      direction: maximize
    constraints:            # admissibility; violated => config infeasible
      - {metric: continuous_max_drawdown, op: ">=", value: -0.60}
      - {metric: trigger_rate_pct, op: ">", value: 0.0}
    regimes:                # conjunction: must hold in EVERY regime
      - {id: crashleg,  metric: improvement_crashleg_pct, op: ">",  value: 0}
      - {id: uptrend,   metric: improvement_uptrend_pct,  op: ">=", value: -5}
    held_out:               # recorded at confirm; NEVER an input to fitting
      - held_out_annualized_return
    ceiling:                # optional physical bound
      {metric: achieved_bandwidth_gbps, value: 21.1}
    noise_estimate_pct: 3.0

  design_space:             # author invariants; Python enforces on EVERY config
    invariants:
      - id: I1
        statement: "connector is peer-to-peer, never staged through host memory"
        observable: telemetry.transfer_path
        op: "=="
        value: p2p
      - id: I2
        statement: "workload is single-tier"
        observable: config.tier_count
        op: "=="
        value: 1

  guidance:                 # domain knowledge for the two model-facing stages
    factor_nomination: >
      Scheduling policy is the highest-value axis here. Consider at minimum:
      shortest-job-first, FCFS, EA-WFQ, priority-FCFS. Prefer mechanisms
      already present in the target over net-new code.
    interpretation: >
      A win that depends on multi-tier workloads is out of scope for this
      campaign; report it as a lead, not a result.

  factors:
    # A numeric knob: values between the declared levels are runnable.
    - id: L1
      name: queue_count
      type: numeric                 # numeric | choice
      levels: [2, 4, 8, 16]         # >= 2 entries; screen uses first & last
      grid: 1                       # optimum snaps to this step (integers here)
      apply: "--queues={level}"     # shorthand for {kind: cli_flag, ...}
      manipulation:                 # family A: did the lever engage?
        {observable: telemetry.queue_count, op: "==", value: "{level}"}
      relations:                    # family B: is the mechanism correct?
        - id: R1
          kind: correctness         # violation => hard-fail campaign
          statement: "queue_count at baseline reproduces baseline within noise"
          native_test: "tests/prop_queue.py::test_baseline_noop"
        - id: R2
          kind: behavioral          # violation => recorded finding
          statement: "throughput monotone non-decreasing in queue_count"
          native_test: "tests/prop_queue.py::test_monotone"

    # A choice knob: nothing lives between the levels.
    - id: L5
      name: batching
      type: choice
      levels: [off, on]
      apply: {kind: env_var, name: CERTUS_BATCHING, value: "{level}"}
      manipulation:
        {observable: telemetry.mean_batch_size, op: ">", value: 1, when: "on"}
      relations:
        - id: R3
          kind: correctness
          statement: "batching=off is byte-identical to baseline"
          native_test: "tests/prop_batch.py::test_off_is_noop"

  design:
    screen:  {resolution: 5, center_points: 4}
    refine:  {kind: central_composite, center_points: 5}
    confirm: {replicates: 5}
    max_runs: 120                   # validator fails rather than downgrade

  test_command: "pytest -q tests/prop_*.py --json-report"
  integrity_command: "./scripts/verify_integrity.sh"
```

### 5.2 Field semantics

The authoring surface is deliberately small: a factor needs `id`, `name`,
`type`, `levels`, `apply`, one `manipulation`, and one `correctness` relation.
Everything else has a default.

**`type` is `numeric` or `choice` — a domain question, not a statistics
question.** The only thing the author must decide is *whether values between the
declared levels are runnable*:

* `numeric` — interpolation is meaningful. `tp_low ∈ {0.015…0.040}` (any
  threshold ships), `ms_boundary ∈ {0.75, 0.85, 0.95}` (a continuous ratio,
  coarsely enumerated), `queue_count ∈ {2,4,8,16}`.
* `choice` — nothing lives between the levels. `scheduler ∈ {vector-kvtime,
  static-drf, fcfs}`, `batching ∈ {off, on}`, `preemption ∈ {largest-kappa,
  dumb-tail, none}`.

An earlier draft offered `continuous | ordinal | categorical`. That was dropped:
"ordinal" is a statistics term that makes the author reason about how fitting
works, and the fitting question it was trying to answer is fully determined by
`type` + `grid`.

**`grid` makes the reported optimum runnable.** Refinement fits a continuous
surface and solves for a stationary point, which may land between levels. With
`grid: g` the point **snaps** to the nearest multiple of `g` — so `K = 4.7`
becomes `K = 5`, and `confirm` runs a configuration that actually exists.
`confirm` validates the *snapped* point, not the theoretical one, and if
snapping moves the response outside the predicted CI that is recorded as a
finding rather than hidden. Omit `grid` when any real value ships (thresholds,
ratios). Ignored for `type: choice`.

This resolves what was open question #3: the alternative — restricting
refinement to declared levels — throws away the main advantage of the
response-surface stage (finding interior optima), and plain rounding can report
an optimum the target cannot run.

**Screen levels default to `levels[0]` and `levels[-1]`.** Declare
`screen_levels: [lo, hi]` only when the extremes are known-pathological and the
screen should bracket a narrower span. For the common two-level case, write
`levels: [off, on]` and omit `screen_levels` entirely.

**`apply` is the seam that removes the LLM from the inner loop.** It declares
mechanically how a level becomes a runnable configuration; given it, Python
expands a matrix row into a command with no model involvement. This is the most
load-bearing field in the schema. A bare string is shorthand for a CLI flag —
`apply: "--queues={level}"` — with the long forms being
`{kind: cli_flag, template: ...}`, `{kind: env_var, name: ..., value: ...}`, and
`{kind: config_patch, path: ..., pointer: ..., value: ...}`. `{level}` is the
only interpolation token in the entire spec.

**Factor levels are the pre-registered parameters.** `locked_parameters` keeps
its existing meaning for everything that is *not* a factor. The validator warns
when a knob listed in `target_system.controllable_knobs` appears in neither
`factors` nor `locked_parameters` — the "what did you forget to control" check.

**Both check families are mandatory.** Schema requires ≥1 `manipulation` and
≥1 `correctness` relation per factor. `manipulation` reuses the same
`{metric|observable, op, value}` comparison shape as `constraints` and `regimes`
— one comparison vocabulary across the whole spec, no bespoke assertion
mini-language to learn or mis-type. Two optional guards restrict *which* levels
the check applies to, because a check is often meaningless at one level:
`when: <level | [levels]>` applies it only at those levels, and
`when_not: <level | [levels]>` applies it everywhere else. A batch-size
assertion holds only at `batching: on` (`when: on`); a
"trailing-stop fired at least once" assertion holds at every level except
`off` (`when_not: off`). Supplying both on one check is a validation error.

The validator rejects trivially-true predicates (`> 0`, `!= null`, bare
truthiness) using the same floor `validate_evidence` applies to principles: a
lazy predicate manufactures false confidence and is worse than none.

**`relations` are per-factor but may be stated over the interaction structure**
(e.g. "monotone in queue_count at fixed L2..L8"), so a metamorphic relation is
not confined to one knob in isolation.

### 5.3 Steering the campaign: `design_space` vs `guidance`

Existing campaigns carry substantial domain knowledge in
`target_system.description` — `paper-memorytime-vector`'s runs to ~2600
characters of "Prime directive", "Scientific framing", "Realization to build",
and "Honest scope limitation". That field is inherited unchanged and remains the
right home for narrative framing.

It is not sufficient on its own here, for a reason specific to this kind:
**`screen` and `refine` make zero model calls (§4.3), so a directive that exists
only as prose is structurally unenforceable during the two stages that spend the
benchmark budget.** "Single-tier workload only" written in a description cannot
stop a matrix row from being generated with two tiers. This is the #221 failure
mode exactly — a directive honored by the phase that reads prompts and ignored
by the phase that does the work.

Author intent therefore splits by *who has to act on it*:

**`design_space.invariants` — properties Python enforces on every configuration.**
Same `{observable, op, value}` vocabulary as `constraints` and `manipulation`.
Checked on all runs in all stages. Where a violation is statically determinable
from the matrix row, the row is rejected **before it runs**; where it is only
observable post-hoc, the config hard-fails after running. Either way the
guarantee holds across all 60–90 runs, not just the two the model sees.

How this differs from the two neighbouring mechanisms:

| Mechanism | Asserts | Violation means |
|---|---|---|
| `locked_parameters` | an **input** you set has a pinned value | the spec was rewritten (#246) |
| `design_space.invariants` | a **property of the resulting system** holds | the campaign left its declared design space |
| `response.constraints` | a **measured outcome** is admissible | this config is infeasible; exclude from fitting, keep exploring |

"The connector is P2P" is an invariant rather than a locked parameter because it
may be an emergent consequence of several settings rather than one flag —
asserting the observed transfer path is stronger than pinning the flags you
believe produce it.

**`guidance` — structured prose for the two model-facing stages.** Two named
slots, because they are consumed at different times and blending them wastes
tokens in both:

* `factor_nomination` → read at `verify`, when the model proposes factors and
  levels. This is where "explore scheduling options such as shortest-job-first"
  and "try parameters in a symphony" belong.
* `interpretation` → read at `confirm`, when the model interprets the fitted
  surface. Scope limitations and "report X as a lead, not a result" belong here.

Both are optional; `target_system.description` still applies to both stages.

**The rule for authors:** anything you would be upset to discover was violated
after 60 runs belongs in `invariants`. `guidance` shapes what the model
*proposes*; `invariants` bound what Python will *execute*.

### 5.4 Native tests are target-side artifacts

Property, metamorphic, fuzz, and invariant tests for campaign-generated
mechanism code are written **in the target's native idiom** (`hypothesis` for
Python, `rapid`/`testing/quick` for Go, `proptest`/`quickcheck` for Rust,
RapidCheck for C++), live in the target's test tree, and are committed with the
mechanism code.

Consequences:

1. **They outlive the campaign.** A property test in the target's tree keeps
   protecting the mechanism after Nous exits, and runs in the target's CI.
2. **Nous needs zero language knowledge.** Its role collapses to a contract
   check: relations are declared, each maps to a native test identifier, the
   declared `test_command` ran, and it exited clean. Generator and library
   choice are the target's business.
3. **Mechanism code and its tests are a coupled deliverable** — a lever is not
   done until its native property tests exist and pass. `derived_from` (#266)
   carries both forward automatically, since they are in the same worktree diff.

Metamorphic testing is the load-bearing technique here because agent-generated
mechanism code has no reference implementation to diff against (the oracle
problem). Asserting *relations between runs* sidesteps it. Relations that come
free from factor semantics:

* **no-op at baseline** — a factor at its baseline level reproduces baseline
  within noise. The highest-value relation: it catches "my new code path
  changed behavior even when disabled," which would otherwise contaminate
  *every* cell of the design.
* **conservation** — bytes retrieved == bytes requested; no block delivered
  twice; totals reconcile across layers.
* **permutation invariance** — reordering independent requests must not change
  aggregate throughput beyond noise.
* **scale relations** — halving the workload halves total bytes moved, not
  bandwidth.
* **monotonicity** — classified `behavioral`, never `correctness` (§6.4).

### 5.5 Artifacts

New, schema-validated, per iteration:

* `design_matrix.json` — the pre-registered matrix: rows, generator, alias
  structure, randomized run order, RNG seed. Written **before** execution.
* `runs.jsonl` — one row per executed config: factor levels, response metrics,
  replicate index, manipulation verdicts, constraint verdicts, integrity
  verdict, duration, build hash.
* `effects.json` — fitted main effects and interactions with confidence
  intervals, pure-error estimate, lack-of-fit test, aliasing caveats, and which
  factors were dropped as within-noise.
* `relations.json` — per-relation verdicts from the native test run, with test
  identifier and exit status.

Unchanged in **schema** and still written every iteration: `findings.json`,
`principle_updates.json`, `best_found.json`, `ledger.json`,
`meta_findings.json`. `/post-campaign`, `index-wiki`, `visualize-campaign`, and
the cross-campaign registry therefore keep working with no changes. The
optimization artifacts are strictly additive; the durable findings surface is
satisfied by reuse, not by a parallel artifact system.

**How these are authored without spending tokens (resolves the apparent
conflict with §4.3's "0 LLM calls" for `screen` and `refine`):** in the
reflective flow, `findings.json` and `principle_updates.json` are written by the
model. In the optimization kind they are **projected deterministically from
`effects.json`** by `artifacts.py` — a fitted effect with a confidence interval
already contains everything the findings schema requires (a claim, a direction,
a magnitude, and quantitative evidence), so restating it in prose adds cost
without adding information.

The projection is mechanical and follows the pattern `meta_findings.py` already
established (#155): pure Python, zero tokens, structured entries with concrete
numeric citations. Each surviving effect becomes one finding whose evidence is
the estimate, CI, replicate count, and the matrix row set it was fitted from;
each dropped factor becomes a NULL-result finding naming the noise floor it fell
below. `validate_evidence`'s existing floor applies unchanged, and passes
trivially because the evidence is numeric by construction.

The model authors prose only at `verify` (iter-1, mechanism rationale) and
`confirm` (iter-4, interpretation of the final surface). Those are the two
points where prose carries information a number does not.

## 6. Execution and control flow

### 6.1 The tokenless inner loop

Per configuration: expand matrix row → apply factor levels via `apply` → build
(cached by content hash, so repeated levels do not rebuild) → run → parse
response metrics → evaluate manipulation predicates → evaluate constraints →
append to `runs.jsonl`. Pure Python; the model is never invoked. Implemented
over `parallel_arms.run_units`' injected-runner seam, so it is testable with a
fake runner and no LLM.

### 6.2 Replication and run order

`power.required_seeds` sizes replicates from `noise_estimate_pct`. Center
points supply the pure-error estimate that makes the lack-of-fit test
meaningful. Run order is randomized against a recorded seed: reproducible *and*
immune to time-ordered drift (thermal, cache warming) that a sequential grid
cannot rule out.

### 6.3 Stage transitions are a pure decision rule

`stage.py`, no model call:

* **After `screen`:** drop factors whose effect CI contains zero. If ≥1
  `numeric` factor with >2 levels survives → `refine`. If only `choice` factors
  (or 2-level `numeric` ones) survive → skip to `confirm` at the winning corner.
* **After `refine`:** solve the fitted quadratic's stationary point; check it is
  interior to the declared hull and feasible against `constraints`; then
  `confirm`.

Escalation triggers that *do* re-consult the model — all Python-detected:

1. every factor within noise → the factor set was wrong
2. lack-of-fit significant → the model form is inadequate
3. stationary point outside the declared hull → ranges were too narrow
4. a `behavioral` relation violated → possible real non-monotonicity worth
   interpreting

Iteration N+1 inherits effect sizes and confidence intervals, not prose. This
is a strictly stronger form of "takes full advantage of iteration N" than
principle-passing alone; principles remain valuable for cross-campaign
transfer.

### 6.4 Failure taxonomy

| Failure | Consequence |
|---|---|
| `correctness` relation violated | **Hard-fail campaign.** Apparatus broken; measurements meaningless. |
| `behavioral` relation violated | Recorded finding; campaign continues. |
| Manipulation predicate fails | Hard-fail that **config**; retry once; if persistent, drop the factor, record it, refit on remaining factors with aliasing recomputed. |
| `design_space` invariant violated | **Hard-fail.** Rejected before running when statically determinable from the matrix row; hard-fails the config after running when only observable post-hoc. The campaign has left its declared design space, so continuing would answer a different question than the one asked. |
| Constraint violated | Config marked infeasible; excluded from fitting; retained in `runs.jsonl`. |
| Response above `ceiling` | Hard-fail config — physically impossible means the instrumentation is lying. |
| Executed config ≠ matrix row | **Hard-fail regardless of `--auto-approve`.** Same treatment as `locked_parameters` (#246). |
| Held-out metric present in a fitting input | **Hard-fail.** Prevents the `symphony-generation` leakage class. |
| Build/run crash | Retry with backoff; then mark the config failed; refit on completed cells and **report the reduced resolution honestly**. |

The asymmetry is deliberate: partial failure degrades the *claim* (reported
resolution drops, dropped factors named) rather than silently proceeding as
though nothing happened.

**Why monotonicity must be `behavioral`, never `correctness`:** L5 (batching)
was −9.5% alone and required for the compound. A naive monotonicity check
classified as `correctness` would have hard-failed the campaign on the single
most important discovery in the study. Conflating "the code is wrong" with "the
system is surprising" would make Nous blind to exactly the non-monotonic
compounds this kind exists to find. The schema forces the author to classify
each relation, and the guide (§8) documents this as a named anti-pattern.

## 7. Behavior changes outside `optimize/`

### 7.1 Gate defaults become kind-scoped

Today `--auto-approve` is a single global `store_true` on both `nous run` and
`nous resume` (`orchestrator/cli.py:1072`, `:1130`), defaulting to off. Flipping
that default globally would change gate behavior for every existing
**reflective** campaign, contradicting the "reflective path provably unchanged"
guarantee of §4.

So the default is scoped to the kind, not to the flag:

* `kind: optimization` — gates auto-approve by default. There is no per-stage
  human decision that changes what happens next (§6.3 is a pure decision rule),
  so prompting buys nothing while costing wall-clock.
* `kind: reflective` — unchanged; `--auto-approve` remains opt-in.
* `--interactive` (new) forces prompting for either kind.
* An explicit `--auto-approve` on the command line still wins for either kind,
  so existing invocations and scripts behave exactly as before.

Resolution order: `--interactive` > `--auto-approve` > kind default. The flag
parsing must therefore distinguish "not supplied" from "supplied false", i.e.
`default=None` rather than `store_true`, so the kind default can be applied
without clobbering an explicit choice.

Because optimization campaigns run unattended by default, the following
hard-fail **independently of gate approval**:

* `locked_parameters` deviation (existing, #246)
* executed-config vs `design_matrix.json` drift (new)
* held-out metric appearing in a fitting input (new)
* `correctness` relation violation (new)
* trivially-true manipulation predicate at validation time (new)

### 7.2 The graded-complexity tier ladder does not apply to this kind

`CLAUDE.md` and `orchestrator/complexity_tier.py` (#159) enforce that
**iteration N may use any tier ≤ N**: tier 1 is "single mechanism, single knob,
treatment vs control", tier 3 is "multi-mechanism interactions,
super-additivity, dose-response across knobs", and jumps of more than one tier
across iterations are prominently flagged at the design gate.

This is in direct tension with §1.2. The entire argument for the optimization
kind is that multi-factor interaction *measurement* should happen in iteration 1
or 2, because that is the cheap way to get the answer — and `ordering-theorem`
shows the headline result can be an interaction. Under the ladder as written, a
`screen` stage at iter-2 reads as an unflagged tier-3 leap.

**Resolution: the ladder is scoped to `kind: reflective` and does not gate
optimization campaigns.** The justification is that the ladder guards against a
specific epistemic error — asserting a *causal mechanism claim* before simpler
explanations are refuted. A factorial screen makes no mechanism claim; it
measures a response surface over knobs the author already controls and declares
in advance. Those are different epistemic objects, and the ladder's premise
(that sophisticated hypotheses should be deferred until simpler ones are ruled
out) does not transfer to a design whose whole purpose is to estimate all the
low-order terms simultaneously.

Crucially, the anti-p-hacking property the ladder protects is *strengthened*
here, not weakened: a pre-registered design matrix fixes every configuration
before any result is seen, so there is no opportunity to choose the next factor
after seeing which way the data broke. Sequential OFAT offers exactly that
opportunity; the matrix removes it.

Implementation: `complexity_tier.format_tier_summary` is called only on the
reflective path. Optimization bundles do not declare `complexity_tier` or
`tier_justification`, and the schema rejects those fields under
`kind: optimization` so an author cannot half-adopt both disciplines.

### 7.3 Schema and validator

`campaign.schema.yaml` gains `kind` and the `optimization` block, with
`additionalProperties: false` preserved. Cross-field rules JSON Schema cannot
express (a factor whose `screen_levels` are not members of `levels`; a
`refine.kind` requiring ≥2 surviving `numeric` factors; a `held_out` metric also named
as `primary`) are enforced in `validate.py` alongside the existing
`_validate_locked_parameters` family, and return **actionable repair messages**
rather than bare rejections — the validator is read by AI authors.

## 8. Documentation

`docs/optimization-campaign-guide.md`, paralleling
`docs/campaign-authoring-guide.md`, is a **primary deliverable, not an
afterthought** — optimization campaigns will be authored by AI, so the guide is
the authoring interface, and ambiguity there produces invalid campaigns rather
than a human who asks a clarifying question.

Contents:

1. Mental model: why factorial beats OFAT; screen → refine → confirm.
2. Field-by-field walkthrough of the `optimization` block.
3. Four worked end-to-end examples drawn from the real corpus:
   * multi-level grid → `candidate-threshold-robustness` (1350 cells → ~50 runs)
   * categorical mechanism factorial with a known 7.3× interaction →
     `ordering-theorem`
   * constrained multi-regime response → `composite-sensitivity-boundary`
   * binary throughput levers → the Certus cold-read case
4. A "declare as factor vs lock" inventory, mirroring the #245 "what to lock"
   inventory.
5. Anti-patterns: trivial manipulation predicates; held-out leakage;
   main-effects-only when interactions are expected; monotonicity misclassified
   as `correctness`; treating a constrained conjunction as a scalar objective;
   **putting an enforceable directive in `guidance` (or
   `target_system.description`) instead of `design_space.invariants`** — the
   #221 failure mode, since `screen` and `refine` never read prose.
6. A steering section mapping the three channels: `guidance` (what the model
   proposes) vs `design_space.invariants` (what Python executes) vs
   `target_system.description` (narrative framing), with the "would you be upset
   to find this violated after 60 runs?" test.

Cross-linked from `README.md`, `CLAUDE.md`, and `docs/data-model.md`. Schema
descriptions carry a one-line intent plus a concrete example each and point to
this guide.

## 9. Testing

Per `CLAUDE.md`: no test may make a live LLM call. Every module in `optimize/`
is pure functions over data, so this holds by construction rather than by
mocking discipline.

* **Design generation** — a 2^(8-4) generator must reproduce the textbook alias
  structure; resolution claims verified against known-good tables.
* **Effect fitting** — synthetic data with known ground-truth effects,
  including a **planted L5-style sign flip** (negative main effect, positive
  interaction) that the fitter must recover.
* **Stage rule** — crafted effect tables driving each transition and each of
  the four escalation triggers.
* **Matrix fidelity** — asserts hard-fail on drift between `runs.jsonl` and
  `design_matrix.json`, including under `--auto-approve`.
* **Leakage** — asserts hard-fail when a `held_out` metric reaches a fitting
  input.
* **Relations** — `correctness` violation fails the campaign; `behavioral`
  violation produces a finding and continues.
* **Validator** — trivially-true predicates rejected; cross-field rules
  produce actionable messages.
* **End-to-end** — `StubDispatcher` + a fake runner drive a full four-stage
  campaign, asserting the complete artifact set lands and schema-validates.
* **Reflective-path regression** — existing campaign fixtures produce
  byte-identical behavior with `kind` absent.

## 10. Open questions deferred to implementation

1. **Build-cache key.** Content hash over which inputs exactly? Must include
   the applied factor levels and the mechanism patch, or a stale binary silently
   serves a different configuration.
2. **Fractional-factorial generator source.** Hand-rolled generators with a
   verified alias table, or a dependency (`pyDOE3`)? Preference: hand-rolled for
   the standard resolutions, to keep the dependency tree and the alias claims
   auditable.
3. **Multi-response optimization.** When `regimes` conflict irreconcilably, the
   current design reports the trade rather than picking a winner. Whether to add
   desirability functions is deferred until a campaign needs it.

*(A fourth question — how ordinal factors behave in refinement — was resolved
during review by replacing the three-way type vocabulary with `numeric` +
`grid`; see §5.2.)*

## 11. Worked example: `candidate-threshold-robustness` restated

The corpus campaign that hand-rolled a 5×6×3×5×3 = 1350-cell grid (§2), written
as an optimization campaign. Resolution V over 5 factors is 16 runs; with 4
center points and 3 replicates at confirm, the whole campaign is ~40 runs
against 1350 — and it gains interaction estimates the grid never computed.

```yaml
kind: optimization
run_id: candidate-threshold-robustness-opt
research_question: >
  Is there a category-tp threshold configuration that robustly beats buy&hold
  out-of-sample across both the down-legs and up-legs of the 2025-03..2026-06
  window?

target_system:
  name: vol-backtest
  description: Threshold-based trading strategy evaluated over historical bars.

prompts:                      # required by campaign.schema.yaml for every kind
  methodology_layer: prompts/methodology
  domain_adapter_layer: null

locked_parameters:            # unchanged from the original campaign
  arming_threshold: 0.40
  account_gain_floor: 0.0
  cd: 0
  weighting: equal_daily_rebalanced
  is_start: "2025-03-20"
  oos_start: "2026-02-01"

optimization:
  response:
    primary: {metric: improvement_uptrend_pct, direction: maximize}
    constraints:
      - {metric: trigger_rate_pct, op: ">", value: 0.0}   # not turned off
    regimes:                  # the robustness conjunction, made explicit
      - {id: crashleg,      metric: improvement_crashleg_pct,      op: ">",  value: 0}
      - {id: correctionleg, metric: improvement_correctionleg_pct, op: ">",  value: 0}
      - {id: uptrend,       metric: improvement_uptrend_pct,       op: ">=", value: -5}
    held_out: [walk_forward_blocks_robust]
    noise_estimate_pct: 4.0

  design_space:
    invariants:
      - id: I1
        statement: "every config trades the same instrument set (no survivorship drift)"
        observable: telemetry.instrument_set_hash
        op: "=="
        value: "baseline"
      - id: I2
        statement: "no config peeks past the OOS boundary"
        observable: telemetry.max_bar_date
        op: "<="
        value: "2026-06-18"

  guidance:
    factor_nomination: >
      tp_low and tp_high interact through the category boundary; treat their
      interaction as the primary object of interest rather than either main
      effect. Trailing-stop factors are secondary — screen them, but do not
      spend refinement budget on them unless the screen says they matter.
    interpretation: >
      A config that wins only in the uptrend regime is not a result for this
      campaign; the robustness conjunction across all three regimes is the
      claim. Report uptrend-only winners as leads.

  factors:
    - id: F1
      name: tp_low
      type: numeric
      levels: [0.015, 0.020, 0.025, 0.030, 0.040]
      apply: "--tp-low={level}"
      manipulation: {observable: config.tp_low, op: "==", value: "{level}"}
      relations:
        - {id: R1, kind: correctness,
           statement: "tp_low at 0.015 reproduces the recorded baseline run",
           native_test: "tests/prop_thresholds.py::test_baseline_reproduces"}

    - id: F2
      name: tp_high
      type: numeric
      levels: [0.030, 0.040, 0.050, 0.060, 0.080, 0.120]
      apply: "--tp-high={level}"
      manipulation: {observable: config.tp_high, op: "==", value: "{level}"}
      relations:
        - {id: R2, kind: correctness,
           statement: "tp_high >= tp_low invariant holds for every accepted config",
           native_test: "tests/prop_thresholds.py::test_ordering_invariant"}

    - id: F3
      name: ms_boundary
      type: numeric
      levels: [0.75, 0.85, 0.95]
      apply: "--ms-boundary={level}"
      manipulation: {observable: config.ms_boundary, op: "==", value: "{level}"}
      relations:
        - {id: R3a, kind: correctness,
           statement: "ms_boundary partitions every bar into exactly one category",
           native_test: "tests/prop_thresholds.py::test_partition_is_total"}
        - {id: R3b, kind: behavioral,
           statement: "trigger_rate is monotone non-increasing in ms_boundary",
           native_test: "tests/prop_thresholds.py::test_trigger_rate_monotone"}

    - id: F4
      name: trailing_stop_threshold
      type: choice              # 'off' is not a number; no interpolation
      levels: [off, 0.004, 0.005, 0.007, 0.010]
      apply: "--trailing-stop={level}"
      manipulation: {observable: telemetry.trailing_stop_events, op: ">", value: 0,
                     when_not: off}
      relations:
        - {id: R4, kind: correctness,
           statement: "trailing_stop=off is byte-identical to the no-stop path",
           native_test: "tests/prop_stops.py::test_off_is_noop"}

    - id: F5
      name: trailing_stop_min_peak
      type: numeric
      levels: [0.006, 0.008, 0.012]
      apply: "--min-peak={level}"
      manipulation: {observable: config.min_peak, op: "==", value: "{level}"}
      relations:
        - {id: R5, kind: correctness,
           statement: "min_peak has no effect when trailing_stop=off",
           native_test: "tests/prop_stops.py::test_min_peak_inert_when_off"}

  design:
    screen:  {resolution: 5, center_points: 4}
    refine:  {kind: central_composite, center_points: 4}
    confirm: {replicates: 3}
    max_runs: 60

  test_command: "pytest -q tests/prop_*.py --json-report"
```

Three things this example demonstrates that prose does not:

* **`trailing_stop` is `choice`, not `numeric`,** because `off` sits in a list of
  numbers. An author reaching for `numeric` here would be asking the fitter to
  interpolate between `off` and `0.004`. The `type` question ("is anything
  between these runnable?") makes the right answer obvious without knowing
  anything about regression.
* **R5 encodes a cross-factor inertness relation** — `min_peak` must do nothing
  when `trailing_stop=off`. That is a real bug class in threshold code, it is
  invisible to any single-factor test, and it would otherwise show up as
  unexplained noise in the F5 main effect.
* **The robustness conjunction is declared, not discovered.** The original
  campaign expressed "robust winner" in prose and checked it by hand; here the
  three `regimes` make a config's admissibility mechanical, and the per-regime
  effect fits show directly whether a factor helps everywhere or trades one leg
  against another.
* **I2 is a lookahead-bias tripwire that fires on every one of the ~40 runs.**
  "Don't peek past the OOS boundary" is the kind of instruction that reads as
  obviously-satisfied in prose and is catastrophic when silently violated —
  every downstream number becomes meaningless while still looking excellent.
  As an invariant it is checked mechanically per config, in the stages where no
  model is watching.
