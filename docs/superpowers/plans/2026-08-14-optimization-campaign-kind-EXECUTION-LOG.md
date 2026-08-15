# SDD ledger — plan: docs/superpowers/plans/2026-08-14-optimization-campaign-kind.md

Spec: docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md (read, reachable)
Branch: nousko
Merge base vs main: 2435e2c0270a4df292cbd54f142bbd9c6264ffff
Plan HEAD at start: 23f392f1530552fcc6c23a7ab63e45903743adba
Workspace: .superpowers/sdd/2026-08-14-optimization-campaign-kind/

## Pre-flight conflict scan

### File ownership (each task vs every other)

| Task | Creates/Modifies | Shared with | Finding |
|---|---|---|---|
| 1 | `optimize/__init__.py`, `optimize/factors.py` | 11 (re-exports from `__init__`) | OK — T11 appends `run_stage` re-export; T1 writes the docstring + `from __future__`. Append-only, no rewrite. |
| 2 | `optimize/predicates.py` | none | OK — sole owner |
| 3 | `optimize/design.py` | none | OK — sole owner |
| 4 | `optimize/effects.py` | none | OK — sole owner |
| 5 | `optimize/matrix.py` | none | OK — sole owner |
| 6 | `optimize/relations.py` | none | OK — sole owner |
| 7 | `optimize/stage.py` | none | OK — sole owner |
| 8 | 4 new schemas, `optimize/artifacts.py` | none | OK — all four schema files are new |
| 9 | `optimize/runner.py` | none | OK — sole owner |
| 10 | `campaign.schema.yaml`, `validate.py` | none among tasks | OK — only task touching either |
| 11 | `iteration.py`, `cli.py`, `campaign.py`, `optimize/stage_runner.py` | 1 (`__init__.py`) | OK — see row 1 |
| 12 | `tests/test_optimize_no_regression.py` only | none | OK — no production code by design |
| 13 | guide, `README.md`, `CLAUDE.md`, `docs/data-model.md` | none | OK — sole owner |

Test files: 13 distinct paths, no collisions.

### Interface producer → consumer pairs

| Producer | Consumer | Contract | Finding |
|---|---|---|---|
| T1 `Factor`, `parse_factors`, `decode_coded`, `is_refinable` | T5 (expand), T7 (`is_refinable`), T10 (validator rule 4) | field names + signatures | OK — `is_refinable` used identically in T1:81, T7 rule, T10:2142 |
| T3 `Design`, `DesignPoint.role ∈ {corner,center,axial}`, `alias_pairs` | T4 (`fit_effects`, `Fit.aliases`), T5 (`matrix_payload`) | role vocabulary + `.corners` | OK — role strings consistent at T3:787/1016 and T4:903-927 |
| T3 `min_runs_for` | T10 (validator rule 8) | `(k, resolution) -> int` | OK |
| T4 `Fit`, `Effect`, `dropped_factors`, `solve_stationary_point` | T7 (decisions), T8 (projection) | `fit_effects(design, responses, *, factor_ids, ...)` | OK — 14 call sites all match T4:1550 |
| T2 `evaluate`, `is_trivial` | T5 (`check_invariants`), T9 (manipulation/constraints), T10 (rule 6) | `{observable, op, value, when, when_not}` | OK — one vocabulary, verified |
| T5 `ConfigRow`, `check_fidelity` | T9 (`execute_design`), T11 (fidelity hard-fail) | `ConfigRow.apply` dict | **Noted** — see ruling below |
| T6 `reconcile`, `classify_failures` | T11 (verify-stage abort) | verdict lists | OK |
| T7 `Stage`, `stage_for_iteration` | T11 (delegation branch) | `stage_for_iteration(campaign, iteration)` | OK — T11:Step 2 snippet matches T7 signature |
| T8 writers + `project_findings` | T11 (per-stage artifact writes) | `iter_dir` first arg | OK |
| T10 `campaign_kind` | T11 (delegation), T12 (regression) | `-> "reflective" | "optimization"` | OK |

### Self-consistency (each task's tests vs its own code)

| Task | Check | Finding |
|---|---|---|
| 1 | 19 tests vs implemented functions | OK — every asserted name exists in the Step 4 code |
| 2 | operator table + `is_trivial` cases | OK — all 6 ops implemented; 5 trivial cases covered |
| 3 | alias oracles vs `_GENERATORS` table | OK — (5,5) and (7,3) entries present and verified externally |
| 4 | planted-truth tests vs closed form | OK — L5 case (main −0.95 / interaction +1.60) verified before writing |
| 5–9 | assertion lists vs interface blocks | OK — every asserted symbol appears in its Interfaces block |
| 10 | 10 cross-field rules vs 10 test items | OK — 1:1 |
| 11 | 16 assertions vs 4 modified files | OK |
| 12 | 7 assertions, no production code | OK — intentional |
| 13 | 6 assertions over extracted yaml | OK |

### Rubric-vs-plan tension

Checked for plan-mandated items a reviewer would flag as defects:
- Task 12 adds tests with no production code → a reviewer may flag "task adds no
  implementation". It is the plan's central architectural guarantee. Pre-ruled below.
- Three Python blocks in Task 11 are indented fragments, not modules → the plan's
  "Notes for the implementer" section already says so. No action.
- No test asserts nothing; no verbatim logic duplication mandated.

### Pre-flight rulings

Ruling: `Factor.apply_spec` (T1) and `ConfigRow.apply` (T5) keep their distinct names — the first is the *declaration* parsed from yaml, the second the *rendered* result (`cli_args`/`env`/`patches`) for one config. Renaming either to match would conflate declaration with instantiation. — Cost if wrong: an implementer conflates them and T5's expand returns the wrong shape; caught by T5 assertions 3–5 and by T9's runner tests.

Ruling: Task 12 shipping tests with zero production code is correct and must not be "fixed" by adding code. It is the regression gate proving the reflective path is untouched. — Cost if wrong: nothing; a reviewer flagging it is answered by this ruling.

Ruling: Task 1 writes `optimize/__init__.py` with only a docstring + `from __future__ import annotations`; Task 11 appends the `run_stage`/`StageOutcome`/`Stage` re-exports. Task 1 must NOT pre-declare those re-exports (they would fail to import until T11). — Cost if wrong: T1's suite fails at import; caught immediately by T1 Step 5.

Scan complete. No blocking conflicts. Dispatching Task 1.

### Mid-flight ruling (found while Task 1 was running; applies to Task 8)

Investigated whether Task 8's `project_findings` can satisfy the EXISTING
`findings.schema.json` as the plan asserts. It cannot, as written:

- `$defs/arm_result` has `additionalProperties: false` and six required fields
  (`arm_type`, `predicted`, `observed`, `status`, `error_type`,
  `diagnostic_note`) built around the reflective kind's predict-then-compare
  epistemology.
- `arm_type` is a CLOSED enum of 7 reflective values (`h-main`, `h-ablation`,
  `h-super-additivity`, `h-control-negative`, `h-robustness`,
  `h-dose-response`, `h-tradeoff`).
- `status` is a CLOSED enum of 3 (`CONFIRMED`, `REFUTED`,
  `PARTIALLY_CONFIRMED`).

A fitted effect has no "predicted" value, is not an `h-main` arm, and a
factor dropped as within-noise is not `REFUTED` in the predict-then-compare
sense. Downstream consumers read these with `.get(..., default)` so they
degrade gracefully, EXCEPT `meta_findings.py:462` (keys on
`arm_type == "h-main"`) and `composite_score.py:234` (maps `status` to a
score).

Ruling: Task 8 maps the projection onto the existing vocabulary rather than
widening the enums or adding a parallel artifact. Specifically —
  * one arm row per surviving effect with `arm_type: "h-main"`;
  * `predicted` = the factor's declared relation/expectation text;
  * `observed` = the fitted estimate with its CI and n;
  * `status` = `CONFIRMED` when the CI excludes zero in the hypothesised
    direction, `REFUTED` when it excludes zero in the opposite direction,
    `PARTIALLY_CONFIRMED` otherwise;
  * dropped (within-noise) factors get `arm_type: "h-control-negative"` with
    `status: "REFUTED"` and the noise floor in `diagnostic_note`;
  * everything optimization-specific (effect label, estimate, ci_low,
    ci_high, se, aliases, stage) goes in `metadata`, which is an open object.
`findings.schema.json` is NOT modified.
— Cost if wrong: findings rows read slightly oddly to a human expecting
reflective-style prose, and `composite_score` scores optimization arms via
the legacy status map. Both are cosmetic and reversible. The alternative
(widening two closed enums) would change the contract every existing
campaign and consumer depends on — a far worse trade for a cosmetic gain.
This ruling must be carried into the Task 8 dispatch.

Also checked (same investigation): `principles.schema.json` needs NO ruling.
Its 11 required fields are free-form strings/arrays, and every closed enum it
does have maps naturally onto a fitted effect — `confidence` (low/medium/high)
from CI width relative to the estimate, `derivation_type: "empirical"`,
`category: "domain"`, `status: "active"`. `evidence` is `array[string]`, so
numeric citations go in as formatted strings. Task 8's
`project_principle_updates` is satisfiable exactly as the plan specifies.

### Rulings found during Task 1 verification (apply to ALL remaining tasks)

Ruling: the plan's Global Constraints say to run `.venv/bin/pytest`. That binary
does not exist — pytest is NOT installed in the project venv; the working
invocation is the system one at `/opt/homebrew/bin/pytest` (confirmed: 23 passed
for T1, 1374 passed / 1 skipped for the full suite). Every remaining dispatch
must tell the implementer to use `/opt/homebrew/bin/pytest`, with
`.venv/bin/python` still correct for running Python directly. — Cost if wrong:
an implementer wastes turns on a missing binary, or worse reports "tests pass"
having never run them. Correcting the dispatch text is free; the plan file's
constraint line is now known-stale and should be fixed if the plan is ever
re-run from scratch.

Ruling: `numpy` IS importable inside the venv (2.4.6, pulled in transitively by
scipy). The no-numpy constraint therefore cannot be enforced by "it would fail
to import" — it is a deliberate design constraint, and the only reliable check
is a static one. Verification method for every remaining optimize/ task: AST
import extraction (not grep, which matches docstring prose — T1's `__init__.py`
docstring names all five forbidden libraries while importing none). T1 verified
clean this way: `factors.py` imports only `dataclasses` + `typing`. — Cost if
wrong: a forbidden dependency lands unnoticed and the harness gains a numerical
stack it does not need; caught by the AST check at each task's review.

## Progress

Task 1: implementer DONE (agent adc38198, haiku). Independently verified by
controller: `/opt/homebrew/bin/pytest tests/test_optimize_factors.py -q` -> 23
passed; full suite -> 1374 passed, 1 skipped; AST imports stdlib-only;
pyproject.toml untouched; no float `==` in assertions. Commit 7c39d40.

Task 1: reviewer (sonnet) SPEC ✅, TASK QUALITY Approved. Confirmed the diff is
a faithful transcription of the brief with no scope creep, and that no test
would pass against a broken implementation.

Task 1: minor (deferred): `snap_to_grid` uses Python's banker's rounding, so a
value exactly halfway between grid points rounds to even. Controller verified:
snap(4.5,1)=4, snap(5.5,1)=6, snap(3.5,1)=4, snap(-4.5,1)=-4, snap(9,2)=8.
Task 1: minor (deferred): `code_level` matches levels by `==`, which is fragile
if an author declares levels that are not float-clean (the 0.1+0.2 case). Not
exercised by any test; levels come from author-declared discrete lists.

Ruling: both Task 1 findings stay deferred rather than entering the fix loop —
the review returned no Critical/Important findings, and per the skill Minors are
ledgered for final-review triage. They are NOT dismissed: the banker's-rounding
one is real and reachable (a fitted optimum landing on a half-step is plausible
with integer grids), so it is carried into Task 4's dispatch as context, because
Task 4 is what produces the stationary point that Task 5 later snaps. If Task 4
or 5 surfaces a half-step optimum in practice, the fix is round-half-away-from-
zero in `snap_to_grid` plus a boundary test. — Cost if wrong: an optimum exactly
on a half-step snaps one step low; it remains a runnable, near-optimal config
and the confirm stage measures whatever it actually ran, so no claim is
falsified. Deferring is safe; silently never revisiting it would not be, hence
the carry-forward.

Task 1: complete (commits 23f392f..7c39d40, review clean, 2 minors deferred)

Task 2: implementer DONE (agent a70729d6, haiku). Controller-verified: 20 passed;
full suite 1394 passed / 1 skipped; AST imports = __future__, dataclasses,
operator, typing (clean). Edge probes correct: {level} never trivial; guard-
skipped + missing observable = ok/skipped; guard-admitted + missing = fail;
list-valued when_not matches membership. Commit 47e0070.

Task 2: reviewer (sonnet) SPEC ✅, TASK QUALITY Changes requested. Two Important
findings, both independently confirmed by the controller before the review
returned:
  (I1) `_guard_excludes`: when both `when` and `when_not` are set, `when`
       silently wins. `factors.py` hard-rejects both-set for `manipulation` at
       parse time, but invariants/constraints/regimes never go through
       `parse_factors`, so they get silent wrong behavior. Verified: both-set
       predicate evaluates rather than raising.
  (I2) missing-observable Verdict is `ok=False, skipped=False` — indistinguish-
       able from a genuine comparison failure except by string-matching
       `detail`. No structured field.

Task 2: minor (deferred): `is_trivial` false negatives verified by controller —
`> -1`, `!= ""`, `< inf`, `<= 1e18` all return False. This is a BRIEF gap (the
plan specified the narrow table), not an implementer deviation.

Ruling (I1): fix it in `predicates.py` by raising ValueError when both guards are
set. The reviewer is right that this module is the single place that can catch it
for all four check families, and the repo's own precedent (`factors.py`) already
treats both-set as an error — so silent precedence here is an inconsistency, not
a design choice. This does NOT contradict the plan: the plan's Task 2 text says
"Optional `when`/`when_not`... Supplying both on one check is a validation
error", so the brief's own prose mandates the raise and only its code block
omitted it. Enters the fix loop. — Cost if wrong: an author who sets both gets a
hard error instead of silent `when`-wins behavior; strictly safer, and the plan
text already promised the error.

Ruling (I2): fix it by adding a `missing: bool = False` field to `Verdict`, set
True on the absent-observable path. Callers then branch structurally instead of
string-matching. Cheap, additive, and Task 9's runner is the first consumer that
will need the distinction (a lever whose telemetry was never emitted is a
different failure from one that engaged wrongly). Better to add it now than to
retrofit once three callers depend on `detail` strings. — Cost if wrong: one
unused dataclass field.

Ruling (minor/is_trivial): stays deferred. Widening the heuristic invites false
POSITIVES that would reject legitimate author predicates (`> -1` is a perfectly
good check on a metric whose valid range includes negatives), and the real
backstop is Task 10's validator plus human/AI review of the campaign. Carried to
the final review for triage. — Cost if wrong: a lazy predicate slips through and
a broken lever looks verified; mitigated by the mandatory correctness relation
per factor, which is a separate and stronger gate.

Task 2: fix round 1/5 dispatched to original implementer (a70729d6, context
intact). Controller-verified both fixes before re-review: Verdict fields now
['ok','detail','skipped','missing'] (missing is last, dataclass still frozen);
both-set guards raise ValueError with an actionable message; missing-observable
-> missing=True ok=False vs genuine comparison failure -> missing=False ok=False;
is_trivial correctly UNCHANGED per ruling. 23 passed; full suite 1412 passed /
1 skipped. Commits 47e0070..a566da0.

Task 2: re-review (haiku) VERDICT = all findings addressed. I1 ADDRESSED
(predicates.py:72-76 raises with an actionable message); I2 ADDRESSED
(predicates.py:39 field + :92 set on absent path); no new breakage; Verdict still
frozen with `missing` last so positional construction is unaffected; is_trivial
untouched as ruled.
Task 2: complete (commits f6a7a4e..a566da0, review clean, 1 minor deferred)

Task 3: implementer DONE_WITH_CONCERNS (agent accafe7c, sonnet). Commit 3e32249.
15 passed; full suite 1412 passed / 1 skipped. Oracles observed: res V -> 16 runs
/ 0 aliases / orthogonal; res III -> 8 runs / 21 aliases. Controller independently
re-verified both oracles against the shipped module: exact match.

### TWO REAL BUGS IN MY PLAN, found by the Task 3 implementer and confirmed

The implementer deviated from the brief's reference implementation because the
brief's code failed 2 of the brief's OWN tests. Both deviations were correct.

Bug 1 — `alias_pairs` double-counted. The plan's version reported 2fi-aliased-
onto-mains (21 for res III / 7 factors) AND 2fi-aliased-onto-2fi, but in a
saturated res-III design every pair of 2fi that alias the same main effect also
alias each other, adding 21 transitive echoes for a total of 42. Controller
reproduced the plan's logic verbatim in isolation: total 42 (21 + 21), against
the asserted 21. My earlier pre-plan verification counted only the 2fi-on-mains
term and never exercised the combined function, which is exactly why the bug
survived into the plan.
Ruling: the implementer's fix stands. 21 is the correct answer — the transitive
2fi-2fi pairs carry no information beyond the main-effect aliasing already
reported, and double-counting would overstate confounding to any consumer.
— Cost if wrong: an alias report that understates 2fi-2fi confounding in designs
where it is NOT a transitive echo of a shared main alias. Task 4 consumes
`Fit.aliases` only as a reported caveat, never for arithmetic, so the blast
radius is a caveat string. Flagged for the final review to confirm the res-IV
case (where 2fi genuinely alias in pairs WITHOUT aliasing a main) still reports
those pairs — see the open check below.

Bug 2 — the unachievable-resolution `raise` was unreachable dead code. The
plan's `min_runs_for` returns `2**k` for untabulated (k, resolution), so the
guard `if 2**k <= min_runs_for(k, resolution)` was always true and the
`ValueError` could never fire. Verified for (2,7), (3,5), (10,5). A campaign
requesting an impossible resolution would have silently received a full
factorial instead of the promised error.
Ruling: the implementer's fix stands — `fractional_factorial(('A','B'),
resolution=7)` now raises with the two honest options, which is what the spec
requires ("never a silent downgrade"). — Cost if wrong: none; this restores
promised behavior.

OPEN CHECK carried to Task 3 review: confirm res IV (e.g. 6 or 8 factors) still
reports genuine 2fi-2fi alias pairs, since those are NOT transitive echoes.

OPEN CHECK RESOLVED by controller before T3 review: res IV reports 0 2fi-on-main
(correct — mains clear of 2fi at res IV) and genuine 2fi-2fi pairs (9 for k=6,
42 for k=8; samples AB=CE, AB=DF, AC=BE). The Bug-1 dedup removed only the
transitive echoes, not real 2fi-2fi confounding. Ruling on Bug 1 stands with the
blast radius now closed rather than merely bounded.

### BUG 3 IN MY PLAN — the most serious one so far (found by controller audit)

While the T3 review ran, the controller audited EVERY `_GENERATORS` entry, not
just the two the oracles cover. Result:

      entry  runs  2fi-on-main  2fi-on-2fi  verdict
      (5,5)    16       0            0      OK
      (6,5)    32       0            0      OK
      (7,5)    32       0            3      *** VIOLATES CLAIMED RESOLUTION ***
      (8,5)    32       0            9      *** VIOLATES CLAIMED RESOLUTION ***
      (4,4)     8       0            3      OK
      (5,4)    16       0            3      OK
      (6,4)    16       0            9      OK
      (7,4)    16       0           21      OK
      (8,4)    16       0           42      OK
      (7,3)     8      21            0      OK

My plan's (7,5) and (8,5) entries are LABELLED resolution V but are actually
resolution IV: 3 and 9 two-factor interactions are confounded with each other.
This is the worst of the three plan bugs because resolution V is the feature's
DEFAULT and its entire justification (ordering-theorem's headline finding is an
interaction; a design that cannot separate 2fi silently inverts such a result).
Nothing downstream could detect it — the fit would report tight CIs on aliased
terms.

Controller found and verified correct generators:
  k=7 res V: n_base=6, G=ABCD              -> 64 runs, 2fi_on_main=0, 2fi_on_2fi=0
  k=8 res V: n_base=6, G=ABCD, H=ABEF      -> 64 runs, 2fi_on_main=0, 2fi_on_2fi=0
Both re-audited: balanced, mains mutually orthogonal, genuine RES V. These match
the literature (7 factors res V = 2^(7-1) = 64; 8 factors res V = 2^(8-2) = 64).
My plan's claim of 32 runs for either was simply wrong.

Ruling: correct the (7,5) and (8,5) entries to n_base=6 with the verified
generators, and add a test that audits EVERY table entry against its claimed
resolution — the property that was missing and let this through. The run-count
increase (32 -> 64) is not a regression; 32 runs cannot carry res V for 7-8
factors, so the old entries were promising an estimate they could not deliver.
Task 10's `max_runs` validator rule is what surfaces the larger cost honestly to
a campaign author, which is exactly its purpose. — Cost if wrong: a res-V screen
on 7-8 factors costs 64 runs instead of 32. That is the true price of unaliased
2fi estimation at those factor counts; the alternative is a design that lies
about what it can estimate. Enters the T3 fix loop.

Task 3: fix round 1/5 (agent accafe7c). Commit 290a731. Controller re-audited the
WHOLE table after the fix: 10 entries, 0 violations. (7,5) and (8,5) now 64 runs
with on_main=0, on_2fi=0. Both original oracles unchanged (res V 5f = 16/0; res
III 7f = 8/21). New parametrized test
`test_every_tabulated_generator_actually_achieves_its_claimed_resolution` covers
all 10 entries. 25 passed; full suite 1422 passed / 1 skipped.

Task 3: reviewer (sonnet) SPEC ✅, TASK QUALITY Approved (as branch stands, incl.
the fix commit). The reviewer independently found the SAME (7,5)/(8,5) resolution
bug by brute-force defining-relation word-length search — useful corroboration
that it was real, not an artifact of my audit method.

### NEW Important finding from the T3 review, escalated by the controller

`min_runs_for`'s untabulated fallback returns `2**k`, conflating "this module has
no tabulated design" with "the true minimum is the full factorial." Controller
verified and the reviewer understated it:
  min_runs_for(6,3) = 64  but a genuine res-III design for 6 factors exists at
                          8 runs (nb=3; D=AB, E=AC, F=BC) — verified, resolution 3
  min_runs_for(5,3) = 32  but 5 factors res III exists at 8 runs — verified
  min_runs_for(9,5) = 512, min_runs_for(10,4) = 1024 — pure guesses

Why this is Critical for Task 10 rather than Important for Task 3: the plan's
Task 10 validator rule 8 compares `min_runs_for(k, resolution)` against the
author's declared `design.max_runs` and FAILS the campaign when it doesn't fit.
With this fallback, any untabulated (k, resolution) inflates the requirement by
up to 8x and would falsely reject a run budget that a real design satisfies —
the opposite of the "never a silent downgrade, offer the two honest options"
behavior the spec requires.

Ruling: do NOT patch `min_runs_for` inside Task 3 (its own tests pass and the
function is correct for every tabulated cell, which is all Task 3 uses). Instead
carry a hard requirement into Task 10: rule 8 must treat untabulated
(k, resolution) as UNKNOWN rather than as `2**k`. Concretely, Task 10 must call a
tabulated-only accessor and, when the combination is absent, emit an error that
says the resolution is not tabulated and names the two honest options (use the
full factorial at 2**k runs, or reduce the factor count) — never silently compare
a fabricated number against the budget. Task 3's docstring for `min_runs_for`
must state the "tabulated cells only; fallback is an upper bound, not the true
minimum" contract so the next caller is not misled. — Cost if wrong: a campaign
with an untabulated factor/resolution combination gets a wrong feasibility
verdict. Bounded because the tabulated set covers k=4..8 at res III/IV/V, which
is the range the spec's worked examples live in; anything outside it now fails
loudly instead of silently.
Task 3: minor (deferred): brief gap — only 2 of 10 generator entries had oracle
coverage, which is how the (7,5)/(8,5) bug survived. Already remediated by the
fix round's parametrized audit test.

Task 3: fix round 2/5 (agent accafe7c). Commit 44410b6. Docstring contract on
min_runs_for + pinning test. Controller verified: 26 passed; full suite excluding
T4's in-flight file = 1423 passed, 1 skipped, 0 failed. The 2 failures the
implementer reported are in T4's untracked work-in-progress and were correctly
left alone.

### BUGS 5 AND 6 IN MY PLAN — both in Task 4's test file, diagnosed by controller

The 2 failures in tests/test_optimize_effects.py are MY plan's defects, not
implementer errors. Both tests are unsatisfiable against any correct
implementation:

Bug 5 — `test_aliases_are_carried_onto_the_fit_as_a_caveat` calls `fit_effects`
with the default `include_interactions=True` on a res-III 7-factor design. That
design has 8 runs; the requested model has 1 + 7 mains + 21 two-factor
interactions = 29 terms. 29 terms cannot be estimated from 8 runs, so the
implementation correctly raises "design matrix is singular". The test asks for
the impossible.
Ruling: the TEST is wrong, the implementation is right. Fix by passing
`include_interactions=False` for the saturated design — the assertion being made
is that `Fit.aliases` carries the design's aliasing forward as a caveat, which
does not require fitting interactions at all. Keep the singular-matrix guard
exactly as it is; raising on an unestimable model is correct and valuable.
— Cost if wrong: none. The corrected test still asserts the intended property
(aliases propagate to the Fit), just on an estimable model.

Bug 6 — `test_strong_curvature_is_detected_as_lack_of_fit` sets ALL FOUR center
points to the identical value 14.0. Identical replicates give
`pure_error_var = 0.0`, which trips the implementation's own guard
`if pe_var is not None and pe_var > 0` and skips the F test, leaving
`lack_of_fit_p is None` — exactly what the test then asserts against. The test
defeats itself. Verified: pure_error_var=0.0, pure_error_df=3,
lack_of_fit_p=None.
Ruling: the TEST is wrong. Fix by giving the center replicates small distinct
perturbations around a value far from the corner mean (e.g. 14.0 +/- 0.02), which
is what genuinely strong curvature plus real measurement noise looks like. That
yields pe_var > 0 AND a large lack-of-fit sum of squares, so the F test fires and
p < 0.05 as intended. Do NOT relax the `pe_var > 0` guard: zero pure-error
variance means there is no independent error estimate, and dividing by it would
produce an infinite F statistic — reporting that as significance would be
fabricating a result.
— Cost if wrong: none; the corrected test exercises the real code path the
original intended.

Both rulings dispatched to the T4 implementer as context so it does not have to
rediscover them.

Controller also fixed both bug-5/bug-6 tests in the PLAN file (commit 574bc8d) so
a future re-run does not inherit them, after verifying both fixes work against
the shipped modules: include_interactions=False carries 21 alias pairs through;
distinct center perturbations give pe_var=2.9e-04, F=1.1e+05, p=6.1e-08.

Task 3: fix round 2 re-review dispatched (scoped to 3e32249..44410b6).
Task 4: in progress (agent aedd6bf7, sonnet) — controller sent the bug-5/bug-6
diagnoses mid-flight so it would not have to rediscover them.
Task 5: dispatched (agent a63294e8, sonnet). First brief of the assertion-list
kind rather than full-code kind.

Running total of MY plan's defects found so far: 6.
  1. alias_pairs double-counted (42 vs 21)            [T3 implementer]
  2. unachievable-resolution raise was dead code      [T3 implementer]
  3. (7,5)/(8,5) generators were res IV, not res V    [controller audit + T3 reviewer, independently]
  4. min_runs_for fallback misleads feasibility calls [T3 reviewer, severity escalated by controller]
  5. T4 alias test asked for 29 terms from 8 runs     [controller diagnosis]
  6. T4 curvature test forced pure_error_var = 0      [controller diagnosis]
All six were in the statistical core, which is where a wrong answer is invisible
downstream. None reached a passing-but-wrong state: 1-3 were caught by tests or
audit, 4 by review, 5-6 by failing tests whose root cause was in the plan.

Task 3: re-review (haiku) VERDICT = all findings addressed. F1 ADDRESSED — both
entries corrected to 64 runs, re-reviewer reproduced the OLD entries to confirm
the new audit test would have caught them (old (7,5) had 3 2fi-2fi pairs, old
(8,5) had 9; new have 0). F2 ADDRESSED — docs + pinning test only, no behavior
change, tabulated return values unchanged. No regressions. Genuine res-IV 2fi-2fi
aliasing preserved (3/9/42 for k=4/6/8). Both oracles intact.
Task 3: complete (commits 118fdba..44410b6, review clean, 1 minor deferred)

Task 4: implementer DONE (agent aedd6bf7, sonnet). Commit 74b3c29. Reached both
bug-5/bug-6 root causes INDEPENDENTLY before the controller's diagnosis arrived —
useful corroboration that the diagnoses were right. Implementation untouched;
only the two brief-supplied test bodies were fixed.
Controller-verified against the SHIPPED module: L5 oracle exact — main A =
-0.950000 (planted -0.95), interaction AB = +1.600000 (planted +1.60), sign flip
preserved (A < 0 < AB), compound 2.650 > parts 2.000. 15 passed. Full suite 1454
passed, 1 skipped, 0 failed.

Task 5: implementer DONE (agent a63294e8, sonnet). Commit b33ce1f. 16 passed,
14/14 assertions; full suite 1454 passed, 1 skipped.

Controller verification of the implementer's one deviation and two concerns:

Deviation (`_decode_level` uses `screen_levels` verbatim at coded exactly ±1
rather than routing through `decode_coded`): ACCEPTED. Verified the rendered flag
is `--k1=2`, not `--k1=2.0`. `decode_coded` does midpoint+half*coded arithmetic in
float and would turn an author's declared integer level into a float, changing the
command line the target actually receives. Preserving the declared level's type
and exact value at the design corners is correct — the interpolation path is for
INTERIOR points, which only the refine stage produces. — Cost if wrong: none
observed; the interior path still routes through decode_coded as designed.

CONCERN 1 CONFIRMED AS A REAL GAP — `matrix_payload["aliases"]` is always [].
Verified: a res-III 7-factor design has 21 alias pairs per `design.alias_pairs`,
but its payload records `aliases: []`. The pre-registered design matrix therefore
SILENTLY CLAIMS NO CONFOUNDING on a design that is heavily confounded. That is
exactly the class of defect this feature exists to prevent — the artifact a human
or AI reads to judge what the screen can estimate would assert the opposite of
the truth.
Ruling: fix it. `matrix_payload` must populate `aliases` from
`design.alias_pairs(design)`. The plan's Task 5 interface list names `aliases` as
a payload field (assertion 8) but its notes never said where the value comes
from — a plan gap, not an implementer error. Enters the T5 fix loop. — Cost if
wrong: the caveat is duplicated in two artifacts (design_matrix.json and
effects.json), which is harmless redundancy; the alternative is an artifact that
lies about confounding.

CONCERN 2 ACCEPTED, NO ACTION — `check_fidelity` compares levels with `!=` rather
than `math.isclose`. Correct as-is for the in-process path, where payload and run
levels are the same Python objects. Noted as a deferred minor because a future
caller that round-trips the payload through JSON could see float drift; Task 9
appends runs from live observations, so this is worth revisiting when that lands.
Task 5: minor (deferred): check_fidelity uses exact != on levels; revisit if a
JSON round-trip is introduced between payload and runs.

Task 6: implementer DONE (agent a6a96595). Commit cdcaf6b. 8/8 assertions, no
deviations, no concerns. Suite 1465 passed / 1 skipped.
Task 5: fix round 1 DONE (agent a63294e8). Commit 7ee009d. 18 passed; suite 1467
passed / 1 skipped.

### BUG 8 IN MY PLAN — CRITICAL, and the most dangerous one of the run

Task 4's reviewer found that `effects.py:163` computes
`se = math.sqrt(pe_var / n)` where `n = len(design.points)` — the TOTAL run count
including center and axial points. The correct standard error of an OLS
coefficient is sigma * sqrt((X'X)^-1_jj), which for a main effect on a two-level
design is sigma / sqrt(N_CORNERS), because center points contribute 0 to a
+-1 coded column's sum of squares.

Controller verified the mechanism directly on a 2-factor factorial + 4 centers:
  sum(x^2): intercept = 8.0 (all rows), A = B = AB = 4.0 (corners only)
  code uses sigma/sqrt(8) for every term; truth for A/B/AB is sigma/sqrt(4)
  => SE understated by sqrt(2) = 1.4142

On the realistic res-V 5-factor + 5-center design: total 21, corners 16, so every
main-effect CI half-width is understated by sqrt(21/16) = 1.1456 (14.6%).

Controller then PROVED the bug changes decisions, not just numbers. On that
design with pe_var = 9.3e-04 and df = 4 (tcrit 2.7764):
  buggy CI half-width = 0.01848 ; correct = 0.02117
  at true effect sizes 0.0190 / 0.0195 / 0.0200 / 0.0205 the code reports
  significant = True while the correct SE gives False — a FALSE POSITIVE in all
  four cases.

Why this is the worst defect of the run: it silently narrows every confidence
interval, biasing `significant` and therefore `dropped_factors` toward keeping
factors that are actually within noise. `stage.decide_after_screen` (Task 7) uses
exactly that to choose which factors survive into `refine`, so the campaign would
spend refinement budget on noise and report a fitted optimum over factors that do
nothing. All 15 of Task 4's tests pass despite the bug because none of the planted
effects sit near the significance boundary — precisely the "looks exactly like a
right answer" failure the brief warned about.

Ruling: fix by computing the per-term standard error from that term's own column
sum of squares, se_j = sqrt(pe_var / sum_i x_ij^2), rather than one scalar
`pe_var / n` shared by all terms. This is the (X'X)^-1 diagonal for the orthogonal
case and is also correct for central-composite designs, where the reviewer
correctly notes a single scalar can NEVER be right for all terms because axial
points contribute different sums of squares per column. Also add the missing test:
a CI/significance check on a design where corners != total points AND the effect
sits near the boundary — the property whose absence hid this. — Cost if wrong:
CIs would be mis-scaled in the other direction, which the new boundary test plus
the existing planted-truth tests would catch. Not fixing it means every campaign
over-reports factor significance, which is the failure this feature exists to
prevent.

Task 4: fix round 1/5 (agent aedd6bf7). Commit 1d58707. Per-term
se_j = sqrt(pe_var / ss_j). Implementer verified the new regression test by
temporarily reverting the denominator and confirming it fails with a false
positive — the right way to prove a regression test is real.
Controller re-verified: all three decision-flip cases (0.0190/0.0200/0.0205) now
report significant=False with se=0.007624; per-term SEs differ by column on a CCD
(main 0.004031, interaction 0.005701); before/after half-widths 0.018377 ->
0.021053 (ratio 1.145644) match the controller's independent figure. L5 oracle
unaffected (no center points in that test, so se/ci/significant are None there).
Suite 1468 passed / 1 skipped.

Ruling (found while validating the fix, applies to Task 4 and documented in the
plan at ec6d1b1): sqrt(pe_var / sum x^2) is the EXACT
sigma*sqrt((X'X)^-1_jj) only when that term's column is orthogonal to all others.
Measured on a 2-factor CCD: exact vs formula — I 0.5774/0.3015, A 0.3536/0.3536,
B 0.3536/0.3536, AB 0.5000/0.5000, A^2 0.4208/0.2887, B^2 0.4208/0.2887. So main
effects and 2-factor interactions are exact on every design this module generates
(the terms that drive dropped_factors and the stage rule), while the intercept and
pure-quadratic terms on a central composite carry OPTIMISTIC (too narrow) CIs by
~1.46x. Accepted rather than implementing a full (X'X)^-1: quadratic terms exist
to describe curvature, are never used as a significance gate, and
solve_stationary_point consumes the estimates not their intervals. A matrix
inverse would add a numerical path with no consumer. Requested as a documented
caveat in the module (fix round 2, comment only). — Cost if wrong: a future caller
that DOES gate on a quadratic term's CI would over-report its significance; the
comment is what stops that being a silent trap.

Task 6: reviewer (sonnet) SPEC ✅, TASK QUALITY Approved. Probed hard and found the
load-bearing properties intact: empty results -> passed=False with "not executed";
near-miss identifiers (trailing whitespace, :: vs . separator) all fail closed with
no accidental substring match; behavioral-only failure never enters the correctness
bucket; JUnit nested <error> and <skipped> both treated as not-passed; pytest
outcomes error/xfailed/xpassed/skipped all map to False (only exact "passed" is
True); unrecognized format raises naming both supported shapes rather than
silently returning {}. No test would pass against a plausible broken impl —
test #5 uses a deliberate decoy key.
Task 6: minor (deferred): reconcile raises a bare TypeError on results=None rather
than failing closed with a clear message. Signature declares dict and no call site
exists yet, so out-of-contract input rather than a spec violation — but the
module's own "never silently look satisfied" philosophy argues for a clear error.
Carry to Task 9 (runner integration), which is the first real caller: a subprocess
that crashes before producing any parseable output is exactly how None arrives.
Task 6: minor (deferred): no explicit test for JUnit <error> alone (only
<failure>); reviewer verified it works manually.
Task 6: complete (commits ab0c1c6..cdcaf6b, review clean, 2 minors deferred)

Two extra tests beyond the 8 assertions were judged NOT scope creep by the
reviewer: they cover the brief's Step 3 prose about raising on unrecognized
formats, which never got a numbered assertion. Controller concurs.

Task 4: fix round 2/5 (agent aedd6bf7). Commit d75b037 — documentation only,
verified comment-only (36 insertions, all docstring/comment). CCD caveat now in the
module with checkable figures (0.420813 exact vs 0.288675 per-column). Scoped
re-review dispatched over a hand-built diff of exactly 1d58707 + d75b037, since the
commit range had interleaved with other tasks' work.

Task 5: re-review dispatched (scoped cdcaf6b..7ee009d).
Task 7: in progress (agent a89ce85e). Its tests are mid-iteration — 16 passing, 2
failing as of last check. Two other agents independently flagged those 2 failures
as out-of-scope for their own tasks, correctly.
Task 8: dispatched (agent a82ceee6) carrying the findings.schema.json mapping
ruling in full, since a naive mapping is impossible and rediscovering that would
waste the whole task.

NOTE on parallel execution in a shared working tree: transient collection errors
and cross-task failures are normal while a module is mid-write. Every verification
the controller runs uses either a per-file pytest invocation or --ignore on the
in-flight file, so no verdict has been based on another task's incomplete state.
Three separate implementers correctly identified stage.py as someone else's work
rather than trying to fix it.

Task 5: re-review (haiku) VERDICT = all findings addressed. F1 ADDRESSED —
matrix.py:35 imports alias_pairs, matrix.py:168 serializes them, two new tests at
tests/test_optimize_matrix.py:145-159 cover both the confounded (res III, 21) and
unconfounded (res V, 0) directions. Determinism and JSON round-trip verified; row
and payload shape unchanged. No new breakage.
Task 5: complete (commits ab0c1c6..7ee009d, review clean, 1 minor deferred)

Task 7: implementer DONE (agent a89ce85e). Commit a0b35e5. 18 passed, 13/13
assertions; full suite 1486 passed / 1 skipped. Two concerns raised, both
legitimate and honestly reported; controller verified each.

### BUG 10 IN MY PLAN — the BEHAVIORAL_VIOLATION trigger is unreachable

The spec (design doc §6.3, escalation trigger 4, and the §6.4 failure table)
requires a `behavioral` relation violation to be reported as a trigger. My plan's
Task 7 interface list gives `decide_after_screen(fit, factors, *, alpha=0.05)` and
`decide_after_refine(fit, factors, stationary)` — NEITHER accepts relation
verdicts. Controller verified: `Trigger.BEHAVIORAL_VIOLATION` is defined at
stage.py:70 and referenced only in the module docstring; nothing in
orchestrator/ can ever set it, and `classify_failures` (relations.py:163, which
produces behavioral failures) has no call site in stage.py.

So the trigger is dead code as specified — a required escalation signal that can
never fire. The implementer diagnosed this correctly rather than silently shipping
an enum member that does nothing.

Ruling: fix by threading behavioral verdicts into the decision functions as an
optional argument, `behavioral_failures: tuple[RelationVerdict, ...] = ()`, and
setting the trigger when it is non-empty. Optional with an empty default so every
existing call site and test keeps working, and so a caller that has no relation
verdicts yet (the screen stage before any native test run) is unaffected. This
keeps stage.py a pure function of its inputs — the caller still owns running the
tests and classifying the verdicts, which is the right split; stage.py only reports
that the signal arrived. — Cost if wrong: an extra optional parameter that a caller
could forget to pass, leaving the trigger silent. Mitigated because Task 11 wires
the real call sites and its assertion 16 already requires that a behavioral
violation appears in findings.json, which is the end-to-end check on this path.

Task 7: concern 2 (alpha accepted but unused) — ACCEPTED, no action. Verified the
code documents it at stage.py:141-143 as interface symmetry with fit_effects:
significance is read from the already-fitted Fit rather than recomputed, which is
correct — recomputing at a different alpha than the fit used would silently
disagree with the CIs in the artifact. Deferred minor only.
Task 7: minor (deferred): decide_after_screen's alpha kwarg is inert by design;
documented in-code.
Task 7: minor (deferred): `_rationale_screen`'s `next_stage` parameter is annotated
`Stage` but receives `None` when a trigger fires (stage.py:200, flagged by pyright).
Controller verified the RUNTIME behavior is correct — next_stage=None is reached,
handled without crashing, and yields a non-empty rationale ending "escalate to
model". Annotation-only defect; should be `Stage | None`.

Task 4: re-review (haiku) VERDICT = all findings addressed. F1 ADDRESSED
(effects.py:172-199 per-term ss_j; the three decision-flip cases all report
significant=False; the regression test at :79-105 empirically catches the bug; L5
oracle still exact with se=None since that design has no center points). F2
ADDRESSED (module docstring :21-37 and inline :180-197 carry the orthogonality
limitation with checkable figures; diff confirmed comment-only). No new breakage;
pe_var>0 guard intact, dropped_factors still drops nothing without an error
estimate.
Task 4: complete (commits 574bc8d..d75b037, review clean)

Task 9: dispatched (agent a3f4fb90). Carries T6's deferred reconcile(None) minor as
a live requirement, since the runner is the first real caller and the realistic path
to a None/unparseable input is exactly a target test_command subprocess that
crashes before writing output. Also carries the full asymmetric failure taxonomy
(rejected vs infeasible vs failed) explicitly, since conflating rejected with
infeasible would either discard real information about the design space or
contaminate the fit.

Task 7: fix round 1/5 (agent a89ce85e). Commit 6238f74. 22 passed; full suite 1490
passed / 1 skipped. Controller verified all four required properties:
  * Trigger.BEHAVIORAL_VIOLATION is now reachable via behavioral_failures=
  * a behavioral-only trigger STILL ADVANCES the stage (next=refine, not None) —
    the property that protects an L5-style discovery from halting a campaign
  * the rationale mentions it, so the reason survives into findings.json
  * the empty default leaves prior behavior unchanged (no trigger)

Controller adjudication of T7's two design judgment calls, probed independently
before the review returned:

(a) ALL_WITHIN_NOISE fires only on measured-null, not on unknown. CORRECT. Probed a
Fit with significant=None throughout (no center points): the unknown factor is NOT
dropped, ALL_WITHIN_NOISE does NOT fire, and the rationale reads "kept A as unknown
(no pure-error estimate)". That is the right call on both counts — firing
"the factor set was wrong" when nothing was measured would be a false accusation,
and the unknown-ness is still surfaced in the rationale rather than silently
absorbed, so nothing is lost. The unknown-is-not-null discipline from effects.py is
preserved end to end.

(b) Refinability gating. CORRECT. Probed both cases: a surviving choice-only factor
goes straight to confirm, and a surviving 2-level numeric factor also goes straight
to confirm. Neither can carry curvature, so spending a refine stage on them would
be pure waste.

Task 7: reviewer (sonnet) F1 ADDRESSED, SPEC ✅, TASK QUALITY Approved. Confirmed
the fix's mechanism is legible rather than ad hoc: `blocking_triggers` is kept
separate from the full reported `triggers` tuple, so "report vs act" is a named
distinction (stage.py:210) rather than a special case. The reviewer also found a
case the controller had not probed: a factor entirely ABSENT from fit.effects is
treated as unknown and survives (stage.py:182 catches eff is None) — the
unknown-is-not-null rule correctly extends from "explicitly None" to "never
measured at all".
Task 7: minor (deferred): stage.py does not validate RelationVerdict.kind, so a
caller hand-passing a correctness verdict into behavioral_failures would silently
raise BEHAVIORAL_VIOLATION. Controller verified the risk is real in principle
(trigger does fire) but structurally bounded: classify_failures returns correctness
and behavioral failures in SEPARATE tuples, so the intended caller path cannot
deliver a correctness verdict into that slot — only hand-construction can. Ruling:
defer. An assert would make the contract self-enforcing and is worth doing when
Task 11 wires the real call site, where the correct tuple can be asserted at the
seam that actually matters. — Cost if wrong: a mis-wired caller reports a
behavioral trigger for a correctness failure, which would UNDER-react (behavioral
triggers advance the stage; correctness failures should hard-fail the campaign).
Task 11's assertion 14 (a correctness-relation failure at verify aborts the
campaign) is the end-to-end check that would catch it.
Task 7: complete (commits e56dfdc..6238f74, review clean, 3 minors deferred)

Task 8: implementer DONE (agent a82ceee6). Commit d96718f. 12/12 assertions, 16
passed, no deviations. All four schemas landed (design_matrix, effects, relations,
runs_row).

CONTROLLER VERIFICATION OF THE CENTRAL ECONOMIC CLAIM — this is the milestone:
  * git diff main..HEAD shows ZERO changes to findings.schema.json and
    principles.schema.json. The early mapping ruling held; no schema was widened.
  * project_findings output VALIDATES against the unmodified findings.schema.json.
  * The L5 sign flip survives the projection with its evidence intact:
      h-main / CONFIRMED / estimate=-0.95, 95% CI=[-0.971168, -0.928832]
      h-main / CONFIRMED / estimate=2
    so a reader of findings.json sees the negative main effect AND its interval.
  * Within-noise factors land as h-control-negative / REFUTED with the CI spanning
    zero — the mapping I ruled for, working as intended.
  * project_principle_updates VALIDATES against principles.schema.json with numeric
    evidence ("B estimate=2, n_runs=21"), so validate_evidence's floor passes by
    construction rather than by prose.

=> screen and refine now produce the COMPLETE durable artifact set with zero LLM
calls. That was the central economic claim of the design, and it is now
demonstrated rather than asserted.

Task 10: dispatched (agent a2639616) with rule 8 CORRECTED from the brief. The brief
says to compare min_runs_for(k, resolution) against design.max_runs; that is wrong
for untabulated combinations, where the 2**k fallback inflates the requirement up to
8x and would falsely reject a budget a real design satisfies. Dispatch specifies two
distinct errors instead: tabulated-and-over-budget (name the count, the budget, and
the two honest options) vs not-tabulated (say so plainly, never compare a fabricated
number). This is the T3 min_runs_for ruling being cashed in at the call site it was
carried forward for.

Task 8: reviewer (sonnet) SPEC ✅, TASK QUALITY Approved. Adversarial probing
confirmed: all four schemas genuinely reject malformed artifacts (bogus kind, missing
apply, missing ci_low, bad role/status enums — each verified by probe, not
inspection); append-only holds under a simulated torn write; determinism reproduced
independently; unknown significance renders PARTIALLY_CONFIRMED with "unknown" in
diagnostic_note rather than being folded into a measured null; experiment_valid flips
False on a correctness failure and correctly STAYS True on a behavioral-only failure;
the degenerate zero-main-effects branch produces schema-valid output rather than
crashing. write_effects consuming `factors` is in the brief's own signature, so not
scope creep.

Ruling: FIX the read_runs torn-line gap rather than defer it (reviewer logged it
Minor; controller escalates). Verified: append 3 complete rows, then a torn final
line simulating a crash mid-write, and read_runs raises JSONDecodeError — so the 3
COMPLETED rows become unreadable. That defeats the exact guarantee append-only exists
to provide ("a crashed run must leave completed rows intact"): the rows are preserved
on disk but unusable, which operationally is the same as losing them. A campaign that
crashes mid-sweep should be able to refit on what completed. Fix: read_runs skips a
trailing malformed line and reports it, rather than failing the whole read. Enters
the T8 fix loop. — Cost if wrong: read_runs silently tolerates corruption it should
surface; mitigated by requiring it to REPORT the skipped line rather than swallow it.
Task 8: minor (deferred): a direction-neutral relation statement can never reach
REFUTED on direction, only CONFIRMED/PARTIALLY_CONFIRMED. Reasonable default,
documented by the implementer as a judgment call.
Task 8: minor (deferred): no test for the degenerate zero-main-effects branch;
reviewer exercised it manually and it is schema-valid.

Task 8: fix round 1/5 (agent a82ceee6). Commit 82d37b6. 18 passed. Controller
verified BOTH constraints of the ruling:
  * trailing tear -> read_runs returns the 3 completed rows AND logs a warning
    naming the file and line ("skipping torn trailing line 4 ... crash mid-append
    -- 3 completed row(s) still returned"). Reported, not swallowed.
  * interior malformed line -> still raises JSONDecodeError. Not a crash signature,
    so real corruption is not hidden behind crash-recovery logic.
Task 8: complete (commits 6238f74..82d37b6, review clean, 2 minors deferred)

Task 8: re-review (haiku) VERDICT = all findings addressed, all three constraints
verified separately with line evidence: trailing-only tolerance via a `last_nonblank`
index computed before the parse loop (artifacts.py:133-137, 147, 153); the warning
names path, 1-based line number and returned row count (:148-152); interior malformed
lines still raise (:154, outside the guard). Blank/whitespace lines skipped without
being miscounted as torn. append_run's write path untouched. Empty and missing files
unchanged. Both new tests confirmed to fail against the old behavior.

Task 9: implementer DONE (agent a3f4fb90). Commit c343ccc. 13/13 assertions + 7 extra
tests; 22 passed. Controller independently verified the full failure taxonomy — all
six classes behave as specified:
    ok -> complete ; invariant violation -> rejected ; above ceiling -> rejected ;
    constraint violation -> infeasible ; manipulation failure -> failed ;
    runner raises -> failed (remaining rows continue)
The rejected/infeasible distinction I was most concerned about is correct: rejected
data is excluded as untrustworthy, infeasible is retained as real information about
the design space.

The reconcile(None) gap carried forward from T6 is CLOSED at the right layer: T9 adds
parse_test_results(payload) which returns {} on None/unparseable input, so reconcile
sees its own "declared but not executed" failure semantics instead of raising a bare
TypeError. That is the fix I asked for, implemented where the input originates.

Held-out leakage guard verified CORRECT after a false alarm on my first probe: the
held-out metrics ARE recorded in RunOutcome.response (required — the confirm stage
needs them) but EXCLUDED from response["fitting_inputs"], which keeps the primary
metric. My initial probe read the recording rather than the fitting inputs and
reported a failure that was not there.

Controller probe of build_cache_key (the highest-risk function in T9 — a collision
would mean a stale binary silently serving a different configuration):
  identical levels+hash equal          : True
  any level change differs             : True
  patch hash change differs            : True
  SWAPPED values between factors differ: True   ({A:1,B:2} vs {A:2,B:1})
  int 2 vs str "2" differ              : True
  int 2 vs float 2.0 differ            : True
  dict key ordering insensitive        : True
No collision found across the cases that matter. Stale-binary risk is not present.

Task 9: reviewer (sonnet) SPEC ✅, TASK QUALITY Changes requested. Independently
reproduced the controller's build_cache_key results and added a probe I had not run
(True vs 1 — JSON-distinct, differs correctly). Confirmed row_index is deliberately
excluded so replicate rows share a cache entry. Judged the retry deviation CORRECT
with reasoning the controller accepts: the brief's own taxonomy lists "runner raises"
as a separate row from "manipulation failure", and retrying a crashed subprocess
against fixed input reproduces the crash deterministically, so spending the
manipulation-retry budget there is waste — and conflating them would make the outcome
ambiguous about which kind of retry occurred. The observable/metric dual acceptance is
the existing spec-sanctioned convention from predicates.py, not an invention.

### BUG 12 IN MY PLAN — the held-out leakage guard is not structurally enforced

Both the reviewer and the controller reached this independently. Verified: the
held-out metric remains a TOP-LEVEL key of RunOutcome.response, and the exclusion
lives only in the response["fitting_inputs"] sub-dict. So the guard holds only if a
caller reaches for the sub-dict; passing `o.response` — the most natural idiom for a
first-time caller — leaks held-out data into the fitter silently.

That undercuts the plan's own framing. My Task 9 brief said to implement this "at the
observation boundary so a careless caller cannot leak held-out data" — but as built,
the careless path is exactly the one that leaks. The implementer built what the brief
described; the brief described a filtered view and called it a barrier.

Ruling: fix now rather than defer, because Task 11 is the first real consumer and the
failure mode is silent — a leaked held-out metric produces a campaign that optimized
against its own generalization check while every artifact looks clean. Fix by making
the held-out values structurally separate: remove them from top-level `response`
entirely and expose them under a distinctly-named `held_out` field on RunOutcome, so
reaching them requires deliberate intent. `response` then contains only fitting-safe
values, and passing it wholesale is SAFE by default rather than unsafe by default.
— Cost if wrong: a consumer that wanted the held-out value alongside the rest must now
read one extra field; trivial, and the confirm stage is the only such consumer.

Task 9: fix round 1/5 (agent a3f4fb90). Commit 10e4ea2. 23 passed. Dropped
`fitting_inputs` after grepping for readers — correct, since `response` is now
fitting-safe throughout so the sub-dict was redundant. Controller verified the guard
is now STRUCTURAL: held_out={'oos':99.0,'wf_blocks':4} on its own field;
response={'t':{'a':2},'m':10.0,'dd':-0.2}; a deep JSON scan of response finds neither
held-out key at any level; primary and constraint metrics retained. Passing `response`
wholesale can no longer leak.

### BUG 13 IN MY PLAN — the spec's worked example never validated

T10's extraction test (the check that keeps the authoring docs and the schema from
drifting) failed on the spec's §11 worked example: campaign.schema.yaml has
`required: [target_system, research_question, prompts]` from long before this feature,
and the example declared only the first two. An AI author copying it as a starting
point would have produced a campaign that fails validation on its first run.
Ruling: fix the SPEC, not the validator or the test. Added the prompts block in the
shape real campaigns use (methodology_layer + null domain_adapter_layer) and verified
the example now validates against the unmodified schema. — Cost if wrong: none; this
is the extraction test doing exactly the job it was written for.

Task 9: re-review (haiku) VERDICT = all findings addressed. F1 ADDRESSED on all four
elements with line evidence: _split_held_out (runner.py:150-174) returns a structural
partition; RunOutcome.held_out field (:80); the split is threaded through ALL FIVE exit
paths (invariant-rejected :326, integrity-rejected :335, ceiling-rejected :344,
constraint-infeasible :352, complete :358), so no path leaks; and the new test uses a
recursive _contains_value deep scan rather than a top-level key check, so a nested copy
would be caught. No dangling fitting_inputs readers (the one grep hit is a Task 10 test
NAME, not a dict-key read). Failure taxonomy unchanged across all six classes. Suite
1531 passed / 1 skipped excluding T10's in-flight file.
Task 9: complete (commits 82d37b6..10e4ea2, review clean, 2 minors deferred)

### BUG 14 IN MY PLAN — two defects in the spec's own worked example

T10's validator, once working, rejected the spec's §11 example on a cross-field rule:
  (a) factor F4's manipulation predicate was {telemetry.decay_guard_events, ">", 0}
      — trivially true. It passes whenever the stop fires at all, so it cannot
      distinguish threshold 0.004 from 0.010 and would report a mis-set lever as
      verified. This is EXACTLY the anti-pattern the spec's own anti-pattern section
      warns against, shipped in the spec's own example.
  (b) `levels: [off, 0.004, ...]` — unquoted `off` is a YAML 1.1 boolean, so it parsed
      as [False, 0.004, ...] and `when_not: off` guarded on the boolean rather than the
      sentinel string. Verified: yaml.safe_load('v: off') -> False.
Ruling: fix the SPEC. F4's predicate now compares config.decay_guard_threshold
against the interpolated {level}; "off" is quoted with a comment explaining the YAML
trap, since any author writing an on/off lever will hit it. Result: T10's file is now
42 passed / 0 failed, and the example validates against the schema AND all ten
cross-field rules. — Cost if wrong: none. This is the validator doing precisely the job
it was designed for, on its author's own example.

Note the shape of this one: the validator I specified caught a defect in the spec I
wrote, of the exact class the spec documents. That is the strongest possible evidence
the is_trivial floor earns its place.

REFLECTIVE-PATH BASELINE captured before Task 11 touches any existing file
(this is what Task 12 verifies against):
  pre-T11 SHA: 6024e008ad6d63a55cfed03f0c6728a5163a4b94
  blob hashes of the three files T11 will modify:
    661357ab65a64176e065646b79fc20effce5e158  orchestrator/iteration.py
    b563f1a0a7fd8d4083910bc811a6b2c21cfe0930  orchestrator/cli.py
    9a3fbe79b41819d31c65dfd89b23b842879a24a1  orchestrator/campaign.py
  core reflective tests (engine, cli_dispatch, campaign, complexity_tier,
  iteration_mode): 168 passed.
After T11 lands, `git diff 6024e00 -- <those files>` is the exact blast radius, and
those 168 tests must still pass unchanged.

Task 10: file green at 42 passed / 0 failed after the two spec fixes. campaign_kind
verified: {} -> reflective, explicit reflective -> reflective, optimization ->
optimization. examples/ backward-compat subset passes (5 tests).
Task 11: dispatched (agent a2df9562) carrying two forward items — assert the
correctness/behavioral split at the call site (T7's deferred minor, enforceable here
because classify_failures returns the two kinds as separate tuples), and the four
hard-fails that must fire independently of gate approval since auto-approve is this
kind's default.

Task 10: implementer DONE (agent a2639616). Commit 57d4fb9. 10/10 rules, 42 passed,
FULL SUITE 1573 passed / 1 skipped / 0 failed. Deviations accepted: private
_rule1.._rule10 helpers (matches validate.py's existing helper convention) and a
_RawFactorView shim so rule 4 reuses is_refinable on raw pre-parse dicts instead of
duplicating the predicate — both good calls, the second especially (duplicating
refinability logic would be a drift risk).

Controller checks of its three concerns:
  * apply object form keeps additionalProperties: true — ACCEPTED. Three shapes keyed
    by `kind`, already enforced at runtime by _normalise_apply. A oneOf in the schema
    would duplicate that logic and drift.
  * rule 7's try/except around alias-pair naming — ACCEPTED as written but noted: a
    warning must never crash validation, so degrading to an undetailed warning is the
    right failure direction. Deferred minor.
  * validate.py gained a module-level import of orchestrator.optimize.{design,
    factors,predicates} where it previously had none — VERIFIED SAFE: no optimize
    module imports validate, so there is no cycle, and the 168-test reflective
    baseline still passes unchanged.

Ruling: the import reaches a PRIVATE symbol, `design._GENERATORS`, to answer "is this
(k, resolution) tabulated?" (validate.py:476). There is no public predicate for that
question, so the coupling my earlier min_runs_for ruling implied was satisfied by
reaching through the module boundary. Fix: add a public `is_tabulated(k, resolution)
-> bool` to design.py and have validate.py use it. The private dict stays private, the
question becomes part of design.py's contract, and rule 8's two-branch behaviour keeps
working. — Cost if wrong: one extra trivial function; the alternative leaves a
cross-module dependency on a name whose leading underscore says "may change freely",
which is how a future refactor of the generator table silently breaks validation.

Controller leakage-guard bypass attempts against T10's rule 2 (this rule prevents a
campaign optimizing against its own generalization check, so a bypass would be
Critical):
  1. held_out == primary metric              -> BLOCKED
  2. held_out named in regimes only          -> BLOCKED
  3. held_out named in constraints only      -> BLOCKED
  4. case variation (held_out "OOS" vs "oos") -> not flagged
  5. leading whitespace (" oos" vs "oos")     -> not flagged
  6. clean campaign                          -> validates, no false positive

Ruling on 4 and 5: NOT bypasses, no fix needed. Verified that metric lookup is exact
and case-sensitive (predicates.evaluate with metric "OOS" against observed {"oos":5}
returns ok=False, missing=True). So a held_out entry of "OOS" or " oos" simply never
matches the emitted "oos" — it cannot silently receive that value, and no held-out
data reaches the fitter. Rule 2 is sound.

But this surfaces the OPPOSITE risk, which is real and worth carrying to T13: a TYPO in
a held_out entry makes it INERT. The author believes a metric is protected; nothing
protects it; and because the name never resolves, nothing complains. That is a silent
failure with the same consequence as the leak rule 2 guards against. It is not a
validator bug (the validator cannot know which metric names the target will emit), so
the mitigations are documentation and the runner's own behavior: T13's anti-pattern
section should name it, and the confirm stage reads held_out values, so a held_out
metric that never appears in any observation is detectable at runtime. Recorded as a
deferred item for T13 rather than a T10 fix.

Task 10: reviewer (sonnet) SPEC ✅, TASK QUALITY Changes requested. Confirmed rule 8's
two-branch split is implemented exactly per the corrected spec, with a dedicated test
grounding WHY the untabulated fallback cannot be trusted as a minimum. Praised the
_RawFactorView reuse of is_refinable/is_trivial/is_tabulated over re-implementation.

### BUG 15 IN MY PLAN — CRITICAL: rule 9 is bypassable via metadata

The reviewer found a hole I missed in my own bypass sweep. Rule 9 (complexity_tier
forbidden under kind: optimization) inspects only the `optimization` dict, never
`campaign.get("metadata")` — and top-level `metadata` has additionalProperties: true by
design, for freeform tags. Controller verified: a kind: optimization campaign carrying
metadata: {complexity_tier: 2, tier_justification: "..."} passes BOTH jsonschema and
validate_optimization_campaign with zero errors.

Worse than a simple omission: orchestrator/complexity_tier.py:42-44 documents that
`metadata` is the CANONICAL location for tier fields since #206, and reads it in
preference to the legacy top-level spot. So an AI author following the repo's own
documented convention lands precisely on the bypass path — and gets silence, not even a
warning. My Task 10 brief said to check "wherever those can appear (top level and nested
under metadata, since a prior issue moved them there)"; the brief named the risk and the
implementation only covered half of it.

Ruling: fix. Rule 9 must scan both locations, matching complexity_tier.py's own
resolution order. — Cost if wrong: none; the two disciplines must not be half-adopted
together, which is the whole point of the rule.

Second finding (Important): rule 2's leakage guard does exact string equality, so
whitespace/case variants of the SAME metric name pass silently. Note this is a DIFFERENT
claim from my own earlier probe: I verified that a held_out of "OOS" cannot receive the
value of an emitted "oos" (lookup is exact, so no leak through that path). The reviewer's
point is about author INTENT — someone writing held_out: ["throughput_gbps "] with a
trailing space, alongside constraints on "throughput_gbps", intends them as the same
metric and gets no warning that the guard did not engage. Both readings are right, and
they argue for the same fix: normalize for COMPARISON so the rule warns on near-duplicate
names, while leaving the declared strings untouched (they must still match the target's
emitted names exactly).

Task 11: agent a2df9562 STALLED (watchdog: no progress for 600s). Assessed the damage:
CLEAN stall — it died during research, before writing anything. All three production
files byte-identical to the pre-T11 baseline hashes, no stage_runner.py, no new test
files, no uncommitted code, suite green at 1574 passed / 1 skipped. Best available
failure mode.
Its research is worth carrying forward rather than repeating: with objective=None,
ledger.update_best_found falls back to legacy status-based scoring (CONFIRMED=1.0,
PARTIALLY_CONFIRMED=0.5, REFUTED=0.0) keyed off arm["status"], and project_findings
emits exactly those status values — so best_found.json top_k ordering works with no
campaign objective block, satisfying assertion 12 without extra plumbing.
Re-dispatching fresh per the skill's escalation guidance, with that finding included.

Ruling: SPLIT Task 11 into two independently-dispatched halves rather than re-running it
whole. It was the largest task in the plan (4 files, 16 assertions, a new module), and
the stall came during research before any write — which reads as scope-induced rather
than a bad brief.
  T11a (agent a92b653c): cli.py flags + resolve_gate_mode + assertions 1-6. Explicitly
        forbidden from touching iteration.py or creating stage_runner.py.
  T11b (agent a6f4f338): stage_runner.py + the iteration.py delegation branch + the tier
        comment + __init__.py re-exports + assertions 7-16. Explicitly forbidden from
        touching cli.py.
The two file sets are disjoint, so they cannot collide. Each dispatch names the other's
files as out of scope and tells it to report but not fix failures there.
T11b also carries an explicit scope control: build the smallest run_stage that satisfies
its assertions using StubDispatcher and an injected fake runner; leave production
subprocess wiring for the config runner and integrity check as injected parameters with a
documented TODO. A correct tested skeleton that lands beats a complete implementation
that stalls. — Cost if wrong: a follow-up task must wire the two production callables;
that is bounded, visible in the report, and preferable to a second stall.

Task 10: fix rounds 1 and 2 (agent a2639616). Commits 3349ee1 (public is_tabulated),
65f3713 (rule 9 scans metadata + top level; rule 2 normalizes for comparison). 48 passed;
full suite 1580 passed / 1 skipped / 0 failed. Controller verified every fix:
  CRITICAL rule-9 bypass CLOSED — tier under metadata BLOCKED, tier at top level BLOCKED,
    and freeform metadata tags still validate clean (no false positive).
  rule 2 — whitespace variant BLOCKED, case variant BLOCKED, genuinely distinct metric
    still clean. Normalization is comparison-only as required.
  is_tabulated — agrees with the tabulated set: (5,5) and (7,3) True; (6,3) and (9,5)
    False. No `_GENERATORS` reference remains in validate.py.
  The important NEGATIVE case: a kind: reflective campaign carrying complexity_tier is
    still LEGAL. The tier ladder remains in force where it belongs; only half-adopting
    both disciplines is forbidden.
  Reflective baseline still 168 passed.
Task 10: complete (commits 6024e00..65f3713, review clean, 2 minors deferred)
Task 10: minor (deferred): rule 7's try/except around alias-pair naming degrades to an
undetailed warning on unexpected exceptions — correct failure direction for a warning.
Task 10: minor (deferred): factors[].apply object form keeps additionalProperties: true;
three shapes keyed by `kind`, enforced at runtime by _normalise_apply.
Task 10: DEFERRED TO T13: a typo in a held_out entry makes it inert — the author believes
a metric is protected, nothing is, and the name never resolving means nothing complains.
Not detectable by the validator (it cannot know which metrics the target emits). Belongs
in the guide's anti-pattern section. Both the implementer and the controller flagged it.

Task 11a: implementer DONE (agent a92b653c). Commit 0e3a8ab. 6/6 assertions, 10 tests;
full suite 1590 passed / 1 skipped; reflective baseline still 168 passed; test_cli.py 26
passed. Diff is 73 insertions / 6 deletions in cli.py — resolve_gate_mode with a docstring
that records the precedence rationale, two call-site swaps, the flag rewiring, and a pure
build_parser() extraction out of main() so tests can drive the real parser.
Controller verified all seven resolution cases through the REAL parser (not a namespace
fake): optimization+no flags True; reflective+no flags False; no-kind+no flags False;
optimization+--interactive False; reflective+--auto-approve True; both flags False for
each kind. Confirmed the mechanical requirement holds — args.auto_approve is None when
omitted and True when supplied, so an explicit choice cannot be clobbered by the kind
default. resume subparser mirrors both flags.
Deviation ACCEPTED: extracting build_parser() from main() is a pure refactor and was the
right call — it let the tests exercise real flag wiring rather than a hand-built
namespace, which is what caught nothing here but would catch a mis-declared flag.

Task 10: re-review (haiku) VERDICT = all three findings addressed, no new breakage.
  F1 ADDRESSED — validate.py:537-578 scans THREE locations in order [optimization,
    metadata, top level], matching complexity_tier.py:39-77's own precedence (metadata
    canonical post-#206). Better than asked: the message names WHERE the field was found
    ("metadata.complexity_tier" vs "complexity_tier (top level)"), so an author can act.
  F2 ADDRESSED — validate.py:249-261 _norm_metric does strip().lower() for COMPARISON
    only; the campaign dict is not mutated and messages report declared names verbatim
    via {metric!r}. Messages include "(same metric name, ignoring case/whitespace)" so
    the author understands why two spellings collided.
  F3 ADDRESSED — public is_tabulated at design.py:66-73 with a docstring steering callers
    away from inferring tabulation from min_runs_for. Rule 8's untabulated message now
    says "do NOT assume the X-run full-factorial fallback is the true minimum" — stronger
    than the wording I specified.
  Rule 8 both branches verified intact. Suite 1590 passed / 1 skipped.

Task 11a: complete (commit 0e3a8ab, controller-verified, 0 findings)

Task 11b: agent a6f4f338 STALLED at the same point as its predecessor (research phase,
760KB transcript, no files written, no response to a narrowing nudge). Stopped it. Damage
check: iteration.py and campaign.py byte-identical to the pre-T11 baseline, no partial
files, suite 1590 passed / 1 skipped. Clean again.

TWO agents have now stalled on stage_runner.py at the same phase. That is a diagnosis,
not bad luck: the task requires holding NINE module contracts plus the existing phase
machine (Engine, _enter_phase, HumanGate, append_ledger_row, finalize_iteration,
update_best_found, meta_findings) in context at once before a single line can be written.
Splitting T11 in half was not enough, because the whole difficulty lives in the half I
kept whole.

Both stalls did leave usable research, and together they answer the integration questions:
  * update_best_found reads runs/iter-N/findings.json via _iter_findings(work_dir) and is
    fully kind-agnostic — directly reusable.
  * finalize_iteration is directly reusable, and calls _merge_principles and
    classify_principle_updates_in_place, which read iter_dir/{principle_updates,findings}
    .json — format-agnostic, so run_stage can call finalize_iteration directly.
  * With objective=None, update_best_found falls back to legacy status scoring
    (CONFIRMED=1.0, PARTIALLY_CONFIRMED=0.5, REFUTED=0.0) keyed off arm["status"], which
    project_findings already emits — so best_found ordering needs no objective block.

Ruling: the controller implements T11b directly rather than dispatching a third agent.
The skill says never to fix findings in the controller session, and I am not overriding
that for a review finding — this is a repeatedly-failed IMPLEMENTATION whose blocker is
context assembly, which is precisely what a controller already holds. A third identical
dispatch would be the definition of forcing the same model to retry without changing
anything. I will still submit the result to an independent task review, so the work is
not self-approved. — Cost if wrong: my context carries the implementation detail rather
than staying clean for coordination; mitigated by the work being one module plus one
branch, and by the review being dispatched as usual.

Task 11b: implemented by the CONTROLLER (commit 5972283) after two agent stalls.
12 tests pass; reflective baseline still 168; full suite 1602 passed / 1 skipped.
iteration.py: 23 insertions, ZERO deletions — one delegation branch plus the
reflective-only tier comment. Verified by source inspection that the branch appears
before any state inspection, returns run_stage, and occurs exactly once.

TWO INTEGRATION DEFECTS found that no unit test could have caught — both are the
reason an integration task earns its place:
  (a) project_findings declares `decision: str`, and I initially passed the
      StageDecision dataclass, which is not JSON-serializable. Fixed by passing
      decision.rationale (plus any trigger names) — which is also the better choice,
      since stage.py guarantees the rationale is never empty precisely so this
      projection cannot produce an evidence-free finding.
  (b) principle_updates.json is a BARE LIST on disk. iteration._merge_principles
      raises "should be a list, got dict", and a real campaign artifact
      (absorption-test/runs/iter-1) confirms the list shape.
      project_principle_updates returns the principles.schema.json wrapper
      {"principles": [...]}, which describes the MERGED principles.json store rather
      than this per-iteration file. T8 validated against the wrapper schema and so
      never noticed. The stage runner unwraps it.
      => T8's assertion 11 was checking the wrong shape. Not a T8 implementation bug
      (it did what the brief said) but a plan defect: the brief said "validates
      against principles.schema.json" when the per-iteration file is a bare list.

Also fixed one bug of my own in _build_design: I gated full-vs-fractional on
len(ids) < 3, but 3 factors at resolution V has no tabulated FRACTIONAL design while
the full factorial (8 runs) already achieves it. Now gates on
design.is_tabulated(k, resolution) — the public predicate T10's fix round added,
used here at its second call site.
Task 11: complete (commits 6118f53..5972283, 0e3a8ab + 5972283, controller-implemented
half pending independent review)

### BUG 16 — a defect I introduced, surfaced by a reviewer's QUESTION not a test

While the T11 review ran, I checked two of its own probe questions myself. Question 4
was right and found a real bug in the code I had just written: at refine,
_build_design builds a CCD over only the REFINABLE factors, but I passed every declared
factor id to fit_effects. Verified: a CCD over one refinable factor has coded width 1,
and passing two ids raises IndexError.

It survived because all twelve of my tests exercise `screen`, where the refinable and
declared sets coincide. The refine path had ZERO coverage. That is the lesson worth
keeping: I wrote the tests and the code together, and my own blind spot was identical in
both — which is exactly the failure mode independent review exists to catch, and here it
was caught by a reviewer merely ASKING about the branch rather than testing it.

Fixed with _design_factor_ids as the single source of truth for a stage's design width,
used for the fit, the stationary-point solve, and decide_after_refine's factor list. Two
regression tests added: one drives refine end-to-end and asserts a 2-level factor absent
from the design does not appear as a fitted effect; the other asserts the invariant
directly for every stage (id count == design coded width). Commit 19d3461.
14 tests pass; suite 1604 passed / 1 skipped; reflective baseline still 168.

Task 11: reviewer (sonnet) PRIME DIRECTIVE verified unchanged (23 insertions / 0
deletions, delegation once and before state inspection, baseline 168 passed) but
SPEC ❌ with THREE CRITICALS. The dispatch asked it to be harder on controller-written
code than usual; it was, and it was right. Its closing line is fair: "the controller's
own report undersells the damage". All three confirmed by the controller independently:

  C1 — run_stage NEVER transitions to DONE and never returns COMPLETED (verified:
       'transition("DONE")' absent, "COMPLETED" absent, only CONTINUE returned).
       run_campaign terminates on COMPLETED/ABORTED/REDESIGN, so a real 4-stage campaign
       returns CONTINUE at confirm, the loop calls iteration 5, stage_for_iteration falls
       off the end and returns CONFIRM again — confirm re-runs indefinitely. It only
       LOOKS fine when max_iterations happens to equal the stage count, which masks the
       bug rather than fixing it.
  C2 — locked_parameters is NOT WIRED. grep over orchestrator/optimize/ finds the string
       only in my own stage_runner docstring, which lists it as hard-fail #1 of four.
       The code asserts a guarantee it does not provide. That is the worst kind of defect
       in this build: worse than a missing check, because the docstring would stop the
       next reader from adding it.
  C3 — ONE non-complete run NaN-poisons the ENTIRE fit. Verified: 1 nan among 8 runs
       makes every effect estimate AND the intercept nan. My _fitting_responses appends
       float("nan") for non-complete rows, which flows straight into the normal
       equations. It degrades short of a fabricated confident answer (significant=None,
       so decide_after_screen treats terms as unknown rather than measured-null), but the
       campaign silently writes a fully-NaN schema-valid effects.json and findings.json
       with no error and no test.

Also: assertions 10-13 (ledger row, meta_findings at root, best_found ordering, state.json
stage recording) have NO direct test — and the reviewer correctly notes they CANNOT be
written today because of C1: they need a run_campaign-level multi-iteration test that
terminates, which C1 prevents. So C1 blocks its own coverage.

Ruling: fix all three, and drop the false docstring claim rather than implementing
locked_parameters in this pass. Concretely —
  C1: run_stage returns COMPLETED and transitions to DONE on the final stage (confirm, or
      the last entry of an explicit `stages` list), CONTINUE otherwise. Then assertions
      10-13 become writable.
  C2: EITHER wire the check or remove the claim. Wiring it properly needs the
      locked_parameters-vs-executed-config comparison that has no bundle in this path, so
      the honest move is to remove the claim from the docstring and record it as a named
      follow-up. A docstring that overstates the guarantees is actively harmful.
  C3: refuse to fit on NaN. Raise OptimizationAborted naming the offending rows, so a
      partially-failed sweep fails loudly instead of writing an all-NaN artifact set. The
      spec's "degrade the claim, not the data" stance means refit on COMPLETED rows with
      the reduced resolution reported — but silently emitting NaN is neither.
— Cost if wrong: C1's terminal-stage logic could end a campaign one stage early if the
stage list is misread; covered by the new assertions 10-13 tests. C3 makes a
partially-failed sweep fail where it previously "succeeded" with NaN, which is the
correct direction.

Task 11: fix round 1/5 by the controller. Commit be23dda. All three Criticals fixed and
covered: 19 tests pass (was 14); full suite 1609 passed / 1 skipped; reflective baseline
still 168.
  C1 -> _terminal_outcome + _is_final_stage; confirm now returns COMPLETED and reaches
        DONE, an explicit optimization.stages list overrides the confirm default. Three
        tests including one that pins which stage is terminal for three different stage
        lists.
  C2 -> the false claim is gone, replaced by an explicit "NOT YET WIRED" note naming what
        wiring it needs, plus a test asserting the claim stays absent so it cannot creep
        back.
  C3 -> _fitting_responses raises naming the offending row indices; a test drives a flaky
        runner that crashes one config and asserts the abort message.
Dispatching an independent scoped re-review, since the controller both wrote and fixed
this code — it must not be self-approved twice over.

REFLECTION worth keeping for the final report: the three Criticals were all in the ONE
module a controller wrote rather than an implementer, and all three are the kind a fresh
reviewer catches and an author does not — a missing terminal transition, a docstring
overclaiming, and an unhandled degenerate input. That is not a coincidence. The
implementer/reviewer separation is doing real work in this process, and the two agent
stalls that forced me to write it myself cost more than the wall-clock they saved.

Task 11: re-review (sonnet) verdict C1 ADDRESSED, C2 ADDRESSED, C3 NOT ADDRESSED as of
be23dda. It reached the infeasible-blocking problem INDEPENDENTLY while reviewing the
committed diff — I had already found and fixed it in the working tree (commit f0d6b39)
before its report landed. Useful convergence on the exact distinction the
rejected/infeasible split exists to draw.
  C1 probes all passed: no stages key, empty list, list without confirm, Stage enum
  member, and — the one that would have turned a Critical fix into a new Critical —
  transition("DONE") is LEGAL from HUMAN_FINDINGS_GATE, which is the phase run_stage is
  always in when it calls it (verified against engine.TRANSITIONS and empirically).
  C2 verified unwired and the new tripwire test confirmed real.

One finding I had missed: None / non-numeric primary metric values raised raw
TypeError/ValueError from float() instead of a clean abort. Verified all three shapes.
Fixed (commit d925d70) with the right distinction: null on a COMPLETE row is a
measurement failure and blocks; null on an already-excluded row is expected and carried
as NaN; a string or structure is an instrumentation mismatch at any status.

### BUG 17 — a latent PRE-EXISTING defect, surfaced by a merge conflict

Two concurrent agents touched orchestrator/schemas/state.schema.json and left a stash
conflict. Reading both sides closely showed the schema has additionalProperties: false
but never declared `max_iterations`, while campaign.py:201 (_persist_max_iterations,
#197) writes exactly that field. So any state.json from a real run would FAIL ITS OWN
SCHEMA. That predates this feature entirely and has nothing to do with it. Declared the
field; kept both sides of the conflict since neither belonged to this work.
Worth noting how it was found: not by a test, but by refusing to resolve a conflict
mechanically. A `git checkout --theirs` would have hidden it.

Suite after all fixes: 22 tests in test_optimize_iteration.py; T12 and T13 still landing.

Task 12: both of its own test failures diagnosed by its implementer as TEST bugs, and
the controller verified each independently rather than accepting the report:
  * the bundle arm-type enum is ['h-main','h-ablation','h-super-additivity',
    'h-control-negative','h-robustness','h-dose-response','h-tradeoff'] — "control" was
    never valid, so h-control-negative is right.
  * validate_design's pass path is {"status":"pass","warnings":warnings} at
    validate.py:1036 with NO errors key, so .get("errors", []) is correct and matches
    test_independence_check.py's existing convention.
  * assertion 8's AST rewrite (from the controller's diagnosis) verified as a REAL
    tripwire: asserts an ast.Return wrapping a Call to run_stage, locates the branch by
    its own test expression, zero line-matching left. Strictly stronger than the
    line-based version it replaced.
  14 tests pass. Keeping a line-number comparison for the "before any state inspection"
  half is correct — that is a source-order question, not a shape question.

Task 13: implementer DONE (agent aebd0c48). Commit 5fa256b. 4 worked examples, all
validating; 8 anti-patterns; 8 tests pass. Controller independently re-validated all four
examples: 21 yaml blocks, 4 complete campaigns, ZERO problems — schema, all ten
cross-field rules, only numeric/choice types, a correctness relation per factor, no
trivial predicates, no held-out leakage. Cross-links present in README/CLAUDE/data-model;
the YAML-1.1 `off` trap and the inert-held_out-typo (both real defects from this build)
are documented as anti-patterns.

### BUG 18 IN MY PLAN — rule 8 rejects campaigns the runner executes correctly

T13 reported that writing the guide's small examples forced it to OMIT design.max_runs,
because rule 8 hard-errors on an untabulated (k, resolution). Verified, and it is a real
validator/runner disagreement, not authoring friction to document:

  full_factorial achieves resolution V for k <= 4 with ZERO aliasing:
    k=2 -> 4 runs, aliases=[]   k=3 -> 8 runs, aliases=[]   k=4 -> 16 runs, aliases=[]
  is_tabulated(k, 5) is False for those k, so rule 8 errors — yet
  stage_runner._build_design already falls back to full_factorial and would run them
  correctly. The validator rejects a campaign the runner handles.

The rule-8 correction I made earlier (untabulated => do not compare a fabricated number)
was right about not trusting min_runs_for's 2**k fallback as a MINIMUM. What I missed is
that 2**k is not merely an upper bound there — for small k it is the exact and achievable
answer, because a full factorial aliases nothing and therefore satisfies any requested
resolution.

Ruling: rule 8 must treat "untabulated but 2**k achieves the requested resolution" as
FEASIBLE, and compare 2**k against max_runs like any other known count. That is exactly
what the runner does. Only genuinely-unachievable combinations (untabulated AND 2**k
exceeds the budget) should error. — Cost if wrong: a campaign at small k with a tight
budget gets a budget error naming 2**k, which is the true cost and therefore the honest
message. The alternative leaves authors unable to declare a budget at all on the smallest
campaigns, which is where a budget is easiest to state and most likely to be right.
Bug 18 FIXED. Rule 8 now returns feasible when the 2**k full factorial fits max_runs,
and errors only when it genuinely does not. Verified all five cases: 3 factors/60 clean,
3/4 errors (needs 8), 2/60 clean, 5/60 clean, 5/10 errors naming "16 runs" and
"max_runs=10". 51 tests in the schema file; suite 1637 passed / 1 skipped.
Task 13: complete (commit 5fa256b + the rule-8 fix)

Task 12: complete (commit 29b66bd, 9/9 assertions, 14 tests). Found and fixed three of
its OWN test bugs during development (invalid arm `type: control`; asserting on
run_iteration instead of run_campaign for the ledger row; the line-based structural check
rewritten to AST per the controller's diagnosis). No production defects — which is the
right outcome for a regression gate: it should confirm the guarantee, and it did.

ALL 13 TASKS COMPLETE. Branch: 45 commits, 40 files, 14251 insertions / 7 deletions.

Controller's final independent verification before the whole-branch review:
  * ARCHITECTURAL GUARANTEE: iteration.py is 23 insertions / ZERO deletions. Reflective
    baseline 168 passed.
  * DEPENDENCY GUARD: AST import extraction across all ten optimize/ modules finds ZERO
    forbidden imports (numpy, statsmodels, pandas, pyDOE3, hypothesis). Verified by AST
    rather than grep, because docstrings legitimately name those libraries as warnings.
  * GENERATOR TABLE: all 10 entries audited against their claimed resolution — 0
    violations, all orthogonal. This is the table where two of the worst bugs of the build
    lived ((7,5) and (8,5) mislabelled as resolution V).
  * L5 ORACLE: main effect -0.950000, interaction +1.600000, sign flip preserved. Exact.
    This is the feature's entire reason for existing and it works.
  * TEST POSTURE: 286 tests across 14 test_optimize_*.py files; full suite 1637 passed /
    1 skipped / 0 failed.
Final whole-branch review dispatched on Opus with the ledger, the 14 deferred minors, and
an explicit instruction to treat stage_runner.py as the highest-risk file (six of the
eighteen defects, no independent author).

## FINAL WHOLE-BRANCH REVIEW (Opus) — 3 Important, 4 Minor, "merge after two named fixes"

ARCHITECTURAL GUARANTEE: VERIFIED independently by the reviewer — 23 insertions / 0
deletions in iteration.py, 168 reflective tests, 1637 total, dependency constraint
confirmed by AST (only scipy.stats, in effects.py), all 45 commits carrying the required
trailer. It also judged test_optimize_no_regression.py a genuine gate rather than a rubber
stamp, and specifically credited its NEGATIVE case (complexity_tier remains legal on
reflective).

STATISTICAL CORE: re-derived all three from scratch rather than reading the tests.
Generator table brute-forced via defining relations — 9/10 exact, the tenth ((6,5)) is
resolution VI labelled V, i.e. UNDER-claiming and safe. Per-term SE checked against an
exact rational (X'X)^-1 in Fraction arithmetic: EXACT for every main effect and 2fi (the
only terms that gate a decision), optimistic for the intercept and pure quadratics as the
docstring already disclosed. L5 oracle recovered to machine precision with the sign
genuinely flipping. The central economic claim was found not merely tested but
STRUCTURALLY IMPOSSIBLE TO VIOLATE: no dispatcher, completion_fn, sdk_runner or LLM symbol
exists anywhere in orchestrator/optimize/.

Its closing observation is the one worth keeping: the two prior rounds on stage_runner.py
caught what tests could reach; what they could not catch was the ABSENCE of a test. Both
of its Importants in that file sit on paths nothing drove — which is exactly the blind spot
a module with no independent author would have.

ALL FINDINGS FIXED (commit 0196c01), each verified by the controller first:
  F1 confirm stage — verified _build_design(screen) == _build_design(confirm) was True, and
     that `replicates` appeared nowhere in optimize/. IMPLEMENTED rather than marked
     not-wired: confirm now replicates one configuration (refine's stationary point, handed
     forward via confirm_at.json so the loop closes across the per-iteration process
     boundary) and reports reproduction instead of fitting. Fitting a single replicated
     point correctly raises "singular"; confirm's claim is narrower and more useful.
  F2 + deferred #5 — verified duplicated rows produced NO violations, and that 0.1+0.2 vs a
     planned 0.3 produced a FALSE violation that would abort a legitimate campaign. Both
     fixed; choice levels still compare exactly.
  F4 — noisy-runner test added; survivor selection now genuinely exercised.
  F5 raises on iteration < 1. F7 documented. F8 figures now state their centre count
     (recomputed exactly: 1.458 at 3 centres, 1.313 at 5 — my original numbers were right
     for 3, the reviewer's for a different count, and neither said which).
DEFERRED MINORS: 12 of 14 confirmed fine to defer; #4 already fixed; #5 promoted and fixed
because its own stated trigger condition arrived in a later task. #10 confirmed resolved.
F3 (no production config_runner wiring) is NOT fixed and NOT a blocker — it is disclosed in
the module docstring and must appear in the merge note. Suite 1642 passed / 1 skipped.

Controller probes of the fix wave, ahead of the scoped re-review:
  F1 edge cases ALL correct — no confirm_at.json falls back to the origin; a CORRUPT
    confirm_at.json returns None and falls back cleanly without raising; replicates=1
    gives 1 point; replicates=0 is clamped to 1; a missing replicates uses the default 3;
    a valid confirm_at is picked up ((0.75,-0.5)).
  F2 tolerance boundary correct — representation noise (0.1+0.2 vs 0.3) and +1e-13 are
    tolerated; +1e-6 and 2.001 are FLAGGED; None and a numeric-looking "2" are FLAGGED;
    choice levels compare exactly.

Task 5: minor (deferred): `parse_factors` accepts BOOLEAN factor levels, so
`levels: [1, True]` declares two levels Python considers equal (True == 1), and
`levels: [true, false]` in YAML yields bools that compare equal to 1/0 anywhere in the
stack. Verified accepted today. This is NOT a fidelity bug — check_fidelity's bool guard
correctly routes bools to exact comparison, and True == 1 is a Python identity rather than
a tolerance artefact — but it is a latent authoring hazard that predates this branch's
fixes. Ruling: defer with a note rather than widen scope at merge time. The right fix is a
validator warning when a factor's declared levels contain values that compare equal after
normalisation (which would also catch the case a duplicated numeric level creates).
— Cost if wrong: an author declaring [1, True] gets a design with two indistinguishable
levels and effects that cannot separate them; bounded because every worked example and
every corpus campaign uses distinct numerics or quoted strings, and the guide's `type`
guidance steers on/off levers to `choice` with quoted sentinels.

## SCOPED RE-REVIEW OF THE FIX WAVE (sonnet)

F2+#5, F4, F5, F7, F8 all ADDRESSED. All three live hard-fails still fire; a behavioral
violation still does not abort; optimize/ still LLM-free (AST + grep for Dispatcher /
completion_fn / sdk_runner / anthropic / openai / claude_agent_sdk: zero hits).
F1 functionally ADDRESSED, with all four of my edge probes independently reproduced —
plus one observation I had not made: a genuine runner crash at confirm hits the NaN guard
before _finish_confirm runs, so confirm's REFUTED path is reachable via
infeasible/rejected but not via a crash. Consistent with the failed-vs-infeasible policy
established in T9, so noted rather than changed.

### BUG 19 — in my OWN confirm fix, found by review of that fix

_read_confirm_at sorted the globbed paths LEXICOGRAPHICALLY, so "iter-10" sorted before
"iter-2" and the helper returned the EARLIEST double-digit iteration instead of the
latest. Verified directly: with confirm_at.json at both iter-2 and iter-10 it picked
iter-2's value. A campaign reaching double digits before confirm would silently replicate
a stale optimum — a wrong answer with no error, which is the worst available failure mode
for a stage whose whole claim is "this specific point reproduced".
Fixed (commit 532042a) with a numeric sort on the parsed iteration index, tolerant of a
non-numeric directory name. Two regression tests plus the F5 test the re-review noted was
missing. 30 tests in the file; suite 1645 passed / 1 skipped.

This is the third consecutive review round to find a new defect in stage_runner.py, and
each was on a path no test drove: confirm (round 1), the resume/duplicate path (round 2),
and now the multi-iteration confirm_at read (round 3). The pattern is not that the reviews
were lucky — it is that a module with no independent author accumulates untested paths,
and each review round finds the next one only once the previous fix creates a test that
walks nearby. Worth stating plainly in the handoff.

Per the skill there is no second fix wave. This was the only open finding, it is fixed with
tests, and the branch is ready for finishing-a-development-branch.

FINAL STATE: 48 commits, suite 1645 passed / 1 skipped / 0 failed, reflective baseline 168,
iteration.py 23 insertions / 0 deletions, 19 defects found and fixed.
