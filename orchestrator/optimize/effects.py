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
    """One estimated model term."""

    label: str
    terms: tuple[str, ...]
    estimate: float
    se: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    significant: bool | None = None


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


def pure_error(center_responses) -> tuple[float | None, int]:
    """Sample variance and df of replicated center points."""
    vals = list(center_responses)
    if len(vals) < 2:
        return None, 0
    return variance(vals), len(vals) - 1


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


def fit_effects(design: Design, responses, *, factor_ids,
                include_interactions: bool = True,
                alpha: float = 0.05) -> Fit:
    """Fit main effects (+ 2-factor interactions, + curvature when present)."""
    ids = tuple(factor_ids)
    ys = [float(v) for v in responses]
    if len(ys) != len(design.points):
        raise ValueError(
            f"responses length {len(ys)} != design length "
            f"{len(design.points)}; every planned run needs exactly one "
            f"response value",
        )

    k = len(ids)
    pts = design.points
    has_axial = any(p.role == "axial" for p in pts)

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
    # column, so a caller can report the confounding instead of hiding it.
    alias_classes: dict[str, tuple[tuple[str, ...], ...]] = {}
    if include_interactions and k >= 2:
        seen: dict[tuple[float, ...], int] = {}
        for j2, fid in enumerate(ids):          # main-effect columns already added
            seen.setdefault(tuple(p.coded[j2] for p in pts), 1 + j2)
        for i, j in itertools.combinations(range(k), 2):
            col = [p.coded[i] * p.coded[j] for p in pts]
            key = tuple(col)
            neg = tuple(-v for v in col)
            hit = seen.get(key, seen.get(neg))
            if hit is not None:
                # Aliased with an existing column: record the confounding and do
                # NOT add a duplicate column.
                rep = labels[hit]
                alias_classes.setdefault(rep, ())
                alias_classes[rep] = alias_classes[rep] + ((ids[i], ids[j]),)
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

    coefs = _solve_normal_equations(cols, ys)

    centers = [y for p, y in zip(pts, ys) if p.role == "center"]
    pe_var, pe_df = pure_error(centers)

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
        eff = Effect(label=labels[idx], terms=terms[idx], estimate=est,
                     se=se, ci_low=lo, ci_high=hi, significant=sig)
        (quads if idx >= quad_start else built).append(eff)

    lof_f = lof_p = None
    if pe_var is not None and pe_var > 0 and pe_df > 0:
        resid = [
            ys[r] - sum(coefs[c] * cols[c][r] for c in range(len(cols)))
            for r in range(n)
        ]
        ss_resid = sum(v * v for v in resid)
        ss_pe = pe_var * pe_df
        df_resid = n - len(cols)
        df_lof = df_resid - pe_df
        if df_lof > 0:
            ss_lof = max(ss_resid - ss_pe, 0.0)
            lof_f = (ss_lof / df_lof) / pe_var
            lof_p = float(1.0 - fisher_f.cdf(lof_f, df_lof, pe_df))

    return Fit(
        intercept=coefs[0], effects=tuple(built), n_runs=n,
        pure_error_var=pe_var, pure_error_df=pe_df,
        lack_of_fit_f=lof_f, lack_of_fit_p=lof_p,
        aliases=tuple(alias_pairs(design)), quadratic=tuple(quads),
    )


def dropped_factors(fit: Fit, factor_ids) -> list[str]:
    """Factors whose main effect is indistinguishable from zero.

    With no pure-error estimate nothing can be dropped — an unknown effect
    is not a null effect.
    """
    out: list[str] = []
    for fid in factor_ids:
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
