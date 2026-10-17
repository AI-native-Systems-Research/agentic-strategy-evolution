"""Effect estimation for orthogonal factorial designs.

For a balanced ±1-coded orthogonal design the least-squares coefficient of
any term has the exact closed form::

    beta_j = sum_i (x_ij * y_i) / N          # contrast / N

Verified equal to numpy.linalg.lstsq to machine precision. Using the closed
form keeps the arithmetic auditable and keeps numpy out of the harness.

Non-orthogonal designs (central composite with axial points) need a general
solve; ``_solve_normal_equations`` does Gaussian elimination with partial
pivoting on the normal equations — small systems (k <= 8 means at most ~45
terms), so a direct solve is fine and needs no external library.

Confidence intervals come from the pure-error variance supplied by
replicated center points. Without center points there is no independent
error estimate, so significance is left as ``None`` rather than guessed:
reporting a fabricated interval would be worse than reporting none.

Each term's standard error is computed from that term's own model column
(``sigma / sqrt(sum_i x_ij^2)``), not a single scalar shared across terms
(see the note at the SE computation in ``fit_effects``). That per-column
form is the *exact* ``sigma * sqrt((X^T X)^-1_jj)`` only when the term's
column is orthogonal to every other column — true for main effects and
two-factor interactions on every design this module generates, but not
for the intercept or the pure-quadratic terms (``A^2``, ``B^2``, ...) on a
central composite, whose columns are mutually correlated with each other
and with the intercept. On a 2-factor central composite, measured against
an explicit ``(X^T X)^-1`` inverse: main effects and ``AB`` match exactly
(e.g. 0.353553 vs. 0.353553, 0.500000 vs. 0.500000); the intercept and
``A^2``/``B^2`` are optimistic by a factor of about 1.46 **on a 2-factor
CCD with 3 centre points** (0.420813 exact
vs. 0.288675 from the per-column formula). This is accepted rather than
fixed with a full matrix inverse: quadratic terms exist to describe
surface curvature (consumed by ``solve_stationary_point`` as point
estimates, never gated on their CIs), and ``dropped_factors``/the stage
rule only ever look at main-effect significance, which is exact.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import variance

from scipy.stats import f as fisher_f
from scipy.stats import t as student_t

from orchestrator.optimize.design import Design, alias_pairs


@dataclass(frozen=True)
class Effect:
    """One estimated model term.

    ``aliased_with`` names every term whose design column coincided with this
    effect's column and which was therefore NOT fitted separately — the
    confounding a fractional design cannot resolve. Each entry is
    ``(terms, sign)``:

      * ``terms`` is the alternative term tuple, e.g. ``("C", "D")`` on the
        ``AB`` effect of a resolution-IV screen;
      * ``sign`` is ``+1.0`` when the alternative's column is IDENTICAL to the
        kept column and ``-1.0`` when it is the exact NEGATION of it.

    THE SIGN IS LOAD-BEARING AND IS NOT DECORATION. The coefficient is
    attributed to the KEPT term's column, and re-attributing it to the
    alternative means asking "what would the fit have found had it regressed
    on the alternative's column instead?". For an orthogonal ±1 design the
    coefficient is ``sum_i x_ij y_i / N``, so regressing on ``-x`` instead of
    ``x`` returns exactly ``-beta``. Concretely, with a 4-run design where
    ``col_AB = (1, -1, -1, 1)`` and ``col_C = -col_AB``, a response generated
    purely by ``C`` at ``+2.0`` fits ``beta_C = +2.0`` and ``beta_AB = -2.0``
    (verified arithmetic). A consumer that re-labelled ``AB``'s estimate as
    ``C`` while KEEPING its sign would therefore claim ``C`` pushes the
    response down when it pushes it up — reversing the physical direction of
    the effect. ``decide.alias_consequential`` multiplies by ``sign`` for
    exactly this reason.

    No design ``design.py`` currently builds produces a negated alias (every
    generator word it emits, textbook or constructed, is positive, so all
    aliased columns are
    identical), but the detection loop below has always handled the negated
    case and a hand-built or folded design can reach it — so the sign is
    recorded rather than assumed to be ``+1``.
    """

    label: str
    terms: tuple[str, ...]
    estimate: float
    se: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    significant: bool | None = None
    aliased_with: tuple[tuple[tuple[str, ...], float], ...] = ()


@dataclass(frozen=True)
class FactorTest:
    """The L-1 df main-effect test of a multi-level categorical.

    The Wald F on its contrast coefficients, ``F = b' V^-1 b / (q s_pe^2)`` with
    ``V`` the ``(X'X)^-1`` block and ``q = L - 1``, on ``(q, df_pe)`` -- equal to
    the extra-sum-of-squares F for a linear model (Searle, *Linear Models*,
    1971, §3.6). Same denominator as every other factor's t test (pure error),
    so a two-level factor's t^2 and this F are the same test at q = 1.
    ``significant`` is ``None`` without pure error: unknown, never null.
    """

    factor: str
    columns: tuple[str, ...]
    df: int
    f: float | None
    p: float | None
    significant: bool | None


@dataclass(frozen=True)
class Fit:
    """A fitted model plus everything needed to defend or doubt it."""

    intercept: float
    effects: tuple[Effect, ...]
    n_runs: int
    pure_error_var: float | None = None
    pure_error_df: int = 0
    lack_of_fit_f: float | None = None
    lack_of_fit_p: float | None = None
    aliases: tuple[tuple[str, str], ...] = ()
    quadratic: tuple[Effect, ...] = ()
    #: Mixed-level fits only (a design with a multi-column categorical):
    #: ``(column, factor)`` per main-effect column, the exact unscaled
    #: covariance ``(X'X)^-1`` over ``term_labels`` (intercept first, then the
    #: fitted terms in model order), each term's UNCENTRED relative variance
    #: ``(X'X)^-1_jj * sum_i x_ij^2`` (1.0 for a column orthogonal to all
    #: others; not the textbook centred VIF), and the categoricals' L-1 df F
    #: tests. Empty on every two-level
    #: fit, which keeps the per-column arithmetic (exact for its orthogonal
    #: columns) and its artifacts byte-identical.
    groups: tuple[tuple[str, str], ...] = ()
    term_labels: tuple[str, ...] = ()
    term_terms: tuple[tuple[str, ...], ...] = ()
    covariance: tuple[tuple[float, ...], ...] | None = None
    variance_inflation: tuple[tuple[str, float], ...] = ()
    factor_tests: tuple[FactorTest, ...] = ()
    #: Mixed-level fits only: 2fi terms NOT fitted because on the corner rows
    #: their column lies in the span of the kept columns (stage-1 M1), each
    #: with the labels of the columns spanning it.
    span_aliased: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = ()
    #: Mixed-level fits only: whether the coefficients were estimated with one
    #: indicator per centre configuration (from the corner rows alone).
    centre_isolated: bool = False
    #: Why not, when a mixed fit with centre rows could not isolate them.
    centre_isolation_reason: str | None = None
    #: Replicated centres with ZERO pure error and residuals that vanish: no
    #: F test exists, but the model fits exactly (deterministic targets).
    lof_exact_fit: bool = False
    #: Zero pure error with lack-of-fit df: ``"exact_fit"`` (residuals vanish)
    #: or ``"rejected"`` (nonzero residuals against zero replicate spread --
    #: lack of fit ESTABLISHED, no F needed); ``None`` otherwise.
    lof_exact: str | None = None
    #: Sequential-assembly fits only (refine reusing screen rows, WP-B B4): the
    #: BLOCK nuisance coefficient (screen block coded 1, refine block 0, so the
    #: intercept and every prediction refer to the refine block) as
    #: ``(estimate, se, t, p, df)`` -- the between-stage DRIFT check
    #: (Box & Draper 2007, ch. 15). ``None`` on every unblocked fit.
    block_effect: tuple | None = None


def pure_error(center_responses) -> tuple[float | None, int]:
    """Sample variance and df of replicated center points."""
    vals = list(center_responses)
    if len(vals) < 2:
        return None, 0
    return variance(vals), len(vals) - 1


def alias_rows(points) -> list[int]:
    """Row indices over which two model columns are compared for aliasing.

    Every non-centre row, or every row when the design has nothing but
    centres. Shared with ``exclusions.model_is_full_rank`` so the rank it
    checks is the rank of the matrix ``fit_effects`` will solve.
    """
    idx = [r for r, p in enumerate(points) if p.role != "center"]
    return idx or list(range(len(points)))


def _solve_normal_equations(cols: list[list[float]], ys: list[float]) -> list[float]:
    """Least squares via the normal equations, Gaussian elimination."""
    p = len(cols)
    a = [[sum(cols[i][r] * cols[j][r] for r in range(len(ys))) for j in range(p)]
         for i in range(p)]
    b = [sum(cols[i][r] * ys[r] for r in range(len(ys))) for i in range(p)]

    for col in range(p):
        pivot = max(range(col, p), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError(
                "design matrix is singular — the requested terms are not "
                "estimable from these runs (too few distinct configurations)",
            )
        a[col], a[pivot] = a[pivot], a[col]
        b[col], b[pivot] = b[pivot], b[col]
        for r in range(p):
            if r == col:
                continue
            factor = a[r][col] / a[col][col]
            for c in range(col, p):
                a[r][c] -= factor * a[col][c]
            b[r] -= factor * b[col]
    return [b[i] / a[i][i] for i in range(p)]


def model_matrix(design: Design, factor_ids, *, include_interactions: bool = True,
                 omit_terms=(), span_aliases: list | None = None):
    """The columns ``fit_effects`` solves: ``(labels, terms, cols, quad_start,
    alias_classes)``.

    One implementation, shared with ``exclusions.model_is_full_rank`` and
    ``exclusions.non_estimable_terms``, so the rank they check is the rank of
    the matrix that will actually be solved.
    """
    ids = tuple(factor_ids)
    k = len(ids)
    pts = design.points
    has_axial = any(p.role == "axial" for p in pts)
    # A multi-level categorical owns several columns (its contrasts); products
    # of a factor's OWN columns are part of its main effect, never a 2fi, and
    # are never formed. Every two-level design has no groups: unchanged.
    grp = (dict(zip(design.factor_ids, design.groups))
           if design.groups else {})

    labels: list[str] = []
    terms: list[tuple[str, ...]] = []
    cols: list[list[float]] = [[1.0] * len(pts)]     # intercept
    labels.append("(intercept)")
    terms.append(())

    for j, fid in enumerate(ids):
        labels.append(fid)
        terms.append((fid,))
        cols.append([p.coded[j] for p in pts])

    # Interaction columns, collapsed into ALIAS CLASSES.
    #
    # At resolution IV (and below) two-factor interactions are aliased with each
    # other, which means their ±1 columns are literally identical (or exact
    # negatives). Adding one column per pair then makes X^T X singular and the
    # fit dies with "design matrix is singular". Verified on every tabulated
    # resolution-IV design: k=5,6,7,8 all raise, while resolution V is fine. So
    # `resolution: 4` was documented, validated, and guaranteed to abort at
    # screen.
    #
    # A fractional design cannot separate aliased terms — no arithmetic can — but
    # it CAN estimate one coefficient per alias class and say honestly what that
    # coefficient is confounded with. That is the standard reading of a
    # fractional factorial, and it is what makes aliasing a resource question
    # ("resolve it only if it could change the decision") rather than a crash.
    #
    # `alias_classes` maps the representative label to every term sharing its
    # column, so a caller can report the confounding instead of hiding it. Each
    # entry carries a SIGN: +1 when the aliased column is identical to the kept
    # one, -1 when it is its exact negation. See `Effect.aliased_with` for why
    # the sign cannot be dropped (re-attributing a negated alias's coefficient
    # without flipping it reverses the effect's physical direction), and
    # `decide.alias_consequential` for the one consumer that applies it.
    #
    # THE COMPARISON IS OVER EVERY DESIGN POINT, NOT OVER CORNERS ONLY.
    # `alias_pairs` restricts itself to corners because it answers a question
    # about the design FAMILY's resolution; this loop answers a different
    # question — "is this column a literal duplicate of one already in X?" —
    # and that is a question about the matrix actually being solved. Two
    # consequences of getting it wrong:
    #
    #   * corner-only UNDER-detects nothing but OVER-detects catastrophically on
    #     a design with no corners at all (axial + centre points only, which
    #     `Design.corners` reports as an empty tuple): every column's corner
    #     projection is then the empty tuple, so every term would be recorded as
    #     aliased onto the first main effect and the whole model would collapse
    #     to one column.
    #   * on a central composite the axial rows are what keep `AB` distinct from
    #     `A` in the full matrix; verified that corner-only agrees there (k=2..5,
    #     no spurious alias either way), so nothing is lost by using every row.
    #
    # THE COMPARISON SKIPS CENTRE ROWS (when anything else exists). Under the
    # nominal coding a centre row contributed a matching 0.0 to every column,
    # so it could never make or break an alias. Under INV-STAT14 the fit is
    # handed the coded ACTUAL levels, and a choice factor's centre row codes
    # -1 (the level it ran) -- so on the centre rows a choice main effect
    # reads -1 where the interaction it is aliased with reads 0. Comparing
    # every row would then call the pair "distinct" and fit both, separating
    # them ONLY through the centre replicates: the split would be estimated
    # from the centre-vs-corner contrast, which is exactly what curvature
    # also moves, and the confounding the fraction cannot resolve would be
    # reported as resolved. Aliasing is a property of the factorial and
    # axial part of the design; centre rows are there for pure error.
    akeys = alias_rows(pts)
    alias_classes: dict[str, tuple[tuple[tuple[str, ...], float], ...]] = {}
    # MIXED-LEVEL designs (a categorical owns several columns): a collapsed
    # categorical's contrasts are not individual pseudo-factor columns, so a
    # 2fi can lie in the SPAN of the intercept and kept columns on the corner
    # rows without duplicating any single one (spec 2026-10-16, stage-1 M1:
    # in a collapsed resolution-III screen AB = P1 is a combination of C's
    # contrasts and the intercept on the corners). Such a 2fi is estimable
    # ONLY through the centre rows -- i.e. from the curvature contrast -- so
    # it is not fitted; it is recorded in ``span_aliases``. Judged on the
    # corner (alias) rows, like the exact-duplicate test above. Two-level
    # designs keep the exact-duplicate test alone (byte-identical).
    basis: list[list[float]] = []

    def _resid(v):
        r = list(v)
        for q in basis:
            d = sum(a * b for a, b in zip(r, q))
            r = [a - d * b for a, b in zip(r, q)]
        return r

    def _add_basis(v) -> bool:
        r = _resid(v)
        nrm = math.sqrt(sum(a * a for a in r))
        scale = math.sqrt(sum(a * a for a in v)) or 1.0
        if nrm <= 1e-9 * scale:
            return False
        basis.append([a / nrm for a in r])
        return True

    if grp:
        for c in cols:
            _add_basis([c[r] for r in akeys])
    if include_interactions and k >= 2:
        seen: dict[tuple[float, ...], int] = {}
        for j2, fid in enumerate(ids):          # main-effect columns already added
            seen.setdefault(tuple(pts[r].coded[j2] for r in akeys), 1 + j2)
        for i, j in itertools.combinations(range(k), 2):
            if grp and grp.get(ids[i], ids[i]) == grp.get(ids[j], ids[j]):
                continue
            col = [p.coded[i] * p.coded[j] for p in pts]
            key = tuple(col[r] for r in akeys)
            neg = tuple(-v for v in key)
            hit = seen.get(key)
            sign = 1.0
            if hit is None:
                hit = seen.get(neg)
                sign = -1.0
            if hit is not None:
                # Aliased with an existing column: record the confounding (with
                # the sign relating the two columns) and do NOT add a duplicate
                # column.
                rep = labels[hit]
                alias_classes[rep] = alias_classes.get(rep, ()) + (
                    ((ids[i], ids[j]), sign),
                )
                continue
            if grp and not _add_basis(list(key)):
                if span_aliases is not None:
                    span_aliases.append(((ids[i], ids[j]), _spanning(
                        list(key), [[c[r] for r in akeys] for c in cols], labels)))
                continue
            seen[key] = len(cols)
            labels.append(f"{ids[i]}{ids[j]}")
            terms.append((ids[i], ids[j]))
            cols.append(col)

    quad_start = len(labels)
    if has_axial:
        for j, fid in enumerate(ids):
            labels.append(f"{fid}^2")
            terms.append((fid, fid))
            cols.append([p.coded[j] ** 2 for p in pts])

    # OMITTED TERMS: higher-order terms the caller has established are not
    # estimable from these rows (``exclusions.non_estimable_terms``: the
    # column lies in the span of the intercept and main effects, e.g. ``A^2``
    # when only two levels of A survived an exclusion). Never a main effect.
    if omit_terms:
        omit = {tuple(t) for t in omit_terms}
        if any(len(t) == 1 for t in omit):
            raise ValueError(f"omit_terms may not name a main effect: {sorted(omit)}")
        keep_idx = [i for i, t in enumerate(terms) if t not in omit]
        n_lin = sum(1 for i in keep_idx if i < quad_start)
        labels = [labels[i] for i in keep_idx]
        terms = [terms[i] for i in keep_idx]
        cols = [cols[i] for i in keep_idx]
        quad_start = n_lin

    return labels, terms, cols, quad_start, alias_classes


def _spanning(v, cols, labels) -> tuple[str, ...]:
    """The labels of the kept columns a corner-dependent column is a
    combination of (least squares over the corner rows; |coefficient| > 1e-9)."""
    try:
        coef = _solve_normal_equations(cols, v)
    except ValueError:
        return tuple(labels)
    return tuple(lab for lab, c in zip(labels, coef) if abs(c) > 1e-9)


def fit_effects(design: Design, responses, *, factor_ids,
                include_interactions: bool = True,
                alpha: float = 0.05, omit_terms=(), blocks=None) -> Fit:
    """Fit main effects (+ 2-factor interactions, + curvature when present).

    ``blocks`` (one 0/1 per row, or ``None``): a sequentially assembled design
    (WP-B B4). When both blocks are present a block indicator enters the
    solve as a NUISANCE column, pure error pools within (coordinates, block),
    every SE comes from the exact ``(X'X)^-1``, and ``Fit.block_effect`` is
    the drift check. ``None`` or a single block: the unblocked fit, unchanged.
    """
    ids = tuple(factor_ids)
    ys = [float(v) for v in responses]
    if len(ys) != len(design.points):
        raise ValueError(
            f"responses length {len(ys)} != design length "
            f"{len(design.points)}; every planned run needs exactly one "
            f"response value",
        )

    # A NaN RESPONSE IS REFUSED HERE, at the module boundary, and not only by the
    # caller that happens to remember. The normal equations propagate a single NaN
    # into the intercept and EVERY coefficient -- verified: one NaN among eight
    # runs turns all six effects and the intercept into NaN -- and the result is
    # still a structurally valid `Fit`. That is the dangerous part: every
    # comparison against NaN is False, so an all-NaN surface does not raise, does
    # not warn, and reads downstream as "no factor is significant", which is a
    # plausible scientific finding rather than an obvious defect. A campaign can
    # emit a schema-valid effects.json describing nothing at all.
    #
    # `stage_runner` does pre-filter (spec §4 D2: fit on the complete-row subset
    # and record the exclusions in fit_exclusions.json), and that remains the
    # right place for the POLICY decision about which rows are admissible --
    # including the identifiability and rank floors, which need the design.
    # But D2 was implemented at that one call site, leaving the module itself
    # willing to return nonsense to any other caller: the harness, a test, a
    # future stage, or a notebook. Refusing at the boundary makes the invariant
    # "a returned Fit never contains a NaN coefficient" true of the FUNCTION
    # rather than of one of its callers.
    nan_at = [i for i, v in enumerate(ys) if v != v]
    if nan_at:
        raise ValueError(
            f"response(s) at index {nan_at} are NaN. Fitting would return a "
            f"structurally valid Fit whose intercept and every coefficient are "
            f"NaN, and because every comparison against NaN is False that result "
            f"reads as 'no factor is significant' rather than as an error. The "
            f"caller must decide which rows are admissible and fit on that subset "
            f"-- see stage_runner's exclusion handling, which drops non-complete "
            f"rows, enforces the identifiability and rank floors, and records what "
            f"it dropped in fit_exclusions.json.",
        )

    span: list = []
    labels, terms, cols, quad_start, alias_classes = model_matrix(
        design, ids, include_interactions=include_interactions,
        omit_terms=omit_terms, span_aliases=span,
    )
    pts = design.points

    blk = None
    if blocks is not None and len(set(int(b) for b in blocks)) > 1:
        if len(blocks) != len(ys):
            raise ValueError("blocks must give one entry per row")
        blk = [float(int(b)) for b in blocks]
    coefs = _solve_normal_equations(cols + ([blk] if blk else []), ys)
    coefs_blocked = coefs
    coefs = coefs[:len(cols)]
    # A fit with a categorical's contrast columns (several per factor, or one
    # surviving contrast of a categorical reduced to two levels, N6).
    mixed = bool(design.groups) and any(
        c != g for c, g in zip(design.factor_ids, design.groups))
    coefs_lof = coefs_blocked
    lof_cols = cols + ([blk] if blk else [])
    centre_ind = _centre_indicators(pts, cols) if mixed else []
    if centre_ind:
        # CURVATURE ISOLATION (mixed fits; stage-1 M1). A collapsed
        # categorical's contrasts are correlated with the intercept on the
        # corners, so with centre rows in a first-order fit the centre-vs-corner
        # contrast -- curvature -- leaks into the categorical and every column
        # correlated with it. One indicator per centre CONFIGURATION absorbs the
        # centres, so every reported coefficient is estimated from the factorial
        # (corner) rows alone, the textbook reading of a 2-level screen with
        # centre points (Montgomery, DAE 8e §6.8). The lack-of-fit test is still
        # computed from the model WITHOUT the indicators (``coefs_lof``), so
        # under H0 it is exactly F-distributed and curvature still triggers it.
        coefs = _solve_normal_equations(
            cols + centre_ind + ([blk] if blk else []), ys)[:len(cols)]

    # Pure error from the centre rows, POOLED WITHIN IDENTICAL COORDINATES.
    # Pure error is only pure if every row in a group is a replicate of ONE
    # configuration. Under the nominal coding every centre row was the origin
    # by construction; under INV-STAT14 the coordinates are the coded actual
    # levels, so this is checked rather than assumed. A design without choice
    # factors yields one group (every centre at the numeric midpoints), so the
    # pooled estimate is exactly the plain sample variance there. A design WITH
    # choice factors runs its centres in ``g`` configurations over the choice
    # levels (``matrix.centre_configurations``, spec 2026-10-16 feature 3), and
    # gets the textbook pooled within-group estimate (Draper & Smith, 3e §2.1):
    # SS_pe = sum of within-group SS, df_pe = n_centre - g. A plain variance
    # over all centres would silently include the choice factor's effect.
    groups: dict[tuple[float, ...], list[float]] = {}
    for r, (p, y) in enumerate(zip(pts, ys)):
        if p.role == "center":
            key = tuple(p.coded) + ((blk[r],) if blk else ())
            groups.setdefault(key, []).append(y)
    if len(groups) <= 1:
        pe_var, pe_df = pure_error(next(iter(groups.values()), []))
    else:
        ss_g = df_g = 0
        for g in groups.values():
            if len(g) >= 2:
                v, d = pure_error(g)
                ss_g += v * d
                df_g += d
        pe_var, pe_df = (ss_g / df_g, df_g) if df_g else (None, 0)

    n = len(pts)
    tcrit = None
    have_se = pe_var is not None and pe_var > 0 and pe_df > 0
    if have_se:
        tcrit = float(student_t.ppf(1 - alpha / 2, pe_df))

    built: list[Effect] = []
    quads: list[Effect] = []
    for idx in range(1, len(labels)):
        est = coefs[idx]
        se = lo = hi = None
        sig = None
        if have_se:
            # Per-term SE from that term's own column sum of squares —
            # sigma / sqrt(sum_i x_ij^2) — NOT a single scalar shared
            # across terms. Center (and, on a central composite, axial)
            # points contribute differently to each column's sum of
            # squares, so a shared n-based scalar systematically
            # understates the SE of every two-level term whenever
            # non-corner points are present.
            #
            # This per-column formula equals the exact
            # sigma * sqrt((X^T X)^-1_jj) only when the column is
            # orthogonal to every other column in the model. That holds
            # for every main effect and two-factor interaction on every
            # design this module generates — the terms that actually gate
            # significance in dropped_factors and the stage rule — so
            # those CIs are exact. It does NOT hold for the intercept or
            # for pure-quadratic terms (A^2, B^2, ...) on a central
            # composite: those columns are mutually correlated (with each
            # other and with the intercept), so their reported SEs are
            # optimistic (too narrow). Measured on a 2-factor central
            # composite against an explicit (X^T X)^-1 inverse: A^2/B^2
            # composite with 3 CENTRE POINTS (the ratio moves with the
            # centre count: 1.458 at 3 centres, 1.313 at 5 — so the figure
            # is only reproducible if the configuration is stated), the
            # exact SE is 0.420813 vs. 0.288675 from this formula — about
            # 1.46x too narrow. Accepted rather than fixed with a full
            # matrix inverse: quadratic terms describe surface curvature
            # and are consumed by solve_stationary_point as point
            # estimates only, never gated on their CIs.
            ss_j = sum(v * v for v in cols[idx])
            se = math.sqrt(pe_var / ss_j)
            lo, hi = est - tcrit * se, est + tcrit * se
            sig = not (lo <= 0.0 <= hi)
        # Surface the confounding on the Effect itself. `alias_classes` was
        # already being built above and then silently discarded, which left the
        # aliasing knowable only as `Fit.aliases` — a design-level list of label
        # pairs with no link to the coefficient that actually carries the shared
        # estimate. `decide.alias_consequential` needs that link (which
        # coefficient, which alternatives, at which sign) to ask whether
        # resolving the alias could change the recommendation.
        eff = Effect(label=labels[idx], terms=terms[idx], estimate=est,
                     se=se, ci_low=lo, ci_high=hi, significant=sig,
                     aliased_with=alias_classes.get(labels[idx], ()))
        (quads if idx >= quad_start else built).append(eff)

    extra: dict = {}
    aliases = None
    if blk and not mixed:
        # A BLOCKED fit (B4): the block column is correlated with the
        # quadratics (and with every column when the reuse is unbalanced), so
        # every SE comes from the exact inverse, the block a nuisance column.
        built, quads, extra = _exact_inference(
            design, labels, terms, cols, coefs, built, quads, quad_start,
            alias_classes, pe_var, pe_df, tcrit, have_se, alpha,
            extra_cols=[blk])
    if mixed:
        built, quads, extra = _exact_inference(
            design, labels, terms, cols, coefs, built, quads, quad_start,
            alias_classes, pe_var, pe_df, tcrit, have_se, alpha,
            extra_cols=centre_ind + ([blk] if blk else []))
        extra["centre_isolated"] = bool(centre_ind)
        if not centre_ind and any(p.role == "center" for p in pts):
            # Recorded, never silent (stage-1b N3): the corner model is not of
            # full column rank, so indicators would make it singular and the
            # coefficients rest partly on the centre rows -- curvature can leak.
            extra["centre_isolation_reason"] = "corner_model_rank_deficient"
        # The aliasing THIS matrix has, read off the model it solved (stage-1
        # M6): exact duplicates collapsed into a kept column, and 2fi columns
        # in the span of kept columns on the corner rows. ``alias_pairs`` reads
        # a PLANNED design's pseudo-factor columns; on a fit design (contrast
        # columns) it would treat subsets of contrasts as pseudo-factors and
        # fabricate pairs.
        aliases = sorted(
            [("".join(alt), rep) for rep, alts in alias_classes.items()
             for alt, _s in alts]
            + [("".join(t), "span(" + ",".join(sp) + ")") for t, sp in span])
        extra["span_aliased"] = tuple((tuple(t), tuple(sp)) for t, sp in span)

    lof_f = lof_p = None
    if pe_var is not None and pe_var > 0 and pe_df > 0:
        resid = [
            ys[r] - sum(coefs_lof[c] * lof_cols[c][r] for c in range(len(lof_cols)))
            for r in range(n)
        ]
        ss_resid = sum(v * v for v in resid)
        ss_pe = pe_var * pe_df
        df_resid = n - len(lof_cols)
        df_lof = df_resid - pe_df
        if df_lof > 0:
            ss_lof = max(ss_resid - ss_pe, 0.0)
            lof_f = (ss_lof / df_lof) / pe_var
            lof_p = float(1.0 - fisher_f.cdf(lof_f, df_lof, pe_df))

    # A DETERMINISTIC response (replicated centres, zero pure error) has no F
    # test, but lack of fit is then decidable exactly: a model whose residuals
    # vanish fits (stage-1b N5). Not written to effects.json.
    # Only when there IS lack-of-fit df (n - p - df_pe > 0, stage-1c P5): with
    # none, the residuals are pure error by construction and nothing is
    # decided. With df and zero pure error, nonzero residuals are an
    # ESTABLISHED lack of fit, recorded as such (``lof_exact``), not "not
    # computable".
    exact_fit = False
    lof_exact = None
    df_lof_all = n - len(lof_cols) - pe_df
    if (lof_p is None and pe_df > 0 and pe_var is not None and pe_var == 0.0
            and df_lof_all > 0):
        resid0 = [ys[r] - sum(coefs_lof[c] * lof_cols[c][r] for c in range(len(lof_cols)))
                  for r in range(n)]
        scale = 1.0 + sum(v * v for v in ys)
        exact_fit = sum(v * v for v in resid0) <= 1e-18 * scale
        lof_exact = "exact_fit" if exact_fit else "rejected"
    extra["lof_exact_fit"] = exact_fit
    extra["lof_exact"] = lof_exact
    if blk:
        # The between-stage DRIFT check: the block coefficient's t on pure
        # error, from the exact inverse over the solved columns.
        allc = cols + list(centre_ind) + [blk]
        xtx = [[sum(a[r] * b[r] for r in range(n)) for b in allc] for a in allc]
        vb = _invert(xtx)[-1][-1]
        b_est = float(coefs_blocked[len(cols)])
        if have_se:
            b_se = math.sqrt(pe_var * max(vb, 0.0))
            b_t = b_est / b_se if b_se > 0 else None
            b_p = (float(2.0 * (1.0 - student_t.cdf(abs(b_t), pe_df)))
                   if b_t is not None else None)
        else:
            b_se = b_t = b_p = None
        extra["block_effect"] = (b_est, b_se, b_t, b_p, pe_df)

    return Fit(
        intercept=coefs[0], effects=tuple(built), n_runs=n,
        pure_error_var=pe_var, pure_error_df=pe_df,
        lack_of_fit_f=lof_f, lack_of_fit_p=lof_p,
        aliases=tuple(alias_pairs(design) if aliases is None else aliases),
        quadratic=tuple(quads),
        **extra,
    )


def _invert(a: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse with partial pivoting (small p; no numpy)."""
    p = len(a)
    m = [list(row) + [1.0 if i == j else 0.0 for j in range(p)] for i, row in enumerate(a)]
    for c in range(p):
        piv = max(range(c, p), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            raise ValueError("design matrix is singular -- (X'X) has no inverse")
        m[c], m[piv] = m[piv], m[c]
        d = m[c][c]
        m[c] = [v / d for v in m[c]]
        for r in range(p):
            if r != c and m[r][c] != 0.0:
                fac = m[r][c]
                m[r] = [x - fac * y for x, y in zip(m[r], m[c])]
    return [row[p:] for row in m]


def _centre_indicators(pts, cols) -> list[list[float]]:
    """One 0/1 column per distinct centre configuration, when the design has
    corner rows on which the model is of full column rank (otherwise the
    indicators would make it singular, and none are added)."""
    akeys = [r for r, p in enumerate(pts) if p.role != "center"]
    if len(akeys) == len(pts) or not akeys:
        return []
    sub = [[c[r] for r in akeys] for c in cols]
    from orchestrator.optimize.factors import _rank

    if _rank(list(zip(*sub))) < len(cols):
        return []
    groups: dict[tuple, list[int]] = {}
    for r, p in enumerate(pts):
        if p.role == "center":
            groups.setdefault(tuple(p.coded), []).append(r)
    return [[1.0 if r in set(idx) else 0.0 for r in range(len(pts))]
            for idx in groups.values()]


def _exact_inference(design, labels, terms, cols, coefs, built, quads, quad_start,
                     alias_classes, pe_var, pe_df, tcrit, have_se, alpha,
                     extra_cols=()):
    """SEs from the exact ``(X'X)^-1`` covariance, that covariance, and the
    categoricals' F tests for a MIXED fit.

    A mixed-level design is non-orthogonal by construction -- a collapsed
    categorical's contrasts are correlated with each other and the intercept,
    and cycled centre rows are coded at their levels -- so the per-column
    ``sigma / sqrt(sum x^2)`` would be optimistic. Here every term's SE is
    ``sigma sqrt((X'X)^-1_jj)`` and the full ``(X'X)^-1`` is kept on the Fit so
    prediction intervals and the model regret bound use ``x'(X'X)^-1 x``.
    """
    n = len(cols[0])
    p = len(cols)
    allc = list(cols) + list(extra_cols)
    xtx = [[sum(allc[i][r] * allc[j][r] for r in range(n)) for j in range(len(allc))]
           for i in range(len(allc))]
    # The model coefficients' covariance is the leading p x p block of the
    # inverse (the centre indicators, when present, are nuisance parameters).
    cov = [row[:p] for row in _invert(xtx)[:p]]
    effs = list(built) + list(quads)
    new: list[Effect] = []
    for idx, e in zip(range(1, p), effs):
        se = lo = hi = sig = None
        if have_se:
            se = math.sqrt(pe_var * max(cov[idx][idx], 0.0))
            lo, hi = e.estimate - tcrit * se, e.estimate + tcrit * se
            sig = not (lo <= 0.0 <= hi)
        new.append(Effect(label=e.label, terms=e.terms, estimate=e.estimate, se=se,
                          ci_low=lo, ci_high=hi, significant=sig,
                          aliased_with=e.aliased_with))
    nb = len(built)
    vif = tuple((labels[j], cov[j][j] * sum(v * v for v in cols[j]))
                for j in range(1, p))
    pairs = tuple(zip(design.factor_ids, design.groups))
    tests: list[FactorTest] = []
    by_factor: dict[str, list[str]] = {}
    for c, g in pairs:
        by_factor.setdefault(g, []).append(c)
    for g, cs in by_factor.items():
        # A single column that is NOT the factor's own id is a categorical
        # reduced to two retained levels (one contrast; stage-1b N6): it keeps
        # its 1-df test so the survivor rule can still drop it.
        if len(cs) < 2 and cs[0] == g:
            continue
        idxs = [labels.index(c) for c in cs if c in labels]
        q = len(idxs)
        fval = pval = sig = None
        if have_se and q:
            b = [coefs[i] for i in idxs]
            v = [[cov[i][j] for j in idxs] for i in idxs]
            vinv = _invert(v)
            quad = sum(b[i] * vinv[i][j] * b[j] for i in range(q) for j in range(q))
            fval = quad / (q * pe_var)
            pval = float(1.0 - fisher_f.cdf(fval, q, pe_df))
            sig = pval < alpha
        tests.append(FactorTest(factor=g, columns=tuple(cs), df=q, f=fval, p=pval,
                                significant=sig))
    extra = {
        "groups": pairs,
        "term_labels": tuple(labels),
        "term_terms": tuple(tuple(t) for t in terms),
        "covariance": tuple(tuple(r) for r in cov),
        "variance_inflation": vif,
        "factor_tests": tuple(tests),
    }
    return new[:nb], new[nb:], extra


def factor_test(fit: Fit, factor_id: str) -> FactorTest | None:
    """The categorical's F test on ``fit``, or ``None`` (not a categorical)."""
    return next((t for t in fit.factor_tests if t.factor == factor_id), None)


def prediction_variance(fit: Fit, xa: dict, xb: dict | None = None) -> float | None:
    """``s_pe^2 d'(X'X)^-1 d`` for ``d = x(xa) - x(xb)`` from the fit's exact
    ``(X'X)^-1`` covariance (``xb=None``: the variance of the estimated MEAN
    response at ``xa``, intercept included -- a CONFIDENCE, not a prediction,
    interval quantity: no new-observation variance is added), or ``None`` when
    the fit carries no covariance (every two-level fit, whose consumers keep
    their per-term arithmetic, exact only for columns orthogonal to all
    others)."""
    if fit.covariance is None or not fit.pure_error_var:
        return None
    def row(x):
        return [1.0] + [math.prod(float(x[t]) for t in ts) for ts in fit.term_terms[1:]]
    a = row(xa)
    d = a if xb is None else [u - v for u, v in zip(a, row(xb))]
    c = fit.covariance
    q = sum(d[i] * c[i][j] * d[j] for i in range(len(d)) for j in range(len(d)))
    return float(fit.pure_error_var) * max(q, 0.0)


def dropped_factors(fit: Fit, factor_ids) -> list[str]:
    """Factors whose main effect is indistinguishable from zero.

    With no pure-error estimate nothing can be dropped — an unknown effect
    is not a null effect.
    """
    out: list[str] = []
    for fid in factor_ids:
        t = factor_test(fit, fid)
        if t is not None:
            if t.significant is False:
                out.append(fid)
            continue
        for e in fit.effects:
            if e.terms == (fid,):
                if e.significant is False:
                    out.append(fid)
                break
    return out


def solve_stationary_point(fit: Fit, factor_ids) -> dict[str, float] | None:
    """Coded-space stationary point of the fitted quadratic surface.

    Solves ``2B x + b = 0`` where ``b`` holds the linear coefficients and
    ``B`` the quadratic/interaction terms. Returns ``None`` when the fit has
    no curvature terms (a plane has no interior optimum).
    """
    ids = tuple(factor_ids)
    if not fit.quadratic:
        return None
    k = len(ids)
    idx = {f: i for i, f in enumerate(ids)}

    b = [0.0] * k
    for e in fit.effects:
        if len(e.terms) == 1:
            b[idx[e.terms[0]]] = e.estimate

    B = [[0.0] * k for _ in range(k)]
    for e in fit.quadratic:
        i = idx[e.terms[0]]
        B[i][i] = e.estimate
    for e in fit.effects:
        if len(e.terms) == 2 and e.terms[0] != e.terms[1]:
            i, j = idx[e.terms[0]], idx[e.terms[1]]
            B[i][j] = B[j][i] = e.estimate / 2.0

    a = [[2.0 * B[i][j] for j in range(k)] for i in range(k)]
    rhs = [-b[i] for i in range(k)]
    try:
        for col in range(k):
            pivot = max(range(col, k), key=lambda r: abs(a[r][col]))
            if abs(a[pivot][col]) < 1e-12:
                return None
            a[col], a[pivot] = a[pivot], a[col]
            rhs[col], rhs[pivot] = rhs[pivot], rhs[col]
            for r in range(k):
                if r == col:
                    continue
                f = a[r][col] / a[col][col]
                for c in range(col, k):
                    a[r][c] -= f * a[col][c]
                rhs[r] -= f * rhs[col]
        return {ids[i]: rhs[i] / a[i][i] for i in range(k)}
    except ZeroDivisionError:
        return None



def planned_aliases_separated(planned_pairs, fit: Fit) -> list[dict]:
    """Planned (pseudo-factor space) alias pairs that this fit nevertheless
    ESTIMATED SEPARATELY (stage-1 M7).

    In a collapsed design the fit codes the level that ran, so a collapsed row
    no longer reproduces the planned pseudo-sign identity that made two
    columns equal; least squares then separates the pair through those rows
    alone. That is legitimate but expensive and fragile -- the variance
    inflation says how expensive -- so every such pair is reported beside the
    planned aliasing instead of the two lists silently disagreeing.
    """
    fitted = {e.label for e in fit.effects}
    vif = dict(fit.variance_inflation)
    out = []
    for a, b in planned_pairs or ():
        if a in fitted and b in fitted:
            out.append({
                "planned": [a, b],
                "variance_inflation": {a: vif.get(a), b: vif.get(b)},
                "reason": ("aliased in the planned pseudo-factor columns, but the "
                           "fit codes the level that RAN, and the collapsed "
                           "combination(s) break the planned identity, so the "
                           "pair is separated through those rows only"),
            })
    return out
