# The compiled epoch's invariant inventory

**What this is.** An enumerated, ID'd, machine-checkable inventory of the
invariants `kind: optimization` relies on, classified by TYPE and by LEVEL,
each traced to the docstring / comment / spec section / historical defect it
comes from — plus a companion enumeration of the kind's **behaviors** (§8),
which are a different thing and are confused with invariants routinely.

**Why it exists.** There are ~128 invariant-flavored statements in
`orchestrator/optimize/*.py` docstrings and comments, phrased as "MUST NEVER",
"load-bearing", "always", "by construction", "the whole point is". The
codebase knows its invariants. Before this file none of them was
machine-checkable, and a real field test burned ~14 hours during which several
stated invariants were silently violated and nothing noticed. Prose that
cannot fail is documentation of an intention, not a guard.

**Why here and not in `docs/superpowers/specs/`.** The design spec
(`docs/superpowers/specs/2026-08-16-compiled-policy-design.md`) is a **dated,
frozen record of decisions** — "accepted, not yet implemented", written before
the code existed, and amended only with post-implementation naming notes. This
file is the opposite: a **living checklist that tracks the code** and is
expected to change whenever a seam moves. Putting it in the specs directory
would either freeze it (useless) or make a spec mutable (worse). It sits in
`docs/` beside `docs/data-model.md` (per-artifact reference) and
`docs/optimization-campaign-guide.md` (authoring), which is the same
altitude: reference material a reviewer reads while looking at code.

The spec remains the **binding design authority**. Where this file and the
spec disagree about what SHOULD be true, the spec wins and this file is the
bug. Where this file and the spec disagree about what IS true, the code
decides and both get fixed.

**How to use it as a reviewer.** For a change under `orchestrator/optimize/`:
find the invariants whose LEVEL your change touches, confirm each still
holds, and if you weaken one, say so in the PR. If your change adds a new
"MUST NEVER" to a docstring, it needs an ID here and a checker — otherwise
you have added prose that cannot fail.

**Anti-drift.** Every ID below exists in
`orchestrator/optimize/invariant_registry.py`, and every registry entry
appears below. `tests/test_optimize_invariant_registry.py::test_document_and_registry_do_not_drift`
parses this file and fails on either direction of mismatch. That test is what
keeps this inventory alive rather than archaeological.

---

## 1. The two axes

### By TYPE

| Type | Prefix | What makes it this type |
|---|---|---|
| **Structural** | `INV-ST` | Shape, schema, reference integrity. Checkable on one artifact or one object with no reference to what it means. |
| **Semantic/accounting** | `INV-SEM` | Meaning-preserving. Two things that must stay distinct, or a value whose *interpretation* is load-bearing (`None` ≠ 0). |
| **Statistical** | `INV-STAT` | Properties of estimates: monotonicity of uncertainty, non-negativity, estimability, independence of exclusions from levels. |
| **Temporal/ordering** | `INV-TMP` | Sequencing. Something must be written before, after, or exactly once relative to something else. |
| **Resource/isolation** | `INV-RES` | No two things share what must not be shared; a copy is a copy. |
| **Economic** | `INV-ECO` | Token and budget cost. |

Two categories the starting taxonomy did not have and the evidence demanded:

- **`INV-PROV` — provenance/identity.** A group of invariants is about
  *two records of one commitment agreeing* (`policy.json` ↔ `policy.sha256`,
  `mechanism.sha256` ↔ `compiled_from.mechanism_patch_hash`,
  `adapter_contract.json` ↔ `adapter_contract.sha256`). Calling these
  "structural" loses what makes them hard: the failure is not a malformed
  document, it is two well-formed documents that no longer describe each
  other. Calling them "temporal" loses that the ordering is incidental — the
  *agreement* is the invariant, not the write order.
- **`INV-VOC` — closed vocabulary.** `OBSERVATION_KEYS`, `COMPARISON_OPS`,
  `FAILURE_KINDS`, `recommendation.basis`, `RunOutcome.status`. Each is a set
  that must stay closed AND fully consumed. This is not structural: a policy
  referencing an unknown key is structurally fine and semantically dead. The
  characteristic defect is *dead vocabulary that reads like a live guard* —
  `runs_needed_confirm` was exactly that for six tasks, per the note in
  `policy.py`'s `OBSERVATION_KEYS` docstring.

### By LEVEL

| Level | Where it is checkable | Cost of checking |
|---|---|---|
| `function` | one call, pure inputs | free |
| `module` | across a module's public API | free |
| `artifact` | one file on disk | one read |
| `iteration` | one `runs/iter-N/` directory | walks rows |
| `epoch` | work-dir root across iterations | walks the epoch |
| `campaign` | whole work-dir, all epochs | walks everything |

A `function`/`module` invariant can be a property test. An `artifact`
invariant can be a schema plus a checker. An `epoch`/`campaign` invariant can
usually only be checked *post hoc* from the artifacts — which is exactly why
they are the ones that went unnoticed for 14 hours.

### Enforcement classes

| Class | Meaning |
|---|---|
| `always` | Checked on every production run at the named seam. Must be O(rows) at worst and side-effect-free. |
| `paranoid` | Checked when `NOUS_OPTIMIZE_PARANOID=1`. Reserved for checks that are cheap but whose failure mode has never been observed, or that duplicate a guard one layer down. |
| `test` | Checked only by the test suite. Either it needs constructed inputs (a mutated policy) or it is a property over a generated space. |
| `audit` | Checked by a post-hoc walk over a finished work-dir (`audit_work_dir`), not inline. For `epoch`/`campaign`-level invariants where inline checking would mean holding the whole campaign in memory. |

---

## 2. Structural (`INV-ST`)

| ID | Statement | Level | Evidence | Checked | Defect? |
|---|---|---|---|---|---|
| `INV-ST01` | Every non-terminal policy state has a `default` transition. | artifact | `policy.check_policy`; spec §3.1 | `always` — `check_policy` at compile; registry re-checks | — |
| `INV-ST02` | Every transition's `from` and `to`/`default` names a declared state. | artifact | `policy.check_policy` | `always` | — |
| `INV-ST03` | The `initial` state is declared AND is a spending state. | artifact | `policy.check_policy` | `always` | — |
| `INV-ST04` | Every spending state can reach `exception` (when `exception` exists). | artifact | `policy.check_policy` | `always` | — |
| `INV-ST05` | No `when` clause is empty (an empty guard fires unconditionally and shadows every later rule for the same `from`). | artifact | `policy.py` comment at the empty-guard check | `always` | — |
| `INV-ST06` | A `when` predicate dict carries exactly one operator per key. | artifact | `policy.check_policy` | `always` | — |
| `INV-ST07` | `response` and `held_out` are a structural split: no metric named `held_out` appears in `response`. | function | `runner.RunOutcome` docstring ("fitting-safe by construction") | `always` at `_run_row`; `test` for the property | — |
| `INV-ST08` | A `RunOutcome` with `status != "complete"` carries a non-empty `failure_kind`; a `complete` row carries `""`. | function | `runner.RunOutcome.failure_kind` docstring | `always` | — |
| `INV-ST09` | `report.json` always carries a `recommendation.basis`, and it is one of the six declared values. | artifact | `stage_runner._run_report` ladder; CLAUDE.md | `always` | — |
| `INV-ST10` | Every field the producer writes is declared by the consumer's schema — verified against a row from the REAL code path, never a hand-written dict. | artifact | `runs_row.schema.json`'s `additionalProperties: false` vs what `_run_row` writes | `always` | **yes** |

## 3. Closed vocabulary (`INV-VOC`)

| ID | Statement | Level | Evidence | Checked | Defect? |
|---|---|---|---|---|---|
| `INV-VOC01` | Every `when` clause's observation key is in `OBSERVATION_KEYS`. | artifact | `policy.check_policy`; spec §3.2 | `always` | — |
| `INV-VOC02` | Every `when` predicate's operator is in `COMPARISON_OPS` (`>`, `>=`, `<`, `<=`) — deliberately narrower than `predicates.OPS`, which also has `==`/`!=`. | artifact | `policy.COMPARISON_OPS` docstring; spec §3.2 | `always` | — |
| `INV-VOC03` | `COMPARISON_OPS ⊆ predicates.OPS`. A policy `check_policy` refuses must not be one `step` can still drive. | module | `policy.py` comment above the `_OP_FUNCS` import | `always` | — |
| `INV-VOC04` | Every member of `OBSERVATION_KEYS` has a named consumer: a registered transition, an artifact field, or a documented non-branching note. No dead vocabulary that reads like a live guard. | module | `policy.OBSERVATION_KEYS` docstring, which names `runs_needed_confirm` as having been exactly this for six tasks | `test` | **yes** — `runs_needed_confirm` |
| `INV-VOC05` | Every `RunOutcome.failure_kind` value is in `FAILURE_KINDS` and in the `runs_row.schema.json` enum — the two sets are equal. | module | `runner.FAILURE_KINDS` docstring ("CLOSED for the same reason `OBSERVATION_KEYS` is") | `always` | — |
| `INV-VOC06` | Every `RunOutcome.status` is one of `complete`/`failed`/`infeasible`/`rejected`. | function | `runner.RunOutcome.status`; spec §6.4 | `always` | — |
| `INV-VOC07` | `behavioral_violation` is in `OBSERVATION_KEYS` and is read by NO `when` clause — it is a reporting key, deliberately non-branching. | artifact | `policy.py`'s `behavioral_violation` note; `stage.decide_after_screen` | `always` | — |
| `INV-VOC08` | A closed vocabulary's producers and consumers agree: no consumer compares against a value no producer can emit, and no produced value falls through every consumer. | module | the `n_excluded == "excluded"` regression in `_finish_confirm` | `always` | **yes** |

**`INV-VOC08` — the defect class, and why it needs its own invariant.** A
status literal produced in one place and compared in another is a reference
with no referential integrity, and nothing in the toolchain checks it: not a
schema, not a type checker, not a unit test that exercises the producer and the
consumer separately. The finalist-status vocabulary in `_finish_confirm` was
split from a single `"excluded"` into `"infeasible"` / `"unmeasured"` — a
correct change, because a timed-out finalist was being reported as though it had
violated a constraint, which is the opposite claim about a configuration. But
the consumer three hundred lines later still read the retired literal:

```python
n_excluded = sum(1 for v in status.values() if v == "excluded")
```

`n_excluded` silently became 0 for every campaign. Nothing withheld
certification, the registered `confirm -> confirm` top-up never fired, and the
`sla` synthetic surface **certified** an answer 6.12% off the true constrained
optimum. Only the end-to-end synthetic oracle caught it, after the fact.

The general form is cheap to check — collect what the producer can emit,
collect what the consumers compare against, require the second to be a subset
of the first — and it would have failed at test time rather than via an
oracle. Both directions are reported and they mean different things:
consumed-but-never-produced is a **dead branch** (the defect above);
produced-but-never-consumed is an **unhandled case**, which is how a newly
added status falls through a dispatch that has no arm for it.

The vocabularies in this module with the same exposure, and therefore worth
binding: finalist `status` (`ok`/`infeasible`/`unmeasured`),
`recommendation.basis` (6 values, also a schema enum), `FAILURE_KINDS` (also a
schema enum), `RunOutcome.status`, `certification_withheld`'s reason labels,
`concurrency.BASES`, `OBSERVATION_KEYS`, and `COMPARISON_OPS`. The two that
already have a schema enum are the *least* exposed, because the enum is a second
declaration a producer can be validated against — which is itself an argument
for giving the others one.

**`INV-ST08` — a correction to an earlier framing.** An earlier version of this
claim said failed rows carried no cause. That was **wrong**: `error` was always
populated and always written. The real gap was narrower — a timeout and an
adapter crash both surfaced as `RuntimeError: config run ...`, so telling them
apart meant substring-matching prose the raise site is free to reword. That is
what `failure_kind` fixes, and the invariant is about the closed *label*, not
about the presence of a cause.

## 4. Semantic / accounting (`INV-SEM`)

| ID | Statement | Level | Evidence | Checked | Defect? |
|---|---|---|---|---|---|
| `INV-SEM01` | `residual_regret_model` and `residual_regret_terminal` are separate fields in `report.json` and are never collapsed into one number. `Pr(wrong global decision) ≤ δ_s + δ_t` is only meaningful while they stay apart. | artifact | `certificate.py` module docstring; spec §3.5; CLAUDE.md | `always` | — |
| `INV-SEM02` | A `null` bound means "not estimable". An unknown is never reported as a zero. | artifact | `certificate.py` ("an unknown is not a zero"); spec §3.5 | `always` for the model bound; **VIOLATED** for the terminal bound | **yes** — see `INV-SEM02`'s note below |
| `INV-SEM03` | `δ_s` and `δ_t` are reported with their own bounds and are never summed into a single reported δ. | artifact | spec §3.5 | `always` | — |
| `INV-SEM04` | A semantic exception removes ONLY the `model` rung of the ladder. Rungs 1/2 (terminal) and 4/5 (measured/baseline) are unaffected, and the report still names an action. | artifact | `stage_runner._run_report`'s `epoch_ended` comment; CLAUDE.md | `always` | — |
| `INV-SEM05` | Every conditional transition names an `accounting` rule. An adaptive branch with no named inferential accounting rule does not ship. | artifact | `policy.check_policy`; spec §5 non-goals | `always` | — |
| `INV-SEM06` | A missing or `None` observation NEVER matches a guard — unknown is not a fact. An omitted key is not the same as a zero or a `False`. | function | `policy.step` / `_match_one` docstrings | `always` | — |
| `INV-SEM07` | `significant is None` (unknown) is never treated as `significant is False` (measured null). An unknown effect is never dropped as if known-absent. | module | `stage.py` module docstring | `test` | — |
| `INV-SEM08` | An alias's re-attributed coefficient carries its `sign`: re-labelling `AB`'s estimate as `C` while keeping the sign reverses the physical direction of the effect. | function | `effects.Effect.aliased_with` ("THE SIGN IS LOAD-BEARING AND IS NOT DECORATION") | `always` | — |
| `INV-SEM09` | A failed `behavioral` relation is never folded into the `correctness` bucket: behavioral failures advance the stage, correctness failures abort. | function | `relations.classify_failures`; `stage_runner._assert_all_behavioral` | `always` | — |
| `INV-SEM10` | A declared relation absent from the results is a FAILURE, never a pass. A typo'd `native_test` must not silently disable a correctness gate. | function | `relations.py` ("The load-bearing rule") | `always` | — |
| `INV-SEM11` | Contract drift is a campaign ABORT, not a row failure: re-running a row against a changed instrument produces a number that still cannot be compared to rows measured before the change. | epoch | `adapter_contract.AdapterContractDrift` docstring | `always` | — |
| `INV-SEM12` | `null` is its own fingerprint type. `{"slope": 0.4}` and `{"slope": null}` must not fingerprint alike. | function | `adapter_contract._type_name` ("that is the whole point") | `always` | **yes** — defect 4 |

**`INV-SEM02` — the violation.** `certificate.model_regret_bound` returns
`RegretBound(None, ..., method="none")` when `pure_error_df <= 0`, correctly
refusing to certify from no variance estimate.
`certificate.terminal_regret_bound` does **not** have the equivalent guard: on
bit-identical replicates (the deterministic target of spec §3.5, which is a
*measured* condition, not a hypothetical) every `variance()` is 0, so `se` is
0, so the bound comes back `value=0.0` with
`method="bonferroni_one_sided_t_paired"` — a claim of exact ε-optimality
derived from zero information, wearing the label of a real t-based
certificate. Its own docstring says "`value=None` when any finalist has fewer
than two replicates: a single measurement gives no variance estimate, and an
unknown is not a zero" — four identical measurements give no variance estimate
either. See `INV-STAT05`.

## 5. Statistical (`INV-STAT`)

| ID | Statement | Level | Evidence | Checked | Defect? |
|---|---|---|---|---|---|
| `INV-STAT01` | One fitted coefficient per ALIAS CLASS, not per two-factor interaction. A resolution-IV design must not make `XᵀX` singular. | function | spec §4 D1 | `always` at the fit; `test` over every tabulated `(k, resolution)` | **yes** — D1 |
| `INV-STAT02` | No fitted coefficient is NaN. A single NaN response must not poison every coefficient while returning a schema-valid `Fit`. | function | spec §4 D2 | `always` at the `stage_runner` caller; **module boundary still poisons** | **yes** — D2, partially open |
| `INV-STAT03` | A residual-regret bound is never negative. The gap to the true optimum cannot be below zero. | function | `certificate.model_regret_bound` / `terminal_regret_bound` ("floors at 0.0") | `always` | — |
| `INV-STAT04` | A bound is non-decreasing as δ shrinks. A stronger confidence requirement cannot produce a narrower certificate. | function | implied by the t-quantile; spec §3.5 | `test` (property, `hypothesis`) | — |
| `INV-STAT05` | A bound computed from a zero-variance sample is `None`, not `0.0` — the deterministic-target case of spec §3.5. | function | spec §3.5 ("`pure_error = 0` and every interval came back `None`") | **VIOLATED** for the terminal bound; checker present and failing | **yes** |
| `INV-STAT06` | More replicates never widen a bound; fewer rows never narrow it. Dropping information can only widen uncertainty. | function | spec §2.5 minimum information loss | `test` (property) | — |
| `INV-STAT08` | Row exclusions from the fit are independent of factor levels. A level-correlated exclusion set is a confounded design, not a reduced one. | iteration | historical defect 6 (two timeouts on the same corner, perfect 2×2 separation, nothing detected) | `always` — delegated to `orchestrator.optimize.exclusions` (Agent A) | **yes** — defect 6 |
| `INV-STAT09` | Every excluded row is recorded in `fit_exclusions.json` with its index and reason. No infeasible row is dropped without record. | iteration | spec §2.5; `stage_runner` fit-exclusion block | `always` | **yes** — D2 |
| `INV-STAT10` | A fit is refused rather than attempted when fewer than 2 rows survive exclusion. | function | `stage_runner`'s `len(keep) < 2` abort | `always` | — |
| `INV-STAT11` | Sign symmetry: negating every response and flipping `direction` yields the identical bound. | function | metamorphic property over `certificate` | `test` (property) | — |
| `INV-STAT12` | The terminal bound never RAISES on an admissible sample: a variance it cannot estimate is `None`, not an exception. | function | `certificate.terminal_regret_bound`'s Welch df denominator | `test` | **yes** |

**`INV-STAT12` — a crash on the certification path, found by the property test.**
The Welch degrees-of-freedom denominator is `(vk**2)/(nk-1) + (vb**2)/(nb-1)`,
guarded only by `if (vk + vb) > 0`. For subnormal-magnitude variances that guard
passes while `vk**2` **underflows to exactly `0.0`**, so the denominator is zero
and `terminal_regret_bound` raises `ZeroDivisionError`. Minimal input: two
finalists whose replicates are `[-3.117993501313441e-82, 0.0]`, giving
`vk == vb == 2.43e-164`. A campaign reporting its objective in tiny absolute
units (a fraction, a normalized rate) can reach this, and the consequence is an
unhandled exception where the honest answer is a bound of `None` — the same "not
estimable" verdict spec §3.5 requires for a variance it cannot obtain. The
paired branch divides by `n` rather than by a squared variance and survives the
same input, which localises the defect. The guard should test the
**denominator**, not the sum of the variances. Found by the hypothesis property,
not by construction — which is the argument for the property tests.

**`INV-STAT02` — how far the fix reaches.** Spec §4 D2 is fixed *at the
`stage_runner` call site*: rows carrying NaN are dropped and named in
`fit_exclusions.json`. `effects.fit_effects` itself is unchanged — handed a
NaN response directly it still returns a `Fit` whose every coefficient is NaN,
with no raise and no warning. Verified: `[1.0, 0.5, 0.0]` becomes all-NaN.
That is defensible as a division of labour (the caller owns admissibility),
but it means the invariant is enforced at exactly one of the module's callers,
and the *next* caller inherits the defect. `check_fit_has_no_nan` in the
registry makes the module-boundary version checkable, classified `always` at
any site that fits.

## 6. Temporal / ordering (`INV-TMP`)

| ID | Statement | Level | Evidence | Checked | Defect? |
|---|---|---|---|---|---|
| `INV-TMP01` | `policy.json` + `policy.sha256` are written BEFORE the first benchmark run of the epoch. That ordering IS the pre-registration. | epoch | spec §3.1; CLAUDE.md | `always` at `execute_design` entry; `audit` post hoc | — |
| `INV-TMP02` | `transitions.jsonl` is append-only across epochs. An exception must not truncate it. | campaign | `policy.epoch_transitions` docstring | `audit` | — |
| `INV-TMP03` | Every consumer asking "what has happened so far?" means "so far IN THIS EPOCH" — `epoch_transitions`, never `read_transitions`. | module | `policy.epoch_transitions` ("One filter, one place, so the two cannot drift") | `test` | — |
| `INV-TMP04` | The adapter contract is captured from the first SUCCESSFUL row of the epoch, never from a `failed`/`infeasible`/`rejected` one. | epoch | `runner.py`'s guards-run-LAST comment; `adapter_contract` guard 1 | `always` | — |
| `INV-TMP05` | Freshness compares against the IMMEDIATELY PRECEDING row that produced a usable measurement, never against the whole history. | epoch | `adapter_contract.check_freshness` | `always` | — |
| `INV-TMP06` | `confirm`'s `round` observation is 1-based and counts rounds SPENT INCLUDING THE CURRENT ONE; `screen`/`refine` report `round: 0` because they cannot self-loop. | iteration | `stage_runner`'s OBSERVATION CONVENTIONS block | `test` | — |
| `INV-TMP07` | An epoch that ended on a semantic exception recompiles on the next resume and starts at `initial` — it never resumes at the terminal `exception`. | campaign | `_load_or_compile_policy`; `policy.current_state` | `always` | — |
| `INV-TMP08` | A transition row is appended for every state the epoch actually entered, INCLUDING one that aborted before its fit. An epoch that died must leave a record of why. | epoch | historical defect 7 | **VIOLATED** — abort paths raise before `_close_iteration` | **yes** — defect 7 |

**`INV-TMP08` — the 14-hour silence, and its trigger is lower than it looks.**
Defect 7 was `transitions.jsonl` completely empty after 14 hours, because every
iteration aborted before the fit and the transition write lives in the iteration
closer (`_close_iteration`). Every `OptimizationAborted` raised upstream of that
closer — the held-out leak, the non-numeric primary metric, contract drift —
unwinds past the only site that appends to the audit trail.

Reproduced empirically, and the **lowest-threshold gate is not the
`len(keep) < 2` abort** this prose originally cited: it is
`_fitting_responses`' "N of M runs produced no usable measurement", which fires
on **one** failed row out of twelve. Measured: five iterations, **60 benchmark
runs spent**, `transitions.jsonl` never created, no `epoch_end-*.json`, no
`report.json`. A single transient benchmark crash per iteration is enough to
produce the whole 14-hour silence — which makes this far likelier to be hit in
practice than the `len(keep) < 2` framing implies. The audit trail therefore records nothing about the one category of
failure a reader most needs it for. This is listed as VIOLATED rather than
fixed here because the fix is a change to `stage_runner`'s abort paths, which
this work does not own (Agent A owns the fit region); the registry provides
`check_transitions_nonempty_for_entered_states` as an `audit`-class checker so
the condition is at least detectable from a finished work-dir.

## 7. Provenance / identity (`INV-PROV`), resource (`INV-RES`), economic (`INV-ECO`)

| ID | Statement | Level | Evidence | Checked | Defect? |
|---|---|---|---|---|---|
| `INV-PROV01` | `policy.json` must **have** a `policy.sha256` sidecar **and agree** with it. Absence is as fatal as disagreement. | artifact | `_load_or_compile_policy`; CLAUDE.md | `always` on every stage | **yes** |
| `INV-PROV02` | `mechanism.sha256` and `policy.json`'s `compiled_from.mechanism_patch_hash` agree. Two records of one commitment must not be individually well-formed and jointly meaningless. | artifact | `stage_runner`'s "Two records of ONE commitment" comment | `always` | — |
| `INV-PROV03` | `adapter_contract.json` must have a sidecar and agree with it. Inherits `INV-PROV01`'s conditional hole — `read_contract` guards with the same `sidecar.exists() and`. | artifact | `adapter_contract.read_contract` | `always` | — |
| `INV-PROV04` | Every `transitions.jsonl` row carries the `policy_hash` it ran under, so "which policy scheduled this design?" is answerable for every epoch, not only the current one. | artifact | `_close_iteration`; `_load_or_compile_policy` | `always` | — |
| `INV-PROV05` | A fingerprint's hash equality does not depend on dict insertion order. | function | `adapter_contract.build_cache_key` comment | `test` (property) | — |
| `INV-RES01` | A per-run config patch is a COPY. The input document is never mutated, so a caller holding the parsed doc is safe. | function | `config_patch` ("Pure: the input document is never mutated") | `always` | — |
| `INV-RES02` | A level is serialized in its native type, never through `str()`. An int level stays an int. | function | `config_patch` ("never stringified"); the bool/int mismatch that failed 67 of 67 runs | `always` | — |
| `INV-RES03` | `config_patch` never CREATES structure: a pointer that does not exist is a `ConfigPatchError`, never a silent no-op. | function | `config_patch` line ~107 | `always` | — |
| `INV-RES04` | No two concurrent rows share a filesystem path or a build output. Two rows patching the same file must never collide. | iteration | `config_patch` line ~292; `stage_runner` line ~246 | `always` — delegated to `orchestrator.optimize.concurrency` (Agent B) | — |
| `INV-RES05` | Run-order randomization uses a local `random.Random`, never global module state, so the same seed always yields the same order and global state is unperturbed. | function | `matrix.randomize` | `test` (property) | — |
| `INV-RES06` | `duration_ms` is monotonic-clock derived, **positive** on any row that ran, and `0` is RESERVED for "did not run" (floored at 1ms). Populated at EVERY construction site including the failing ones. | function | `runner.RunOutcome.duration_ms` docstring | `always` | **yes** — defect 3 |
| `INV-ECO01` | ZERO model calls inside any compiled epoch state, for any reason, including "just to interpret a result". A semantic exception ends the epoch instead of improvising. | epoch | spec §2.2, §5; CLAUDE.md ("the single most important invariant in the kind") | `always` — import-graph check; `test` | — |
| `INV-ECO02` | `compile_policy` is a pure function of the campaign: zero tokens, no measurement read, same input → same hash. | function | spec §3.1; `policy.compile_policy` | `always` | — |
| `INV-ECO03` | `budget_remaining` absent a declared `max_runs` means "unbounded", never "exhausted". A missing cap must never route a campaign to `report`. | iteration | `stage_runner`'s OBSERVATION CONVENTIONS | `test` | — |

**`INV-PROV01` — an undocumented conditional hole, verified end to end.** The
shipped guard is `if recorded.exists() and recorded.read_text().strip() != ...`,
so **deleting `policy.sha256` disables the check entirely** rather than failing
closed. Nothing downstream regenerates it or notices:
`_compile_and_write_policy` is reached only when `pol is None`, so the deletion
is not self-healing. Verified by tampering meaningfully — `screen`'s
`default: confirm` rewritten to `default: report`, removing terminal
discrimination from a pre-registered design — with the sidecar deleted:

```
screen ran, outcome: COMPLETED
transitions.jsonl:  epoch=1 screen->report policy_hash=98743536b78a4700
recorded policy_hash == TAMPERED hash: True
recorded policy_hash == HONEST hash:   False
report.json written (confirm was SKIPPED): True
  recommendation.basis: model
  confirmation.json anywhere?: NONE
policy.sha256 exists now: False
```

The epoch produced a `report.json` claiming `basis: model` with terminal
discrimination silently skipped, and the tampered hash was recorded in
`transitions.jsonl` as though it were the registration. A pre-registration whose
only proof of integrity can be removed by deleting a file is not a
pre-registration, so the invariant is restated above as *must have a sidecar AND
agree with it*. `read_contract` has the identical `sidecar.exists() and`
conditional, so `INV-PROV03` should be read the same way.

**`INV-SEM12` — the `null` guarantee is one level deep.** Verified to hold at
the top level: `float -> null` raises `AdapterContractDrift`, and `int`/`float`/
`bool`/`str` are all kept distinct. But nested *value types* are not
fingerprinted, so `{"telemetry": {"rate": 2.0}}` → `{"telemetry": {"rate":
null}}` gives `diff_contract == ([], [], [])` — defect 4's exact signature, one
level down. Nested *key sets* are covered (`object{depth,rate}` →
`object{NEW,depth}` fires), and `array[…]` is a sorted *set* of element kinds, so
`[1,2,3]`, `["a",1]`, and `[1,"a"]` are not distinguished. `_type_name`'s
docstring does say nesting is summarized one level deep, so this is documented —
but the prose "must not fingerprint alike" reads wider than what holds, and this
inventory says so rather than inheriting the overclaim.

**`INV-TMP05` — the freshness limit is real.** Verified: an adapter that echoes
its own configuration back cannot trip guard 2, because the echoed block makes
every canonical encoding differ even when the objective is byte-identical across
levels (measured: `objective: 1.3125` unchanged across `L1: 2 -> 4`, guard did
not fire). Declaring that block in `response.constant_fields` restores detection.
This is asserted in the guard's own docstring, and it is worth knowing that the
mitigation exists.

**`INV-SEM09` — enforced upstream of the public classifier.**
`relations.classify_failures` silently drops a verdict whose `kind` is
off-vocabulary: `RelationVerdict(kind="perf", passed=False)` lands in *neither*
bucket, so a failure would vanish. Not reachable through the real path —
`factors._check_relations` rejects any kind but `correctness`/`behavioral` at
parse time — but `classify_failures` is a public function, so "every failure is
classified" is a property of its *caller's* input validation, not of the
classifier. The registry's checker states that as a dependency rather than
assuming it.

---

## 8. Behaviors

An invariant says what must always hold. A **behavior** says what the system
should DO in a given situation. They fail differently: a violated invariant is
a contradiction, a wrong behavior is a *plausible* outcome that happens to be
the wrong branch — which is why the ones with a ladder or a taxonomy are where
a wrong branch is invisible.

Each row: trigger → expected outcome → the artifact that records it → test
reference.

### 8a. The `recommendation.basis` ladder

Six values for spec §3.6's four rungs. Evaluated top-down; the FIRST condition
that holds wins. `report.json` always carries exactly one.

| Basis | Trigger | Expected outcome | Recorded in | Test |
|---|---|---|---|---|
| `certified` | `confirmation.json` exists with a `best`, and `certified` is true (`R_t ≤ ε`). | The terminally-discriminated winner, with `residual_regret_terminal ≤ epsilon`. | `report.json.recommendation`, `certified: true` | `BEH-BASIS-01` |
| `terminal_best` | `confirmation.json` exists with a `best`, `certified` false. | Same winner, uncertified. Still a measured configuration compared against measured rivals. | `report.json`, `certified: false` | `BEH-BASIS-02` |
| `model` | No confirmation; a `recommendation.json` with `levels`; **AND** no semantic exception ended the epoch; **AND** those exact levels have not been measured infeasible. | The fitted argmax with its model bound. The ONLY rung resting on the fitted surface. | `report.json`, `residual_regret_model` | `BEH-BASIS-03` |
| `measured` | The model rung is unavailable (no recommendation, or `epoch_ended`, or the argmax was measured infeasible) and some `complete` row exists. | The best measured VALID configuration — never the largest noisy observation; `_best_observed` filters to `complete`. | `report.json` | `BEH-BASIS-04` |
| `baseline` | Nothing above survives, and the policy carries a `known_valid_baseline`. | The author's known-good configuration. | `report.json` | `BEH-BASIS-05` |
| `none` | Not a rung. No baseline was declared, so there is genuinely nothing legal to return. | Empty levels, and saying so rather than inventing an origin. | `report.json` | `BEH-BASIS-06` |

**The rule that is easy to get wrong** (`INV-SEM04`): a semantic exception
removes ONLY the `model` rung, because the fitted surface is precisely what the
exception impeached. Rungs 1/2 are measurements of a shortlist against itself
and do not consult the surface, so an exception at a later state does not
retract a terminal comparison that actually happened. And the report ALWAYS
names an action — the pre-ladder behavior (raise, no `report.json` at all) is
the defect the ladder exists to fix.

### 8b. Row-outcome taxonomy

Four statuses. Three of the four are excluded from the fit, and they are
excluded for **three different reasons** — collapsing them is how defect 2's
NaN reached the coefficients.

| Status | Meaning | Effect on the fit | Retained as information? | Test |
|---|---|---|---|---|
| `complete` | Ran, parsed, every manipulation predicate and design-space invariant held, under the ceiling, within constraints, all three adapter guards clean. | Included. | yes | `BEH-ROW-01` |
| `failed` | A MEASUREMENT failure: timeout, non-zero exit, unparseable output, adapter exception, manipulation retry exhausted, or an adapter freshness / self-check violation. | Excluded, recorded in `fit_exclusions.json`. | Says nothing about the design space — a re-run can repair it. | `BEH-ROW-02` |
| `infeasible` | A `response.constraints` violation. The configuration is INADMISSIBLE. | Excluded (spec §6.4) — but this is real, trustworthy information about `X_valid`, and `decide.ranked` uses it to exclude the point from the candidate space. | **yes, load-bearing** | `BEH-ROW-03` |
| `rejected` | Untrustworthy instrumentation: a `design_space.invariants` violation, above the physical ceiling, or a failed integrity check. | Excluded. | No — the reading itself is not believable. | `BEH-ROW-04` |

The discriminator between `infeasible` and `rejected` is **whose fault it
is**: `infeasible` says the *configuration* is illegal (believe the
measurement, exclude the point), `rejected` says the *measurement* is illegal
(disbelieve the measurement, say nothing about the point).

### 8c. The three adapter guards and their consequences

Three guards, three different blast radii. Getting the radius wrong is the
whole risk: a drift treated as a row failure produces numbers that silently
cannot be compared.

| Guard | Trigger | Consequence | Why that radius | Recorded in | Test |
|---|---|---|---|---|---|
| 1 — contract drift | A top-level key appears, disappears, or changes TYPE (including a real value becoming `null`) versus the epoch's first successful row. | **Campaign ABORT** (`AdapterContractDrift` → `OptimizationAborted`), on exactly the path a `policy.sha256` mismatch takes. | A row failure means "re-run this configuration"; re-running against a changed instrument produces a number that still cannot be compared to rows measured before the change. The damaged rows are the ones measured BEFORE the edit, which is why an ADDED key aborts too. An apparatus change is an epoch boundary, not an edit. | `adapter_contract.json` + `.sha256` | `BEH-GUARD-01` |
| 2 — output freshness | A response byte-identical to the immediately preceding successful row's, while the factor levels differ. | **ROW failure** (`status="failed"`, `failure_kind="adapter_guard"`). | It is a signal about one reading, not about the instrument's contract. `response.constant_fields` are excluded, which makes the check stricter on what remains. Documented limit: cannot fire for an adapter that echoes its own configuration back. | `runs.jsonl` row | `BEH-GUARD-02` |
| 3 — declared self-check | A `response.self_check` predicate is false for this row. | **ROW failure**, verdicts recorded per-row. | In the real defect, 4 of 12 rows were sound — a campaign abort would have discarded the 4 good rows along with the 8 bad ones. Also evaluated by `--smoke`/`--liveness`, so a violated invariant surfaces pre-registration. | `runs.jsonl`'s `self_check` | `BEH-GUARD-03` |

Note that only guard 1 raises out of the loop, and `stage_runner` converts it
to `OptimizationAborted` rather than routing it to the `exception` branch: the
exception branch still returns an action from the fitted surface, and a surface
fitted over two different instruments has no action to certify.

### 8d. Semantic exception vs measurement failure vs campaign abort

Three things routinely confused. The discriminator is **what a re-run would
accomplish**.

| | Semantic exception | Measurement failure | Campaign abort |
|---|---|---|---|
| **Discriminator** | No further measurement INSIDE this epoch can repair it. The condition is about MEANING — the interface, the objective, or the design's range is wrong. | Re-running the configuration repairs it. Nothing semantic has been discovered. | The apparatus or the pre-registration is broken, so no measurement in this work-dir is interpretable. |
| **Scope** | Ends the EPOCH. Campaign continues and still returns an action. | Ends the ROW. | Ends the CAMPAIGN. |
| **Examples** | `stationary_in_hull: false` (the fitted optimum is an extrapolation past the declared range); `nan_response: true` (the objective and the instrumentation disagree about what is measurable there); an observation key outside `OBSERVATION_KEYS`. | Timeout; non-zero exit; unparseable output; manipulation retry exhausted; freshness violation; self-check violation. | `policy.sha256` mismatch; adapter contract drift; `primary` also declared `held_out`; a held-out metric reaching a fitting input; a non-numeric-but-not-NaN primary metric; fewer than 2 rows surviving exclusion. |
| **Artifact** | `epoch_end-<epoch>.json` (why + `next_epoch_requires`) plus `report.json` on the strongest non-model rung. | `runs.jsonl` row with `status` and `failure_kind`. | Nothing new. **This is `INV-TMP08`'s gap** — the audit trail records nothing. |
| **Recovery** | Revise the campaign out of band; `nous run --resume` recompiles and starts a fresh epoch at `initial`. | Re-run the row. | Fix the apparatus; an apparatus change is an epoch boundary. |
| **Test** | `BEH-EXC-01` | `BEH-EXC-02` | `BEH-EXC-03` |

The `nan_response` case is the sharpest illustration of the boundary, and
`_fitting_responses`' docstring draws it explicitly: a NaN on a row that ran to
COMPLETION is semantic (ends the epoch, campaign still reports), while a row
that never reached `complete` is a measurement failure (re-run repairs it), and
a primary metric that is a *string* is a campaign abort (instrumentation
mismatch, not a measurement). Three outcomes from three shades of "the number
is not a number".

---

## 9. Counts

Generated from the registry; `test_document_and_registry_do_not_drift` fails if
they disagree.

| Type | Count | `always` | `paranoid` | `test` | `audit` |
|---|---|---|---|---|---|
| Structural (`INV-ST`) | 10 | 10 | 0 | 0 | 0 |
| Closed vocabulary (`INV-VOC`) | 8 | 7 | 0 | 1 | 0 |
| Semantic (`INV-SEM`) | 12 | 11 | 0 | 1 | 0 |
| Statistical (`INV-STAT`) | 11 | 7 | 0 | 4 | 0 |
| Temporal (`INV-TMP`) | 8 | 4 | 0 | 2 | 2 |
| Provenance (`INV-PROV`) | 5 | 4 | 0 | 1 | 0 |
| Resource (`INV-RES`) | 6 | 5 | 0 | 1 | 0 |
| Economic (`INV-ECO`) | 3 | 2 | 0 | 1 | 0 |
| **Total** | **63** | **50** | **0** | **11** | **2** |

By level: `function` 24, `module` 6, `artifact` 20, `iteration` 5, `epoch` 6, `campaign` 2. Checkable (a
checker function exists): 41 of 63. The 22 without one are
recorded with a `note` saying WHY — an invariant enforced by construction, by an
exception type, or by a call-site discipline is real, and dropping it because it
resists a checker would make the inventory a list of what is easy to check
rather than of what must hold.

**Open violations — invariants the current code is known to break** (5):
`INV-SEM02`, `INV-STAT05`, `INV-STAT12`, `INV-TMP08`, `INV-PROV01`. Queryable as
`invariants.open_violations()`. A disclosed violation is worth more than a hidden
one: it tells a reviewer which guarantees not to rely on, and the next owner
where the work is.

**One entry was REMOVED after refutation**, and that is a feature of the process
rather than an embarrassment: `INV-STAT07` (the CRN-tightening claim) failed
three successive formulations under property testing and is demoted to §10. An
inventory that only ever grows is not being tested against the code.

Historical defects covered: 7 of 7 (D1 → `INV-STAT01`; D2 → `INV-STAT02` /
`INV-STAT09`; `duration_ms` → `INV-RES06`; mid-epoch adapter edit →
`INV-SEM12` / `INV-SEM11`; three-failed-rows abort → `INV-STAT09` /
`INV-STAT10`; level-correlated timeouts → `INV-STAT08`; empty
`transitions.jsonl` → `INV-TMP08`). Plus two found during this work:
the `n_excluded` vocabulary drift → `INV-VOC08`, and the schema-vs-producer
mismatch → `INV-ST10`.

## 10. Prose that is NOT an invariant

Statements found in the module's docstrings that read like invariants but are
not, and should be rewritten or dropped rather than given an ID. Recording
them here is the point: an inventory that silently omitted them would leave
the reader believing they are checked.

| Prose | Where | Why it is not an invariant |
|---|---|---|
| "Uses the paper's own vocabulary consistently" | CLAUDE.md | A style convention. Real and worth keeping, but a naming preference cannot be violated by a value at runtime. |
| "the measurement path is already race-free" | `resolve_max_parallel` | A claim about the *current* implementation, offered as a premise and then explicitly set aside ("It is the statistics"). Not the reason for the behavior, so nothing enforces it. |
| "Bonferroni is conservative … the true simultaneous quantile is smaller" | `certificate.py` | A true statement about the method's slack. Directional, not a bound — there is no threshold to check. |
| "the intercept and `A²`/`B²` are optimistic by a factor of about 1.46" | `effects.py` | Measured on one specific 2-factor CCD with 3 centre points. A calibration note, not a general property; the docstring now says so, and the constant must not be read as a checkable ratio. |
| "a duplicate must not pass" | `matrix.py` ~248 | Genuinely an invariant but about `ConfigRow` identity, already fully enforced by the code it annotates. Given no ID because there is no seam where it could be violated without the annotated line being deleted — a checker would test the language, not the system. |
| "never let logging break the gate" / "must never be the reason a campaign fails" | `runner.py` ~1034, ~1184, ~1294 | A defensive-coding policy over diagnostics helpers. Checkable only as "does this function have a bare except", which is a lint rule, not an invariant over values. |
| "`stage_runner` … no longer decides anything inside the epoch" | `stage_runner.py` ~66 | Aspirational and currently **false in one narrow sense**: `stage_runner` decides that contract drift aborts rather than routing to `exception`. That is a deliberate, documented exception to the rule, but the prose states the rule absolutely. Rewrite to "decides no NEXT STATE inside the epoch" — which is the true and checkable form, and is what `INV-ECO01`'s sibling rule in CLAUDE.md actually says. |
| "`confirm` is the paper's `discriminate`" | CLAUDE.md, spec §3.3 | A naming mapping. Load-bearing for a reader, not checkable. |
| "an unpaired comparison on a noisy server needs an order of magnitude more runs for the same bound" (the CRN tightening claim) | spec §3.8; `certificate.terminal_regret_bound` | **Refuted as an invariant.** Held the ID `INV-STAT07` until a property test refuted all three formulations of it — see below. |

**The CRN claim, refuted three times.** This one earned its own note because it
is the clearest argument in this work for property tests over example tests. The
statement "a paired (CRN) bound is never wider than the unpaired bound on the
same samples" was registered as `INV-STAT07`, straight from spec §3.8's
rationale. Hypothesis refuted it, then refuted both repairs:

1. unconditional → refuted at n=2 (paired **6.3137** vs unpaired **2.0647**);
2. "at n ≥ 4" → refuted at n=7 (**0.4240** vs **0.3601**);
3. "under an actually shared seed effect" → refuted at n=4 even with a shared
   component (**0.006767** vs **0.001870**).

The mechanism is that pairing changes two things in opposite directions: it
removes the shared seed effect from the variance (the benefit) *and* collapses
the degrees of freedom from Welch's `~n_k + n_b − 2` to `n − 1` (the cost).
Which dominates depends on the **ratio** of shared to independent variance, so no
unconditional statement over `n`, or over "the seeds were shared", can be true.
Measured across regimes, 600 trials each — fraction of cases where the **paired
bound is wider**:

| `shared_sd` | `noise_sd` | n=4 | n=8 | n=16 |
|---|---|---|---|---|
| 3.0 | 0.3 | 2/600 | 0/600 | 0/600 |
| 3.0 | 1.0 | 19/600 | 3/600 | 0/600 |
| 1.0 | 1.0 | 179/600 | 75/600 | 24/600 |
| 0.3 | 3.0 | 360/600 | 338/600 | 323/600 |

CRN pays when the shared component **dominates** the independent noise, and is a
net loss when it does not — 60% of the time in the last regime. That is a real
engineering fact about when to spend on workload seeds, and it is not what §3.8's
flat claim says. It is a **tendency**, not an invariant, so it is recorded here
rather than as a registry entry a checker would have to lie about;
`test_crn_tightening_is_a_TENDENCY_not_an_invariant` asserts the refutation so the
demotion cannot be quietly reverted.
