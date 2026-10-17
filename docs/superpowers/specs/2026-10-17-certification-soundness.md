# Certification soundness for `kind: optimization` (WP-A)

Brief: `nous-e2e/audit/wp-a-inference.md`, trimmed by `WRAPUP-PLAN.md`.
Evidence: the stage-0 audit, Q1 (error control), Q2 (robustness) and Q4
(certificate scope), re-measured here before and after.

**Scope split.**
- WP-B decides HOW model adequacy is determined: the three-valued, sticky
  `model_adequate` over every fitting stage of the epoch (INV-STAT19).
- WP-A decides what a certificate CLAIMS. It reads `model_adequate` and does
  not change how it is determined.
- WP-C records the cross-epoch error budget (`report.json` `error_budget`).
  This spec refers to that record and does not duplicate it.

In scope (MUST): A1 the whole bound, A2 alpha-spending, A4 the scope record.
In scope (SHOULD): A3 the baseline as a reference finalist.
Deferred to documented limits (§7): A5 (noise diagnostics, a robust small-n
bound) and A6 (outliers, censoring).

## 1. What a certificate claims

Notation, for one epoch of a single-objective campaign:
- `X` is the candidate space of the epoch's latest fitting stage: the
  declared levels of the fitted factors, with `held_fixed` factors at their
  held level (§4). It excludes measured-inadmissible configurations and, when
  constraints are modelled, confidently infeasible ones.
- `x*` is the best member of `X`, `x̂` the fitted argmax, and `w` the
  recommended configuration (the winner of the final confirm round).
- `S` is the final round's admissible measured shortlist, and `i*` its best
  member.
- `ε` is the epoch's indifference width.

**The statement.** `certified: true` means

> Pr( certified and f(x*) − f(w) > ε ) ≤ δ_screen + δ_terminal

under assumptions M1-M4 below, where δ_terminal is the declared value (A2
spends it over the looks).

**The rule** (`stage_runner._finish_confirm`, `_global_bound`). Certify iff
all of the following hold:
1. `R_terminal ≤ ε`, and `G = R_model,out + R_terminal ≤ ε` (§2);
2. `x̂` is an admissible, measured finalist of the final round;
3. `model_adequate` is True. WP-B's verdict is sticky, so this means True at
   every fitting stage of the epoch;
4. none of the earlier vetoes fired: an inadmissible or unmeasured finalist,
   a level-correlated exclusion, a refill round, or unknown adequacy;
5. the candidate space was enumerated, not searched.

Assumptions:
- **M1.** The registered response class (first order + 2fi at screen,
  second order at refine) holds over `X`. It is not refuted by WP-B's lack
  of fit and validation checks; that is checked, not proved (§7).
- **M2.** Replicates are independent, with errors whose means are
  approximately normal. Welch or paired t; under CRN, the paired form when
  `workload.seed_env` is declared.
- **M3.** The centre-replicate pure error is the error variance at every
  configuration. The model bound uses it.
- **M4.** The shortlist is chosen before the round's replicates are seen.
  Selecting the best FROM those replicates is covered by the multiple
  comparisons with the best argument (Hsu 1996, ch. 4).

## 2. A1: the whole bound

Two events:
- **E_s, the model family** (`certificate.model_regret_bound`, δ_screen).
  The one-sided bounds `U_m(z, x̂) ≥ f(z) − f(x̂)` hold simultaneously for
  every challenger `z ∈ X` (Bonferroni over all `M = |X| − 1` challengers),
  with probability ≥ 1 − δ_screen under M1 and M3. Because the family is
  simultaneous, any data-chosen subset of it holds on the same event. That
  is the only reason a max over "the candidates outside `S`" is legitimate.
- **E_t, the terminal family** (`certificate.terminal_regret_bound`, at the
  per-look δ_t/L of §3). The bounds on `f(z) − f(i*)` for `z ∈ S` hold
  simultaneously at the look where certification happens. This is the Hsu
  MCB argument: only the |S| − 1 comparisons against the true best of `S`
  matter.

On E_s ∩ E_t:
- If `x* ∈ S`: `f(x*) − f(w) ≤ f(i*) − f(w) ≤ R_terminal`.
- If `x* ∉ S`: `f(x*) − f(w) = [f(x*) − f(x̂)] + [f(x̂) − f(w)] ≤ R_model,out + R_terminal`.
  The first bracket is `U_m(x*, x̂)` for a challenger outside `S`. The second
  uses that `x̂ ∈ S` is admissible, so `f(x̂) ≤ f(i*)`, and then E_t.

So `f(x*) − f(w) ≤ G`, and certifying on `G ≤ ε` is wrong with probability
at most `Pr(E_s^c) + Pr(E_t^c) ≤ δ_screen + δ_terminal`.

`R_model,out` is read from `recommendation.json`
`residual_regret_model_profile`. That record holds the 3k+5 largest
per-challenger bounds, where k is the shortlist size, and the max over the
rest, so confirm needs no fit (`certificate.model_bound_outside`). Records
without the profile fall back to the whole-space `R_model`, which is a
larger and still valid stand-in.

Two shortlist rules make the bound reachable:
- **The largest-bound challenger is seated** after the anchors, before the
  model's ranking. Spec §3.6 rung 2 calls it "the point the next experiment
  should be directed at". Measuring it moves its term from the model family
  to the terminal family.
- **`x̂` stays seated in every round** (round r > 1 used to retire it).

**Withheld reasons** (schemas, `report_md.WITHHELD_MEANING`, guide):
`model_bound_above_epsilon`, `model_bound_not_computable`,
`model_bound_not_exhaustive`, `model_recommendation_not_compared` and
`model_recommendation_infeasible`. The existing `model_inadequate` and the
`model_adequate_basis` reasons cover adequacy.

**Multi-objective** campaigns keep their front rules (INV-SEM18) and the
alpha-spending of §3. The global bound is single-objective only (§7).

## 3. A2: alpha-spending across confirm looks

Every confirm round evaluates `certified` and stops on it, so each round is
a look.
- **Before:** single-objective judged every look at the full δ_t, and split
  δ_t only after a refill. A Monte Carlo of the shipped bound gave 0.071 at
  2 looks and 0.108 at 4 looks, against δ_t = 0.05.
- **Now:** both paths take each look at `δ_t / L`, with
  `L = policy.confirm_looks(pol)` = `confirm_max_rounds`, + 1 when the refill
  branch (`REFILL_ACCOUNTING`) is registered. The refill branch fires only
  at the cap and buys exactly one more look. L is fixed at compile time, so
  the per-look level does not depend on the data. By the union bound,
  `Pr(any look's family fails) ≤ L · δ_t/L = δ_t`. A `max` with the round
  number is a backstop.
- **Recorded in** `confirmation.json` `alpha_spending` (declared, L,
  per-look). `delta_terminal` there is the per-look level (INV-SEM20).

The multi-objective path used `max(max_rounds, round)`. It now uses the same
`confirm_looks`, so the refill look is charged up front on both paths.

## 4. A4: certificate scope

`report.json` `certificate_scope` is read from the epoch's latest fitting
record:
- `region`: `slice` when that stage held factors fixed (refine holds every
  non-refinable factor at the screen's best), `declared_space` when every
  factor varied, and `none` when no fitting stage ran;
- `held_fixed`, `fitting_stage` and `searched`;
- `boundary_axes`, with `boundary_optimum`;
- a plain `statement`.

`report.md` prints the slice. `X` in §1 is exactly this region, so the
probability statement is scoped and never global over levels that were not
varied. The audit's case is `ridge_cubic`, which certified C=on while the
optimum has C=off; it is now recorded as a slice. WP-B's validation check
already withholds it, too.

Seat flips (a confirm finalist at each alternative level of a held factor)
were not implemented. On the measured surfaces they are not cheap: they cost
one seat × replicates per held level per round, and would need their own
model half. Recorded as a limit (§7).

## 5. A3: the baseline as a reference finalist; an unbiased gain

When `known_valid_baseline` is declared (single-objective), confirm seats it
in every round:
- one seat beyond `shortlist_size`;
- the round's replicate seeds are shared, so the comparison is CRN-paired
  under `workload.seed_env`;
- it competes like any finalist;
- the preview counts the seat.

`confirmation.json` and `report.json` `gain_over_baseline` give the winner's
gain over it from the round's fresh replicates:
- `[low, high]` is two-sided at δ_t (per look), Bonferroni over every
  finalist vs the baseline, `t_{1−δ/(2M)}`. It covers all `f(i) − f(b)`
  simultaneously, hence the data-selected winner's (Hsu 1996, ch. 1:
  simultaneous intervals are selection-proof).
- `estimate` is the winner's mean difference on the selecting replicates. It
  is biased upward and labelled so; the interval is the claim.

Measured (bowl, noise sd 0.4, seeds 1-12, unpaired): 11/12 intervals cover
the true gain. The mean estimate bias is +0.19 against a true gain of about
6.5.

Not done: a separate post-selection validation block whose fresh replicates
would give an unbiased point estimate and the ε reference. That would cost
another `replicates × 2` runs per campaign. The simultaneous interval gives
a valid claim at no extra runs, so the extra block is deferred (§7).

## 6. Error budget across stages, rounds and epochs

| level | budget | how it is spent |
|---|---|---|
| stages within an epoch | δ_screen | one simultaneous model family at the latest fitting stage (§2). Earlier stages' decisions (screen drop, foldover, curvature routing) select the region but spend no stated δ: their errors are covered only through M1 (§7). |
| confirm rounds within an epoch | δ_terminal | Bonferroni over the L registered looks (§3) |
| constraint exclusion within an epoch | δ_constraint | Bonferroni over the modelled constraints, only at `x*` (§6) |
| one epoch's certificate | δ_screen + δ_terminal (+ δ_constraint) | union of the families (§2, §6) |
| epochs | Σ_e (δ_s,e + δ_t,e) | recorded by WP-C in `report.json` `error_budget` (`cumulative`, union bound over epochs). Each epoch's certificate is judged at its own deltas. |

**The constraint-exclusion term (#321 P2 item 3, fixed).** Constraint-model
exclusion removes a candidate when, for some modelled constraint, its
one-sided bound lies entirely on the violating side
(`constraint_models.confidently_infeasible`). Let `E_c` be the event that the
TRUE constrained optimum `x*` is not removed. `x*` is a fixed point, not a
data-chosen one, and it is feasible, so for each of the `C` modelled
constraints a removal needs that constraint's one-sided bound at `x*` to fail:
`Pr(E_c^c) ≤ C · δ_c/C = δ_c` (Bonferroni over constraints; no division by
the candidate count is needed, since removing a truly infeasible candidate
costs nothing). `E_c` is not implied by `E_s` (a different response, a
different fit), so the statement in §1 holds on `E_s ∩ E_t ∩ E_c`:

> Pr( certified and f(x*) − f(w) > ε ) ≤ δ_screen + δ_terminal + δ_constraint.

`δ_constraint` is `policy.objective.delta_constraint`
(`optimization.policy.delta_constraint`, default δ_screen, the level the
exclusion always used). It is registered at compile time exactly when a
declared constraint has a violating side and no `when` guard, so it is fixed
before any data; it is charged even when the constraint later proves
unmodellable (conservative). `report.json` carries `delta_constraint`, and
`error_budget.epochs[].spent` includes it. A campaign without such a
constraint spends the two terms as before (byte-identical policy). Caveat:
like E_s, E_c rests on the constraint model's response class (M1) and on its
pure error (M3).

## 7. Documented limits (deferred items and open questions)

**From the WP-A review (merge gate, 2026-10-17)** -- recorded, not fixed:

- The refill look is charged in `confirm_looks` but a refill round never
  certifies (`shortlist_refilled`), so the +1 costs power without buying
  validity: deliberate conservatism.
- FIXED (#321 P2): `_baseline_seat_extra` no longer counts a seat when the
  baseline is carried inside the cap. Fixing it exposed the opposite defect:
  `_next_round_finalists` costed round r+1 at its carry-over, but
  `_confirm_rows` tops a round up to `shortlist_size`, so 24/96 probe
  campaigns (bowl/additive, noise 0.4, 4 rounds, max_runs 30-50) overspent
  `max_runs`. The estimate is now `shortlist_size` (+ the baseline seat).
- FIXED (#321 P2): a baseline measured inadmissible still vetoes, under its
  own reason `baseline_measured_inadmissible`.
- `test_spending_holds_the_sequential_error_at_delta` checks certificate
  arithmetic only; product-path coverage is `test_every_confirm_look_is_charged`.
- Paired (CRN) gain intervals are not exercised end to end: the synthetic
  target's seeded workload gives zero-spread paired differences.
- Retired earlier-round finalists and the current round's infeasible
  finalists stay in the model max (conservative).
- Power: 621 -> 425 certificates on the noise sweep, concentrated on near-tied
  surfaces with few pure-error df (saddle 82 -> 3, interaction_only 7 -> 1).
  The remedy is more centre points, not a weaker rule (quickstart).
- The gain interval's level: computed per look, REPORTED at the guaranteed
  1 - delta_terminal (the round shown is the one the campaign stopped at).
  Fixed in report.md / report.json (`delta_guaranteed`).


1. **A5, small-n noise.** No per-finalist variance-ratio or skewness
   diagnostic is recorded. No robust bound (bootstrap-t or permutation on CRN
   differences) or replicate floor is applied. The terminal Monte Carlo with
   heteroscedastic, skewed noise at n = 3 gives 0.17 vs 0.05 for the
   terminal half alone (stage-0 Q2).
2. **A6, outliers and censoring.** No studentized-residual flag is written.
   A timeout is "unmeasured", not right-censored. Constraints are "every
   replicate passes", not a mean or chance constraint.
3. **M1 is checked, not proved.** The global bound inherits the response
   class. WP-B's checks have local power only (its limits 1-12).
4. **The constraint-exclusion δ** is in the stated sum since #321 (§6).
5. **Seat flips for held factors** are not implemented (§4). The scope is
   recorded instead.
6. **No post-selection validation block** (§5). The gain estimate is biased,
   and the ε reference still comes from the best finalist's mean on the
   selecting data (stage-0 Q5).
7. **Multi-objective** has no global (model-half) bound.
8. **Bonferroni conservatism.** Large X with few pure-error df gives a wide
   `R_model,out`; expect `model_bound_above_epsilon`. The remedy is more
   centre points (more pure-error df), not a weaker rule.
9. **A baseline measured inadmissible** vetoes the round, named
   `baseline_measured_inadmissible` (#321 P2). The baseline is declared
   valid, so the contradiction is evidence.

## 8. Evidence

Probes:
- `nous-e2e/audit/wpa/scripts/` (`probelib.py` and `sweep.py`: the stage-0
  Q1/Q2 noise sweep and the rounds probe);
- the WP-B oracle (`nous-e2e/audit/wpb/oracle.py`), run through
  `nous-e2e/bin/heavy` with 3 workers.

"Before" is nousko at 948ad14: stage-0 fixes, mixed-level factors, WP-B and
WP-C merged. "After" is this branch. A false certificate is `certified` with
a true gap > ε, or an invalid recommendation.

Nominal bound: δ_screen + δ_terminal = 0.10.

**8.1 Noise sweep** (stage-0 Q2). 7 surfaces: additive, bowl, saddle,
bowl_centred, choice_x_numeric, geometric_knob_log and sla. 6 noise models ×
3 noise multipliers, seeds 1-16, so 2016 campaigns per side. Each cell shows
false certificates / certificates, and Pr(certified and wrong) over 112
campaigns.

| noise | ×1 before | ×1 after | ×4 before | ×4 after | ×8 before | ×8 after |
|---|---|---|---|---|---|---|
| Gaussian | 0/79 | 0/65 | 0/49 | 0/34 | 0/25 | 0/8 |
| t(3) | 0/83 | 0/70 | 0/57 | 0/39 | 3/31 (0.027) | 0/17 |
| skewed (centred exp) | 0/85 | 0/72 | 0/47 | 0/34 | 2/23 (0.018) | 0/9 |
| heteroscedastic (1-9×) | 0/45 | 0/26 | **5/15 (0.045)** | 0/0 | 3/5 (0.027) | 0/0 |
| hetero, edges loud | 0/10 | 0/8 | 0/1 | 0/0 | 0/0 | 0/0 |
| outliers (5% ±25 sd) | 0/35 | 0/27 | 2/21 (0.018) | 0/13 | 2/10 (0.018) | 0/3 |
| **total** | | | | | **17/621 (0.0084)** | **0/425 (0)** |

All 17 "before" false certificates had R_model between 9 and 90 against an
ε of about 0.2-0.4: the model half was ignored, never wrong. Certificates
lost: 621 → 425. Per surface: saddle 82 → 3, additive 77 → 39, bowl
89 → 71, bowl_centred 98 → 74, choice_x_numeric 175 → 150,
geometric_knob_log 99 → 88, sla 1 → 0.

**8.2 Confirm rounds** (stage-0 Q1). 4 surfaces at ×8 Gaussian noise, 1 vs
4 rounds, seeds 1-40, 320 campaigns.

| | 1 round | 4 rounds |
|---|---|---|
| before: false / certified | 1/49 | 1/73 |
| after: false / certified | 0/17 | 0/16 |

Monte Carlo of the shipped terminal bound alone: 2 finalists with a true gap
of ε + 0.001, sd 1, n = 3, certify on the first look within ε, 20,000 trials.
Pr(false certificate), before → after:

| noise | 1 look | 2 looks | 4 looks |
|---|---|---|---|
| Gaussian | 0.039 → 0.039 | 0.067 → 0.032 | **0.105 → 0.029** |
| t(3) | 0.030 → 0.030 | 0.050 → 0.022 | 0.070 → 0.018 |
| skewed | 0.026 → 0.026 | 0.043 → 0.022 | 0.063 → 0.020 |

**8.3 WP-B oracle.** Every single-objective SURFACES entry plus step_cliff,
ridge_cubic and two_peaks, ×1 and ×4, seeds 1-8, 288 campaigns. "Smooth" is
the 9 surfaces the response class describes. "Non-quadratic" is step_cliff,
ridge_cubic and two_peaks. "Other" is the constrained and failing surfaces
that never certified.

| group | ×1 before | ×1 after | ×4 before | ×4 after |
|---|---|---|---|---|
| smooth: certified (power) | 61/72 | 48/72 | 36/72 | 24/72 |
| smooth: false | 0 | 0 | 0 | 0 |
| non-quadratic: certified / false | 0/0 | 0/0 | 3/1 | 0/0 |
| other: certified | 0 | 0 | 0 | 0 |

Power per smooth surface (×1, then ×4), before → after:
- unchanged: bowl 6 → 6, 4 → 3; geometric_knob_log 6 → 6, 4 → 4;
  choice_x_numeric 8 → 8, 8 → 8; drift 8 → 8, 7 → 7;
  infeasible_corner_interior 8 → 8, 2 → 1; bowl_centred 6 → 6, 4 → 1;
  additive 6 → 5, 1 → 0.
- lost: saddle 6 → 0, 3 → 0; interaction_only 7 → 1, 3 → 0.

The lost power is real model-bound width, not a defect:
- saddle has two near-tied ridges;
- interaction_only has four near-tied corner optima;
- in both, pure-error df = 3 and Bonferroni over 15-80 challengers gives
  t ≈ 6.7-12, so `R_model,out` is 0.2-0.7 against ε ≈ 0.22-0.25.

The remedy is more centre points (df), not a weaker rule (§7.8).

**Reading the table.**
- Pr(certified and wrong) is now 0 in every cell, against a nominal 0.10.
  The bound is conservative here, as Bonferroni families are.
- The sweep is not a stress test of M1. WP-B's validation check (not WP-A)
  is what withholds the non-quadratic surfaces. With it, A1 also removes the
  one remaining ridge_cubic ×4 false certificate.

## 9. Byte-identity

What changes on disk:
- `confirmation.json` gains `alpha_spending` on every round and
  `global_bound` on single-objective rounds that consult the model half.
  `delta_terminal` becomes the per-look level wherever L > 1: rounds > 1,
  constrained campaigns (refill registered) and multi-objective.
- `recommendation.json` gains `residual_regret_model_profile`.
- `report.json` gains `certificate_scope` always, and `gain_over_baseline`
  with a baseline.
- Shortlists change in three cases: the largest-model-bound challenger takes
  a seat in round 1, `x̂` is kept in rounds > 1, and a declared baseline
  adds a seat.
- `policy.json`'s certified rule changes its `accounting` string, so
  `policy_hash` changes for every campaign.

Unchanged: an unconstrained single-objective campaign with one round and no
baseline keeps its per-look δ_t (L = 1), its terminal bounds and its
measured runs. That holds only where the round-1 seat order is unchanged,
i.e. where the largest-bound challenger was already a seated finalist.
