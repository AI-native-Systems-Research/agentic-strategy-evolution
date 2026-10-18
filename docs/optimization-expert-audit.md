# Expert audit of `kind: optimization`, questions Q1-Q11 (P8, final)

**Code audited:** branch `nousko` at `4ccc6b3`. That is the merge of P1-P6b
for PR #302 (#320, #321), plus the fix this audit found (`01eded8`, §12 H-P8).

**Benchmarks (Q6):** read from branch `nk-p7-bench` at `0c57b40`,
`docs/benchmarks/optimization-benchmark.md` and its four JSON files. Those
benchmarks were generated at Nous digest `44d94bc5ee2a41b2`, which is code
before `01eded8`. P7 re-runs them on the fixed code before the release.

**Questions.** The audit asks Q1-Q11 as a panel of specialists would: design
of experiments; statistics and multiple testing; Bayesian optimization and
decision theory; and AI-native experimentation.

**Method.**
- For every question, I first name the single most likely way an expert would
  break the claim. Then I check whether a test or a measurement already
  constructs that case, and construct it myself when it is cheap and missing.
- I traced every number below to a file:
  - the per-package results under `nous-e2e/audit/{p2,p3,p4,p6b}/`;
  - the specs in `docs/superpowers/specs/`;
  - the benchmark document;
  - or my own probes in `nous-e2e/audit/p8/`.
  A number I could not trace is not used. Two such numbers in the user-facing
  docs were corrected (§12).
- **Spot-checks.** I re-ran 70 named tests (13 + 57 in two runs), at least 2 per question, at
  `-n 4`. All passed. The targeted optimize suite on the fixed code also
  passed: `-k optimiz` through `nous-e2e/bin/heavy`, 3227 passed, 11 skipped.

**Verdict key.**
- **holds**: the code implements the claim, a test pins it, and the
  falsifying case is constructed.
- **holds with stated limits**: as above, with limits that the guide states
  in plain words.
- **does not hold**: the claim is false as written.

| Q | verdict |
|---|---|
| Q1 error control | holds with stated limits. One HIGH found and fixed (H-P8). |
| Q2 noise robustness | holds with stated limits |
| Q3 misspecification, adequacy power | holds with stated limits |
| Q4 design rationale, efficiency | holds with stated limits |
| Q5 post-selection inference | holds with stated limits |
| Q6 benchmarks | holds with stated limits. The losses are real and are stated. |
| Q7 reproducibility, pre-registration | holds with stated limits |
| Q8 measurement validity | holds with stated limits |
| Q9 failures, missing data, constraints | holds with stated limits. The H-P8 path ran through here. |
| Q10 AI-native risks | holds with stated limits |
| Q11 run allocation | holds with stated limits |

---

## Q1. Error control: what does `certified: true` guarantee?

**Answer.** On one epoch of a single-objective campaign:

> Pr(certified and f(x*) − f(w) > ε) ≤ δ_screen + δ_terminal
> (+ δ_constraint + δ_feasibility when registered)

The terms:
- x* is the best configuration in `certificate_scope`, and w is the
  recommendation.
- δ_constraint is registered when a declared constraint has a violating side.
- δ_feasibility is registered when a `mean` or `chance` constraint is
  declared.

The statement rests on four assumptions:
- **M1.** The registered response class holds over the scope.
- **M2.** Replicates are independent, with approximately normal means, made
  robust by A5 (Q2).
- **M3.** The centre pure error stands for every configuration. It is
  checked, by veto.
- **M4.** The shortlist is fixed before the round's replicates are seen.

The proof is a union of simultaneous families:
- **E_s**, the model family. The constant is min(Bonferroni over the
  *declared* grid, Scheffé over the q model terms). It is chosen from
  (δ, m, q, df) only.
- **E_t**, the terminal family: Hsu's multiple comparisons with the best,
  Bonferroni over challengers and over the L registered looks.
- **E_c**, the constraint exclusion family.
- **E_f**, the distributional feasibility family.

Earlier routing decisions spend no δ. The screen's Holm labels decide no
route (Q4), so they need no δ share.

**Evidence.**
- Code:
  - `stage_runner._finish_confirm`: the `certified = (...)` conjunction at
    `stage_runner.py:7889`;
  - `_global_bound` (`:8900`);
  - `certificate.simultaneous_critical` (`certificate.py:127`),
    `model_regret_bound` (`:196`), `region_bound` (`:296`),
    `robust_terminal_bound` (`:836`);
  - `policy.confirm_looks` (`policy.py:1315`), `policy.delta_stated`
    (`:498`).
- Measured, false certificates / certificates:
  - noise sweep, 1008 campaigns: 0/245 after P2 (`p2/final_noise.json`),
    0/149 after P3 (`p3/p3_noise.json`), 0/157 after P4
    (`p4/p4_noise.json`), 0/117 with allocate (`p6b/alloc_noise.json`);
  - rounds sweep, 320 campaigns: 0/56 (`p2/final_rounds.json`);
  - WP-B oracle, 288 campaigns: 0/50 under the shipped per-test adequacy
    rule (`p4/review_new.json`);
  - P7 benchmark: 0 false in every arm. Suite 50/336, audit repro 60/360,
    ablations, and 36/72 front certificates.
- Constants. These match the guide; I recomputed them.
  - At df 3, Bonferroni over 15 challengers is 6.74 and Scheffé (q = 3) is
    5.28.
  - Over 80 challengers, 11.98 against 6.71 (q = 5).
  - Over 9^4 − 1 challengers, 52.47 against 11.05 (q = 14).
- Monte Carlo of looks: 4 looks give 0.105 before spending and 0.029 after
  (spec §8.2).

**Tests run.**
- `test_optimize_certification_soundness.py`:
  - `test_a_certificate_states_both_halves_within_epsilon`
  - `test_every_confirm_look_is_charged`
  - `test_inv_sem20_holds_on_oracle_campaigns_and_has_teeth`
- `test_optimize_cert_followups.py`:
  - `test_constraint_exclusion_is_a_third_union_term`
  - `test_scheffe_is_chosen_from_the_design_alone_and_beats_bonferroni_on_large_m`
  - `test_the_region_bound_equals_brute_force_over_the_grid`
  - `test_an_epoch_certifies_at_its_share`
- `test_optimize_exact_second_order.py`: all 8 tests.

**Falsification.** The likeliest break is an SE that the family's level
silently depends on. The stage-0 audit found one on second-order fits (H1,
fixed in `2f2c913`).
- I constructed the analogous case on **first-order** fits: a two-level design
  that lost rows. Script: `nous-e2e/audit/p8/probe_family_exact.py`.
- The event is truth-free: under the class, est − f is pure noise, so this is
  the worst case over surfaces. The setup is 2^k + 4 centres, δ = 0.05, and
  the shipped `simultaneous_critical`. The table gives worst-x\* Pr(E_s fails).

  | design | before `01eded8` | after | exact (X'X)^-1 |
  |---|---|---|---|
  | k = 3, nothing lost | 0.030 | 0.030 | 0.030 |
  | k = 3, one corner lost | **0.065 ± 0.004** | 0.032 | 0.032 |
  | k = 3, two opposite corners lost | **0.085 ± 0.004** | 0.031 | 0.031 |
  | k = 4, two opposite corners lost | 0.043 | 0.020 | 0.020 |
  | k = 2, one corner lost | **0.109 ± 0.004** | 0.039 | 0.039 |

- It reached `certified` end to end. Two opposite *failed* corners are not
  `level_correlated`, and a *rejected* corner is never bias-relevant, so
  neither withholds. Two-level factors are not refinable, so
  `model_class_unchecked` does not apply.
- On a 4 × two-level screen → confirm campaign with the all-low and all-high
  corners failing, seeds 1 and 3 certified. The recorded R_model was 0.041,
  where the exact value is 0.055.
- This is a **HIGH, found and fixed** (§12 H-P8). The before/after numbers are
  in `p8/family_exact.txt` and `p8/family_exact_fixed.txt`.

**Documented limits.**
1. M1 is checked, not proved (Q3).
2. M3 is checked by a veto with limited power (Q2).
3. The cross-epoch `error_budget` is informational unless
   `campaign_delta` is declared. When declared, it binds.
4. The constants are conservative, so the measured rates are 0 against a
   nominal 0.10. The price is power (Q4).

**Verdict: holds with stated limits** (after `01eded8`).

---

## Q2. Robustness to noise: heavy tails, skew, heteroscedasticity, outliers, drift

**Answer.**
- **Terminal half (A5).** Per challenger, the terminal bound is
  max(t, robust) at the same per-look, per-challenger level. The robust bound
  is the sign-flip bound under CRN (Hartigan; exact for symmetric
  differences; a Monte Carlo inversion above n = 16) or the bootstrap-t
  otherwise.
- **Two vetoes:**
  - a replicate floor: the smallest n with 2^-n ≤ δ_t/(L(S−1)); 6 at the
    defaults, 7 with a constraint (`policy.replicate_floor`);
  - a skewness pretest at a priori α = 0.25 (`noise_skewed`).
- **M3 check.** A one-sided Brown-Forsythe contrast, "the finalists spread
  more than the pure-error cells", withholds the model half
  (`heteroscedastic_pure_error`).
- **Outliers** are flagged and never deleted, with a sensitivity refit.
- **Drift** is handled by randomized order, concealed by a salt, and blocked
  confirm; `reuse_screen` adds a block term.

**Evidence.**
- Code: `certificate.robust_terminal_bound`;
  `noise.sign_flip_upper`, `sign_flip_upper_mc`, `bootstrap_t_upper`,
  `skewness_test`, `brown_forsythe_contrast`, `studentized_outliers`;
  `stage_runner._heteroscedasticity_check` (`:8977`).
- Terminal half alone (`p3/mc_a5_final_seed1000.txt`; 96 cells, 4000 trials
  each, fresh seeds):
  - every cell is ≤ 0.05 + 2 SE;
  - the worst is **0.0483 ± 0.0034** (paired, n = 8, lognormal, sd ratio 10);
  - t alone reaches 0.148 (paired, n = 6, lognormal, ratio 10).
- Power cost: noise-sweep certificates fell 245 → 149 (P3), and mean runs
  rose 32.2 → 42.9.

**Tests run.**
- `test_optimize_noise_quality.py`:
  - `test_skewed_replicates_withhold_noise_skewed`
  - `test_the_sign_flip_bound_is_exact_for_symmetric_differences`
  - `test_the_monte_carlo_sign_flip_keeps_its_level`
  - `test_a_campaign_below_the_replicate_floor_withholds_by_name`
  - `test_heteroscedastic_pure_error_withholds_the_model_half`
  - `test_brown_forsythe_size_and_power_at_confirm_group_sizes`

**Falsification.** The likeliest break is heteroscedastic noise that the pure
error under-states, so the model half is anti-conservative. It is
constructed (`p3/item1_mc.txt`; bowl and saddle, sd from 1× at the centre to
(1 + h)× at the corners, 1000 fits):
- conditional miss rate given that lack of fit and Brown-Forsythe both pass:
  0.013 / 0.041 / **0.317 ± 0.046** / 0.296 at h = 1 / 3 / 8 / 10 (bowl);
- for saddle at h = 8: 0.149 ± 0.044.

The guarantee does NOT hold conditionally at h ≥ 8. End to end, 800
campaigns at h up to 8 gave no false certificate (`p3/item1_camp.txt`),
because lack of fit withholds most of them. This is stated, not fixed.

**Documented limits** (guide, "Noise and data-quality checks" and limit 3):
- the h ≥ 8 conditional miss rate;
- the skewness pretest withholds about 26% of Gaussian rounds;
- the pretest's null is approximate under CRN (paired differences share the
  best's replicates);
- below the floor nothing is certifiable;
- the bootstrap-t is second-order accurate, not exact.

**Verdict: holds with stated limits.**

---

## Q3. Model misspecification: cliffs, cubics, multimodality, and the power of the adequacy checks

**Answer.**
- **Checks.**
  - Refine holds out off-lattice validation points: 4 at ±0.5, plus an outer
    ring of 2 at ±0.8. A joint predictive F tests them.
  - Lack of fit runs at every fitting stage.
  - Opt-in validation points run at screen.
  - Each test is a per-test veto at α = 0.05 (`adequacy_multiplicity:
    per_test`, the default). A Holm family is recorded as information.
- **Sticky verdict.** Only a strictly higher class with a completed check
  overturns a rejection, and an unknown basis is never promoted.
- **Under a rejected model:** the `model` rung is barred, confirm seats the
  measured leaders, the MO shortlist seats no predicted point, and report.md
  names the remedies.

**Evidence.**
- Code: `adequacy.validation_points`, `prediction_check` (`adequacy.py:432`),
  `adequacy_family` (`:520`), `epoch_verdict` (`:548`);
  `stage_runner._adequacy_record`.
- 288-campaign oracle (`p4/review_new.json`): non-quadratic surfaces
  (step_cliff, ridge_cubic, two_peaks; ×1 and ×4; 48 campaigns) certified 0;
  the smooth family 29 at ×1 and 21 at ×4; 0 false.
- 40 seeds at ×4 (`p2/final_oracle40.txt`): ridge_cubic and two_peaks
  certified 0/40 each.
- Size under a true quadratic (k = 2 composite, 6 validation points, 3 × 4000
  designs): per-test "reject if either" 0.068-0.072; Holm 0.032-0.037.

**Tests run.**
- `test_optimize_model_adequacy.py::test_non_quadratic_surfaces_are_never_falsely_certified`
- `test_optimize_adequacy_power.py`:
  - `test_the_outer_ring_has_power_where_the_inner_ring_has_none` (corner_bumps:
    inner ring 0/4 rejections, ring 4/4)
  - `test_the_adequacy_family_is_size_alpha_under_a_true_quadratic`

**Falsification.** The likeliest break is a misfit the checks cannot see:
- a feature narrower than the validation spacing;
- cancelling quadratics (a saddle) with refine skipped.

Constructed:
- `corner_bumps`, at ±0.8, is caught by the ring.
- The masked saddle, f = 10 + xa² − xb² + 0.036 xb, used to certify falsely
  6/40 under per-test and 12/40 under Holm. It is now 0 false in 40, with 21
  certified (`p4/review/saddle_new.txt`), because refine runs whenever a
  refinable factor exists.
- two_peaks still converges to the wrong peak (true gap 0.364). It is reported
  `terminal_best`, not certified.

**Documented limits** (guide, "Model adequacy: documented limits"):
- power is local to the validation points;
- the denominator is centre pure error (M3);
- the foldover gets no validation points of its own;
- per-test vetoes cost certificates on smooth surfaces (per-test 50 against
  Holm 63 of 288, both 0 false);
- a non-quadratic surface still gets the quadratic model's answer.

**Verdict: holds with stated limits.**

---

## Q4. Design rationale, assumptions, efficiency, mixed knob types, any knob count

**Answer.**
- **Design.** A regular two-level screen at resolution III, IV or V for any k
  up to 100. Then a registered foldover, a face-centred CCD refine with
  validation points, and confirm.
- **Assumptions.** Effect sparsity, hierarchy, heredity and low-order
  smoothness are tabulated with where each is relied on, and what catches each
  one.
- **Routing.** Since #321 P4, routing does not rest on sparsity: refine runs
  whenever a refinable factor exists. The screen's Holm labels (FWER 0.05)
  decide no route.
- **Efficiency.** D, G and I are recorded for every fitting stage, all from the
  exact (X'X)^-1.
- **Certification on many knobs.** It is now bounded in principle: a Scheffé
  constant, plus branch and bound over the unevaluated grid. In practice it
  rarely certifies (below).

**Evidence.**
- Code: `design.generators_for`; `adequacy.design_efficiency`
  (`adequacy.py:368`); `effects.screening_family`; `certificate.region_bound`.
- Recomputed for the k = 2 face-centred CCD with 4 centres: D = 0.408,
  G = 0.632, I = 3.633. This matches guide limit 6. The model-adequacy spec
  §2.4 said D = 0.594, which is the 2² screen's value; it is corrected (§12).
- Screen FWER under the global null at k = 6: 0.173 per-test against 0.031
  Holm, over 2000 screens (test docstring and `p4/mc_screen_fwer.py`).
- Many knobs (`p2/src-item1_many.json`: sparse_knobs 5/6/8, 36 campaigns):
  0 certified; `model_bound_above_epsilon` in 32 of 36; true regret at most
  0.08.
- P7 benchmark, 48 campaigns: 0 certified (47 before P3/P4), 42 of 48
  `model_bound_above_epsilon`.
- CPU: `sparse_knobs_12` 2.8 s → 37.5 s per campaign. `region_bound` is
  47.7 s of a 98 s profile.

**Tests run.**
- `test_optimize_screening_multiplicity.py::test_the_screen_holds_its_family_wise_error_under_the_global_null`
- `test_optimize_model_adequacy.py::test_d_efficiency_matches_the_textbook_value`
- `test_optimize_cert_followups.py::test_a_searched_space_is_no_longer_a_permanent_veto`

**Falsification.** The likeliest break is "any knob count", read as "any knob
count certifies". It does not, as measured above. The quickstart now says so
plainly. It previously said "regret 0" on sparse_knobs, but the recorded
maximum is 0.08; that is corrected (§12).

**Documented limits:**
- at 3 pure-error df, many-knob and near-tied campaigns withhold on width; the
  remedy is more centre points;
- G is an upper bound with quadratic terms;
- G and I are declined for multi-level categoricals;
- partial `reuse_screen` across choice slices is rejected.

**Verdict: holds with stated limits.**

---

## Q5. Post-selection inference and the winner's curse

**Answer.**
- **The certificate is selection-valid.** The terminal family is simultaneous
  over the shortlist (Hsu's MCB), and the model family is simultaneous over
  the declared grid, so it holds for a data-chosen x̂ and a data-chosen
  "outside S".
- **The baseline gain interval** (`certificate.simultaneous_gain_interval`,
  `certificate.py:519`) is Bonferroni over every finalist against the
  baseline. It is reported at the guaranteed 1 − δ_terminal after optional
  stopping (`delta_guaranteed`). Its point estimate is labelled "biased upward
  by selection" in report.md.
- **The opt-in `design.validate` block** gives unbiased point estimates. It
  measures the winner and the baseline on r fresh paired blocks, with seeds
  offset past confirm. It reports the value, a gain interval and the ε
  reference.
- **The opt-in `design.inertness`** runs a TOST of each held-factor flip at
  δ_t / F.

**Evidence.**
- Code: `stage_runner._gain_over_baseline` (`:8780`); `_confirm_epsilon`
  (`:9063`, `source: best_finalist` without the block); `policy.VALIDATE_ACCOUNTING`.
- Measured (guide): validate on bowl, noise 0.4, r = 4, seeds 1-8. The fresh
  intervals cover the true gain in at least 7 of 8.
- TOST size at the margin boundary: ≤ 0.05 over 4000 trials.

**Tests run.**
- `test_optimize_cert_followups.py`:
  - `test_the_validation_block_estimates_the_gain_without_the_winners_curse`
  - `test_pinned_seeds_give_validation_draws_confirm_never_used`
  - `test_tost_is_an_equivalence_test_of_size_alpha`
- `test_optimize_certification_soundness.py::test_the_gain_interval_reports_the_coverage_it_guarantees_after_stopping`

**Falsification.** The likeliest break is a reported value taken from the
selecting replicates. Without `design.validate`, `recommendation.value`,
`finalists[*].mean` and a percentage ε all come from selecting data. All
three are labelled as such. The interval, not the point, is the claim. The
pinned-seed case, where "fresh" draws could reuse confirm's seeds, is
constructed and refused.

**Documented limits:**
- unbiased points only with the opt-in block, which costs 2r runs;
- validate and inertness are separate claims at δ_terminal, outside the
  certificate's union bound (guide limit 3);
- multi-objective has no baseline seat.

**Verdict: holds with stated limits.**

---

## Q6. Benchmarks against random search, LHS, GP-BO and ParEGO

Source: `nk-p7-bench@0c57b40`, `docs/benchmarks/optimization-benchmark.md` and
its JSON files, at Nous digest `44d94bc5ee2a41b2`. That code is before
`01eded8`, and P7 re-runs the benchmark on the fixed code. The fix only widens
model bounds on fits that lost rows, so regret is unaffected unless the
ranking changes; certificate counts can only fall.

**Answer.**

*Protocol and baselines.*
- The analysis was pre-declared and committed in `dc489e0` before the first
  regenerated row.
- **Matched budget:** each baseline gets exactly Nous's own N on the same
  (surface, noise, seed).
- **Primary metric:** per family, the mean normalised true regret, Nous minus
  GP-BO (GP-mean pick), with a seeded bootstrap over 8 seeds.
- **Baselines:** RS, LHS, a fitted GP-BO (Matern-5/2 ARD with MAP priors, EI,
  constrained EI) and the audit's crude GP-BO.
- **Multi-objective:** ParEGO, judged by hypervolume regret.

*Single objective, suite.*
- **Primary results, Nous minus GP-BO, per family:**

  | family | difference [95%] |
  |---|---|
  | shipped | −0.055 [−0.066, −0.037] |
  | non-quadratic | −0.059 [−0.082, −0.021] |
  | many-knob | +0.0002 [−0.0002, +0.0008] |

- **Both "favours Nous" results rest on one surface each.** This reading is
  post hoc and labelled so.
  - Without `stochastic_constraint_boundary`, the shipped result is
    **+0.004 [+0.0004, +0.007]**, a small loss.
  - Without `two_peaks`, the non-quadratic result is **+0.043 [+0.032,
    +0.052]**, a loss.
  - Part of the stochastic-boundary gap is design asymmetry: Nous replicates
    its finalists and the baselines do not.
- **Wins and ties.**
  - Smooth surfaces are parity with GP-BO: 1 better / 127 tie / 0 worse
    within ε.
  - Nous wins clearly against RS and LHS.
  - Drift: Nous has 0 regret. The ablation shows this is NOT from randomized
    order: regret is unchanged with randomization off, while certificates fall
    10 → 4 of 16.
- **Losses.**
  - GP-BO wins on `ridge_cubic` (10-70× lower regret), `step_cliff`,
    `sla` (Nous 0.40 / 0.275 against 0) and `fails_at_one_level` (0.32-0.36
    against 0.08).
  - Many knobs: GP-BO reaches 0.004 by 20% of N.
- **Audit repro.** Against the fitted GP-BO, Nous is 83 better / 166 tie /
  111 worse exact, and 56 / 264 / 40 within ε. Nous still loses more often
  than it wins.

*Multi-objective.*
- Pooled HV regret, Nous minus ParEGO: **+0.038 [+0.035, +0.040]**. ParEGO wins
  the majority of seeds on all 9 surfaces.
- Nous beats RS (−0.022 [−0.027, −0.017]) and LHS (−0.015 [−0.020, −0.009]).

*Certificates and cost.*
- **0 false certificates in every arm of every section.**
  - Suite: 50 of 336 certified, against 162 with 26 false before P3/P4.
  - Audit repro: 60 of 360, against 170 with 53 false.
  - Fronts: 36 of 72.
- **Cost of the soundness fixes:**
  - runs +24% (suite) and +54% (audit repro);
  - many-knob certificates 47 → 0;
  - `sparse_knobs_12` CPU 2.8 s → 37.5 s, against GP-BO's 79.6 s.

*D4 ablations.*
- **Allocate, single objective.**
  - Paired Δ normalised regret: −0.0012 [−0.0032, 0.0000] on smooth surfaces.
  - Runs 45.1 → 52.3, certificates 20 → 12.
- **Allocate, multi-objective.**
  - Paired Δ HV regret: −0.0063 [−0.0100, −0.0029].
  - Front certificates 36 → 37 of 72.
- **BO proposer.** No measurable benefit: MO −0.0039 [−0.0080, +0.0002], and
  on `pareto_with_constraint` certificates 2 → 0 of 8.

**Tests.** `test_optimization_benchmark_smoke.py::test_every_method_spends_exactly_nous_budget_and_is_judged_in_truth`
was run, with the smoke suite in the targeted run.

**Falsification.** The likeliest break is a family mean carried by one cell, or
a matched-budget rule tilted toward Nous. The benchmark itself shows the first
(both headline wins vanish without one surface each) and states the second:
- every comparison is at Nous's chosen N;
- the anytime curves show GP-BO ahead earlier on many-knob surfaces;
- the within-ε tie width is Nous's own ε.

**Documented limits:**
- 8 seeds, so percentile intervals collapse when seeds agree;
- no EHVI baseline; ParEGO only;
- no replicated-confirmation baseline;
- the regenerated numbers predate `01eded8` until P7 re-runs.

**Verdict: holds with stated limits.** Nous does not beat GP-BO on regret
except where it replicates finalists under noisy constraints, and it loses to
ParEGO on fronts. Its distinct value is a certificate that was sound in every
campaign measured.

---

## Q7. Reproducibility and pre-registration

**Answer.**
- **Pre-registration.** `policy.json` and `policy.sha256` are compiled at
  verify, before any run, and checked on every stage. The hash covers:
  - every registered branch and its accounting;
  - the constants the certificate uses (adequacy rule, robustness rule,
    validation design, allocate seats, `planner.bo`);
  - the run-order salt.
- **Anchors.** The registration is anchored outside the work dir at compile
  (state home), and optionally to `--out`, a git ref, or a pushed ref. Refs are
  create-only, re-anchoring after data is refused, and `--verify --remote`
  reads only the remote.
- **Run order.** Derived from the policy hash plus a recorded CSPRNG salt
  (`policy.run_order_seed`, `policy.py:1093`).
- **Provenance** records:
  - the Nous version, commit and source digest;
  - runtime versions;
  - the input hashes;
  - the analysis constants, read live;
  - the waivers;
  - the requested and served model per call.
- **`nous reanalyze`** re-drives the real stage runner over the recorded
  rows: exit 0 identical, 1 differs, 2 cannot reanalyse.

**Evidence.**
- Code: `orchestrator/optimize/anchor.py` (`verify`, `refuse_reanchor_after_data`);
  `provenance.build_provenance`, `error_budget`;
  `reanalyze.reanalyze` (`reanalyze.py:340`).

**Tests run.**
- `test_optimize_anchor.py`:
  - `test_a_fully_consistent_forged_work_dir_is_caught_only_by_the_anchor`
  - `test_reanchoring_a_forgery_after_data_is_refused_and_still_detected`
- `test_optimize_reanalyze.py::test_an_edited_measurement_is_detected_twice`
- `test_optimize_run_order_concealment.py::test_two_campaigns_differing_only_in_salt_run_rows_in_different_orders`

**Falsification.** The likeliest break is a same-user process that rewrites
`policy.json`, its sidecar and the local anchors together. This case is
constructed: the fully consistent forgery is caught only by an anchor the
forger did not rewrite. The guide states that only a pushed ref, on a remote
that refuses force-pushes, or a third-party timestamp, holds against a
same-user forger.

**Documented limits:**
- reanalyze proves analysis determinism, not data integrity;
- a copied and altered work dir reports "no anchor" (anchors are keyed by
  resolved path), so use `--out` or `--remote`;
- `snapshot_pinned` is always false: no dated snapshot of the model alias is
  verifiable;
- the cross-epoch budget is informational unless `campaign_delta` is declared.

**Verdict: holds with stated limits.**

---

## Q8. Measurement validity: manipulation checks, locks, held-out data, gates vs advisories

**Answer.**

*Hard gates*, regardless of `--auto-approve`:
- design-matrix fidelity;
- held-out leakage;
- correctness relations;
- adapter-contract and mechanism-tree drift;
- 2(b) pre-build failure;
- 2(c) baseline equivalence, now a ratio-of-means TOST, paired under CRN;
  unarmed, it is a gate with a written waiver;
- 2(d) the mutant;
- the write scope;
- sealed gate records;
- unobservable locks, as a validation error;
- the CRN seed probe at verify: a random-effects ANOVA; a target that ignores
  the seed fails verify.

*Reported, not gating:*
- echo-only manipulation predicates are flagged; `evidence: target` makes
  them enforced;
- `workload.held_out_seeds` measures the winner and the baseline on unseen
  seeds after the answer, and never feeds certification.

**Evidence.**
- Code: `stage_runner._baseline_equivalent` (`:1258`), `_baseline_unarmed`
  (`:1697`); `noise.tost_ratio`, `crn_probe_verdict`; `locked.validation_findings`.
- TOST at n = 3 has power of only 0.61-0.75 for a margin of 3 sd, so
  `baseline_replicates` defaults to 6.

**Tests run.**
- `test_optimize_noise_quality.py`:
  - `test_a_seed_the_target_ignores_fails_verify`
  - `test_the_old_relative_mean_rule_passed_an_undecidable_control`
- `test_optimize_manipulation_evidence.py::test_evidence_target_on_an_echo_predicate_fails_validation`
- `test_optimize_held_out_seeds.py::test_an_overfit_winner_is_exposed_and_no_decision_moves`
- `test_optimize_locked_parameters.py::test_a_target_that_ignores_the_locked_value_aborts_the_campaign`

**Falsification.** The likeliest break is a `paired: true` label on a target
that ignores the seed. It is constructed, and verify fails. The second
likeliest is a manipulation check satisfied by the rendered config. It is
flagged echo-only; under `evidence: target` it is refused.

**Documented limits:**
- `evidence: target` checks the observable's root, not that the predicate is
  tied to the level;
- the CRN probe has power about 0.59 at a 2× effect (P3 documented limit);
- held-out seeds make overfitting visible but do not withhold;
- the certificate covers a slice when refine holds factors.

**Verdict: holds with stated limits.**

---

## Q9. Failures, missing data, constraints

**Answer.**

*Missing data.*
- Failed and rejected rows are excluded from the fit and recorded (planned =
  fitted + excluded + held out).
- A level-correlated loss withholds (`fit_exclusions_level_correlated`).
- An unmeasured finalist withholds, and R_terminal becomes unknown, not
  smaller.
- Timeouts are right-censored at `run_timeout_sec` and never imputed.
- Since `01eded8`, a fit on a subset of a two-level design uses the exact
  (X'X)^-1, so the remaining rows widen the bound by the right amount.

*Constraints.*
- `every_replicate` (the default), `mean` (approximate; exact with
  `support:`, by Hoeffding) or `chance:<α>` (exact, Clopper-Pearson).
- Shown per finalist at δ_feasibility/(S·C·L), a union term.
- Constraint-model exclusion spends δ_constraint.
- A refill round never certifies.

**Evidence.**
- Code: `exclusions.analyse`; `noise.feasibility_shown`, `censored_bound`;
  `stage_runner._distributional_feasibility` (`:8711`).
- Measured, `mean` semantics with the true mean on the threshold, n = 6:
  a plain t is 3.5× nominal (lognormal σ 0.5); the shipped max(t,
  bootstrap-t) is about 2× (guide).

**Tests run.**
- `test_optimize_noise_quality.py`:
  - `test_a_timeout_is_right_censored_never_imputed`
  - `test_chance_semantics_is_a_clopper_pearson_bound`
  - `test_mean_semantics_holds_its_level_under_skew`
- `test_optimize_refill.py::test_the_refill_never_certifies_falsely_on_a_stochastic_boundary`
- `test_optimize_exact_second_order.py::test_a_campaign_that_lost_two_opposite_corners_bounds_with_the_exact_covariance`

**Falsification.** The likeliest break is a missing-data pattern the
level-correlation detector passes, on which the fit is still optimistic. That
is H-P8 (Q1): two opposite failed corners, or one rejected corner. It was
constructed, found, and fixed in `01eded8`. The end-to-end test fails on
`4ccc6b3` (R_model 0.041 against exact 0.055) and passes after.

**Documented limits:**
- censoring is informative, so a fit with censored rows is optimistic about
  them; a censored finalist still withholds;
- `mean` semantics are approximate at small n (Bahadur & Savage);
- a `chance` constraint needs log(level)/log(1 − α) replicates.

**Verdict: holds with stated limits** (after `01eded8`).

---

## Q10. AI-native risks

**Answer.**
- **Where the model runs.** Only in `plan` and `build`, before the epoch.
  Every epoch state is tokenless (INV-ECO01); report.md and the gate summaries
  render with zero tokens.
- **Measurement isolation.** Runs happen in a clean checkout (base commit plus
  the sealed patch).
- **Records.** Gate records are HMAC-sealed outside the agent's tree.
- **Write scope.** The write-scope diff refuses out-of-scope writes and
  protected-input edits, the benchmark harness included.
- **Leftover processes.** Processes the build leaves running are killed and
  fail the build.
- **Vacuous tests.** The 2(d) mutant rejects import-only tests.
- **Review and model records.** Build review is recorded as "unreviewed" under
  `--auto-approve`. The requested alias and the served model are recorded per
  call.
- **Allocation.** The allocator, plan-next and Optuna never reach inference
  (Q11).

**Evidence.** `clean_tree.py`, `gate_records.py`, `build_scope.py`,
`provenance.model_record`, `campaign.OPTIMIZATION_MODEL = "claude-opus-5"`.

**Tests run.**
- `test_optimize_build_scope.py`:
  - `test_the_harness_is_protected_however_the_run_command_reaches_it`
  - `test_forging_a_record_and_its_digest_together_fails_the_seal`
  - `test_an_auto_approved_build_review_is_recorded_as_unreviewed`
- `test_optimize_test_vacuity.py::test_an_import_only_test_of_a_new_module_is_rejected_as_vacuous`
- `test_optimize_model_id.py::test_an_unreported_served_model_is_recorded_as_unknown_not_as_the_alias`

**Falsification.** The likeliest break is a build agent that edits the
measuring harness, or forges a gate record together with its digest. Both are
constructed and caught.

**Documented limits** (guide, "What all of this still does not cover"):
- in-process tampering by in-scope mechanism code;
- a seal key reachable by same-user code;
- changes undone within one batch;
- double-forks inside one polling interval;
- the default is unreviewed;
- the model ID is an alias;
- the build can read the workload and special-case it; held-out seeds expose
  this but do not prevent it.

**Verdict: holds with stated limits.**

---

## Q11. Run allocation: is it decision-theoretically justified?

**Answer.**
- **Default.** Runs are allocated by registered branches with named
  accounting rules: foldover, curvature to refine, confirm rounds, refill,
  front gap-fill. `step()` is pure and deterministic, and every decision is a
  row in `transitions.jsonl` with the policy hash.
- **The decision-theoretic layer (WP-D, #320) is opt-in, and it is kept away
  from inference.**
  - **`design.confirm.allocate`.** A registered allocate round seats
    candidates from a recombination pool, ranked by EI or knowledge gradient
    (one objective) or EHVI (exact in 2-D, seeded Monte Carlo in 3-D; it
    declines above 3 objectives).
    - It declines, by name, on an inadequate or unknown-adequacy model, with
      no free seat, or with no expected gain.
    - Its look is charged in every divisor and in the replicate floor.
    - Seats are digest-anchored in the transition row and verified before
      measurement.
    - Claims come only from the seats' fresh replicates.
  - **`nous plan-next`.** It scores next-epoch moves by a true lower bound on
    the expected increment per run, under the model's joint posterior. It
    writes a sealed `planner_decision.json`. `--accept` refuses edited
    campaigns, stale inputs and tampered decisions.
  - **`planner.bo` (Optuna TPE).** It is lazy, seeded, hashed into the policy,
    and reaches only the allocate pool.

**Evidence.**
- Code: `policy.ALLOCATE_ACCOUNTING` (`policy.py:255`), `confirm_looks`;
  `allocate.score`, `ehvi_2d`, `joint_increment_bound` (`allocate.py:743`);
  `allocate_seat.plan`, `seats_digest`; `planner.plan`, `_value`, `accept`.
- Allocate-round soundness: of the campaigns where the allocate round itself
  certified, 0 of 101 were false, which is a one-sided 95% Clopper-Pearson
  upper bound of 0.029 on the false rate. The 101 are 86 on saddle
  (`p6b/m3_saddle.txt`, CP95 0.034), 10 on saddle ×0.5 and 5 on additive.
- Oracle with allocate: 0 false among 48 certificates over 288 campaigns
  (`p6b/alloc_oracle.json`); MO, 37 of 72 with 0 false.
- Benefit (Q6): negligible single-objective regret gain at a cost in
  certificates; a small, real MO gain; no gain from the BO proposer.

**Tests run.**
- `test_optimize_allocate_seat.py`:
  - `test_rewriting_every_predicted_number_leaves_every_bound_unchanged`
  - `test_an_inadequate_model_declines_and_seats_nothing`
  - `test_edited_registered_seats_are_refused_not_measured`
  - `test_the_allocate_round_itself_certifies_soundly`
- `test_optimize_planner.py::test_the_score_is_a_true_lower_bound_on_the_increment`
- `test_optimize_bo_proposer.py::test_optuna_and_the_proposer_never_reach_an_inference_module`

**Falsification.** The likeliest break is allocation leaking into inference
(selection on predictions). It is constructed:
`test_rewriting_every_predicted_number_leaves_every_bound_unchanged` rewrites
every predicted number and every bound is unchanged. The second likeliest is
a planner "lower bound" that is really a difference of two lower bounds. This
was the WP-D review's counterexample, where the old score was 0.299 against a
true increment of about 0.014. It is constructed and now bounded.

**Documented limits:**
- moves are compared by single-point lower bounds, which lean toward small
  moves (no q-EI or q-EHVI);
- the reference point depends on the pool when no frame exists;
- the allocator's extra look costs certificates even when it does not fire
  (Q6: 20 → 12);
- the default allocation remains registered sequential RSM, not an optimal
  policy for any stated utility.

**Verdict: holds with stated limits.**

---

## 12. Claims the code does not back

**HIGH, found by the P8 audit and fixed in `01eded8`:**

- **H-P8. The model half used an understated SE on two-level fits that lost
  rows.**
  - **Cause.** `effects.fit_effects` kept the per-column SE
    σ/√(Σx²) for every first-order fit. That SE is exact only when X'X is
    diagonal. A failed, rejected, censored or infeasible-excluded corner makes
    the main-effect and 2fi columns correlated.
  - **Why nothing withheld.** Two opposite failed corners are not
    level-correlated, a rejected corner is not bias-relevant, and two-level
    factors are not refinable.
  - **Effect.** A screen → confirm campaign could certify on an understated
    R_model. The family-level table is in Q1.
  - **The P2 review** had recorded the path as LOW (L6, "per-term SE after a
    dropped corner"). The guide did not mention it.
  - **Fix.** Any fit whose X'X is not diagonal takes the exact (X'X)^-1. A
    full balanced design is unchanged, byte for byte. Every consumer
    (`model_regret_bound`, `region_bound`, `front_model_half`, the constraint
    models, the allocator posterior, adequacy V) already reads
    `fit.covariance`.
  - **Tests.** Five new tests fail on `4ccc6b3`. One existing test pinned the
    defective SE (`test_optimize_exclusions.py::test_a_partial_fits_uncertainty_is_compared_against_the_full_fit_exactly`);
    it is re-pinned to the exact value.

**Over-claims in the docs, fixed in this commit.** I grepped both guide
copies, both quickstart copies, the plugin skill, `report_md.py`, docstrings
and `data-model.md` for "certified", "unbiased", "exact", "lower bound",
"within δ" and "guarantee", and verified each hit.

1. **Guide, "Two bounds".** It named only `bonferroni_one_sided_t` for the
   model bound and the pre-P3 t methods for the terminal bound. The code
   writes `scheffe_one_sided` when Scheffé is smaller, and
   `bonferroni_max_t_paired_sign_flip` / `bonferroni_max_welch_bootstrap_t`
   under the robust rule. Corrected.
2. **Guide, INV-SEM17 paragraph.** It said "the validation check rejects a
   smooth surface 1-3 times in 40". That figure predates the per-test veto,
   the outer ring and the sticky family. Replaced with the measured per-test
   size 0.068-0.072, with a statement that the epoch rate is higher.
3. **Guide, searched space.** It said "`sparse_knobs` 5-8: R_model 0.76
   against ε 0.50". I could not trace this to any results file. Replaced with
   the recorded counts: `model_bound_above_epsilon` in 32 of 36, true regret
   at most 0.08 (`p2/src-item1_many.json`).
4. **Quickstart (both copies).** It said "measured: regret 0 on
   `sparse_knobs` 5-8". The recorded maximum is 0.08. Corrected.
5. **Guide, limit 1.** It called the sign-flip bound "exact" unconditionally.
   It is exact only for symmetric differences, the guarding pretest is
   approximate under CRN, and the bootstrap-t is not exact. Corrected.
6. **Guide, the certified statement and the error budget.** They omitted
   δ_feasibility, which the code adds (`policy.delta_stated`). Added. The
   error-budget paragraph's "22 of 22" is now marked as history, with the
   current 0 of 48.
7. **`docs/data-model.md`.** "Pr(wrong global decision) ≤ δ_s + δ_t" became
   "Pr(certified and wrong) ≤ …", with the extra terms and the assumptions.
   The same phrase in `CLAUDE.md` is left for the owner: project instructions
   are outside this audit's write scope.
8. **Plugin skill, §7.** The `certified` row now names the extra delta terms
   and the assumptions.
9. **Model-adequacy spec §2.4.** It gave D = 0.594 for the k = 2 face-centred
   CCD with 4 centres; that is the 2² screen's value. The correct value,
   recomputed, is 0.408, matching guide limit 6.

**Verified as backed** (spot-checked against the cited source):
- every number in Q1-Q5 and Q7-Q11 above;
- "TRUE lower bound" (planner): pinned by its counterexample test;
- "unbiased" (post-selection validation): fresh draws, test-pinned;
- "exact" for `chance` (binomial), `support:` (Hoeffding), interval branch and
  bound (converged) and Brown-Forsythe's null;
- "NOT within δ at h ≥ 8": stated as a limit, and matches `p3/item1_mc.txt`;
- report.md's "biased upward by selection" and "coverage ≥ 1 − δ".

## 13. Remaining limits

These are the documented limits after #320 and #321. Each one is stated in the
guide or a spec at the place it applies. None is a deferred fix.

1. **M1 is checked, not proved.** Adequacy power is local to the validation
   points (±0.5, ±0.8). A feature narrower than their spacing can pass. The
   foldover has no validation points of its own. A non-quadratic surface gets
   the quadratic model's answer, uncertified.
2. **M3 under strong heteroscedasticity.** The Brown-Forsythe veto's
   conditional miss rate is 0.317 at h = 8, which is NOT within δ. No false
   certificate was observed end to end in 800 campaigns. The remedy is more
   centre points or a variance-stabilising transform.
3. **Small-n noise.** Below the replicate floor (6, or 7) nothing certifies.
   The skewness pretest costs about 26% of Gaussian power. Its null is
   approximate under CRN. The bootstrap-t is second-order accurate, not exact.
4. **Certification power.** The simultaneous constants are conservative. At
   3 pure-error df, many-knob and near-tied campaigns withhold on width
   (`model_bound_above_epsilon`; P7: 0 of 48 many-knob campaigns certified).
   A max-t quantile would be tighter but is not shipped.
5. **Cost.** P3/P4 raised runs by 24-54% (P7). `region_bound` and the
   outer-ring maximin dominate the CPU on 12 knobs (37.5 s per campaign).
6. **Censoring is informative.** Fits with censored rows are optimistic about
   them, and confirm withholds such finalists. `mean` constraint semantics are
   approximate at small n.
7. **Slice scope.** A refine certificate covers the held slice. Inertness
   TOST is a local equivalence, not full-space certification, which was
   rejected as exponential.
8. **Point estimates** are selection-biased unless `design.validate` is
   declared. Validate and inertness are separate claims at δ_terminal.
9. **Pre-registration anchoring** holds against a same-user forger only
   through a pushed ref or a third-party timestamp. A copied work dir reports
   "no anchor". `snapshot_pinned` is always false.
10. **Measurement validity.** `evidence: target` checks the observable root,
    not that the predicate is tied to the level. The CRN probe has power 0.59
    at 2×. Held-out seeds expose overfitting without withholding.
11. **AI-native.** The limits are same-user threats, an unreviewed default,
    and an undated model alias. The build can still special-case the workload.
12. **Allocation.** Moves are ranked by single-point lower bounds (no q-EI).
    The allocate look costs certificates even when it does not fire. The BO
    proposer showed no measurable benefit in P7.
13. **Benchmarks.** They are descriptive at 8 seeds, use ParEGO without EHVI,
    have no replicated-confirmation baseline, and their regenerated figures
    predate `01eded8` until P7 re-runs them.
