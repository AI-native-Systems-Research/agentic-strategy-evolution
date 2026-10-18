# Model adequacy and design efficiency for `kind: optimization` (WP-B)

Brief: `nous-e2e/audit/wp-b-model-adequacy.md` (items B1-B5). Evidence: the
stage-0 audit, sections Q3 and Q4, and the WP-C matched-budget benchmark. In
that benchmark 22 of 48 non-quadratic campaigns certified, and all 22 were
false.

**Scope split** (DELIVERY-PLAN.md):
- WP-B decides HOW adequacy is determined. It writes the three-valued
  `model_adequate` and its basis.
- WP-A decides what a certificate claims.
- The certification rule is unchanged. It still withholds on
  `model_adequate` false or null; WP-B changes the verdict that rule reads.

## 1. Why lack of fit alone was not enough

Refine's composite has its axial points clamped to the range edge, so it is
face-centred and every numeric factor has exactly 3 levels. A full quadratic
interpolates any one-dimensional shape through 3 points. The lack-of-fit F
therefore has power only through cross-structure. Measured over 40 seeds, it
rejected `step_cliff` 3/40 and `ridge_cubic` 5/40, which is about α. The
screen's rejection (p ≈ 1e-5) was then overwritten by refine's pass.
Accepting the null of a 3-df lack-of-fit test is not evidence of adequacy.

## 2. Design

### 2.1 Validation points (B1)

**The rule.** Refine registers `design.refine.validation_points` (default 4)
extra runs:
- coded **±0.5 on every refinable axis**, the point of [-1, 1] farthest from
  the lattice {-1, 0, +1};
- chosen among {±0.5}^k by a **seeded greedy maximin** (Johnson, Moore &
  Ylvisaker 1990), where each next point maximises its minimum distance to
  those already chosen and the RNG seeded by `validation_seed` breaks ties;
- enumerated up to k = 12 and sampled (4096 seeded vectors) above that, so the
  candidate grid is bounded.

At k = 2 the 4 points are one per quadrant. At every k, each axis is visited
at both +0.5 and -0.5.

**How they run.**
- They are appended AFTER the composite, so every composite row keeps its
  position and `row_index`.
- They execute as their **own block**, after the composite, in a separately
  seeded order.
- They are **held out of the fit**. `effects.json["held_out_rows"]` records
  them, so planned = fitted + excluded + held out.
- They are pre-registered: `design_matrix.json["validation"]`, and the
  policy's refine design (`validation_points`, `validation_seed`), so the
  policy hash changes.

**Why off-lattice, interior, and ±0.5.** A point on the lattice is
interpolated, so it tests nothing. A point at ±0.5 is where a quadratic
through {-1, 0, 1} is least constrained by the data. These are standard
"check points" for model validation (Myers, Montgomery & Anderson-Cook 2016,
§2.7, §8.2; Box & Draper 2007, ch. 13).

### 2.2 The prediction check

Let `e = y_v - X_v b` for the m measured validation points, under the model
fitted WITHOUT them, and let `V = I + X_v (X'X)^-1 X_v'`. The test statistic
is the joint predictive F (Chow 1960):

    F = e' V^-1 e / (m s_pe²)  ~  F(m, df_pe)  under H0

It is exact under the registered model with iid normal errors: `e` depends on
the composite's fit and the new runs, `s_pe²` on the centre replicates'
deviations from their mean, and the two are independent. The check rejects at
α = 0.05.

Per-point Bonferroni prediction intervals (half-width
`t(1-α/2m, df_pe) · s_pe · sqrt(V_ii)`) are recorded beside it, to say WHICH
point disagreed. The joint F is the decision because it uses the correlation
between the predictions; Bonferroni is a conservative per-point reading.

- For a multi-objective campaign, each objective model is checked the same
  way, and any rejection is inadequacy.
- When it cannot be computed (no pure error, no validation row measured, a
  singular model), `rejected` is null with a `reason`. The lack-of-fit verdict
  then stands for this stage.

**PRESS** (Allen 1974): `Σ (e_i / (1 - h_ii))²` and R²_pred over the fitted rows
are recorded as **diagnostics, not gates**. On a face-centred CCD, PRESS has
the same blind spot as lack of fit, because a deleted lattice point is
predicted from the same three-level structure.

### 2.3 Stickiness

`model_adequate` is the **epoch verdict**, recorded in
`model_adequacy.epoch` (`adequacy.epoch_verdict`). Model classes: class 1 is
first order + 2fi (screen, foldover); class 2 is second order (refine).

- A **rejection** (false) is overturned ONLY by a later stage of a
  **strictly higher** model class that **completed a validation check**.
  Refine is the registered augmentation for a screen rejection
  (CURVATURE_ACCOUNTING), and only its held-out check has power against the
  one-dimensional misspecification the screen saw.
- A **same-class refit never overturns a rejection.** A foldover's combined
  fit after a screen rejection is the same first-order model, with the same
  blindness, refitted on more rows. The verdict stays false.
- A strictly higher class **without** a completed check
  (`validation_points: 0`, or not computable) makes the verdict UNKNOWN,
  `screen_rejection_unresolved`.
- Any other verdict (true / null) is superseded by a later stage of at least
  its class.

Whatever is not superseded combines three-valued: any false gives false;
otherwise any null gives null; otherwise true. INV-STAT19's checker enforces
exactly this.

### 2.4 D-efficiency and VIFs (B3)

Recorded for every fitting stage, on the model matrix as run:
- `D = |X'X / n|^(1/p)` (Atkinson, Donev & Tobias 2007, §11.3), computed in
  logs so it cannot overflow;
- each term's centred VIF `[(X'X)^-1]_jj · Σ(x_ij - x̄_j)²`.

The preview prints the planned D-efficiency of the screen and refine designs.
Example: a 2² screen with 4 centres has D = 0.595 and VIF 1; a k = 2
face-centred CCD with 4 centres has D = 0.594 and VIF(A²) = 1.04.

### 2.5 Screen-row reuse with a block term (B4, opt-in)

With `design.refine.reuse_screen: true`:
- A refine cube corner whose levels (held factors included) equal a measured
  screen corner's is filled from that row (`reused_from.stage: screen`) and
  is not re-run.
- The screen's centre rows at refine's centre are appended as **block-1
  centres**.
- The fit gets a block indicator as a **nuisance column**: screen = 1,
  refine = 0, so predictions refer to the refine block. Its t on pure error is
  the drift check (`model_adequacy.reuse.block_effect`, `drift_detected`).
  Pure error pools within (configuration, block). The constraint and objective
  models carry the same block term.

This is standard sequential assembly of a CCD from a factorial (Box & Draper
2007, §15.3). Each block keeps its own centre points, so the block effect is
estimable from the centres, and in a balanced arrangement it is orthogonal to
the model terms.

**Assumption:** no between-stage drift beyond a constant shift, which is
fitted and tested.

**Refused** at runtime (logged at INFO, so the stage runs as without the
option) when the screen ran under another policy hash. With any choice factor
declared it is a **validation error** (rule 33, #321 P4): partial reuse across
choice slices is rejected, for the reason in §6 item 12.
Default off: it changes the run count and the design. On `bowl` it saves 4 of
33 runs. Recommendations are identical, the block p is 0.996, and a planted
+0.5 shift is detected.

### 2.6 Inadequate models (B5)

- With a false verdict, confirm already seats measured leaders. With no
  confirm stage, the report's `model` rung is now **barred**, so the
  `measured` rung answers.
- `report.json` gains `model_rejected_by`.
- `report.md` says the surface is not well approximated, says what the answer
  rests on, and names the remedies: narrower ranges, `scale: log`, a
  transform, more levels, or a method that assumes no low-order model.

### 2.7 Assumptions (B2)

Effect sparsity, hierarchy, heredity, low-order smoothness, no qualitative
interaction outside the held slice, and no between-stage drift. The guide
section "The assumptions the design family rests on" tabulates where each is
relied on, what breaks, and what catches it. The validation check is the
first diagnostic aimed at low-order smoothness rather than at curvature in
aggregate.

**Assumptions of the check itself:**
- iid normal errors, homoscedastic between the centre and the validation
  points;
- pure error from centre replicates represents run-to-run variance. Spec §3.5
  already warns this can be optimistic; if so, the check is anti-conservative
  on smooth surfaces;
- the validation block runs after the composite, so a time trend between them
  can only push toward rejection (the conservative side).

## 3. Oracle results (B1)

Every single-objective `SURFACES` entry except `bowl_out_of_hull`, plus
`NON_QUADRATIC` (ported verbatim from the audit probe and the WP-C benchmark),
seeds 1-8, noise ×1 and ×4 of each surface's `noise_sd`, benchmark
constraints. "false" means certified while the true gap exceeds ε.

| surface | noise | certified (false) before | certified (false) after | runs/campaign before -> after |
|---|---|---|---|---|
| additive | x1 | 7/8 (0) | 6/8 (0) | 33 -> 37 |
| additive | x4 | 1/8 (0) | 1/8 (0) | 33 -> 37 |
| bowl | x1 | 6/8 (0) | 6/8 (0) | 29 -> 33 |
| bowl | x4 | 4/8 (0) | 4/8 (0) | 29 -> 33 |
| bowl_centred | x1 | 7/8 (0) | 6/8 (0) | 33 -> 37 |
| bowl_centred | x4 | 4/8 (0) | 4/8 (0) | 33 -> 37 |
| choice_x_numeric | x1 | 8/8 (0) | 8/8 (0) | 17 -> 17 |
| choice_x_numeric | x4 | 8/8 (0) | 8/8 (0) | 17 -> 17 |
| deterministic_constraint_axis | x1 | 0/8 (0) | 0/8 (0) | 39 -> 43 |
| deterministic_constraint_axis | x4 | 0/8 (0) | 0/8 (0) | 39 -> 43 |
| drift | x1 | 8/8 (0) | 8/8 (0) | 17 -> 17 |
| drift | x4 | 7/8 (0) | 7/8 (0) | 17 -> 17 |
| fails_at_one_level | x1 | 0/8 (0) | 0/8 (0) | 21 -> 21 |
| fails_at_one_level | x4 | 0/8 (0) | 0/8 (0) | 21 -> 21 |
| geometric_knob | x1 | 0/8 (0) | 0/8 (0) | 29 -> 33 |
| geometric_knob | x4 | 4/8 (4) | 0/8 (0) | 29 -> 33 |
| geometric_knob_log | x1 | 6/8 (0) | 6/8 (0) | 29 -> 33 |
| geometric_knob_log | x4 | 4/8 (0) | 4/8 (0) | 29 -> 33 |
| infeasible_corner_interior | x1 | 8/8 (0) | 8/8 (0) | 29 -> 31 |
| infeasible_corner_interior | x4 | 2/8 (0) | 2/8 (0) | 29 -> 31 |
| interaction_only | x1 | 7/8 (0) | 7/8 (0) | 29 -> 29 |
| interaction_only | x4 | 3/8 (0) | 3/8 (0) | 29 -> 29 |
| nan_at_corner | x1 | 0/8 (0) | 0/8 (0) | 8 -> 8 |
| nan_at_corner | x4 | 0/8 (0) | 0/8 (0) | 8 -> 8 |
| ridge_cubic | x1 | 7/8 (7) | 0/8 (0) | 33 -> 37 |
| ridge_cubic | x4 | 3/8 (3) | 3/8 (1) | 33 -> 37 |
| saddle | x1 | 6/8 (0) | 6/8 (0) | 29 -> 33 |
| saddle | x4 | 3/8 (0) | 3/8 (0) | 29 -> 33 |
| sla | x1 | 0/8 (0) | 0/8 (0) | 38 -> 42 |
| sla | x4 | 0/8 (0) | 0/8 (0) | 38 -> 42 |
| step_cliff | x1 | 6/8 (6) | 0/8 (0) | 29 -> 33 |
| step_cliff | x4 | 5/8 (5) | 0/8 (0) | 29 -> 33 |
| stochastic_constraint_boundary | x1 | 0/8 (0) | 0/8 (0) | 38 -> 42 |
| stochastic_constraint_boundary | x4 | 0/8 (0) | 0/8 (0) | 38 -> 42 |
| two_peaks | x1 | 0/8 (0) | 0/8 (0) | 29 -> 33 |
| two_peaks | x4 | 0/8 (0) | 0/8 (0) | 29 -> 33 |

**Totals (288 campaigns).**
- False certificates: 25 before, 1 after.
- Non-quadratic false certificates: 21/48 before, 1/48 after. That one is
  `ridge_cubic` ×4 seed 1, where the validation check had p = 0.18.
- Certificates: 124 before, 100 after.

**Smooth surfaces** (additive, bowl, bowl_centred, saddle, geometric_knob_log,
infeasible_corner_interior, choice_x_numeric, drift, interaction_only):
- certified 99 of 144 before and 97 after;
- no false certificate on either side;
- the two lost certificates are seeds where the validation check rejected a
  true quadratic, the expected α error.
- `geometric_knob` (linear coding of a log bowl, a misspecified model): its 4
  false certificates at ×4 go to 0, and the true gap falls from 26.2 to 7.6.

**40-seed check** (seeds 1-40, ×1 / ×4, certified (false)):

| surface | before ×1 | after ×1 | before ×4 | after ×4 |
|---|---|---|---|---|
| step_cliff | 37 (37) | 0 (0) | 32 (32) | 0 (0) |
| ridge_cubic | 35 (35) | 0 (0) | 16 (16) | 11 (3) |
| two_peaks | 0 (0) | 0 (0) | 1 (1) | 1 (1) |
| bowl | 37 (0) | 33 (0) | 20 (0) | 19 (0) |
| saddle | 37 (0) | 33 (0) | 11 (0) | 10 (0) |
| bowl_centred | 35 (0) | 32 (0) | 27 (0) | 25 (0) |
| additive | 35 (0) | 32 (0) | 11 (0) | 9 (0) |
| geometric_knob_log | 37 (0) | 33 (0) | 23 (0) | 21 (0) |

**Size and power of the check, 40 seeds** (refine-stage rejections):
- Validation check on smooth surfaces: 1-3 of 40, against a nominal 2.
- Lack of fit on smooth surfaces: 3-5 of 40.
- The unit test `test_the_prediction_check_is_size_alpha_under_the_registered_model`
  measures size < 0.09 over 400 designs.
- Power: step_cliff 40/40 at ×1 and ×4; ridge_cubic 40/40 at ×1 and 26/40 at
  ×4; two_peaks 38/40 at ×1 (lack of fit alone already had 40/40).

**Residual false certificates** at ×4 are on surfaces whose misfit at ±0.5 is
comparable to noise: ridge_cubic 3/40, two_peaks 1/40. For two_peaks the
missed narrow peak lies between validation points. A misspecification smaller
than the noise at the points tested is not detectable by any check at this run
count; it is a documented limit (§6).

## 4. Byte-identity

Method: every artifact of every `SURFACES` + `PARETO_SURFACES` campaign
(192 campaigns, seeds 1-8), base b8e4c11 against this branch, with paths and
timestamps normalised. The intended additions are then removed:
- the policy hash value;
- the policy refine keys `validation_points`, `validation_seed`,
  `reuse_screen` and the refine accounting string;
- the keys `model_adequacy`, `model_rejected_by`, `held_out_rows` and
  `design_matrix.validation`;
- the validation rows in design_matrix / runs.jsonl / run_order.

**Default (`validation_points: 4`): 171 of 192 campaigns identical.** The 21
that differ:
- **5 changed verdicts.** Refine's validation check rejected (additive s8,
  bowl_centred s8, pareto_choice_split s1, pareto_three s4,
  pareto_three_noisy s4). Recommendation unchanged in all 5; 4 certificates
  withdrawn. These are α-level rejections of a true model.
- **8 `geometric_knob` campaigns**, verdict false on both sides. The
  measured-leader shortlist now draws from more measured configurations: the
  validation rows are measured leaders, and better ones. Recommendation moves
  from (32, 8320) to (17, 4288), and the true gap falls from 26.2 to 7.6.
- **8 `pareto_with_constraint` campaigns**, same verdict. The validation rows
  are admissible measured configurations, so
  `supported_feasible_candidate.n_admissible_configurations` grows, and on 5
  seeds the refill pool and confirm shortlist change. Recommendation unchanged
  in all 8; one certificate (seed 4) withdrawn.

**Why the rest is identical:**
- the validation block runs after the composite;
- the synthetic target draws validation noise from its own seeded substream,
  so later draws are unchanged;
- the validation rows are excluded from the measured front.

Run counts: refine +4 rows on every refining campaign. That is the stated
cost, and the preview counts it.

**`validation_points: 0`: 108 of 192 identical.** All 84 differences are the
stickiness rule: refine's lack-of-fit pass no longer overturns the screen's
rejection, so the verdict is null (`screen_rejection_unresolved`) and
certification is withheld. That is the intended semantics without a
validation check. Recommendations are unchanged in all 84.

## 5. Tests (behavioral; `tests/test_optimize_model_adequacy.py`)

All fail on b8e4c11 (verified in a scratch copy with only the test surfaces
ported), except the 4 noted as guards.

| item | test |
|---|---|
| B1 | `test_non_quadratic_surfaces_are_never_falsely_certified[step_cliff, ridge_cubic]`: 6/8 and 7/8 false before, 0/8 after |
| B1 | `test_validation_rows_are_registered_held_out_and_reconciled` |
| B1 | `test_validation_points_are_a_seeded_maximin_design` |
| B1 | `test_the_prediction_check_is_size_alpha_under_the_registered_model` |
| B1 | `test_without_validation_refine_cannot_overturn_a_screen_rejection`: certified before |
| B1 | `test_every_oracle_campaign_satisfies_the_adequacy_invariant` (INV-STAT19) |
| B1 | `test_smooth_surfaces_keep_their_power[bowl, saddle, geometric_knob_log]`: guard, passes before and after |
| B3 | `test_design_efficiency_is_recorded_for_the_design_as_run` |
| B3 | `test_d_efficiency_matches_the_textbook_value` |
| B3 | `test_the_preview_counts_validation_runs_and_reports_efficiency` |
| B4 | `test_reuse_skips_the_screen_corners_and_fits_a_block_term` |
| B4 | `test_reuse_detects_a_between_stage_shift` |
| B4 | `test_reuse_is_refused_with_a_choice_factor`: guard |
| B5 | `test_an_inadequate_model_never_supplies_the_answer_and_report_md_says_so`: basis `model` before |
| INV-STAT19 | `tests/test_optimize_invariants.py::test_adequacy_determination_checker_has_teeth` |

Two existing tests were updated for the intended change:
- `test_optimize_harness`: refine's level set now includes the validation
  levels;
- `test_optimize_contract_chain`: the held-out bucket in the reconciliation.

## 6. Limits and open questions for the expert audit

Items 1-6 are the design's own limits; 7-11 come from the WP-B review; 12 is
a design choice. Items 1-4 are open questions for the audit.

1. **Power beyond ±0.5 (#321 P4).** Refine also runs an outer ring, `validation_outer_points` (default 2) at ±`validation_outer_offset` (default 0.8), chosen by the same seeded maximin against the ±0.5 points and tested in the same joint F. On `corner_bumps` (narrow bumps at coded ±0.8) the ±0.5 check rejected 0/4 seeds and the ring 4/4. What remains: a feature narrower than the spacing between the 6 points, or a misfit below noise, can still pass (`two_peaks` ×4: refine rejects 7/8 with the ring against 5/8 without, under Holm).
2. **The denominator is pure error from the centre replicates.** If they understate run-to-run variance, the check is anti-conservative on smooth surfaces.
3. **One family across the adequacy tests (#321 P4).** Lack of fit and the validation check (for the primary and every objective model) are combined by Holm (1979) at family-wise `policy.adequacy_alpha` (default 0.05), so a true model is called inadequate with probability ≤ α. Before this, "reject if either" ran above α. The two tests share the pure-error denominator, so they are positively dependent: on a k = 2 composite with 6 validation points and a true quadratic, "either" measured 0.068-0.072 and the Holm family 0.032-0.037 (3 × 4000 designs). Each check's `rejected` is the family's decision, `rejected_at_alpha` the single test's, and `model_adequacy.family` lists p and adjusted p. Vetoes are outside the family: an exact lack-of-fit rejection on zero pure error, or an objective model that could not be estimated. The family is a veto on the model half, so it spends no δ; α is its power cost on smooth surfaces. Measured, seeds 1-8 ×1/×4, 144 smooth campaigns: 55 certified before, 67 with Holm + ring.
4. **Validation rows can be shortlist nominees under a rejected model** (as measured leaders). They are re-measured before they can win.
5. **Validation at screen (#321 P4, opt-in).** `design.screen.validation_points` (default 0) runs off-lattice points after the screen: ±0.5 on every numeric factor with a runnable interior, ±1 on the rest. They are held out of the first-order + 2fi fit, checked by the same joint F, and enter the screen's adequacy family (`model_adequacy.screen_validation`). Declined, with nothing appended, for a mixed-level screen (categorical contrasts) or a screen with no interior. They are never part of the foldover's combined fit; the foldover itself still rests on the centre points. Cost: 4 runs per campaign. Measured: `step_cliff` screen check rejects 4/4 seeds; on the 288-campaign oracle certificates fall from 67 to 65, with no false certificate.
6. **Efficiency: D, G and I (#321 P4).** `model_adequacy.design_efficiency` records D-efficiency `|X'X/n|^(1/p)` and centred VIFs, plus G-efficiency `p / max SPV` and the I-criterion `i_average_spv` (the average scaled prediction variance `n f'(X'X)^-1 f` over the coded region; Atkinson, Donev & Tobias 2007, §10.6, §11.4), all from the same exact `(X'X)^-1`. I is exact (region moments, uniform on [-1, 1] per numeric axis, {-1, +1} per two-level choice factor). No I-efficiency RATIO is reported, because no closed-form I-optimal reference exists for a general model; compare `i_average_spv` between designs of one model (smaller is better). G is exact for first-order + 2fi models (max at a vertex, `g_exact: true`). With quadratic terms it is a max over a 5-level grid polished by coordinate ascent, so it is an upper bound (`g_exact: false`); past a fixed budget the evaluation set is a seeded sample (`g_seed`). Declined, named `g_i_declined`, for multi-level categorical contrasts, where the region is not a cube. Measured on the k = 2 face-centred CCD with 4 centres: D = 0.408, G = 0.632 (max SPV 9.5), I = 3.633.
7. **Under `screen_rejection_unresolved`** (reachable only with `validation_points: 0`), the report's `model` rung still answers with the model's argmax. Certification is withheld.
8. **Snapping (#321 P4).** Points are chosen among their images as run. Each candidate is decoded to a runnable level (grid or `levels_only` snap, clamp) and re-coded. A candidate whose image is a composite point (the fit interpolates it, so it tests nothing) or another chosen point's image is declined, and the maximin takes the next-best. `design_matrix.validation` records `planned_coded`, `as_run_coded` and `points_declined`. When every candidate collapses (e.g. two `levels_only` knobs on {2, 8, 16}), nothing runs, `declined_reason: every_candidate_snaps_onto_a_design_point`, and the check is `no_validation_point_runnable`. A refine cannot then overturn a screen rejection (`screen_rejection_unresolved`).
9. **V from the rows actually fitted (#321 P4).** `V = I + X_v (X'X)^-1 X_v'` uses the fit's own exact covariance (every second-order, blocked or mixed fit carries it; the leading block of the inverse over model and nuisance columns) or the fitted rows' matrix. An objective model fitted on a subset (a metric missing on some rows) uses its own rows (`ObjectiveModel.positions`). `v_from` records which.
10. **The Pareto path and a rejected model (fixed in #321).** `shortlist_plan` reads the epoch's `model_adequate`: when it is false, round 1 seats no predicted extreme and no predicted preferred point; each objective's measured best and the measured nondominated points take those seats (up to `max(K, shortlist_size // 2)`), and the predicted front's spread fills the rest, as on the single-objective ladder. Predicted rivals stay in the front statuses: a rival can only remove confidence, so that is the conservative side. Certification is withheld (`model_inadequate`) as before. Cost: on `pareto_with_constraint` seed 3 the measured anchor makes a constraint-boundary point preferred, a later round strikes it off, and the hypervolume drops 0.967 -> 0.952 (1 of 16 seeds).
11. **The mixed-fit V and nuisance columns.** V now comes from the fit's covariance, whose leading block already accounts for the centre indicators and block term (fixed with limit 9).
12. **`reuse_screen` with a choice factor is a validation error (rule 33), and partial reuse across choice slices is rejected.** Refine fits one slice of each choice factor. A screen row at another level of that factor carries the factor's effect and its interactions with the refined numerics, and the per-slice model has no column for either, so reusing the row biases the slice fit. A block term absorbs only a constant shift between slices, never those interactions (Box & Draper 2007, §15.3: blocking assumes additive block effects; `test_a_block_term_cannot_absorb_a_choice_by_numeric_interaction` shows a slice slope of 6 pooled to 2). Reusing only the rows AT the held level would be unbiased, but it is declined: at most 1/L of the screen's corners lie on the slice, and the screen's centres cycle the choice levels, so the slice has too few block-1 centres to estimate the block effect.

Review items fixed rather than documented:
- H1: a same-class refit never overturns a rejection (§2.3).
- H2: refine's copies of screen rows are skipped by `_top_measured` and the
  measured front, using the same `_stage_reused` test the budget uses.
- The reuse refusal is now logged.
- A retry of a reusing refine keeps `reused_from.stage`, so the budget never
  charges it twice.
- The always-True expression at `_adequacy_record` is simplified.
