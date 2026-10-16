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

**Literature.** Rounding the continuous optimum to the nearest feasible point
is the standard treatment of discrete-valued factors in response-surface work
(Myers, Montgomery & Anderson-Cook, *Response Surface Methodology*, 4e, ch. 7
on non-standard regions); regressing on the levels actually used rather than
the nominal coordinates is the errors-in-variables argument of Box (1963,
"The effects of errors in the factor levels...", *Technometrics* 5) already
behind INV-STAT14. A CCD whose axial points cannot leave the cube is the
face-centred CCD (Montgomery, *DAE*, 8e, §11.4.2), which remains a valid
second-order design when at least three distinct levels per factor run.

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

**Rule (deterministic).** In the screen (and foldover) the centre replicate
with index `i` runs each choice factor `j` at level `levels_j[i mod L_j]`
(`L_j` = the levels the screen uses for `j`: the screen pair for a two-level
choice, every declared level for a multi-level categorical once feature 1
lands). Numerics stay at their midpoint. Call this the **diagonal cyclic
assignment**.

**Why diagonal, not the full product.** Pure error needs several replicates of
ONE configuration. The full product of choice levels across n_c centre points
(e.g. (off,off),(on,off),(off,on),(on,on) at n_c = 4) makes every centre a
singleton and leaves ZERO pure-error df. The diagonal assignment uses
`min(n_c, lcm(L_j))` distinct centre configurations, so for two 2-level choice
factors and n_c = 4 it gives two configurations of two replicates (df 2).
Balance: each level of each choice factor is run `floor(n_c/L_j)` or
`ceil(n_c/L_j)` times; exactly balanced when `L_j` divides n_c. (Textbook
practice -- Montgomery, *DAE* 8e §6.8, and Myers, Montgomery & Anderson-Cook, RSM, on
qualitative factors -- is to run centre points at each level of the
qualitative factors; the diagonal assignment is that practice under a fixed
centre-point budget.)

**Pure error is pooled within groups of identical configurations**
(Draper & Smith, *Applied Regression Analysis*, 3e, §2.1): SS_pe = sum over
groups of within-group SS, df_pe = n_c - (#groups with >= 1 row). This was
already the rule in `effects.fit_effects` (grouped by the coded-as-run
coordinates). Consumers that computed `n_c - 1` independently are fixed to
the same count: `preview` (screen MDE df). Lack of fit uses
`df_lof = df_resid - df_pe` from the fit, unchanged.

**The curvature contrast stays unbiased.** Each centre row is coded at the
level it ran, so the fitted linear model (main effects and two-factor
interactions, estimated from the corners) predicts the centre under that
level; choice x numeric interactions vanish at the numeric midpoint. The
residual at a centre of level l therefore estimates that level's pure
curvature (sum of pure quadratic coefficients under l). The pooled
lack-of-fit F tests H0: every level's curvature is zero (and no other misfit).
Assumption, stated in `matrix.expand`: the linear part is correctly estimated
from the corners -- true at resolution >= V, or when the aliased terms are
zero.

**centre_points vs level count.** If n_c < L_j for some choice factor, levels
`n_c .. L_j-1` get no centre point: curvature is not checked under them. If
some configuration gets one replicate, df_pe drops below n_c - 1. Both are
recorded: `design_matrix.json["centre_points"]` (the per-level centre counts,
the number of distinct centre configurations, df_pe and the warnings), a
validator WARNING, and the preview. No silent change of n_c.

**Refine under curvature.** The held level of a choice factor on the
lack-of-fit branch was the best CORNER marginal mean -- which is biased in
exactly the gap-3 case (curvature under one level makes that level look bad at
the corners). When every level of a held choice factor has at least one
complete centre row, the held level is the argmax of the CENTRE-POINT MEANS
per level: an unbiased estimate of the response at refine's design centre
under each level, which is the point refine's CCD is built around. Otherwise
the corner-marginal rule is kept. The basis is recorded in
`design_matrix.json["held_fixed_basis"]`.

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
Hamada, *Experiments*, 2e, ch. 7 (method of replacement, 2^m4^n designs,
collapsing); Wu & Zhang (1993, *Biometrika* 80:203-209: word length in
two- and four-level designs counts the four-level factor ONCE); Mukerjee &
Wu, *A Modern Theory of Factorial Designs* (2006), mixed-level regular
designs; Rao (1947) and Hedayat, Sloane & Stufken, *Orthogonal Arrays* (1999):
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

**Generalized resolution.** Each factor f owns a subspace S_f of the GF(2)
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

**Exact inference.** Whenever a fit contains a multi-column categorical the
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
generalized resolution read off the PSEUDO-COLUMN matrix (no word shorter than
R) and the strength R-1 proportional-frequency property read off the LEVEL
matrix (Addelman / Rao).

## What this design cannot answer (open questions)

- Non-regular mixed-level designs (e.g. the 18-run OA(18, 2^1 3^7), 36-run
  designs, Xu's (2002) algorithmic mixed-level designs) can be far smaller
  than the replacement method for many 3-level factors; a 3-level factor here
  always costs four slots.
- Curvature *interacting* with a categorical is detected (feature 3) but
  refine models it only at the held level; a CCD crossed with the categorical
  (or a sequential refine per level) is not offered.
- After collapsing, interactions aliased in the pseudo space become PARTIALLY
  aliased in the level space; they are fitted by least squares with exact
  (inflated) variances rather than reported as alias pairs, so
  `alias_consequential` does not see them.
