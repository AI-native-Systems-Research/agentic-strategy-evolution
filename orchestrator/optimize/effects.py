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

    if include_interactions and k >= 2:
        for i, j in itertools.combinations(range(k), 2):
            labels.append(f"{ids[i]}{ids[j]}")
            terms.append((ids[i], ids[j]))
            cols.append([p.coded[i] * p.coded[j] for p in pts])

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
    se = None
    tcrit = None
    if pe_var is not None and pe_var > 0 and pe_df > 0:
        se = math.sqrt(pe_var / n)
        tcrit = float(student_t.ppf(1 - alpha / 2, pe_df))

    built: list[Effect] = []
    quads: list[Effect] = []
    for idx in range(1, len(labels)):
        est = coefs[idx]
        lo = hi = None
        sig = None
        if se is not None and tcrit is not None:
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
