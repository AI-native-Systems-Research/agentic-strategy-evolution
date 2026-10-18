# Expert audit of `kind: optimization`, questions Q1-Q11

**Code audited:** branch `nousko` at `9e354a2`. This is the merged result of
the stage-0 fixes, mixed-level factors, WP-C (benchmarks,
reanalyze/provenance, AI-native build gates), WP-B (model adequacy) and WP-A
(certification soundness).

**Baseline:** the stage-0 adversarial audit at `1a0d68b`
(`nous-e2e/audit/stage0-audit.md`). Its verdicts were five GAP and five
PARTIAL; Q11 was not asked.

**Method.** Read-only. Each claim below was checked against the code, not
only against the specs. Spot checks were re-run on a `git archive` of
`9e354a2`, through `nous-e2e/bin/heavy` with 3 workers. Scripts and raw
output are in `nous-e2e/audit/final/`.

| probe | what | result at 9e354a2 | the spec says |
|---|---|---|---|
| WP-B oracle (`wpb/oracle.py`), seeds 1-8, ×1 and ×4 | step_cliff, ridge_cubic, bowl | step_cliff 0/8 and 0/8 certified, 0 false; ridge_cubic 0/8 and 0/8, 0 false; bowl 6/8 and 3/8 certified, 0 false | WP-A §8.3: non-quadratic 0/0 after; bowl power 6 → 6 at ×1, 4 → 3 at ×4. **Reproduced.** |
| WP-B oracle, seeds 1-40, ×4 | ridge_cubic, two_peaks | 0/40 and 0/40 certified | WP-B §3 (WP-B alone): 11 (3 false) and 1 (1 false). WP-A's global bound removes those residual false certificates. |
| WP-A noise-sweep cells (`wpa/scripts/probelib.py`), seeds 1-16, ×4 | saddle `hetero`, saddle `outlier`, bowl `t3` | 0, 0 and 8 certified; 0 false | `wpa/after_noise.json`: the same cells give 0, 0 and 8 certified, 0 false. **Reproduced.** Stage-0 had saddle `hetero` ×4 at 16/80 false. |
| Terminal-bound Monte Carlo (`wpa/scripts/mc_looks.py`) | 20,000 trials | Gaussian at 4 looks: 0.1046 before, 0.0289 after; t(3): 0.0697 → 0.0175; skewed: 0.0630 → 0.0203 | WP-A §8.2. **Reproduced to 4 digits.** |
| `sparse_knobs(6)` and `sparse_knobs(8)`, seeds 1-8, declared noise | many-knob certification | **0 of 16 certified.** 14 withheld `model_bound_not_exhaustive` + `model_bound_above_epsilon`, 2 withheld `model_inadequate`. True gap 0 on every seed. | The benchmark doc reports 6/8 and 8/8 certified at ×1 and says Nous "certifies". **Not backed** (H3). |
| `sparse_knobs(4)` and `sparse_knobs(5)`, seeds 1-2 | where certification stops | k = 4: withheld `model_bound_above_epsilon`. k = 5 (59,049 candidates, above `CANDIDATE_CAP`): withheld `not_exhaustive` + `above_epsilon`. | see Q4 |
| Exact vs per-column SE of a model-bound contrast, face-centred CCD (numpy, exact `(X'X)^-1`) | the SE behind `R_model` | the worst-case ratio exact / per-column is 1.30 (k = 2, 4 centres), 1.32 (k = 2, 3 centres) and 1.53 (k = 3, 4 centres) | not stated in the spec's assumptions (H1) |
| Targeted tests | certification soundness, model adequacy, reanalyze, provenance, build scope, build oracles, benchmark smoke, certificate | **207 passed** in 82 s (`-n 3`) | |

Verdict key:
- **ANSWERED**: the code implements a defensible answer, tests pin it, and
  the user-facing text matches it.
- **PARTIAL**: a real answer with documented limits that an expert would
  still raise.

Items marked **HIGH** are claims that the code at 9e354a2 does not back. They
are collected in §12.

---

## Q1. Error control: what does "certified" guarantee?

**(a) Answer, as implemented.**
- `certified: true` asserts that Pr(certified and f(x*) − f(w) > ε) ≤ δ_screen + δ_terminal.
  - x* is the best configuration in the certificate's scope.
  - w is the recommendation.
- `_finish_confirm` certifies only when all of the following hold:
  1. `R_terminal ≤ ε`, and `G = R_model,outside + R_terminal ≤ ε`;
  2. the fitted argmax x̂ is an admissible, measured finalist of the final round;
  3. `model_adequate` is True. WP-B's sticky verdict makes this "True at every fitting stage";
  4. no finalist was excluded or unmeasured, no level-correlated exclusion occurred, the round was not a refill, and adequacy is known;
  5. the candidate space was enumerated, not searched.
- The proof is a union of two simultaneous families:
  - **E_s:** the Bonferroni family over all |X| − 1 challengers of x̂. It is valid for the data-chosen "outside S" subset because it is simultaneous.
  - **E_t:** Hsu's multiple-comparisons-with-the-best family over the shortlist.
- **Error budget.**
  - Confirm looks: Bonferroni α-spending at δ_t / L, where L is the registered round cap, plus 1 when the refill branch is registered. L is fixed at compile time.
  - Single- and multi-objective confirm share the same divisor.
  - Epochs: a union-bound `error_budget` in `report.json`. It is **informational**. Each epoch certifies at its own deltas.
  - Earlier stages' routing decisions (screen drops, foldover, curvature routing) spend no stated δ. They are covered only through assumption M1.

**(b) Evidence.**
- The rule:
  - `orchestrator/optimize/stage_runner.py:6765-6779`, where `certified = (...)`;
  - `_global_bound` at `stage_runner.py:7432-7487`;
  - the largest-model-bound challenger is seated at `stage_runner.py:5872`;
  - per-look δ: `stage_runner.py:6467-6468` and `policy.confirm_looks` at `policy.py:827-848`. Multi-objective uses it at `pareto_stage.py:542`.
- The bounds:
  - `certificate.model_regret_bound` (`certificate.py:147-208`);
  - `model_bound_outside` (`certificate.py:211-236`);
  - `terminal_regret_bound` (`certificate.py:239`).
- Artifacts:
  - `confirmation.json` `global_bound` (`value`, `residual_regret_model_outside`, `delta_terminal_per_look`) and `alpha_spending`;
  - `recommendation.json` `residual_regret_model_profile`;
  - `report.json` `error_budget` (`cumulative`, `epochs[].compiled_after_data`).
- Numbers:
  - Noise sweep (2016 campaigns): false certificates 17/621 → **0/425** (WP-A §8.1). Spot-checked cells reproduce.
  - Rounds, Monte Carlo at 4 looks: 0.105 → 0.029. Reproduced.
  - Live bowl campaign: `error_budget.cumulative = 0.1` over one epoch.

**(c) Tests.**
- `tests/test_optimize_certification_soundness.py`:
  - `test_a_wide_model_bound_withholds_the_certificate`
  - `test_a_certificate_states_both_halves_within_epsilon`
  - `test_the_model_bound_outside_a_shortlist_drops_only_measured_members`
  - `test_every_confirm_look_is_charged`
  - `test_the_refill_look_is_charged_before_it_is_taken`
  - `test_spending_holds_the_sequential_error_at_delta`, which covers arithmetic only, as the spec says
  - `test_inv_sem20_holds_on_oracle_campaigns_and_has_teeth` (INV-SEM20)
- `tests/test_optimize_provenance.py::test_the_error_budget_accumulates_across_epochs`

**(d) What the user is told.** Guide, "Reading `report.json`":

> With probability at least `1 − delta_screen − delta_terminal`, the
> recommended configuration is within ε of the best configuration in the
> certificate's scope.

report.md prints "**Cumulative (union bound over epochs): …** Certification
above is judged at this epoch's deltas; the cumulative figure is the
probability bound that ANY epoch's decision on this work_dir is wrong."

**(e) Limits.**
1. **M1 (response class) is checked, not proved.** See Q3.
2. **M3: pure error stands in for every configuration.** See Q2.
3. **The constraint-model exclusion δ is a third union term,** and it is not in the stated sum (spec §6).
4. **Multi-objective has no global (model-half) bound.**
5. **The cross-epoch budget does not gate anything.**
6. **HIGH (H1): the model bound's SE for the second-order refine fit is per-column, not exact.**
   - Two-level and CCD fits carry no covariance (`Fit.covariance is None`). So `prediction_variance` returns None, and `model_regret_bound` falls back to Σ se_e² dz_e² (`certificate.py:186-191`). This uses `effects.py`'s per-column SE `sigma / sqrt(sum x^2)` (`effects.py:525-560`).
   - The fallback ignores the correlation between the pure-quadratic columns. My exact check finds the contrast SE understated by up to 1.30× (k = 2, 4 centres) and 1.53× (k = 3).
   - The quantile at M = 80 and df = 3 is t = 11.98. Deflating the SE by 1.3 raises each challenger's tail to 1.35e-3 against the nominal 6.25e-4. So the Bonferroni guarantee on E_s is no longer δ_s (its union bound is about 0.11 instead of 0.05).
   - `effects.py` still justifies the shortcut with "quadratic terms ... are consumed ... as point estimates only, never gated on their CIs". Since WP-A, `R_model` gates certification, so that justification no longer holds.
   - The spec's M1-M4 and the guide's assumption list do not mention it. Empirically there are 0 false certificates because Bonferroni is very conservative here, but the stated guarantee is not what the arithmetic delivers.
   - **Fix:** always compute the exact `(X'X)^-1` (`effects._exact_inference` already exists, and is used for mixed and blocked fits). Or state the factor as an assumption.

**(f) Verdict: PARTIAL.** Stage-0 was GAP. The probability statement now
exists, is assembled correctly from two simultaneous families, is
α-spent, and is empirically conservative. Remaining: H1, M1/M3 are
assumed, the constraint δ is not in the sum, and multi-objective has no
model half.

---

## Q2. Robustness to noise: heavy tails, skew, heteroscedasticity, outliers, drift

**(a)** Inference assumes independent replicates with approximately normal
means (M2) and a single centre-point pure-error variance (M3). Nothing
models heteroscedasticity, applies a robust estimator, or flags outliers.
- Drift is handled at two places:
  - **by design:** randomized run order, and confirm blocked by replicate;
  - **optionally:** a fitted block term with a drift test when `reuse_screen` is on.
- WP-A A5 (noise diagnostics, a robust small-n bound) and A6 (outliers) were **deferred**.

**(b) Evidence.**
- Validation check rows run as their own block after the composite. A time trend can only push toward rejection (WP-B §2.7).
- `reuse_screen` block term: `model_adequacy.reuse.block_effect` and `drift_detected` (WP-B §2.5). On bowl: block p = 0.996; a planted +0.5 shift is detected.
- No diagnostic exists in the code: grep for outlier, studentized and censor finds none in `orchestrator/optimize/`.
- Noise sweep after WP-A, in false certificates / certificates (WP-A §8.1):

  | noise model | ×4 | ×8 |
  |---|---|---|
  | heteroscedastic | 0/0 | 0/0 |
  | outliers | 0/13 | 0/3 |
  | t(3) | 0/39 | 0/17 |
  | skewed | 0/34 | 0/9 |

  Stage-0 had heteroscedastic ×4 at 6/14 false, and saddle at 0.20.
- **This is conservatism, not robustness.** The terminal bound alone, under heteroscedastic, skewed noise at n = 3, is still 0.17 against 0.05 (stage-0 Monte Carlo). Nothing in WP-A changed it. The sweep is clean because the model half now withholds those campaigns: saddle `hetero` ×4 withheld `model_bound_above_epsilon` on all 16 seeds in my rerun.

**(c) Tests.**
- `tests/test_optimize_model_adequacy.py`:
  - `test_reuse_detects_a_between_stage_shift`
  - `test_reuse_skips_the_screen_corners_and_fits_a_block_term`
- The `drift` oracle surface, through `test_smooth_surfaces_keep_their_power` and the oracle invariants.
- No test pins small-n robustness. None exists to pin.

**(d)** Guide, "Certification: documented limits", item 1:

> **Small-n noise (A5, deferred).** … With heteroscedastic, skewed noise it
> can be anti-conservative: in a Monte Carlo of the bound alone, 0.17
> against a nominal 0.05. … If your metric is a tail latency, raise
> `design.confirm.replicates`.

Item 3:

> **Pure error stands in for every configuration.** … If those under-state
> the variance elsewhere, the model half is anti-conservative.

**(e) Limits.** A5 and A6 are deferred. There is:
- no per-finalist variance-ratio or skewness diagnostic;
- no replicate floor;
- no bootstrap or permutation bound;
- no outlier flag;
- no heteroscedasticity test of M3.

Drift between screen and refine is tested only under the opt-in
`reuse_screen`.

**(g) Update, #321 P3.** A5, A6 and the M3 check are implemented (spec §7
items 1, 2, 2a): the robust terminal family, the replicate floor, the skewness
pretest, Brown-Forsythe on M3, outlier flags and censoring. The terminal
half's false-certificate rate under heteroscedastic, skewed noise is now
<= 0.05 + 2 SE in all 96 measured cells. The worst is 0.048 +- 0.003. The M3
check's conditional miss rate at h >= 8 is NOT within δ (0.32 at h = 8).

**(f) Verdict: PARTIAL.** Documented limits A5 and A6. The campaign-level
false-certification rate is now 0 in every swept cell, but by
conservatism. The terminal half's small-n anti-conservatism is stated, not
fixed.

---

## Q3. Model misspecification: cliffs, cubics, multimodality, and the power of the adequacy checks

**(a) The validation check.**
- Refine registers 4 off-lattice validation points: coded ±0.5, chosen by a seeded greedy maximin design.
- They are held out of the fit. A joint predictive F (Chow 1960) at α = 0.05 tests them against the model's predictions.
- PRESS and R²_pred are recorded as diagnostics, not gates.

**(a) The sticky verdict.**
- `model_adequate` is sticky over the epoch.
- A rejection is overturned only by a strictly higher model class that completed a validation check.
- A same-class refit never overturns one.
- A higher class without a check leaves the verdict unknown (`screen_rejection_unresolved`).

**(a) What happens when the model is inadequate.**
- Confirm seats the measured leaders.
- The `model` rung is barred.
- report.md says the surface is not well approximated and names remedies.

**(b) Evidence.**
- Code:
  - `adequacy.validation_points` (`adequacy.py:64`);
  - `prediction_check` (`adequacy.py:198-250`);
  - `epoch_verdict` (`adequacy.py:252`);
  - `stage_runner._adequacy_record` (`stage_runner.py:7892`);
  - `report_md._inadequate_lines` (`report_md.py:940-971`).
- Artifacts:
  - `recommendation.json` `model_adequacy` (`lack_of_fit`, `validation`, `press`, `epoch`, `design_efficiency`);
  - `report.json` `model_rejected_by`;
  - `effects.json` `held_out_rows`;
  - `design_matrix.json` `validation`.
- Power, 40 seeds (WP-B §3):
  - step_cliff: 40/40 at ×1 and ×4;
  - ridge_cubic: 40/40 at ×1, 26/40 at ×4;
  - two_peaks: 38/40 at ×1.
- Size on smooth surfaces: 1-3 of 40 (nominal 2). The unit test measures size < 0.09 over 400 designs.
- False certificates on the non-quadratic family:

  | surface | stage-0 | after WP-B | after WP-A, my 40-seed rerun |
  |---|---|---|---|
  | step_cliff ×1 | 37/40 | 0/40 | — |
  | ridge_cubic ×1 | 35/40 | 0/40 | — |
  | ridge_cubic ×4 | — | 3/40 | **0/40 certified** |
  | two_peaks ×4 | — | 1/40 | **0/40 certified** |

**(c) Tests.**
- `tests/test_optimize_model_adequacy.py`:
  - `test_non_quadratic_surfaces_are_never_falsely_certified[step_cliff, ridge_cubic]`
  - `test_the_prediction_check_is_size_alpha_under_the_registered_model`
  - `test_without_validation_refine_cannot_overturn_a_screen_rejection`
  - `test_a_foldover_pass_does_not_erase_a_screen_rejection`
  - `test_the_epoch_rule_is_strictly_higher_class_with_validation`
  - `test_an_inadequate_model_never_supplies_the_answer_and_report_md_says_so`
  - `test_smooth_surfaces_keep_their_power`, a guard
- `tests/test_optimize_invariants.py::test_adequacy_determination_checker_has_teeth` (INV-STAT19)

**(d)** report.md, when the model is rejected:

> **Model adequacy:** rejected — … The response surface is NOT well
> approximated by the registered model over these ranges, so the
> recommendation above is NOT the model's argmax … **What to do about it:**
> narrow the ranges …; code a geometric knob with `scale: log`; transform
> the response; declare more levels …; or, for a cliff, threshold or
> multi-modal surface, use a method that does not assume a low-order model.

Guide, "Model adequacy: documented limits", item 1:

> **Power is local to ±0.5.**

**(e) Limits** (WP-B §6, all in the guide):
- power is local to ±0.5, so a narrow peak between points can pass;
- the check's denominator is centre pure error, which is M3 again;
- an α cost of about 5% on true quadratics, with no multiplicity correction across lack of fit plus validation;
- no validation points at screen or foldover;
- snapping on `levels_only` knobs can cancel a validation point;
- V is slightly too small when the objective model is fitted on a subset;
- **the Pareto path ignores a validation rejection** (`modelled` and `shortlist_plan` do not read it).

A non-quadratic surface still converges to a fixed wrong answer. It is now
reported as uncertified with a remedy, not certified.

**(f) Verdict: PARTIAL.** Stage-0 was GAP. False certificates on cliffs,
cubics and two peaks fell from 35-37/40 to 0/40 in every cell measured.
Documented limit: the check's power is local, and the multi-objective path
does not read it.

---

## Q4. Design rationale, assumptions, efficiency, mixed knob types, any knob count

**(a) The design family and its assumptions.**
- The design is a regular two-level fraction at resolution III, IV or V, built for any k up to 100. Then:
  - a registered foldover when aliasing is consequential;
  - a face-centred CCD refine with off-lattice validation points;
  - confirm.
- The assumptions are tabulated, each with where it is relied on, what breaks when it fails, and what catches it:
  - effect sparsity, hierarchy and strong heredity;
  - low-order smoothness;
  - no qualitative interaction outside the held slice;
  - no between-stage drift.
- D-efficiency and centred VIFs are recorded for every fitting stage as run, and the preview prints them.
- Screen-row reuse with a block term is opt-in (`reuse_screen`).

**(a) Mixed knob types.**
- `levels_only` ordered discrete numerics;
- multi-level categoricals through pseudo-factor contrasts, fitted with the exact `(X'X)^-1`;
- centre points cycled over the categorical levels;
- `scale: log`.

**(b) Evidence.**
- Code:
  - `design.generators_for`;
  - `adequacy.design_efficiency` (`adequacy.py:145`);
  - `effects._exact_inference` (`effects.py:706`) for mixed and blocked fits.
- Live `sparse_knobs(6)`, `recommendation.json` `model_adequacy.design_efficiency`:
  - screen: D = 0.894, max VIF 1.0, n = 36, p = 22;
  - refine: D = 0.424, VIF(X²) = 4.17, n = 48, p = 28.
- Textbook checks (WP-B §2.4): a 2² screen with 4 centres has D = 0.595; a k = 2 face-centred CCD with 4 centres has D = 0.594 and VIF(A²) = 1.04.
- `reuse_screen` on bowl saves 4 of 33 runs.
- Construction is checked off the matrix for 3-24 factors, with a GF(2) check to 64 factors at V and 128 at III/IV.

**(c) Tests.**
- `tests/test_optimize_design_construction.py`
- `tests/test_optimize_model_adequacy.py`:
  - `test_design_efficiency_is_recorded_for_the_design_as_run`
  - `test_d_efficiency_matches_the_textbook_value`
  - `test_the_preview_counts_validation_runs_and_reports_efficiency`
  - `test_reuse_*`
- `tests/test_optimize_mixed_construction.py`, `test_optimize_categorical_oracles.py`, `test_optimize_levels_only.py`, `test_optimize_many_knobs.py`

**(d)** Guide, "The assumptions the design family rests on":

> Fractional screening followed by a second-order refine is valid under four
> standard assumptions (Wu & Hamada …; Myers, Montgomery & Anderson-Cook …).
> Nous relies on each of them at a named place.

Quickstart: "**Any number of knobs works** (up to 100 at resolution V)".

**(e) Limits.**
1. **Screening multiplicity.** k per-term tests at α = 0.05 have no family-wise or false-discovery control. The resulting forks spend no δ (spec §6).
2. **Efficiency: D, G and I** (#321 P4). G is exact for first-order models and an upper bound with quadratics; I is exact by region moments; both are declined for multi-level categorical contrasts.
3. **`reuse_screen` with any choice factor is a validation error** (rule 33, #321 P4): partial reuse across choice slices is rejected because a block term cannot absorb choice-by-numeric interactions.
4. **The certificate covers a slice** when refine holds factors fixed (see Q8 and Q5).
5. **HIGH (H3), "any knob count" holds for design and recommendation, not for certification.**
   - Above `decide.CANDIDATE_CAP` = 50,000 candidates, the space is searched and `_global_bound` always adds `model_bound_not_exhaustive`. That is 5 refinable numeric knobs at 9 points each (59,049 candidates).
   - So no campaign with 5 or more refinable numeric knobs can ever certify.
   - Even at k = 4 (6,561 candidates), the Bonferroni t at df = 3 is about 25, so `model_bound_above_epsilon` withholds at the default 4 centre points.
   - Measured: `sparse_knobs(6)` and `sparse_knobs(8)` certified 0 of 16, while true regret was 0 on every seed.
   - Neither the guide nor the quickstart says certification is impossible in this regime. The benchmark doc says the opposite (§12).
   - A Scheffé-type simultaneous band over the whole fitted region would not depend on M and would cover unsearched candidates: sqrt(p·F(p, df)) = 7.3 at p = 6, df = 3. It is the natural follow-up.

**(f) Verdict: PARTIAL.** Stage-0 was PARTIAL. The design rationale,
assumptions, efficiency and mixed types are answered. Documented limits:
screening multiplicity and D-only efficiency. Undocumented limit (H3):
many-knob campaigns never certify.

---

## Q5. Post-selection inference and the winner's curse

**(a) The certificate.** It is selection-valid: Hsu's MCB argument for the
terminal half, and a simultaneous family for the model half.

**(a) The baseline seat.** When `known_valid_baseline` is declared
(single-objective), it is a permanent CRN-paired confirm seat.
`gain_over_baseline` gives a two-sided simultaneous interval:
- Bonferroni over every finalist against the baseline, at δ_t per look;
- reported at the guaranteed `1 − delta_terminal` (`delta_guaranteed`);
- valid for the data-selected winner.

**(a) What is still biased.**
- The point estimate comes from the selecting replicates and is labelled as biased upward.
- `finalists[*].mean` is the selecting mean.
- A percentage ε still resolves against the best finalist's selecting mean (`_confirm_epsilon`, `source: best_finalist`).
- No post-selection validation block exists.

**(b) Evidence.**
- Code:
  - `stage_runner._gain_over_baseline` (`stage_runner.py:7366-7400`);
  - `certificate.simultaneous_gain_interval` (`certificate.py:298-337`), with `t_{1-δ/(2M)}`;
  - `delta_guaranteed` (`stage_runner.py:7017`);
  - `_confirm_epsilon` (`stage_runner.py:7546-7573`).
- Artifacts: `report.json` and `confirmation.json` `gain_over_baseline`, with `estimate`, `low`, `high`, `delta`, `delta_guaranteed`, `simultaneous_over` and `method`.
- Measured (WP-A §5; bowl, sd 0.4, seeds 1-12, unpaired): 11/12 intervals cover the true gain. The mean estimate bias is +0.19 against a gain of about 6.5. Stage-0 measured a winner bias of +0.21 (+0.52 sd) at sd 0.4.

**(c) Tests.**
- `tests/test_optimize_certification_soundness.py`:
  - `test_the_baseline_is_a_reference_finalist_with_a_gain_interval`
  - `test_no_baseline_means_no_reference_seat`
  - `test_the_gain_interval_reports_the_coverage_it_guarantees_after_stopping`

**(d)** report.md:

> **Gain over the baseline** …: [low, high] (coverage >= 0.95 over the
> registered confirm looks -- the round reported is the one the campaign
> stopped at; from that round's fresh replicates; point estimate …, biased
> upward by selection)

Guide, limit 6:

> The baseline's gain point estimate is selection-biased. The interval is
> not. Report the interval.

**(e) Limits.**
- No unbiased point estimate of the winner's value.
- ε (when given as a percentage) is still referenced to selected data.
- Paired (CRN) gain intervals are not exercised end to end, because the synthetic seeded workload gives zero-spread differences.
- Multi-objective has no baseline seat.
- `_baseline_seat_extra` over-counts one seat when the baseline is already a finalist, so `confirm_affordable` can stop a round early.
- An inadmissible baseline vetoes the round with no dedicated reason.

**(f) Verdict: PARTIAL.** Stage-0 was GAP. A selection-proof interval for the
gain is now reported, at no extra runs. Documented limits: no
post-selection validation block, and the ε reference uses selected data.

---

## Q6. Benchmarks against random search, LHS and GP-BO

**(a) The harness.** `benchmarks/optimization/` runs Nous and four baselines
at Nous's own budget N, judged by true regret on the noiseless surface:
- RS and LHS;
- a fitted GP-BO: Matern-5/2 ARD, MAP under BoTorch-legacy priors, EI, constrained EI, a never-re-pick-a-failure rule;
- the audit's crude GP-BO.

Rows carry the code digest, and the digest is part of the cache key.

**(b) Evidence.** `docs/benchmarks/optimization-benchmark.md` and `.json`
were generated at `fd2e722`, with Nous source digest `10d74ceaa7add3b7`.
- Suite: 336 campaigns.
- Audit repro: 360 campaigns. Nous against the fitted GP-BO (GP-mean rule) is better 21, tie 186, worse 153.
- Smooth family: within ε of the best baseline in 128/128.
- Non-quadratic family, against GP-BO: 0 / 17 / 31 within ε.
- The CPU figure at 12 knobs: 2.6 s against 88 s.

**(c) Tests.** `tests/test_optimization_benchmark_smoke.py`, 16 tests,
including:
- `test_every_method_spends_exactly_nous_budget_and_is_judged_in_truth`
- `test_gp_gradient_matches_finite_differences`
- `test_a_cached_row_from_other_code_is_not_reused`

**(d)** The benchmark doc:

> **This is a descriptive comparison, not a statistical one.** … There are
> no anytime (regret-vs-budget) curves and no confidence intervals on the
> means.

Guidance table:

> Response suspected multimodal, cliff-like or strongly non-polynomial |
> **GP-BO.**

**(e) Limits.**
- **HIGH (H2): the published tables predate WP-B and WP-A.** `fd2e722` is an ancestor of both, so the certification columns describe the old certificate. They still say:
  - "162 of 336 suite campaigns certified, of which **26 are false**";
  - "in 22 of these 48 campaigns, and all 22 certificates are false";
  - `cert/false` cells such as step_cliff 6/6 and ridge_cubic 7/7;
  - "Many knobs, few of which matter | **Nous** … and certifies".

  At 9e354a2 the non-quadratic family certifies 0, and `sparse_knobs` certifies 0 of 16 at seeds 1-8. The regret columns are probably unchanged except where WP-B's validation rows altered the run count: N is now 33 rather than 29 on bowl, and the geometric_knob recommendation moves. They have not been regenerated.
- Other limits: no anytime curves, no CIs, no multi-objective benchmark, and no ablation for the drift advantage.

**(f) Verdict: PARTIAL.** Stage-0 was GAP. A reproducible matched-budget
benchmark exists and its interpretation is honest. Its certification
figures are stale against the code under audit (H2). Documented limit: it
is descriptive only.

---

## Q7. Reproducibility and pre-registration

**(a) The pre-registration.** `policy.json` and `policy.sha256` are compiled
at verify, before any benchmark run, and verified on every stage, failing
closed. The policy hash includes:
- the validation design (`validation_points`, `validation_seed`);
- `reuse_screen`;
- each rule's accounting string.

**(a) Provenance.** `report.json` `provenance` records:
- the Nous version, commit and a source sha256 over a stated scope;
- runtime versions;
- the sha256 of every `runs.jsonl`, `design_matrix.json`, `relations.json` and `campaign.epoch-*.yaml`;
- the analysis constants and switches, read live from the code;
- the waivers.

**(a) Re-analysis.** `nous reanalyze` re-drives the real stage runner over a
replay of the recorded rows and diffs every derived artifact:
- exit 0: identical;
- exit 1: differs, with each difference listed;
- exit 2: cannot be reanalysed.

The cross-epoch `error_budget` records which epochs were compiled after
earlier epochs' data.

**(b) Evidence.**
- Code:
  - `provenance.analysis_constants` (`provenance.py:142`), `input_hashes` (`:196`), `error_budget` (`:351`);
  - `reanalyze.reanalyze` (`reanalyze.py:314`).
- A live bowl `report.json` has provenance keys `analysis_constants`, `inputs`, `nous`, `policy_hash`, `runtime` and `waivers`.
- Run order is `matrix.randomized_run_order(n, seed=iteration)` (`matrix.py:460`, `stage_runner.py:3359`).

**(c) Tests.**
- `tests/test_optimize_reanalyze.py`, 21 tests, including:
  - `test_an_edited_measurement_is_detected_twice`
  - `test_a_changed_analysis_constant_is_reported`
  - `test_a_two_epoch_campaign_reproduces_each_epoch_from_its_own_registration`
  - `test_reanalysis_executes_nothing`
- `tests/test_optimize_provenance.py`, 6 tests.
- `tests/test_optimize_policy.py::test_hash_is_stable_and_changes_with_the_mechanism_patch`

**(d)** Guide, "Re-deriving a report's analysis":

> 0: the analysis re-derives identically under this code (the measurements
> themselves are taken as recorded)

On the error budget:

> It is valid only under each epoch's own response-model assumptions.

**(e) Limits.**
- **The pre-registration is self-attested.** Same-process writers can rewrite `policy.json` together with its sidecar. Gate records are HMAC-sealed, but the guide says the key is reachable by same-user code. There is no external timestamp or signature.
- **Reanalyze takes the measurements as recorded.** It proves analysis determinism, not data integrity.
- **The run-order seed is the iteration index,** so it is identical across campaigns: reproducible, not concealed.
- **Stopping at a continue gate after seeing data** is recorded, but not charged.
- **The cross-epoch budget is informational.**
- **The guide's error-budget paragraph is stale.** It still says "22 of 22 certificates were false" as a current qualification (MEDIUM, §12).

**(f) Verdict: ANSWERED** for re-analysis and provenance, which stage-0
listed as missing: content hashes, code version, analysis constants, a
re-analysis command, and an error budget across epochs. External anchoring
is a documented limit, tracked below.

---

## Q8. Measurement validity: manipulation checks, locks, held-out, gates vs advisories

**(a) Hard gates, regardless of `--auto-approve`:**
- design-matrix fidelity;
- held-out leakage;
- correctness-relation failures;
- adapter-contract and mechanism-tree drift;
- 2(b): the authored tests must fail before the build;
- 2(c): baseline equivalence. **An unarmed 2(c) is now a gate,** with a written waiver;
- 2(d): the tests must fail by assertion against a mechanism-reverted mutant;
- the build write scope;
- the sealed gate records;
- **a locked parameter with no observable is a validation error**, unless it is acknowledged in `unverified_locks`, which is recorded under `provenance.waivers`.

**(a) Advisory or weak checks:**
- **Manipulation checks** compare an observable with the level, and fall back to `applied.*`, the rendered config. Target-emitted keys win on collision.
- **`held_out`** is a different metric on the same rows. It decides nothing.
- **CRN pairing** is labelled when `seed_env` is declared. It is not verified to affect the target.

**(b) Evidence.**
- `stage_runner._baseline_unarmed` (`stage_runner.py:1560-1580`), which raises `OptimizationGateFailed` unless `allow_unarmed_baseline` is set.
- `locked.validation_findings` (`locked.py:73-150`): "AN ERROR, NOT A WARNING".
- `runner._check_manipulation` (`runner.py:421-440`).
- `held_out.py:1-20`: "decides nothing and feeds nothing".
- `_baseline_equivalent` (`stage_runner.py:1240-1262`): a relative mean difference within a tolerance, not TOST.
- `test_vacuity.py`; `build_scope.check` (`build_scope.py:331`).

**(c) Tests.**
- `tests/test_optimize_locked_parameters.py`, 14 tests, including:
  - `test_an_unenforceable_lock_is_an_error_not_a_warning`
  - `test_a_target_that_ignores_the_locked_value_aborts_the_campaign`
- `tests/test_optimize_test_vacuity.py`:
  - `test_an_import_only_test_of_a_new_module_is_rejected_as_vacuous`
- `tests/test_optimize_build_oracles.py`:
  - `test_a_test_that_passed_before_build_fails_verify`
- `tests/test_optimize_held_out.py::test_held_out_is_reported_and_shifting_it_changes_no_decision`
- `tests/test_optimize_campaign_halts_on_gates.py`

**(d)** Guide:

> **Oracle 2(c) unarmed is a gate.** … `verify` aborts. If the target truly
> cannot run the control before the build, waive it in writing …

On 2(b):

> 2(b) accepts a test that failed before the build only because the module
> or symbol it imports did not exist … Each declared `correctness` test …
> needs one of two kinds of evidence

**(e) Limits.**
- No automated seed-sensitivity probe, so a `paired: true` label can be decorative.
- No held-out workload or seed set is evaluated on the winner.
- 2(c) is not a formal equivalence test.
- Manipulation predicates can be satisfied by the rendered config when the target emits nothing.
- **The certificate's scope is a slice when refine holds factors** (`certificate_scope.region: slice`, `held_fixed`, `stage_runner._certificate_scope` at `:7403`). It is recorded and printed, but the alternative levels are not seated (A4 seat flips deferred).

**(f) Verdict: PARTIAL.** Stage-0 was PARTIAL. Two stage-0 advisories are now
gates (unarmed 2(c), locks without observables), and 2(d) closes the
import-only gaming. Documented limits: CRN is unverified, there is no
held-out workload, and manipulation checks are echo-based.

---

## Q9. Failures, missing data, constraints

**(a) Failures and missing data.**
- Failed and timed-out rows are dropped from the fit and recorded in `fit_exclusions.json` (planned = fitted + excluded + held out).
- A level-correlated loss withholds certification (`fit_exclusions_level_correlated`).
- An unmeasured finalist withholds (`finalist_unmeasured`) and nulls `R_terminal`.

**(a) Constraints.**
- A configuration is admissible only if **every replicate** passes.
- Constraint models exclude confidently infeasible candidates at `δ_screen / C` (`constraint_models.per_constraint_delta`, `constraint_models.py:272`).
- A refill round replaces vacated seats. It never certifies, and its look is charged.

**(b) Evidence.**
- `exclusions.analyse` (`exclusions.py:416`).
- Withheld reasons `finalist_measured_infeasible`, `no_admissible_finalist`, `shortlist_refilled` and `finalist_unmeasured` (`report_md.WITHHELD_MEANING`, `report_md.py:54`).
- Stage-0 arithmetic for the every-replicate rule at n = 3:
  - a constraint with mean = bound + 0.3σ passes with probability ≈ 0.055;
  - one with mean = bound − 0.3σ is struck off with probability ≈ 0.76.

**(c) Tests.**
- `tests/test_optimize_exclusions.py`, properties a-f.
- `tests/test_optimize_refill.py`:
  - `test_the_refill_round_never_certifies_and_halves_delta`
  - `test_the_refill_never_certifies_falsely_on_a_stochastic_boundary`
- `tests/test_optimize_no_admissible_finalist.py`
- `tests/test_optimize_constraint_models.py`

**(d)** Guide, limit 2:

> **Outliers and censoring (A6, deferred).** … A timed-out run is an
> unmeasured row …, not a right-censored observation with the bound it
> implies. Constraints are judged "every replicate passes", not as a mean or
> chance constraint.

**(e) Limits.** A6 is deferred:
- no censoring model;
- no `constraint_semantics: mean | chance`;
- no feasibility probability on a certified answer;
- the constraint δ is not in the stated sum.

**(g) Update, #321 P3.** Timeouts are right-censored and never imputed.
`constraints[].semantics: every_replicate | mean | chance:<alpha>` is
implemented, with a one-sided t or Clopper-Pearson bound per finalist at
`δ_feasibility/(S C L)`. `δ_feasibility` is in the stated sum.

**(f) Verdict: PARTIAL.** Unchanged from stage-0 in substance. Missing data
is detected honestly and now named. Documented limit: censoring and chance
constraints (A6).

---

## Q10. AI-native risks

**(a) Where the LLM runs.** Only in `plan` and `build`, before the epoch.
Every epoch state makes zero model calls (INV-ECO01).

**(a) Isolation.**
- Measurement runs in a **clean checkout**: the base commit plus the sealed mechanism patch, in its own repository, with hardened git.
- Gate records are HMAC-sealed outside the agent's tree.
- The write-scope diff refuses out-of-scope writes, git manipulation and protected-input edits, including the benchmark harness, however the run command reaches it.
- Processes the build leaves running are killed and fail the build.

**(a) Human review.** The build review gate (`build_review.json`) asks a
human **only without `--auto-approve`**, which is this kind's default.
Auto-approval is recorded as "unreviewed" in `provenance.waivers`.

**(a) Cost.** One `llm_metrics.jsonl` row per attempt, with `cost_usd`.
The model is `OPTIMIZATION_MODEL = "claude-opus-5"`.

**(b) Evidence.**
- `orchestrator/optimize/clean_tree.py`, `gate_records.py:1-40`, `build_scope.py:191,331`, `isolation.py`.
- Build review: `stage_runner.py:1595-1621`, with `gate.prompt` at `:1606`.
- Cost rows: `build.py:190-219`.
- Model: `orchestrator/campaign.py:68`.

**(c) Tests.**
- `tests/test_optimize_build_scope.py`, 30 tests, including:
  - `test_editing_the_benchmark_harness_aborts`
  - `test_the_harness_is_protected_however_the_run_command_reaches_it`
  - `test_forging_a_record_and_its_digest_together_fails_the_seal`
  - `test_an_auto_approved_build_review_is_recorded_as_unreviewed`
  - `test_an_interactive_reviewer_is_asked_and_the_answer_recorded`
  - `test_a_process_the_build_leaves_running_is_killed_and_fails_the_build`
- `tests/test_optimize_clean_tree.py`; `tests/test_optimize_guide_security_claims.py`; `tests/test_optimize_gate_defaults.py`

**(d)** Guide:

> Under `--auto-approve` (this kind's default) **no human sees it**: the
> gate approves itself, and `report.json` `provenance.waivers` lists the
> build as auto-approved, unreviewed.

The guide also has a list headed "What all of this still does not cover".

**(e) Limits** (all stated in the guide):
- in-process tampering by in-scope mechanism code, such as monkeypatching the timer;
- the seal key is reachable by same-user code;
- changes undone within one batch;
- anything outside the clean tree;
- double-forks inside one polling interval;
- non-Python import paths;
- the script path itself.

Also:
- The default is unreviewed.
- The model ID is an alias, not a dated snapshot, so builds are not reproducible across model updates. The patch is hashed.
- The build agent can still read the workload and special-case it, with no held-out workload to reveal the overfit (Q8).

**(f) Verdict: PARTIAL.** Stage-0 was PARTIAL. The defences are now
substantive and tested: clean checkout, sealed records, scope diff, vacuity
mutant and review gate. Documented limits: same-user threats, an unreviewed
default, and an undated model.

---

## Q11. Run allocation: is it decision-theoretically justified?

**(a) Answer for this release.** Runs are allocated by **registered branches
with accounting rules**, not by a decision-theoretic allocator. The compiled
policy fixes:
- every state's design;
- every branch's trigger, on closed-vocabulary observations, and each branch's `accounting` string:
  - foldover when aliasing is consequential and affordable;
  - curvature to refine at lack-of-fit α = 0.05;
  - survivors to refine;
  - a confirm round when the bound exceeds ε;
  - refill when seats are vacated;
  - front gap-fill (multi-objective);
- shortlist seating rules: anchors, then the largest-model-bound challenger, then the model ranking, then the baseline, with x̂ kept in every round.

`step()` is pure and deterministic. Every decision is a row in
`transitions.jsonl`, with the rule and the `policy_hash`. Inference is
protected from the allocation by:
- simultaneous families;
- per-look α-spending fixed at compile time;
- refill rounds never certifying.

Nothing scores where the next run buys the most value of information,
expected improvement or hypervolume improvement. Nothing proposes the next
epoch.

**(b) Evidence.**
- `policy.py:161-245`: `CURVATURE_ACCOUNTING`, `FRONT_GAP_ACCOUNTING` and `REFILL_ACCOUNTING`.
- `policy.confirm_looks` (`policy.py:827`).
- `stage_runner.py:5872`, the seat for the largest-model-bound challenger.
- The guide's "States and registered branches" table.
- There is no allocator. Optuna appears only in the reflective kind's `orchestrator/arm_sweep.py`.

**(c) Tests.**
- `tests/test_optimize_policy.py::test_every_conditional_transition_names_accounting_and_known_keys`
- `tests/test_optimize_certification_soundness.py::test_every_confirm_look_is_charged`
- `tests/test_optimize_refill.py::test_only_a_constrained_policy_registers_the_branch_and_it_comes_first`

**(d)** Guide:

> `step(policy, state, observations) -> (next_state, rule)` is the *only*
> thing that decides what runs next. It is pure, total, and deterministic …

**(e) Limits.** The allocation is principled (sequential RSM after Box &
Draper) but not optimal in any stated decision-theoretic sense. The run
budget a branch spends is not chosen to maximise any stated utility.
WP-D (below) is the follow-up:
- a recombination pool ranked by EHVI or knowledge gradient per run;
- `nous plan-next` with a stated utility;
- Optuna as a hashed, seeded proposal-only tool, never used for inference.

**(f) Verdict: PARTIAL.** Documented limit: registered branches with
accounting rules. A decision-theoretic allocator and an Optuna planning tool
are the follow-up.

---

## 12. Claims the code does not back

**Resolution (commit 2f2c913, after this audit was written).** All four HIGH
items and the three MEDIUM items below were fixed before release:
H1 -- second-order fits now take SEs and covariance from the exact
`(X'X)^-1` (`tests/test_optimize_exact_second_order.py`, checked against
numpy; the WP-B oracle re-run on step_cliff / ridge_cubic / saddle / bowl at
x1 and x4 gives 0 false certificates, bowl power 6/8 and 2/8); H2 -- the
benchmark document carries a banner that its certificate columns predate
WP-B/WP-A, with the current figures; H3 -- the quickstart states that
many-knob campaigns find the optimum but do not certify; H4 -- the guide states
the measured power cost. The Scheffé-band bound (H3's real fix) and the
benchmark regeneration are tracked follow-ups (section 13). The findings are
kept below as found.

**HIGH (as found):**

- **H1. The model half of the certificate uses an optimistic SE on second-order fits.**
  - Location: `certificate.py:186-191`, with `effects.py:525-560`.
  - The spec's M1-M4 and the guide present the bound as "Bonferroni one-sided t at δ_screen" with no caveat. `effects.py` still says the quadratic SEs are "never gated on their CIs", which stopped being true when WP-A gated certification on `R_model`.
  - Measured understatement of the contrast SE: up to 1.30× (k = 2) and 1.53× (k = 3).
  - Fix: use the exact `(X'X)^-1` for every fit (`_exact_inference` exists). Or add the factor to M3 and to the guide's assumptions and re-measure.
- **H2. `docs/benchmarks/optimization-benchmark.md` describes the pre-WP-B and pre-WP-A certificate.**
  - The tables were generated at `fd2e722`.
  - It claims "26 are false", "22 of these 48 … all 22 certificates are false" and step_cliff 6/6, ridge_cubic 7/7. It also says Nous on many sparse knobs "certifies".
  - At 9e354a2 the non-quadratic family certifies 0/48 and `sparse_knobs` certifies 0/16.
  - Fix: regenerate both tables under the current digest, or banner the certification columns as historical.
- **H3. "Any number of knobs" has no certification caveat.**
  - Above `CANDIDATE_CAP` (5 or more refinable numeric knobs at 9 points each), `model_bound_not_exhaustive` always withholds. At 4 knobs the Bonferroni t at df = 3 is about 25.
  - The guide and quickstart do not tell the user that such campaigns can never certify. The benchmark's guidance table says they do.
  - Fix: state it in the quickstart and the guide's knob-count section and in the benchmark guidance. The Scheffé-band issue below is the real fix.
- **H4. Guide, "What `certified: true` claims":** "It costs no power on surfaces the model describes".
  - Contradicted by the WP-A spec itself: §8.1 shows 621 → 425 certificates; §8.3 shows smooth-surface power 61 → 48 at ×1, with saddle 6 → 0 and interaction_only 7 → 1.
  - Fix: replace it with the measured power cost (the spec's own text: "the remedy is more centre points").

**MEDIUM (wording):**

- Guide, `INV-SEM17` paragraph: "When the latest fitting stage's lack-of-fit test rejected the model". The verdict is now sticky over every stage and includes the validation check. The figure "(measured: 2 of 20 seeds on `bowl`)" predates WP-B.
- Guide, error-budget qualification: "on the benchmark's non-quadratic family, 22 of 22 certificates were false at a nominal 0.10". This is history, not current behaviour (the same staleness as H2).
- `effects.py`'s module docstring and the per-column comment ("never gated on their CIs"). This is part of H1.

Verified as backed:
- WP-A §8.1-8.3 and WP-B §3 numbers in every cell spot-checked;
- the Monte Carlo of the terminal bound;
- the withheld-reason vocabulary in report.md;
- the `certificate_scope` slice record;
- `delta_guaranteed` on the gain interval;
- unarmed 2(c) and unobservable locks as hard errors;
- the provenance keys;
- reanalyze exit codes (tests).

## 13. Deferred items for GitHub issues

1. **WP-D: decision-theoretic run allocation** (`nous-e2e/audit/wp-d-decision-theoretic-allocation.md`).
   - D1: a recombination pool, ranked by EHVI per run (EI or knowledge gradient for a single objective), seated in a registered "allocate" confirm round. It spends only when the models are adequate.
   - D2: `nous plan-next`, which scores candidate next-epoch moves by expected value of information under a stated utility and writes a validated campaign diff plus `planner_decision.json`.
   - D3: Optuna as an optional `nous[bo]` proposal-only tool, seeded and hashed into the policy, never used for inference.
   - D4: benchmark evidence, single- and multi-objective.
   - D5: Q11 in every later audit.
   - Stacked on #302.
2. **A5: small-n noise diagnostics and a robust terminal bound.** Record per-finalist variance ratio and skewness. Add a replicate floor, or a bootstrap-t / permutation bound on CRN differences. Withhold with a named reason when the diagnostics fail. Motivation: the terminal bound alone reaches 0.17 against 0.05 under heteroscedastic, skewed noise at n = 3. Today the sweep is clean only because the model half withholds.
3. **A6: outliers, censoring, constraint semantics.**
   - Flag outlying rows by studentized residuals in `effects.json` and `confirmation.json`.
   - Record a timeout as right-censored at `run_timeout_sec`, with the bound it implies.
   - Add `constraints[].semantics: every_replicate | mean | chance:<alpha>`, with a one-sided or Clopper-Pearson feasibility bound folded into the stated δ.
4. **Exact covariance in the model regret bound (H1)**, if it is not fixed before release. Use `s² d'(X'X)^-1 d` for every fit, two-level and CCD included, so the model family's Bonferroni level is the stated δ_screen. Re-measure power, because the bound widens by up to about 1.5× on refine.
5. **A model bound that does not depend on the candidate count (H3).** Replace or supplement Bonferroni over enumerated candidates with a Scheffé-type simultaneous band over the fitted region, or a max-t over the region. That gives a finite bound for searched spaces, removes `model_bound_not_exhaustive` as a permanent veto, and makes many-knob campaigns certifiable. State its cost against Bonferroni on small spaces.
6. **A post-selection validation block (A3 remainder).** After the winner is chosen, run fresh paired replicates of the winner against the baseline. Take the unbiased reported value, the gain point estimate and the ε reference from them, so selection data never feed a reported estimate. The preview states the cost (`replicates × 2`).
7. **Seat flips for held factors (A4 remainder).** Seat a confirm finalist at each alternative level of every held factor, so a refine-slice certificate can cover the declared space. Each flip needs a model half for its own slice.
8. **The constraint-exclusion δ in the stated budget.** Constraint-model exclusions spend `δ_screen / C` on a family distinct from E_s. Add it as a third union term, or fold it into δ_screen's split. Report it in `error_budget`.
9. **A multi-objective global bound.** Front certificates have α-spending but no model half. An unshortlisted configuration that dominates the chosen front point by ε is not bounded.
10. **Screening multiplicity.** Main-effect drops at a per-term α = 0.05, with no FWER or FDR control, decide which factors refine. Account for them, for example with Holm or Benjamini-Hochberg at screen, or with a δ share, or state the fork in the budget.
11. **Adequacy power beyond ±0.5, and at screen/foldover** (WP-B limits 1, 3, 5, 8, 9). Add space-filling validation points beyond ±0.5 or at screen, and a multiplicity correction across lack of fit plus validation. Handle snapping onto a lattice level on `levels_only` knobs. Build V from the rows actually fitted.
12. **The Pareto path ignores a validation rejection** (WP-B limit 10). `modelled` and `shortlist_plan` should read `model_adequate`, so that predicted front extremes are not seated from a rejected model.
13. **A heteroscedasticity check of M3.** Compare the replicate variance at the confirm finalists, and at the centre, with the pure error (Brown-Forsythe). When it fails, withhold or widen the model half.
14. **CRN verification.** Add an automated seed-sensitivity probe at verify: the same configuration with the same seed twice, then two different seeds. Fail when `paired: true` would be decorative. Add an end-to-end test of paired gain intervals with nonzero spread.
15. **A held-out workload on the winner.** Add `workload.held_out_seeds` (or a held-out workload): after certification, measure the winner and the baseline on unseen seeds, so generalization and build-agent overfitting become visible.
16. **Manipulation checks beyond echo.** Require target-emitted evidence (not `applied.*`) for factors that declare a manipulation predicate, or flag the predicate as echo-only in the report.
17. **2(c) as a formal equivalence test.** Replace the relative-mean tolerance with TOST at a declared margin, using the paired form under CRN.
18. **A dated model ID.** Pin a dated snapshot for `OPTIMIZATION_MODEL` and record the resolved ID in `llm_metrics.jsonl` and `provenance`.
19. **External anchoring of the pre-registration.** Anchor `policy.sha256` and the input hashes outside the work_dir: a git commit, a signed timestamp, or a remote. Move the gate-record seal key out of same-user reach, or document the threat model.
20. **Benchmark completeness (H2 remainder).** Regenerate under the current digest. Add regret-against-budget (anytime) curves, CIs on the means, a multi-objective (hypervolume) benchmark and an ablation of the drift advantage.
21. **Run-order concealment.** The run-order seed is the iteration index, identical across campaigns. Derive it from the policy hash plus a recorded salt, so that periodic environmental effects do not line up across campaigns.
22. **Baseline-seat accounting.** `_baseline_seat_extra` over-counts a seat when the baseline is already a finalist. A baseline measured inadmissible should have its own withheld reason (WP-A review items).
23. **Charging the cross-epoch budget.** `error_budget.cumulative` is informational. Offer a mode where epoch e certifies at a δ share of a declared campaign-wide budget, and charge a stop at a continue gate.
24. **Design-efficiency breadth, and reuse with choice factors** (WP-B limits 6, 12). Report G- and I-efficiency. Support partial `reuse_screen` across choice slices.
