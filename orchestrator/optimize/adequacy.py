"""How model adequacy is DETERMINED (WP-B; spec 2026-10-17-model-adequacy-design.md).

Pure arithmetic, no numpy, zero LLM tokens. Four pieces:

* ``validation_points`` -- the registered rule that places refine's off-lattice
  VALIDATION runs: coded +-0.5 on every refinable axis (the point of [-1, 1]
  farthest from the face-centred CCD lattice {-1, 0, +1}), chosen among
  ``{-0.5, +0.5}^k`` by a seeded greedy MAXIMIN (Johnson, Moore & Ylvisaker
  1990): each next point maximises its minimum distance to the points already
  chosen, ties broken by the seeded RNG. Interior by construction.
* ``prediction_check`` -- the validation observations against the model fitted
  WITHOUT them. The decision is the joint predictive F test (Chow 1960): with
  ``e = y_v - X_v b`` and ``V = I + X_v (X'X)^-1 X_v'``, under the registered
  model and iid normal errors ``F = e' V^-1 e / (m s_pe^2)`` is exactly
  ``F(m, df_pe)`` (``e`` and ``s_pe^2`` are independent: the centre replicates'
  pure error is orthogonal to the fit and to the new runs). Per-point Bonferroni
  prediction intervals (Myers, Montgomery & Anderson-Cook 2016, §2.7) are
  recorded beside it to say WHICH point disagreed.
* ``press`` -- Allen's (1974) prediction sum of squares and R^2_prediction over
  the fitted rows, ``sum (e_i / (1 - h_ii))^2``: a diagnostic, not a gate.
* ``design_efficiency`` -- D-efficiency ``|X'X / n|^(1/p)`` (Atkinson, Donev &
  Tobias 2007, §11.3) and each term's centred variance inflation factor
  ``VIF_j = [(X'X)^-1]_jj * sum_i (x_ij - xbar_j)^2`` of the design AS RUN.
"""
from __future__ import annotations

import itertools
import math
import random

from scipy.stats import f as fisher_f
from scipy.stats import t as student_t

#: Family-wise level of the validation prediction check (the same alpha as the
#: lack-of-fit test it sits beside).
VALIDATION_ALPHA = 0.05

#: Default number of validation points refine registers (``design.refine.
#: validation_points``). Four: one per quadrant at k = 2, and at every k the
#: maximin set puts each refinable axis at both +0.5 and -0.5.
DEFAULT_VALIDATION_POINTS = 4

#: The coded offset of a validation point on every refinable axis.
VALIDATION_OFFSET = 0.5

#: Above this many refinable factors the candidate set {-0.5, +0.5}^k is
#: SAMPLED (seeded) rather than enumerated: 2^12 = 4096 candidates is the cap.
_ENUMERATE_UP_TO_K = 12
_SAMPLE = 4096


def n_validation_points(refine_cfg: dict | None, k: int) -> int:
    """The registered count: ``design.refine.validation_points`` (default 4),
    never more than the 2^k distinct candidates."""
    raw = (refine_cfg or {}).get("validation_points", DEFAULT_VALIDATION_POINTS)
    m = max(0, int(raw))
    return min(m, 2 ** k) if k < 31 else m


def _dist2(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def validation_points(k: int, m: int, seed: int) -> list[tuple[float, ...]]:
    """``m`` coded points in ``{-0.5, +0.5}^k`` by seeded greedy maximin.

    Deterministic in ``(k, m, seed)``. The candidate set is enumerated up to
    k = 12 (4096 points) and sampled (4096 seeded sign vectors) above, so the
    size is bounded before anything is enumerated (RESOURCE-PROTOCOL rule 4).
    """
    if m <= 0 or k <= 0:
        return []
    rng = random.Random(f"validation:{seed}")
    o = VALIDATION_OFFSET
    if k <= _ENUMERATE_UP_TO_K:
        cands = [tuple(o * s for s in signs)
                 for signs in itertools.product((-1.0, 1.0), repeat=k)]
    else:
        seen: set = set()
        cands = []
        while len(cands) < _SAMPLE:
            c = tuple(o * rng.choice((-1.0, 1.0)) for _ in range(k))
            if c not in seen:
                seen.add(c)
                cands.append(c)
    chosen = [cands[rng.randrange(len(cands))]]
    while len(chosen) < min(m, len(cands)):
        rest = [c for c in cands if c not in chosen]
        score = [min(_dist2(c, p) for p in chosen) for c in rest]
        top = max(score)
        ties = [c for c, s in zip(rest, score) if s == top]
        chosen.append(ties[rng.randrange(len(ties))])
    return chosen


# ── linear algebra on small dense matrices (p <= ~45) ───────────────────────

def _invert(a):
    from orchestrator.optimize.effects import _invert as inv

    return inv(a)


def _logdet(a) -> float | None:
    """``log det(a)`` of a symmetric positive-(semi)definite matrix by
    Gaussian elimination with partial pivoting, accumulated in logs so a
    large design cannot overflow; ``None`` when singular or not positive."""
    m = [list(r) for r in a]
    n = len(m)
    out = 0.0
    sign = 1.0
    scale = max((abs(v) for r in m for v in r), default=0.0) or 1.0
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) <= 1e-12 * scale:
            return None
        if piv != c:
            m[c], m[piv] = m[piv], m[c]
            sign = -sign
        d = m[c][c]
        sign *= 1.0 if d > 0 else -1.0
        out += math.log(abs(d))
        for r in range(c + 1, n):
            f = m[r][c] / d
            if f:
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return out if sign > 0 else None


def _xtx(cols):
    n = len(cols[0])
    return [[sum(ci[r] * cj[r] for r in range(n)) for cj in cols] for ci in cols]


def model_columns(design, factor_ids, *, include_interactions=True, omit_terms=()):
    """``(labels, terms, cols)`` of the matrix ``fit_effects`` solves."""
    from orchestrator.optimize.effects import model_matrix

    labels, terms, cols, _q, _a = model_matrix(
        design, factor_ids, include_interactions=include_interactions,
        omit_terms=omit_terms)
    return labels, terms, cols


def design_efficiency(cols, labels) -> dict | None:
    """D-efficiency and centred VIFs of the model matrix ``cols`` (intercept
    first). ``None`` when ``X'X`` is singular (nothing is estimable to rate)."""
    n = len(cols[0])
    p = len(cols)
    if n == 0 or p == 0:
        return None
    a = _xtx(cols)
    ld = _logdet(a)
    if ld is None:
        return None
    d_eff = math.exp((ld - p * math.log(n)) / p)
    try:
        inv = _invert(a)
    except ValueError:
        return None
    vif = {}
    for j in range(1, p):
        mu = sum(cols[j]) / n
        sst = sum((v - mu) ** 2 for v in cols[j])
        vif[labels[j]] = round(inv[j][j] * sst, 6) if sst > 0 else None
    return {"d_efficiency": round(d_eff, 6), "n": n, "p": p,
            "max_vif": max((v for v in vif.values() if v is not None), default=None),
            "vif": vif}


def press(cols, ys) -> dict | None:
    """Allen's PRESS and R^2_prediction over the fitted rows; ``None`` when a
    row has leverage 1 (its deleted residual does not exist) or X'X is singular."""
    n = len(ys)
    if n == 0:
        return None
    try:
        inv = _invert(_xtx(cols))
    except ValueError:
        return None
    from orchestrator.optimize.effects import _solve_normal_equations

    b = _solve_normal_equations(cols, ys)
    p = len(cols)
    s = 0.0
    for r in range(n):
        x = [cols[c][r] for c in range(p)]
        h = sum(x[i] * inv[i][j] * x[j] for i in range(p) for j in range(p))
        if h >= 1.0 - 1e-9:
            return None
        e = ys[r] - sum(b[c] * x[c] for c in range(p))
        s += (e / (1.0 - h)) ** 2
    mu = sum(ys) / n
    sst = sum((y - mu) ** 2 for y in ys)
    return {"press": s, "r2_prediction": (1.0 - s / sst) if sst > 0 else None}


def prediction_check(fit, cols, terms, points, *, alpha: float = VALIDATION_ALPHA,
                     nuisance=()):
    """The validation observations against the fit.

    ``points`` is ``[(coded dict, y)]`` for every validation row that produced
    a primary value (coded AS RUN over the fitted factors). ``cols``/``terms``
    are the fitted model's matrix. ``nuisance`` are extra solved columns that
    are NOT model terms (the B4 block indicator); a validation point sits at 0
    on each (it is a refine-block run, the block the predictions refer to). Returns the record written to
    ``recommendation.json["model_adequacy"]["validation"]``; ``rejected`` is
    ``None`` when no test is computable (no pure error, no measured point).
    """
    m = len(points)
    s2 = fit.pure_error_var
    df = int(fit.pure_error_df or 0)
    base = {"alpha": alpha, "method": "joint_predictive_F_chow_1960",
            "points_measured": m}
    if m == 0:
        return {**base, "rejected": None, "reason": "no_validation_point_measured"}
    if not s2 or s2 <= 0 or df <= 0:
        return {**base, "rejected": None, "reason": "no_pure_error"}
    allc = list(cols) + [list(c) for c in nuisance]
    try:
        inv = _invert(_xtx(allc))
    except ValueError:
        return {**base, "rejected": None, "reason": "singular_model"}
    from orchestrator.optimize.decide import predict

    def row(coded):
        return ([1.0] + [math.prod(float(coded[t]) for t in ts) for ts in terms[1:]]
                + [0.0] * len(nuisance))

    xs = [row(c) for c, _y in points]
    p = len(allc)
    e = [float(y) - predict(fit, c) for c, y in points]
    hv = [[sum(xs[a][i] * inv[i][j] * xs[b][j] for i in range(p) for j in range(p))
           for b in range(m)] for a in range(m)]
    v = [[(1.0 if a == b else 0.0) + hv[a][b] for b in range(m)] for a in range(m)]
    vinv = _invert(v)
    q = sum(e[a] * vinv[a][b] * e[b] for a in range(m) for b in range(m))
    fval = q / (m * s2)
    pval = float(1.0 - fisher_f.cdf(fval, m, df))
    tcrit = float(student_t.ppf(1.0 - alpha / (2.0 * m), df))
    per = []
    for (c, y), ei, a in zip(points, e, range(m)):
        half = tcrit * math.sqrt(s2 * v[a][a])
        per.append({"coded": {k: round(float(x), 6) for k, x in c.items()},
                    "observed": float(y), "predicted": float(y) - ei,
                    "pi_half_width": half,
                    "outside_bonferroni_pi": abs(ei) > half})
    return {**base, "df": [m, df], "f": fval, "p": pval, "rejected": pval < alpha,
            "bonferroni_t": tcrit, "points": per}


def epoch_verdict(stage_verdicts) -> tuple[object, list, str | None]:
    """The STICKY verdict over an epoch's fitting stages.

    ``stage_verdicts`` is ``[(stage, model_class, verdict, validated)]`` in
    order: ``model_class`` 1 (first order + 2fi: screen, foldover) or 2
    (second order: refine); ``verdict`` True / False / None; ``validated``
    whether the stage COMPLETED a validation prediction check.

    * A REJECTION (False) is overturned only by a later stage of a STRICTLY
      HIGHER model class that completed a validation check. A same-class
      refit -- a foldover's combined fit after a screen rejection -- never
      overturns it. Refine's second-order model is the registered augmentation
      for a screen rejection (CURVATURE_ACCOUNTING), but its 3-level lack of
      fit alone has ~alpha power against one-dimensional misspecification
      (stage-0 audit Q3); without a completed check the verdict is UNKNOWN,
      basis ``screen_rejection_unresolved``.
    * Any other verdict (True / None) is superseded by any later stage of at
      least its class.

    Whatever is not superseded combines three-valued: any False -> False, else
    any None -> None, else True. Returns ``(verdict, decided_by, basis)``;
    ``basis`` is ``"screen_rejection_unresolved"`` or ``None``.
    """
    rows = [tuple(r) + (False,) * (4 - len(r)) for r in stage_verdicts]
    live, unresolved = [], []
    for i, (st, cls, v, _val) in enumerate(rows):
        later = rows[i + 1:]
        if v is False:
            if any(c2 > cls and val2 for _s2, c2, _v2, val2 in later):
                continue
            if any(c2 > cls for _s2, c2, _v2, _val2 in later):
                unresolved.append(st)
                continue
            live.append((st, v))
        elif not any(c2 >= cls for _s2, c2, _v2, _val2 in later):
            live.append((st, v))
    if any(v is False for _s, v in live):
        return False, [s for s, v in live if v is False], None
    if unresolved:
        return None, unresolved, "screen_rejection_unresolved"
    if any(v is None for _s, v in live):
        return None, [s for s, v in live if v is None], None
    return True, [s for s, _v in live], None
