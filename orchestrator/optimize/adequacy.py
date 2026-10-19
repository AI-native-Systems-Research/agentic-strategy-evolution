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
  ``VIF_j = [(X'X)^-1]_jj * sum_i (x_ij - xbar_j)^2`` of the design AS RUN,
  with the G-efficiency and the exact I-criterion (average prediction
  variance over the coded region) from the same inverse
  (``prediction_variance``; #321 P4 item 3).
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


#: #321 P4 item 2: the OUTER validation ring's coded offset. A quadratic
#: through {-1, 0, 1} misses a cubic most at |x| = 1/sqrt(3) = 0.58 (the inner
#: ring) and a quartic at 1/sqrt(2) = 0.71; features near the faces and corners
#: (a second peak, a cliff close to an edge) lie beyond both. 0.8 is the
#: interior point closest to the faces that a grid of 7+ steps per half-range
#: still resolves off the lattice.
VALIDATION_OUTER_OFFSET = 0.8
DEFAULT_VALIDATION_OUTER_POINTS = 2


def _sign_candidates(k: int, o, rng) -> list[tuple[float, ...]]:
    """``{-o_j, +o_j}`` per axis; ``o`` is one offset or one per axis."""
    offs = list(o) if isinstance(o, (list, tuple)) else [float(o)] * k
    if k <= _ENUMERATE_UP_TO_K:
        return [tuple(oj * s for oj, s in zip(offs, signs))
                for signs in itertools.product((-1.0, 1.0), repeat=k)]
    seen: set = set()
    cands = []
    while len(cands) < _SAMPLE:
        c = tuple(oj * rng.choice((-1.0, 1.0)) for oj in offs)
        if c not in seen:
            seen.add(c)
            cands.append(c)
    return cands


def _greedy_maximin(cands, m, rng, chosen=(), key=None, forbidden=(), declined=None):
    """Greedy maximin over ``cands`` given the points already ``chosen``.

    ``key(c)`` is a candidate's image AS RUN (its snapped coded point). A
    candidate whose image is in ``forbidden`` (a design point) or equals the
    image of a point already chosen is skipped, and the next-best candidate
    takes its seat; distances are measured between images, so the maximin is
    over the points that will actually run."""
    key = key or (lambda c: c)
    used = set(forbidden) | {key(c) for c in chosen}
    pool_img = [key(c) for c in chosen]
    out: list = []
    live = [c for c in cands if key(c) not in used]
    if declined is not None:
        declined.extend(c for c in cands if key(c) in set(forbidden))
    if not live or m <= 0:
        return out
    if not chosen:
        first = live[rng.randrange(len(live))]
        out.append(first)
        used.add(key(first))
        pool_img.append(key(first))
    while len(out) < m:
        rest = [c for c in live if c not in out and key(c) not in used]
        if not rest:
            break
        score = [min(_dist2(key(c), q) for q in pool_img) for c in rest]
        top = max(score)
        ties = [c for c, s in zip(rest, score) if s == top]
        pick = ties[rng.randrange(len(ties))]
        out.append(pick)
        used.add(key(pick))
        pool_img.append(key(pick))
    return out


def validation_points(k: int, m: int, seed: int, *, outer: int = 0,
                      outer_offset: float = VALIDATION_OUTER_OFFSET,
                      key=None, forbidden=(), offsets=None,
                      declined=None) -> list[tuple[float, ...]]:
    """``m`` coded points in ``{-0.5, +0.5}^k`` by seeded greedy maximin, then
    ``outer`` points in ``{-outer_offset, +outer_offset}^k`` chosen by the same
    greedy maximin against EVERY point already chosen (#321 P4 item 2).

    Deterministic in its arguments. The candidate set is enumerated up to
    k = 12 (4096 points) and sampled (4096 seeded sign vectors) above, so the
    size is bounded before anything is enumerated (RESOURCE-PROTOCOL rule 4).
    The outer ring draws from its own seeded stream. ``key``/``forbidden``
    (``stage_runner``): a candidate's image as run, and the design points'
    images; a candidate that SNAPS onto a design point or onto another chosen
    point is declined and the next-best takes its seat, so fewer than
    ``m + outer`` points come back only when the candidates run out.
    ``offsets`` replaces the inner ring's 0.5 per axis.
    """
    if k <= 0:
        return []
    rng = random.Random(f"validation:{seed}")
    inner = (_greedy_maximin(_sign_candidates(
        k, VALIDATION_OFFSET if offsets is None else offsets, rng), m, rng,
        key=key, forbidden=forbidden, declined=declined) if m > 0 else [])
    if outer <= 0:
        return inner
    rng2 = random.Random(f"validation_outer:{seed}")
    return inner + _greedy_maximin(_sign_candidates(k, float(outer_offset), rng2),
                                   outer, rng2, chosen=inner, key=key,
                                   forbidden=forbidden, declined=declined)


def n_validation_outer_points(refine_cfg: dict | None, k: int) -> int:
    """The registered outer-ring count (``design.refine.validation_outer_points``,
    default ``DEFAULT_VALIDATION_OUTER_POINTS``), at most 2^k."""
    raw = (refine_cfg or {}).get("validation_outer_points",
                                 DEFAULT_VALIDATION_OUTER_POINTS)
    m = max(0, int(raw))
    return min(m, 2 ** k) if k < 31 else m


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


#: Budget for the max-SPV search of G-efficiency, in multiply-adds
#: (points x p^2). Bounded before anything is enumerated (RESOURCE-PROTOCOL
#: rule 4); past it the evaluation set is a SEEDED sample, recorded.
_G_BUDGET = 2_000_000
_G_SAMPLE = 2048


def _term_powers(terms):
    """``[{factor: exponent}]`` per model term (``("A", "A")`` -> ``{A: 2}``)."""
    out = []
    for t in terms:
        d: dict = {}
        for fid in t:
            d[fid] = d.get(fid, 0) + 1
        out.append(d)
    return out


def _moment(a: int, discrete: bool) -> float:
    """``E[x^a]`` for x uniform on [-1, 1] (``1/(a+1)``, a even) or on the two
    points {-1, +1} (1, a even); 0 for odd a."""
    if a % 2:
        return 0.0
    return 1.0 if discrete else 1.0 / (a + 1)


def prediction_variance(inv, terms, factor_ids, n: int, *, discrete=(),
                        seed: int = 0) -> dict | None:
    """G- and I-criteria of a design over the CODED REGION, from the exact
    ``(X'X)^-1`` (``inv``) the D-efficiency already inverted.

    The region R is the product over the model's factors of ``[-1, 1]``
    (numeric, uniform) or ``{-1, +1}`` (a two-level choice factor, ``discrete``).
    The scaled prediction variance is ``SPV(x) = n f(x)'(X'X)^-1 f(x)``
    (Myers, Montgomery & Anderson-Cook 2016, §8.2.1).

    * **I** (average prediction variance; Atkinson, Donev & Tobias 2007,
      §10.6) is EXACT: ``avg_R f'(X'X)^-1 f = tr((X'X)^-1 M_R)`` with the
      region moment matrix ``M_R[i][j] = prod_f E[x_f^(a_if + a_jf)]`` under
      the product-uniform measure. No sampling. No closed-form I-optimal design
      exists for a general model, so no I-EFFICIENCY RATIO is reported --
      ``i_average_spv`` is the criterion (smaller is better) for comparing
      designs of one model.
    * **G** = ``p / max_R SPV`` (Atkinson et al. §11.4). ``max SPV >= p`` for
      any design whose points lie in R (the n leverages sum to p), so
      ``G <= 1``. When every term has degree <= 1 in each factor (first order
      + 2fi), SPV is a convex quadratic in each coordinate with the others
      fixed, so its max over the cube is at a VERTEX: enumerating the 2^k
      vertices is exact (``g_exact``). With squared terms it is not; the max
      is then taken over the 5-level grid ``{-1, -.5, 0, .5, 1}^k`` (or the
      3-level lattice when that exceeds the budget; past the budget over a
      SEEDED sample, ``g_seed``), polished by coordinate ascent from its 4
      best points. That is a max over a subset, so ``g_efficiency`` is then an
      UPPER bound, recorded as ``g_exact: false`` with the evaluation set.

    ``None`` for a model whose terms are not products of the listed factors
    (multi-level categorical contrasts: the region is not a cube; declined).
    """
    ids = list(factor_ids)
    p = len(terms)
    if p == 0 or n <= 0:
        return None
    pw = _term_powers(terms)
    if any(f not in ids for d in pw for f in d):
        return None
    disc = set(discrete)
    # I: exact, tr(inv M_R).
    def m_ij(i, j):
        v = 1.0
        for f in set(pw[i]) | set(pw[j]):
            v *= _moment(pw[i].get(f, 0) + pw[j].get(f, 0), f in disc)
            if v == 0.0:
                return 0.0
        return v
    mr = [[m_ij(i, j) for j in range(p)] for i in range(p)]
    avg = sum(inv[i][j] * mr[j][i] for i in range(p) for j in range(p))
    # G: max SPV over an evaluation set.
    k = len(ids)
    second = any(a >= 2 for d in pw for a in d.values())
    cost = max(1, p * p)
    cap = max(1, _G_BUDGET // cost)

    def axis(f, lv):
        return (-1.0, 1.0) if f in disc else lv
    basis = None
    pts = None
    if not second:
        if 2 ** k <= cap:
            pts = itertools.product(*[(-1.0, 1.0)] * k)
            basis, size = "vertices", 2 ** k
    else:
        for name, lv in (("grid_5", (-1.0, -0.5, 0.0, 0.5, 1.0)),
                         ("lattice_3", (-1.0, 0.0, 1.0))):
            size = math.prod(len(axis(f, lv)) for f in ids)
            if size <= cap:
                pts = itertools.product(*[axis(f, lv) for f in ids])
                basis = name
                break
    if pts is None:
        rng = random.Random(f"g_efficiency:{seed}")
        size = min(cap, _G_SAMPLE)
        # First order + 2fi: the max is at a vertex, so sample vertices only.
        nv = size if not second else size // 2
        verts = [tuple(rng.choice((-1.0, 1.0)) for _ in ids) for _ in range(nv)]
        unif = [tuple(rng.choice((-1.0, 1.0)) if f in disc else rng.uniform(-1.0, 1.0)
                      for f in ids) for _ in range(size - nv)]
        pts = verts + unif
        basis = "seeded_sample"
    idx = {f: i for i, f in enumerate(ids)}

    def spv(x):
        fx = [math.prod(x[idx[f]] for f in t) for t in terms]
        return sum(fx[i] * sum(inv[i][j] * fx[j] for j in range(p)) for i in range(p))
    scored = sorted(((spv(x), tuple(x)) for x in pts), reverse=True)
    best = scored[0][0] if scored else 0.0
    if second and scored:
        # Coordinate ascent from the 4 best evaluated points: each coordinate
        # (numeric only) over a 41-point line in [-1, 1], 3 sweeps. Raises the
        # max found; still a subset max, so G stays an upper bound.
        line = [-1.0 + i / 20.0 for i in range(41)]
        for _v, x0 in scored[:4]:
            x = list(x0)
            for _sweep in range(3):
                for f in ids:
                    if f in disc:
                        continue
                    j = idx[f]
                    x[j] = max(line, key=lambda u: spv(x[:j] + [u] + x[j + 1:]))
            best = max(best, spv(x))
        basis = basis + "+coordinate_ascent"
    g_exact = basis == "vertices"
    out = {
        "i_average_variance": round(avg, 6),
        "i_average_spv": round(n * avg, 6),
        "i_method": "exact_region_moments",
        "region": {f: ("{-1,+1}" if f in disc else "[-1,1]") for f in ids},
        "g_max_spv": round(n * best, 6),
        "g_efficiency": round(p / (n * best), 6) if best > 0 else None,
        "g_exact": g_exact,
        "g_evaluated": basis, "g_points": size,
    }
    if basis == "seeded_sample":
        out["g_seed"] = seed
    if not g_exact:
        out["g_note"] = ("max over a subset of the region: g_efficiency is an "
                         "upper bound")
    return out


def design_efficiency(cols, labels, *, terms=None, factor_ids=None,
                      discrete=(), seed: int = 0) -> dict | None:
    """D-efficiency and centred VIFs of the model matrix ``cols`` (intercept
    first), and -- given ``terms``/``factor_ids`` -- the G- and I-criteria of
    ``prediction_variance`` from the same exact inverse. ``None`` when ``X'X``
    is singular (nothing is estimable to rate)."""
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
    out = {"d_efficiency": round(d_eff, 6), "n": n, "p": p,
           "max_vif": max((v for v in vif.values() if v is not None), default=None),
           "vif": vif}
    if terms is not None and factor_ids is not None:
        pv = prediction_variance(inv, terms, factor_ids, n, discrete=discrete,
                                 seed=seed)
        if pv is None:
            out["g_i_declined"] = "categorical_contrasts_region_not_a_cube"
        else:
            out.update(pv)
    return out


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
    # V from the rows ACTUALLY FITTED (#321 P4 item 2; WP-B limits 9, 11).
    # A fit that carries its exact covariance (every second-order, blocked or
    # mixed fit) supplies (X'X)^-1 over its own rows -- the leading block of
    # the inverse over model + nuisance columns (block term, centre
    # indicators), which is the marginal covariance a validation point (at 0
    # on every nuisance column) needs. Otherwise ``cols`` must be the fitted
    # rows' model matrix (``fit_matrix``).
    if getattr(fit, "covariance", None) is not None and getattr(fit, "term_terms", ()):
        inv = [list(r) for r in fit.covariance]
        terms = list(fit.term_terms)
        nuisance = ()
        v_source = "fit_covariance"
    else:
        allc = list(cols) + [list(c) for c in nuisance]
        try:
            inv = _invert(_xtx(allc))
        except ValueError:
            return {**base, "rejected": None, "reason": "singular_model"}
        v_source = "fitted_rows"
    from orchestrator.optimize.decide import predict

    def row(coded):
        return ([1.0] + [math.prod(float(coded[t]) for t in ts) for ts in terms[1:]]
                + [0.0] * len(nuisance))

    xs = [row(c) for c, _y in points]
    p = len(inv)
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
            "bonferroni_t": tcrit, "points": per, "v_from": v_source}


def fit_matrix(fit, design, factor_ids) -> list[list[float]]:
    """The model matrix ``fit`` SOLVED, rebuilt from its own terms on
    ``design``'s points (the rows that fit was fitted on)."""
    ids = list(factor_ids)
    idx = {f: i for i, f in enumerate(ids)}
    terms = [()] + [e.terms for e in list(fit.effects) + list(fit.quadratic)]
    return [[math.prod(float(pt.coded[idx[t]]) for t in ts) for pt in design.points]
            for ts in terms], terms


#: #321 P4 item 2: the registered adequacy family -- Holm (1979) across every
#: adequacy TEST of a fitting stage (lack of fit and the validation check, for
#: the primary and every objective model), so Pr(a true model is declared
#: inadequate) <= ADEQUACY_ALPHA. Vetoes (an exact rejection against zero pure
#: error, an objective model that could not be estimated) are not tests: they
#: reject outright.
ADEQUACY_ALPHA = 0.05
ADEQUACY_METHOD = "holm"


def adequacy_family(tests, *, alpha: float = ADEQUACY_ALPHA,
                    method: str = ADEQUACY_METHOD) -> dict:
    """``tests``: ``[(name, p)]``; ``p is None`` = not computed (outside the
    family). Returns ``{method, alpha, family_size, tests: [{name, p,
    p_adjusted, rejected}], rejected: [names]}``."""
    from orchestrator.optimize.effects import holm

    live = [(n, float(p)) for n, p in tests if p is not None]
    m = len(live)
    if method == "holm":
        rej = holm([p for _n, p in live], alpha)
    elif method == "per_test":
        rej = [p < alpha for _n, p in live]
    else:
        raise ValueError(f"unknown adequacy multiplicity method {method!r}")
    order = sorted(range(m), key=lambda i: live[i][1])
    adj = [0.0] * m
    run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * live[i][1]))
        adj[i] = run if method == "holm" else live[i][1]
    rows = [{"name": n, "p": p, "p_adjusted": a, "rejected": bool(x)}
            for (n, p), a, x in zip(live, adj, rej)]
    return {"method": method, "alpha": alpha, "family_size": m,
            "m_declared": len(list(tests)), "tests": rows,
            "rejected": [r["name"] for r in rows if r["rejected"]]}


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
