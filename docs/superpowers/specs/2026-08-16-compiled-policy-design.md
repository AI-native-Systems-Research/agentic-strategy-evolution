# Compiled experimental policy — design spec

Status: accepted, not yet implemented. Target branch `nousko`, PR #302.
Companion plan: `docs/superpowers/plans/2026-08-16-compiled-policy.md`.
Paper: `../papers/nousko/paper.{tex,pdf}` (read §Introduction; the method is
entirely in the introduction and the two figures).

**Read this file before executing the plan.** It records *why* each decision was
taken. The executing session should need neither the originating conversation nor
the paper.

---

## 1. The gap

`kind: optimization` on `nousko` implements the paper's **semantic boundary** and
its **token economics**. It does not implement the paper's **decision layer**.
Measured on a real campaign: 115 configurations for ~$0.38, zero model calls in
`screen`/`refine`/`confirm`. That half works.

| Paper | Branch today | Gap |
|---|---|---|
| Policy compiled to an immutable state machine; one execution is an *epoch* | Hard-coded `screen → refine → confirm` ladder in `stage_runner.run_stage` | No policy object, no registration, no `step()` |
| `recommend()` = `argmax` over `X_valid`, deterministic, no model judgment | `confirm` replicates a solved stationary point, or best-observed | No enumeration; a saddle point is reported as an optimum |
| Residual regret `R_δ(x) = max_z U_δ(z,x)`; certify ε-optimal | Point estimate + `confirmed_is_best_observed` flag | **No bound of any kind** |
| Terminal discrimination: shortlist `S`, fresh measurements, comparison independent of the fitted model | One configuration replicated | Final claim rests entirely on the response model |
| Aliasing is a resource question: resolve only when it can change the winner; spend a registered foldover when it can | Validator *warns* that res-IV aliases 2fis | No alias record, no consequence test, no foldover |
| `Pr(wrong decision) ≤ δ_s + δ_t`, reported separately | Neither term exists | No error budget |
| Registered adaptive branches, each naming its inferential accounting rule | `Trigger` enum, documented as "reported, not acted on" | Diagnosis without action — a real campaign hit this |
| Fallback ladder ending at `known_valid_baseline` | Abort | A campaign that cannot certify returns nothing |
| Semantic exception ends the epoch | No epoch concept | Cannot end cleanly and recompile |

Also, and this drives Phase 0: the guide claims `verify` "writes mechanism code
with native tests" and `confirm` spends "one analyze call". Neither is true.
`verify` is pure Python; `confirm` makes no model call. Those sentences are
**phantom claims** and must go before anything else lands, because a plan that
builds on a false description of the current state compounds the error.

## 2. Goals, in priority order

Ties break toward the earlier goal.

### 2.1 Oracle-first
No paper mechanism is implemented before a synthetic surface exists that
*fails* without it and *passes* with it. Every claimed capability must be
falsifiable on a target whose truth is known in closed form. This is the
lesson of the last two weeks: fourteen defects reached real campaigns because the
test suite injected fakes at exactly the seams that were broken, and every one of
them was schema-valid on the way out.

### 2.2 Minimum model tokens
`T = Σ_e (T_author,e + T_compile,e)`, and **`T_compile = 0`**: compilation is
pure Python at the end of `verify`. No benchmark-spending state may invoke a
model. This is already true and must stay true; `step()` must therefore be a
pure function of the policy and the observation vocabulary.

### 2.3 Correctness gates evidence
A fast configuration cannot win on invalid evidence. Preserve the existing
three-way contract split — semantic (`X_valid` membership), apparatus
(measurement admissibility), behavioral (falsifiable, may fail *because* the
system revealed something useful). Behavioral surprise triggers confirmation or
augmentation; it never invalidates evidence for being surprising.

### 2.4 Optimality with a certificate
Always name an action. Attach `R_δ(x̂)`. Certify ε-optimal when
`R_δ(x̂) ≤ ε`. A recommendation is not a certificate, and the absence of a
certificate must not prevent a decision.

### 2.5 Minimum information loss
Every completed run's information reaches the decision. No silent NaN, no
infeasible row dropped without record, no aliased term discarded without the
alias written down. *(The originating brief said "maximize information loss";
that was read as minimize — the inverse is nonsense. Flag if otherwise
intended.)*

### 2.6 Systems-target readiness
The kind must be usable on inference servers, vector databases, and serverless
autoscalers without per-target Python. That means: workload seeds as
first-class, common random numbers for paired comparison, and an adapter
contract a target author can satisfy with a CLI and one JSON line.

### 2.7 Behaviour-preservation is not a goal (added after Task 6)
**`nous` itself has not GA'd — repo-wide, not just this kind, not just this
branch.** This is now a top-level rule in `CLAUDE.md` ("Pre-GA: achieving
goals outranks preserving behaviour"); this subsection is a pointer plus
its specific bearing on this plan, not a separate or narrower rule.
**Correctness against this spec and the paper's method outranks matching
what `nousko` does today.** Where the two
conflict — a legacy code path that produces a *wrong* answer, an abort that
a correct compiled policy would not hit, an assertion that encoded the old
index-based scheduler's behaviour rather than a real requirement — fix it
and update the semantic version; do not contort the new mechanism to
reproduce the old defect.

This is a **priority change, not a license to regress silently**: still
name every observable difference from `nousko`'s current behaviour in the
task report, still explain why the new behaviour is correct, and the task
reviewer still checks that reasoning — the bar moves from "does not deviate"
to "deviates for a stated, correct reason." An unexplained behaviour change
is still a defect; an explained, spec-correct one is no longer a risk to
justify against a behaviour-preservation bar that does not apply.

This priority reverses only on explicit word from the project owner that
`nous` has reached GA.

Two things this does NOT touch, because they are different claims:
- **§5's "no reflective-path change"** is about `orchestrator/iteration.py`
  (the unrelated `kind: reflective` loop) staying untouched by this branch —
  that constraint is about blast radius on a different kind, not about
  `kind: optimization`'s own behaviour, and it stands.
- **The correctness gates (§2.3)** and the fallback ladder (§3.6) are not
  "behaviour to preserve" either way — they are requirements this spec
  imposes regardless of what `nousko` did before.

## 3. Locked decisions

### 3.1 The policy is data
A JSON document, schema `orchestrator/schemas/policy.schema.json`, emitted by
`compile_policy(campaign, verify_result) -> dict` — **pure Python, zero tokens**,
run at the end of `verify`. It carries a content hash; `check_policy` refuses a
mutated policy. `run_stage` becomes an interpreter over it.

Rationale: registration is what makes adaptation auditable. If the branch list
lives in Python control flow, "pre-registered" is a claim about the source tree
rather than about the run.

### 3.2 `step()` over a closed observation vocabulary
```
step(policy, state, obs) -> (next_state, actions)
```
Pure, total, deterministic. `obs` is drawn from a **closed vocabulary** — the
observation keys are enumerated in the schema. A key outside the vocabulary is a
**semantic exception**, not a new branch: measurements choose among registered
branches, they never invent one.

`enumerate_paths(policy)` returns every reachable path, so registration is
checkable by enumeration rather than by inspection. Property tests assert
totality (no observation leaves `step` undefined) and termination (no cycle
without a decreasing budget).

### 3.3 States

| State | Spends benchmark? | Registered branches out |
|---|---|---|
| `screen` | yes | `refine`, `foldover`, `confirm`, `exception` |
| `foldover` | yes | `refine`, `confirm`, `exception` |
| `refine` | yes | `confirm`, `exception` |
| `confirm` | yes | `report`, `exception` — **terminal discrimination**, not replication |
| `report` | no | terminal |
| `exception` | no | terminal; **ends the epoch** |

`confirm` changes meaning: it takes a shortlist `S ⊆ X_valid` and measures its
members freshly, so the final comparison does not rest on the fitted surface.
The remaining global claim is only that screening did not exclude the winner.

**Naming note:** the paper's Figure 1 names this stage `discriminate`. This
branch's schema, `policy.py`, `stage_runner.py`, and every test file across
Tasks 1–6 call it `confirm` — a name that predates this alignment work.
`confirm`'s *behavior*, as redefined above, already matches the paper's
`discriminate` exactly; only the token differs. Deliberately not renamed
(would touch a wide, already-reviewed surface for a naming-only win) — but
every place this state is introduced should say once that `confirm` is this
branch's name for the paper's `discriminate`, so a reader moving between the
paper and the code is not left to infer the mapping.

### 3.4 `recommend()`
```
recommend(fit, X_valid) -> x̂ = argmax_{x ∈ X_valid} f̂(x)
```
Enumeration for a small space; deterministic optimization for a structured one.
**No model judgment.** Two bugs this fixes, both live today:
- a solved stationary point may be a **saddle** or a minimum — `confirm`
  currently reproduces it regardless;
- `choice` factors are excluded from the quadratic solve, so the reported
  optimum silently omits them.

### 3.5 Two bounds, reported separately
- **Model bound** `U_δ^model(z,x)`: simultaneous one-sided upper bound on
  `f(z) − f(x)` under the registered response class. Carries the response-model
  assumption.
- **Terminal bound** `U_δ^term(z,x)`: from fresh shortlist measurements only.
  Assumption-light.

`R_δ(x) = max_z U_δ(z,x)` for each. Report `δ_s` (screening) and `δ_t`
(terminal) separately, with `Pr(wrong global decision) ≤ δ_s + δ_t`. They rest
on different assumptions and must never be collapsed into one number.

**Variance source.** Center-point replication cannot supply pure error on a
**deterministic** target — measured: four center points on a real campaign
returned bit-identical values, so `pure_error = 0` and every interval came back
`None`. The registered variance source is therefore **workload seed variation**
(§3.7), with replication retained only for stochastic targets. A policy whose
bound needs a variance it cannot obtain must say so, not divide by zero.

### 3.6 Fallback ladder
Always act. In order:
1. `R_δ(x̂) ≤ ε` → certified ε-optimal.
2. Model adequate, bound too wide → `x̂` with `R_δ(x̂)`, uncertified.
3. Model inadequate → reserved budget re-measures the leading **measured valid**
   candidates; return the best. Never return the largest noisy observation.
4. Nothing passes the correctness gates → `known_valid_baseline`.

Every rung is recorded in `report.json` as `decision_basis`, so a reader can
tell a certificate from a fallback without reading the log.

### 3.7 Three oracles
1. **Synthetic surfaces** (`orchestrator/optimize/synthetic.py`) — nine closed-form
   responses, each named for a real past bug, so a regression has a name:
   `saddle_not_max`, `choice_omitted`, `interaction_only`, `alias_flip`,
   `nan_poison`, `hump_interior`, `regime_flip`, `deterministic_zero_variance`,
   `infeasible_region`.
2. **Build oracles** — a mechanism `build` authored must (a) produce a
   `mechanism.patch`, hard-failing on drift between the patch and the tree;
   (b) have its declared tests **fail before** the build and pass after, or the
   test proves nothing; (c) satisfy `control ≡ known_valid_baseline` exactly.
3. **Workload CRN** — the same seed set across compared configurations, so a
   paired bound is available and seed variation is not confounded with the
   factor effect.

### 3.8 Workload common random numbers
`workload.seeds: [int]` is part of the policy. Every configuration in a
comparison runs the same seed set; bounds are computed on paired differences.
This is what makes a systems target (queueing, caching, autoscaling) measurable
at all — unpaired comparison on a noisy server needs an order of magnitude more
runs for the same bound.

### 3.9 Artifacts

| File | Written by | Contains |
|---|---|---|
| `policy.json` | end of `verify` | the compiled policy + content hash |
| `transitions.jsonl` | each `step()` | `(state, obs, next_state, actions, branch_id)` |
| `alias_map.json` | `screen` | what is aliased with what, and whether it is consequential |
| `shortlist.json` | `confirm` | `S`, why each member is in it, fresh measurements |
| `report.json` | `report` | `x̂`, both bounds, `δ_s`, `δ_t`, `decision_basis`, `certified` |
| `epoch.json` | `exception` | why the epoch ended, and what a new one would need |

**Naming notes (post-implementation, final whole-branch review).** The
branch's actual artifact names diverge from this table in three places,
verified against the code rather than assumed:
- `epoch.json` above is `epoch_end-<epoch>.json` on disk (`_close_iteration`,
  work-dir root) — same artifact, this branch's name for it.
- `alias_map.json` does not exist as a separate file. Its content is split
  across `effects.json`'s `aliases` (which coefficients were fit per alias
  class) and `recommendation.json`'s `alias_consequential` (whether the
  unresolved alias mattered to the answer).
- `decision_basis` above is `recommendation.basis` in the actual
  `report.json` — six values (certified / terminal_best / model / measured /
  baseline / none), not a bare boolean; see `docs/data-model.md` §7j and
  `CLAUDE.md`'s optimization section for the full mapping.
- `branch_id` was never implemented; every `transitions.jsonl` row carries
  `policy_hash` instead, plus the complete fired `rule` dict (including its
  `accounting` string). This is not a gap: `branch_id` does not appear in
  the paper at all, and `rule` + `policy_hash` is strictly more informative
  than a bare id — a reader needs no cross-reference into `policy.json` to
  know which registered branch produced a row, because the fired rule is
  already inlined in it. Treat `rule` + `policy_hash` as superseding
  `branch_id` in this table, not as a missing field.

## 4. Two latent defects, verified now

Both reproduced on `nousko` at `9e7983d` before the plan was written. Neither is
hypothetical, and both are folded into the plan with these reproductions.

**D1 — every tabulated resolution-IV screen crashes at fit.**
```
k=5 res=4: 16 runs -> ValueError: design matrix is singular
k=6 res=4: 16 runs -> ValueError: design matrix is singular
k=7 res=4: 16 runs -> ValueError: design matrix is singular
k=8 res=4: 16 runs -> ValueError: design matrix is singular
```
`fit_effects` requests one column per two-factor interaction; at resolution IV
aliased columns coincide, so `XᵀX` is singular. Resolution V is fine. So
`resolution: 4` is *documented and validated* but aborts every campaign that
declares it. Fixed in **T10** by an alias-aware fit that estimates one
coefficient per **alias class** and records the class in `alias_map.json`.

**D2 — one infeasible row silently NaN-poisons every coefficient.**
```
clean fit, first 4 estimates: [0.1875, -0.5625, -0.0625, 0.1875]
with ONE NaN row:            ['nan', 'nan', 'nan', 'nan']
all coefficients NaN? True   fit_effects raised or warned? NO
```
`_fitting_responses` appends NaN for any non-`complete` row, and the abort guard
at `stage_runner.py:207` deliberately **excludes** `infeasible`/`rejected` rows
from its check — so those NaNs flow into `fit_effects`, which returns a
schema-valid `Fit` whose every coefficient is NaN. The comment says "carry NaN so
the row is excluded"; nothing downstream excludes it. Fixed in **T7** by fitting
on the complete-row subset and recording the excluded rows.

## 5. Non-goals

- **No adaptive branch without an accounting rule.** The paper is explicit: an
  adaptive branch that does not name its inferential accounting (POSI, data
  splitting, confidence sequences) "is not a valid compiled policy". Only
  branches with a named rule ship.
- **No model call inside an epoch**, for any reason, including "just to
  interpret". A semantic exception ends the epoch instead.
- **No Bayesian optimization / bandit search.** The claim is narrow: once a
  finite verified interface exists, treat the remainder as experimental. Search
  belongs to invention, before the boundary.
- **No new Nous dependency** for property testing. Target-side frameworks
  (`hypothesis`, `rapid`, `proptest`) belong to target repos.
- **No reflective-path change.** `orchestrator/iteration.py` stays at 23
  insertions / 0 deletions against `main`; `tests/test_optimize_no_regression.py`
  proves it. (This is scoped to the *reflective* kind and is unrelated to
  §2.7 — it is not a behaviour-preservation requirement on `kind:
  optimization` itself.)
- **Not a paper reproduction.** This implements the method, not the paper's
  experiments.
