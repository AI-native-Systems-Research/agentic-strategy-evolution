# Mixed-level factors in `kind: optimization`

Status: design, 2026-10-16. Extends `2026-08-16-compiled-policy-design.md`
(binding) and `2026-10-15-pareto-front-design.md`; everything not stated here
keeps those specs' semantics. Implementation order: (2) discrete numeric
levels, (3) centre points over categorical levels, (1) multi-level
categoricals.

## Why — three verified gaps

1. A `type: choice` factor with L > 2 levels is screened, fitted and
   recommended at its two screen levels only. `[lru, lfu, arc]` never tries
   `lfu`, and nothing warns.
2. A numeric knob that runs only at specific values (`[64, 128, 256, 1024]`)
   has no representation. `numeric` + `grid: 1` can recommend 181; `choice`
   loses the ordering (and, by gap 1, all but two levels).
3. Centre points run every choice factor at its FIRST level, so the curvature
   check (lack of fit on pure error) is measured under that level only.

## Principles kept

- The design is pre-registered and constructed by arithmetic; every guarantee
  (resolution, balance) is a property of the matrix and is tested off it.
- Code what ran (INV-STAT14): the fit regresses on the levels that actually
  executed, never on the nominal plan.
- Never approximate silently: every degradation (collapsed levels, snapped
  axial points, a level with no centre point, a non-orthogonal fit) is
  recorded in an artifact.
- A pure two-level campaign is BYTE-IDENTICAL to before (proved against a
  scratch worktree at 1a0d68b); only campaigns that declare a choice factor
  (feature 3) or the new constructs change.

---

## Feature 2 — `levels_only: true` (ordered, discrete, irregular numerics)

**Declaration.** `type: numeric`, `levels: [16, 32, ..., 1024]`,
`levels_only: true` (optionally `scale: log`). Meaning: the knob is ordered
(interpolation is meaningful for *modelling*) but only the declared values are
*runnable*.

**Semantics.** Every place a numeric value is produced from a coded value --
`decode_coded` (the fitted optimum, refine's axial and centre points), the
candidate axes of `decide`, confirm's finalists -- returns a declared level:
the value is mapped to the axis space (log under `scale: log`), and the
NEAREST declared level in that space is taken (ties to the lower level, a
deterministic rule). Candidate axes are exactly the declared levels inside the
screen range (no 9-point interpolation). The fit codes what ran
(`code_actual`), so a snapped axial point is regressed where it ran.

**Literature and its limits.** The snap is a design rule, not a cited
estimator: the candidate axis scores every declared level, so the
recommendation is the fitted argmax over the runnable set. Regressing on the
levels actually used rather than the nominal coordinates (INV-STAT14) is the
fixed-but-recorded case; Box (1963, *Technometrics* 5) treats RANDOM errors in
the factor levels, a different problem -- here the snapped level is known
exactly, so there is no errors-in-variables bias once it is coded. A snapped
central composite is NOT in general a face-centred CCD (its axial and centre
points land where the declared levels are); three distinct runnable levels per
factor are necessary for the quadratic, not sufficient for a well-conditioned
one.

**Assumptions** (stated where used). The response is smooth in the axis
coordinate (so a second-order model in `log(level)` or `level` is adequate
between declared levels); nearest-in-axis-space is the right snap (the
quadratic is evaluated on every declared level anyway, so the snap only
chooses which levels *run*, not which are *considered*).

**Refinability.** Unchanged rule: numeric with >= 3 levels. Refine's CCD over a
levels_only factor runs at most the snapped cube/axial/centre levels; when the
snaps collapse it to fewer than 3 distinct levels the quadratic term is
omitted by the existing `exclusions.non_estimable_terms` path and recorded in
`effects.json["omitted_terms"]`.

**Validation.** `levels_only` with `grid` is a HARD ERROR (two declarations of
the runnable set that can disagree: `grid: 1` says 65 runs, `levels_only` says
it does not). `levels_only` on a `choice` factor is a HARD ERROR (redundant: a
choice already runs only its levels). `levels_only` on a 2-level numeric is a
WARNING (it changes nothing: a 2-level numeric already runs only its pair).
Duplicate or non-numeric levels are a hard error. Rule 24 (integer levels
without grid) no longer fires for a levels_only factor, which is the correct
declaration for that case.

**Oracle.** `levels_only_pow2`: one log-scaled knob with runnable levels
{16, 32, 64, 128, 256, 512, 1024} and optimum at 256, plus one ordinary
numeric. Without `levels_only` (grid 1, scale log) the 9-point interpolated
axis is 16, 27, 45, 76, 128, 215, 362, 609, 1024 -- 256 is not on it, so the
recommendation is off-set. With it: the recommendation is a declared level on
every seed and is 256.

---

## Feature 3 — centre points that cover every categorical level

**Rule (deterministic): replication first, then coverage.** With n_c screen
(and foldover) centre points and choice factors with `L_j` screen levels
(the screen pair for a two-level choice; every declared level for a
multi-level categorical once feature 1 lands), the number of distinct centre
CONFIGURATIONS is

    g = max(1, min(lcm_j(L_j), floor(n_c / 2)))

and centre replicate `i` runs configuration `c = i mod g`, in which choice
factor `j` takes level `levels_j[c mod L_j]`. Numerics stay at their
midpoint. Call this the **diagonal cyclic assignment**.

  * `floor(n_c / 2)` guarantees every configuration at least two replicates
    whenever n_c >= 2, so pure error keeps `n_c - g >= ceil(n_c / 2)` df. A
    rule that cycled every replicate through the levels would leave a
    5-level categorical with 4 centre points four singletons and ZERO
    pure-error df: no significance test and no lack-of-fit test at all.
  * Diagonal rather than the full product of choice levels for the same
    reason: the product (off,off),(on,off),(off,on),(on,on) at n_c = 4 is four
    singletons. The diagonal pairs the factors' level indices, so two 2-level
    choice factors at n_c = 4 give (off,off),(on,on) twice each (df 2).
  * Balance: within the covered levels each is run `floor` or `ceil` of
    `n_c / g` times (exactly balanced when g divides n_c).
  * Textbook practice (Montgomery, *DAE* 8e §6.8; Myers, Montgomery &
    Anderson-Cook, RSM, on qualitative factors) runs centre points at every
    level of the qualitative factors; this is that practice under a fixed
    centre-point budget, with the budget's shortfall recorded, not hidden.

A campaign with no choice factor has g = 1 and is byte-identical. A two-level
choice campaign with n_c = 3 also has g = 1 (all centres at the first level,
as before) and now gets a warning that the second level's curvature is
unchecked.

**Pure error is pooled within groups of identical configurations**
(Draper & Smith, *Applied Regression Analysis*, 3e, §2.1): SS_pe = sum over
groups of within-group SS, df_pe = n_c - (#groups with >= 1 row). This was
already the rule in `effects.fit_effects` (grouped by the coded-as-run
coordinates). Consumers that computed `n_c - 1` independently are fixed to
the same count: `preview` (screen MDE df). Lack of fit uses
`df_lof = df_resid - df_pe` from the fit, unchanged.

**What the lack-of-fit test means.** Each centre row is coded at the level
it ran, so the fitted first-order model predicts the centre under that level;
choice x numeric interactions vanish at the numeric centre. Under H0 (the
model is correct and there is no curvature under any covered level) the
pooled lack-of-fit F is exactly F-distributed; curvature under a covered level
-- including under one level only -- gives it power. It is a test, not an
unbiased estimate of each level's curvature, and it says nothing about levels
no centre ran (`curvature_untested_levels`, model adequacy then UNKNOWN).
Assumption: the first-order part is correctly specified (resolution >= V, or
the aliased terms are zero). A `levels_only` numeric's centre is its snapped
centre level, not the arithmetic midpoint. In MIXED fits the coefficients are
estimated with one indicator per centre configuration (from the corners
alone; stage-1 M1) while the lack-of-fit F is computed without them.

**centre_points vs level count.** If g < L_j for some choice factor, its
levels `g .. L_j-1` get no centre point: curvature is not checked under them
(`n_c >= 2 * max_j L_j` covers every level of every choice factor twice). Whenever g > 1,
df_pe is `n_c - g` rather than `n_c - 1`. Both are recorded: `design_matrix.json["centre_points"]` (the per-level centre counts,
the number of distinct centre configurations, df_pe and the warnings), a
validator WARNING, and the preview. No silent change of n_c.

**Refine under curvature.** The held level of a choice factor on the
lack-of-fit branch was the best CORNER marginal mean -- which is biased in
exactly the gap-3 case (curvature under one level makes that level look bad at
the corners). When EXACTLY ONE choice factor is held, every level of it has at
least one complete centre row, and no other held factor runs off-centre, the
held level is the argmax of its CENTRE-POINT MEANS -- the response at refine's
design centre under each level. With two or more held choice factors the
diagonal assignment moves their centre levels together, so a per-factor centre
mean carries the other factors' effects (stage-1 M2: P=on worth +1, Q=on -3,
centres (off,off)=20 and (on,on)=18 would hold P at off); a held numeric that
refine runs off-centre changes the response through any interaction. In both
cases the corner rule is kept and `centre_mean_confounded_with` records why.
This confounding is the PRICE of the diagonal assignment, a deliberate
departure from Montgomery (DAE §6.8), who runs centres at every combination
of the qualitative factors.

**Oracle.** `curvature_under_second_level`: A, B numeric, C in {off, on};
C=off is flat at 15; C=on is a bowl peaking at 16 at the design centre and
reading 11.1 at the corners. Before: centres all at `off` see no curvature,
nothing refines, the campaign recommends `off` (gap 1.0, epsilon ~0.32).
After: the `on` centres show the bowl, lack of fit fires, refine holds C=on
and the campaign recommends (9, 9, on).

---

## Feature 1 — multi-level categoricals by the method of replacement

**Literature.** Addelman (1962a, "Orthogonal main-effect plans for asymmetrical
factorial experiments", *Technometrics* 4:21-46: collapsing of levels and the
proportional-frequency condition); Addelman (1962b, "Symmetrical and
asymmetrical fractional factorial plans", *Technometrics* 4:47-58); Wu &
Hamada, *Experiments*, 2e, chs. 7-8 (method of replacement, 2^m4^n designs,
collapsing); Wu & Zhang (1993, *Biometrika* 80:203-209: word length in
two- and four-level designs counts the four-level factor ONCE); Mukerjee &
Wu, *A Modern Theory of Factorial Designs* (2006), mixed-level regular
designs; Rao (1947, "Factorial experiments derivable from combinatorial
arrangements of arrays", *JRSS Suppl.* 9:128-139) and Hedayat, Sloane & Stufken, *Orthogonal Arrays* (1999):
resolution R <=> strength R-1. Searle, Speed & Milliken (1980, *Am. Stat.*
34:216-221) for least-squares (population marginal) means.

**Pseudo-factors.** A choice factor with L > 2 levels takes
`m = ceil(log2 L)` two-level pseudo-factor columns `C[1]..C[m]` in the screen
fraction. Its main-effect contrast subspace is the full set of `2^m - 1`
nonzero GF(2) combinations of those columns (`C[1]`, `C[2]`, `C[12]`, ...).
A row's pseudo signs give `b = sum_i [p_i = +1] 2^(i-1)`.

**Collapsing rule (L < 2^m).** `b < L` runs level `b`; `b >= L` runs level
`b - L` (so the surplus `2^m - L` combinations fall on the first-declared
levels, conventionally the baseline). Consequences, recorded in
`design_matrix.json["categoricals"]`: (i) unequal replication -- levels
`0..2^m-L-1` run twice as often as the rest; (ii) loss of within-factor
orthogonality -- the factor's L-1 contrasts are no longer mutually orthogonal
nor orthogonal to the intercept; (iii) by Addelman's theorem, orthogonality
WITH OTHER FACTORS' main effects (proportional frequencies) is preserved.

**Resolution, word length counted in factors.** (Not Deng & Tang's 1999
generalized resolution, which is for non-regular designs.) Each factor f owns a subspace S_f of the GF(2)
column space (dimension m_f; m_f = 1 for a two-level factor). A defining word
is a set of nonzero elements s_f in S_f, one per factor in a set T, summing to
zero; its LENGTH is |T| (Wu & Zhang). Resolution R means every word has length
>= R: no main-effect component of any factor is aliased with another factor's
main effect (R >= 3), or with any 2fi component (R >= 4), and no 2fi component
is aliased with another 2fi component (R >= 5).

**Construction** (`design.mixed_fraction`). Generalizes `_greedy_columns`
from columns to blocks: `sums[j]` holds every XOR of j nonzero elements drawn
from j DISTINCT placed factors (j <= R-2). A factor's block is built vector by
vector (candidates in weight order); a vector is accepted iff every new element
of the block's span is nonzero, not already in the block, and in no `sums[j]`
-- so resolution holds by construction. Factors are placed largest-m first.
Seeded restarts, then one more base bit. The base size starts at the df bound
`N - 1 >= sum_f (2^{m_f} - 1)` (and, for R >= 5, the counting bound that adds
every 2fi component), which the preview reports. The textbook two-level path
(`fractional_factorial` / `full_factorial`) is untouched and used whenever no
factor has L > 2.

**Fit coding.** The fit codes each categorical by the level that RAN, with
L-1 columns: for L = 2^m, the 2^m - 1 Walsh contrasts (products of pseudo
signs) -- orthogonal, +-1, and exactly the columns the resolution guarantee is
about, so the existing exact alias-class collapse applies unchanged; for
L < 2^m, the first L-1 Walsh contrasts (singletons first) that are linearly
independent with the intercept on the levels' canonical codes. The main effect
has L-1 df in either case and its predictions are basis-invariant. Two-factor
interactions between a categorical and another factor are all products of
their columns; products of a categorical's own columns are never formed.

**Exact (X'X)^-1 covariance.** Whenever a fit contains a multi-column categorical the
design is non-orthogonal by construction (collapsing; centre rows coded at
their level), so `fit_effects` computes `(X'X)^-1` and every SE, every
prediction interval (constraint and objective models), and the model regret
bound use the exact `sigma^2 x'(X'X)^-1 x`. Variance inflation per term is
recorded (`effects.json["categoricals"]`). Two-level fits keep the per-column
arithmetic, which is exact for their orthogonal columns (byte-identity).

**Survivor test.** The Wald F on the categorical's L-1 main-effect
coefficients, `F = b' V^-1 b / ((L-1) s_pe^2)` with `V = (X'X)^-1` block,
on (L-1, df_pe) -- equal to the extra-sum-of-squares F for a linear model
(Searle, *Linear Models*, 1971, §3.6). Dropped iff p >= 0.05; unknown (kept)
when there is no pure error, as for every other factor.

**Reporting.** `effects.json["categoricals"]` per factor: its columns, the F
test, and per level the coded vector, the main-effect contribution, the
least-squares (marginal) mean with numerics at their centre and other
categoricals averaged over their levels, and its replication in the design.

**Downstream.** Candidate axes: all L levels. Search: the coordinate ascent
cycles a categorical through all L levels. Constraint/objective models: fit
over the same columns. Refine: holds the categorical at the screen
recommendation, which is the argmax over all L levels (or the centre-mean
rule under curvature). Confirm: any level can be seated. Foldover: folding on
a pseudo-column `C[i]` flips every contrast containing i, so to break a word
the fold picks a two-level factor in the consequential pair if there is one,
else the lowest pseudo-column of the categorical contrast in it. The liveness
sweep already runs every declared level.

**Validation and preview.** An explicit `screen_levels` on a choice factor
with L > 2 is a hard error (every level is screened; to screen fewer, declare
fewer). Rule 8 and the preview use the mixed construction's run count; the
preview prints each categorical's pseudo-factor count, contrast df,
replication pattern and the run cost against the df lower bound.

**Oracles** (each recommends the true optimum within epsilon and never
certifies a wrong answer): (a) 3-level categorical whose MIDDLE level is
best; (b) 4-level categorical interacting with a numeric (the numeric optimum
flips with the level); (c) 5-level categorical whose best-primary level
violates a noisy constraint; (d) a categorical + a levels_only discrete knob +
a continuous knob with an interior optimum, every one of which matters.
Property tests: for random mixes of L in {2..8} and R in {3, 4, 5}, the
factor-counted resolution read off the PSEUDO-COLUMN matrix (no word shorter than
R) and the strength R-1 proportional-frequency property read off the LEVEL
matrix (Addelman / Rao).

## Implementation notes (as built)

- `design.mixed_fraction` / `mixed_screen` build the screen; `Design.groups`
  maps columns to factors (empty on every two-level design, which keeps the
  textbook path and its artifacts byte-identical). `matrix.coded_as_run`
  turns the planned pseudo-factor columns into the fit's L-1 contrast columns.
- When the fitted rows cannot support any 2fi (e.g. a resolution-III mixed
  screen whose collapsed contrasts leave 2fi columns partially aliased), the
  fit is main effects only and `effects.json["interactions_dropped"]` says so.
- Findings and principles project a categorical ONCE, from its F test and
  LS means (its individual contrasts are basis-dependent).
- Validator: rule 3 rejects `screen_levels` on a multi-level choice; rule 7
  names the mixed screen's aliases; rule 8 prices the mixed screen (corners +
  centres); rule 29 (warning) states each categorical's pseudo-factors, df,
  collapsing and the screen's run cost. Rule 28 (feature 3) warns on a level
  no centre point covers.
- Examples whose 3- and 5-level choice factors were previously screened at
  two levels needed larger budgets (finetune-hyperparams: 128 corners at
  resolution V; the guide's alert-threshold example: 64).

## Stage-1 review fixes (nous-e2e/audit/stage1-mixed-review-fixes.md)

- M1: mixed fits estimate coefficients with one indicator per centre
  configuration (corners only) and judge 2fi estimability on the corner rows;
  a 2fi in the span of kept columns there is not fitted (`aliased_in_span`).
- M2: the centre-mean held level only for a lone held choice factor with
  nothing off-centre (above).
- M3: rule 30 refuses resolution III with a multi-level categorical while the
  foldover is on; every fold block of a mixed screen records
  `foldover_basis` and `aliases_after_combination`.
- M4: the level-space full factorial when no larger than the replacement
  fraction (`kind: mixed_level_full`).
- M5: a categorical that loses a level is refitted on the remaining levels;
  lost and inadmissible-wherever-measured levels are recorded and never
  recommended.
- M6/M7: a mixed fit's aliases are read off the solved model; planned aliases
  the fit separated are reported with their (uncentred) variance inflation.
- M8: curvature-untested choice levels recorded; model adequacy then unknown.
- M9: best level follows the campaign's direction. M10: the validator catches
  only parse errors around the mixed screen. M11: levels_only's runnable set
  is the declared levels inside the screen pair. M12: a fold that falls back
  to full records `full_fallback` and the unparsed pairs.
- `variance_inflation` is the UNCENTRED relative variance
  `(X'X)^-1_jj * sum_i x_ij^2`, not the textbook (centred) VIF; a level's
  main-effect contribution is defined only up to a constant (the contrasts'
  basis); the preview's MDE line applies to two-level contrasts, and a
  categorical level comparison has SE about `sd * sqrt(2L/N)`.

## Stage-1b re-review fixes (nous-e2e/audit/stage1b-mixed-rereview-fixes.md)

- N1/N5: `model_adequate` is three-valued, defined once in
  `stage_runner._model_adequacy`: False (lack of fit rejected), None
  (UNKNOWN: `lack_of_fit_not_computable`, `curvature_untested`,
  `curvature_not_isolated`, named in `model_adequate_basis`), True. Unknown
  shortlists like adequate (its ranking was not rejected; every finalist is
  re-measured) and WITHHOLDS certification with the basis as the reason; the
  policy observes None; INV-SEM17 covers it. Replicated centres with zero pure
  error and vanishing residuals (a deterministic exact fit) stay adequate.
- N2: a lost level has `ls_mean`/`effect` null and is never "best"; other
  categoricals are averaged over retained levels.
- N3: a level measured only at centre rows (every corner run failed) is lost
  (its centre rows are left out, `lost_at_corners`); a mixed fit that cannot
  isolate its centres records `centre_isolated: false` + reason and has
  unknown adequacy.
- N4: report.json/report.md carry unknown adequacy, untested curvature, lost
  and inadmissible levels (each only when present).
- N6: a categorical reduced to two levels keeps a 1-df F test and can drop.
- N7: `excluded_measured_infeasible` holds only measured exclusions;
  INV-SEM19 checks the recommended and ranked levels.
- N8: every level inadmissible is recorded (`all_levels_inadmissible`), none
  excluded; a rejected row counts as inadmissible.
- N10: rule 30 skips a level-space factorial screen. N11:
  `design_matrix.json["screen_choice"]`. N12: lost levels are not "untested".
- N13: span-aliased 2fi are listed as `aliases_not_assessed`;
  `alias_consequential` assesses exact aliases only.

**Byte-identity exception (N9), stated precisely.** Every pure two-level
campaign keeps byte-identical artifacts EXCEPT where the new adequacy
semantics apply: (a) a campaign with a choice factor whose centre points do
not cover every level (e.g. one two-level choice and 2-3 centre points), and
(b) a campaign whose final fitting stage has no computable lack-of-fit test
(no replicated centre points, or no residual df beyond pure error) and no exact
deterministic fit. Their recommendation.json / effects.json / report.json gain
the adequacy fields and certification is WITHHELD; with max_rounds > 1 the
registered confirm rounds may then continue, as for `model_inadequate`.
Measured on the 16 SURFACES x seeds 1-8 against nousko fecd076: at the default
4 centre points all 16 are unchanged; at center_points 3 only
`choice_x_numeric` changes (certified 7/8 -> 0/8, curvature_untested); at
center_points 0 only `drift` and `interaction_only` change (8/8 -> 0/8,
lack_of_fit_not_computable). In all 256 runs the recommendation and the stage
path are identical; no false certification appears either side.

## Stage-1c (round 4) fixes (nous-e2e/audit/stage1c-mixed-round4-fixes.md)

- P1/P2: ONE RULE -- a lost level (incl. lost at the corners) or a level
  inadmissible wherever measured (unless every level is) is never recommended
  anywhere: `_config_admissible` (every RETURN / SEED selector) and confirm's
  `_add` refuse it, the exclusion lists are unioned per factor, and INV-SEM19
  reads report.json's recommendation and the confirm finalists too.
- P3/P4/P8: report.json/report.md carry `all_levels_inadmissible` (own line),
  `model_adequate: false` (visible without a confirm), and
  `aliases_not_assessed`.
- P5: zero pure error decides exactly only with lack-of-fit df: residuals that
  vanish are an exact fit, nonzero ones an ESTABLISHED rejection
  (`effects.json["lack_of_fit_exact"]`, model_adequate false).
- P6: a secondary objective's model with no lack-of-fit verdict makes the
  primary's adequacy unknown (`pareto_stage.models_untested`).
- P7: the mixed-screen decision is stored on the Design at construction; a
  design without it records `{"chosen": null, "reason": ...}`.
- P9: `centre_isolation_reason: no_centre_rows`; legacy null adequacy reads
  `model_adequacy_unknown`; rule 30 names a parse failure as such.

**Byte-identity (round 4).** Against f2d4fac, the only artifact change on the
SURFACES / PARETO_SURFACES sweep is P4's: report.json gains
`model_adequate: false` exactly where the latest fitting stage's model was
rejected (14 of 24 surfaces, on the seeds where that happens); nothing else
differs. The non-choice surfaces' other artifacts remain byte-identical to
nousko fecd076.

## Stage-1d (round 5) fixes (nous-e2e/audit/stage1d-mixed-round5-fixes.md)

- Q1: lost levels are the per-factor UNION over every fitting stage of the
  epoch (carried into each recommendation.json, read by `_barred_levels`);
  refine's held level (corner-marginal, centre-mean or first-level fallback)
  never picks a barred level.
- Q2: a factor is FULLY barred when lost ∪ inadmissible covers every level;
  then only its lost levels are excluded and it is listed in
  `all_levels_inadmissible`; lost alone covering every level aborts naming
  the lost levels.
- Q3: `_config_admissible(..., barred=)` -- loops read the bar once.
- Q4: the declared known_valid_baseline is exempt from the bar in confirm, as
  in the report ladder; the seat's provenance and
  `report.json["recommendation_names_barred_level"]` record it; the
  no-finalist abort names the bar and states the baseline truthfully.
- Q5: an exact lack-of-fit rejection sets the LACK_OF_FIT trigger, so the
  policy's lack_of_fit observation agrees with model_adequate. BEHAVIOUR
  CHANGE: a deterministic target whose misfit is established exactly (zero
  pure error, nonzero residuals, lack-of-fit df > 0) now routes on the
  registered lack-of-fit (curvature) branch to refine, where before it went
  straight to confirm.
- Round-5 follow-ups: the bar is EPOCH-scoped (the latest record is the
  latest of THIS epoch, never a previous epoch's); report.md names a
  recommended baseline that sits at a barred level, and its wording for fully
  barred factors and the "never recommended" lines states the baseline and
  lost-level exceptions; the Q3 performance test is work-bound (2000 rows in
  < 1 s CPU; 0.04 s measured, 10.1 s with per-row bar reads).
- Q6: schema text: inadmissible levels of a fully barred factor stay candidates.

## What this design cannot answer (open questions)

- Non-regular mixed-level designs (e.g. the 18-run OA(18, 2^1 3^7), 36-run
  designs, Xu's (2002) algorithmic mixed-level designs) can be far smaller
  than the replacement method for many 3-level factors; they are NOT
  implemented. A 3-level factor uses 3 contrast df of pseudo-factor space
  (7 for 5..8 levels); the level-space full factorial is used instead whenever
  it is no larger (stage-1 M4).
- Curvature *interacting* with a categorical is detected (feature 3) but
  refine models it only at the held level; a CCD crossed with the categorical
  (or a sequential refine per level) is not offered.
- After collapsing, interactions aliased in the pseudo space become PARTIALLY
  aliased in the level space; they are fitted by least squares with exact
  (inflated) variances and listed in `planned_aliases_separated`, but
  `alias_consequential` (exact re-attribution) does not reason about them.
- A 2fi in the span of kept columns on the corners is dropped, not resolved:
  no registered follow-up block targets it.
- The diagonal centre assignment trades coverage of level COMBINATIONS for
  pure-error df; there is no optimal-allocation argument for the choice.
- Curvature isolation (one indicator per centre configuration) is applied to
  mixed fits only; two-level fits keep the original model for byte-identity,
  where mains are orthogonal to the intercept on the corners and the leak
  reaches the intercept alone.
