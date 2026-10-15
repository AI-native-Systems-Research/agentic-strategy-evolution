"""Multi-objective estimation: predicted front, measured front, preference, HV.

Spec ``docs/superpowers/specs/2026-10-15-pareto-front-design.md``. Everything
here is PURE arithmetic over numbers the caller already holds (fitted models,
measured means, pooled variances); no file I/O, no model call. The stage runner
(``stage_runner``) gathers the inputs and writes the artifacts.

Conventions used throughout
---------------------------
* Every objective carries a direction. ``sign(direction)`` turns a raw value
  into a "larger is better" value, so all dominance arithmetic is written once,
  for maximisation.
* ``eps[metric]`` is that objective's ABSOLUTE indifference width (already
  resolved from ``{abs}`` / ``{pct}``). A difference below it is not dominance.
* NORMALISED coordinates: ``z_k = sign_k * (value_k - worst_k) / range_k`` over
  the measured admissible configurations, so ``z`` lies in [0, 1] and 1 is the
  best measured value of that objective. Ranges of zero are replaced by the
  objective's epsilon (a constant objective then contributes nothing).

Decisions (recorded in the spec's "Decisions" section)
------------------------------------------------------
* "Within epsilon of the front" is the standard ADDITIVE epsilon-approximate
  Pareto optimality: ``c`` is within epsilon iff no configuration ``z`` beats
  it by at least ``eps_k`` on EVERY objective. The confident claim for a
  measured point is the mirror image: for every rival ``d`` some objective's
  one-sided UPPER bound on ``d - c`` is below ``eps_k``.
* Variances for measured comparisons are the POOLED within-configuration
  variance per objective (one-way ANOVA mean square over every configuration
  with >= 2 complete rows: screen centre points, refine centre points, confirm
  replicates). With the default 3 replicates a per-pair Welch t has 2-4 df and
  a Bonferroni quantile above 10, which could never claim anything; the pooled
  estimate is the same pure-error variance the fits and constraint models
  already rest on (homoscedasticity is the registered response-class
  assumption). ``method`` strings say so.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from scipy.stats import t as student_t

#: Lack-of-fit p below which an objective model is recorded as REJECTED (its
#: predictions then serve only as ranking hints). Same threshold as the primary
#: model's ``model_adequate`` and the constraint models.
LACK_OF_FIT_ALPHA = 0.05

#: Stored ``possibly_nondominated`` predicted-front entries beyond the point
#: front. The full possibly-nondominated set can be most of a 9^k candidate
#: space when the models are uncertain; the artifact keeps the ones closest to
#: the point front (they are the useful gap-fill candidates) and the count.
MAX_POSSIBLE_STORED = 64

#: Monte Carlo sample count for hypervolume at K > 3 (fixed seed below).
HV_MC_SAMPLES = 200_000
HV_MC_SEED = 20261015


def sign(direction: str) -> float:
    return -1.0 if direction == "minimize" else 1.0


def tcrit(alpha: float, df: float) -> float:
    """One-sided Student quantile at ``1 - alpha``."""
    return float(student_t.ppf(1.0 - float(alpha), max(float(df), 1.0)))


# ── objectives and epsilons ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Objective:
    metric: str
    direction: str
    epsilon: dict  # the declared spec ({abs} | {pct})


def policy_objectives(pol: dict | None) -> list[Objective]:
    """The objectives a compiled policy registered; ``[]`` for single-objective."""
    objs = ((pol or {}).get("objective") or {}).get("objectives") or []
    return [Objective(o["metric"], o.get("direction", "maximize"),
                      dict(o.get("epsilon") or {"pct": 2.0})) for o in objs]


def resolve_eps(objectives, reference: dict) -> dict:
    """Absolute epsilon per objective. ``pct`` is taken of ``|reference[m]|``.

    ``reference`` is the best measured value of each objective (the "of the
    best" the single-objective path uses). A missing/zero reference with a pct
    spec gives ``None`` -- unknown, never zero.
    """
    out: dict = {}
    for o in objectives:
        spec = o.epsilon or {"pct": 2.0}
        if "abs" in spec:
            out[o.metric] = float(spec["abs"])
            continue
        ref = reference.get(o.metric)
        if ref is None or not math.isfinite(float(ref)) or float(ref) == 0.0:
            out[o.metric] = None
        else:
            out[o.metric] = abs(float(ref)) * float(spec.get("pct", 2.0)) / 100.0
    return out


# ── normalisation ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Frame:
    """The normalisation frame: per-objective worst value and range."""

    objectives: tuple
    worst: dict
    range: dict

    def z(self, values: dict) -> list[float]:
        out = []
        for o in self.objectives:
            v = values.get(o.metric)
            if v is None or not math.isfinite(float(v)):
                out.append(float("nan"))
                continue
            out.append(sign(o.direction) * (float(v) - self.worst[o.metric])
                       / self.range[o.metric])
        return out

    def eps_z(self, eps: dict) -> list[float]:
        return [(eps.get(o.metric) or 0.0) / self.range[o.metric]
                for o in self.objectives]

    def as_dict(self) -> dict:
        return {"worst": dict(self.worst), "range": dict(self.range)}


def make_frame(objectives, value_rows, eps: dict) -> Frame:
    """Frame over ``value_rows`` (dicts metric -> value)."""
    worst, rng = {}, {}
    for o in objectives:
        s = sign(o.direction)
        vals = [float(r[o.metric]) for r in value_rows
                if r.get(o.metric) is not None and math.isfinite(float(r[o.metric]))]
        if not vals:
            worst[o.metric], rng[o.metric] = 0.0, 1.0
            continue
        lo = min(s * v for v in vals)
        hi = max(s * v for v in vals)
        worst[o.metric] = s * lo
        r = hi - lo
        e = eps.get(o.metric) or 0.0
        if not r > 0.0:
            r = e if e > 0 else (abs(hi) or 1.0)
        rng[o.metric] = r
    return Frame(tuple(objectives), worst, rng)


# ── point-estimate dominance ─────────────────────────────────────────────────


def eps_dominates(a: list[float], b: list[float], eps: list[float]) -> bool:
    """``a`` dominates ``b`` honouring indifference (larger is better).

    No worse anywhere and better by MORE than epsilon somewhere: a difference
    below epsilon is not dominance.
    """
    return (all(x >= y for x, y in zip(a, b))
            and any(x - y > e for x, y, e in zip(a, b, eps)))


def strictly_dominates(a, b) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def nondominated_indices(vectors, eps=None) -> list[int]:
    """Indices of vectors no other vector dominates (``eps`` = indifference)."""
    import numpy as np

    if not vectors:
        return []
    v = np.asarray(vectors, dtype=float)
    e = np.zeros(v.shape[1]) if eps is None else np.asarray(eps, dtype=float)
    keep = []
    for i in range(len(v)):
        ge = np.all(v >= v[i], axis=1)
        gt = np.any(v - v[i] > e, axis=1) if eps is not None else np.any(v > v[i], axis=1)
        dom = ge & gt
        dom[i] = False
        if not dom.any():
            keep.append(i)
    return keep


# ── preference ───────────────────────────────────────────────────────────────


def _tie_key(levels: dict):
    return tuple((k, isinstance(v, str), 0.0 if isinstance(v, str) else float(v), str(v))
                 for k, v in sorted((levels or {}).items()))


@dataclass(frozen=True)
class Preference:
    method: str = "knee"
    weights: dict = field(default_factory=dict)
    order: tuple = ()


def parse_preference(spec: dict | None, objectives) -> Preference:
    spec = spec or {}
    method = spec.get("method") or "knee"
    return Preference(method=method, weights=dict(spec.get("weights") or {}),
                      order=tuple(spec.get("order") or [o.metric for o in objectives]))


def scalar_direction(pref: Preference, objectives, zs: list[list[float]],
                     chosen: int, ref_z: list[float] | None = None) -> list[float]:
    """The linear scalarisation (in normalised units) whose regret certifies
    ``chosen`` under ``pref``.

    * weights: ``w_k``;
    * knee, K = 2: the unit normal of the line through the two extremes (the
      knee maximises the signed distance from that line, which is linear in the
      point once the extremes are fixed);
    * knee, K > 2: the unit vector of ``chosen``'s BINDING objective (the one
      attaining its minimum improvement): ``min_k z_k(r) - min_k z_k(c) <=
      z_k*(r) - z_k*(c)``, so a bound on that one coordinate bounds the regret;
    * lexicographic: the unit vector of ``order[0]``.
    """
    metrics = [o.metric for o in objectives]
    K = len(metrics)
    if pref.method == "weights":
        return [float(pref.weights.get(m, 0.0)) for m in metrics]
    if pref.method == "lexicographic":
        j = metrics.index(pref.order[0]) if pref.order and pref.order[0] in metrics else 0
        return [1.0 if i == j else 0.0 for i in range(K)]
    if K == 2:
        a, b = _extremes(zs)
        return _knee_normal(zs[a], zs[b])
    ref = ref_z or [0.0] * K
    imp = [zs[chosen][k] - ref[k] for k in range(K)]
    j = min(range(K), key=lambda k: imp[k])
    return [1.0 if i == j else 0.0 for i in range(K)]


def scalar_epsilon(pref: Preference, objectives, eps_z: list[float]) -> float:
    """ε_scalar: weighted sum of normalised ε_k (weights), the order[0] one
    (lexicographic), or the minimum normalised ε (knee) -- spec step 7."""
    metrics = [o.metric for o in objectives]
    if pref.method == "weights":
        return sum(float(pref.weights.get(m, 0.0)) * e for m, e in zip(metrics, eps_z))
    if pref.method == "lexicographic":
        j = metrics.index(pref.order[0]) if pref.order and pref.order[0] in metrics else 0
        return eps_z[j]
    return min(eps_z) if eps_z else 0.0


def _extremes(zs) -> tuple[int, int]:
    a = max(range(len(zs)), key=lambda i: (zs[i][0], zs[i][1]))
    b = max(range(len(zs)), key=lambda i: (zs[i][1], zs[i][0]))
    return a, b


def _knee_normal(pa, pb) -> list[float]:
    """Unit normal of the line through ``pa`` and ``pb``, pointing toward (1, 1)."""
    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    n = [dy, -dx]
    norm = math.hypot(*n)
    if norm == 0.0:
        return [math.sqrt(0.5), math.sqrt(0.5)]
    n = [n[0] / norm, n[1] / norm]
    if n[0] + n[1] < 0:
        n = [-n[0], -n[1]]
    return n


def preferred_index(pref: Preference, objectives, zs: list[list[float]],
                    levels: list[dict], eps_z: list[float],
                    ref_z: list[float] | None = None) -> int | None:
    """Index of the preferred point among ``zs`` (normalised, larger better).

    Ties are broken by the declared order of the levels (``_tie_key``) so the
    same evidence always yields the same choice.
    """
    idx = [i for i, z in enumerate(zs) if all(math.isfinite(x) for x in z)]
    if not idx:
        return None
    K = len(objectives)
    metrics = [o.metric for o in objectives]

    def pick(score):
        return max(idx, key=lambda i: (round(score(i), 12), _neg_key(levels[i])))

    if pref.method == "weights":
        w = [float(pref.weights.get(m, 0.0)) for m in metrics]
        return pick(lambda i: sum(a * b for a, b in zip(w, zs[i])))
    if pref.method == "lexicographic":
        order = [metrics.index(m) for m in pref.order if m in metrics] or list(range(K))
        cand = list(idx)
        for k in order:
            best = max(zs[i][k] for i in cand)
            cand = [i for i in cand if best - zs[i][k] <= eps_z[k] + 1e-12]
        best_k = order[0]
        return max(cand, key=lambda i: (zs[i][best_k], _neg_key(levels[i])))
    if K == 2:
        sub = [zs[i] for i in idx]
        a, b = _extremes(sub)
        pa, pb = sub[a], sub[b]
        n = _knee_normal(pa, pb)
        return pick(lambda i: n[0] * (zs[i][0] - pa[0]) + n[1] * (zs[i][1] - pa[1]))
    ref = ref_z or [0.0] * K
    return pick(lambda i: min(zs[i][k] - ref[k] for k in range(K)))


class _neg_key:
    """Reverse ordering wrapper so ``max`` prefers the FIRST level in tie order."""

    __slots__ = ("k",)

    def __init__(self, levels):
        self.k = _tie_key(levels)

    def __lt__(self, other):
        return self.k > other.k

    def __eq__(self, other):
        return self.k == other.k


# ── hypervolume ──────────────────────────────────────────────────────────────


def _hv2(points) -> float:
    pts = sorted(points, key=lambda p: -p[0])
    hv, best_y = 0.0, 0.0
    for x, y in pts:
        if y > best_y:
            hv += x * (y - best_y)
            best_y = y
    return hv


def hypervolume(points, ref) -> tuple[float, str]:
    """Hypervolume dominated by ``points`` above ``ref`` (maximisation).

    Coordinates are shifted by ``ref`` and clipped at 0, so a point that does
    not beat the reference on some objective contributes nothing. K = 2 exact
    (sweep), K = 3 exact (slicing on the third objective), K > 3 Monte Carlo
    with a fixed seed and ``HV_MC_SAMPLES`` samples over the bounding box.
    Returns ``(value, method)``.
    """
    pts = [[max(0.0, float(p[k]) - float(ref[k])) for k in range(len(ref))]
           for p in points if all(math.isfinite(float(x)) for x in p)]
    pts = [p for p in pts if all(x > 0.0 for x in p)]
    K = len(ref)
    if not pts:
        return 0.0, "exact" if K <= 3 else "monte_carlo"
    if K == 1:
        return max(p[0] for p in pts), "exact"
    if K == 2:
        return _hv2([(p[0], p[1]) for p in pts]), "exact"
    if K == 3:
        zs = sorted({p[2] for p in pts}, reverse=True)
        hv = 0.0
        for i, z in enumerate(zs):
            nxt = zs[i + 1] if i + 1 < len(zs) else 0.0
            hv += _hv2([(p[0], p[1]) for p in pts if p[2] >= z]) * (z - nxt)
        return hv, "exact_slicing"
    rng = random.Random(HV_MC_SEED)
    box = [max(p[k] for p in pts) for k in range(K)]
    vol = math.prod(box)
    hit = 0
    for _ in range(HV_MC_SAMPLES):
        s = [rng.random() * b for b in box]
        if any(all(p[k] >= s[k] for k in range(K)) for p in pts):
            hit += 1
    return vol * hit / HV_MC_SAMPLES, f"monte_carlo(n={HV_MC_SAMPLES},seed={HV_MC_SEED})"


# ── gaps ─────────────────────────────────────────────────────────────────────


def front_gaps(zs: list[list[float]]) -> list[dict]:
    """Gaps between ADJACENT front points in normalised space, largest first.

    K = 2: adjacency along the front sorted by the first objective. K > 2: the
    edges of the Euclidean minimum spanning tree over the front (the natural
    generalisation of "adjacent" when there is no total order). Size is the
    L-infinity distance, the unit the ``2 x max_k eps_k / range_k`` threshold
    is in. ``between`` holds indices into ``zs``.
    """
    n = len(zs)
    if n < 2:
        return []
    K = len(zs[0])

    def linf(i, j):
        return max(abs(zs[i][k] - zs[j][k]) for k in range(K))

    edges = []
    if K == 2:
        order = sorted(range(n), key=lambda i: (zs[i][0], -zs[i][1]))
        edges = [(order[t], order[t + 1]) for t in range(n - 1)]
    else:
        in_tree, rest = {0}, set(range(1, n))
        while rest:
            i, j = min(((a, b) for a in in_tree for b in rest),
                       key=lambda e: math.dist(zs[e[0]], zs[e[1]]))
            edges.append((i, j))
            in_tree.add(j)
            rest.discard(j)
    out = [{"between": sorted([i, j]), "size": linf(i, j)} for i, j in edges]
    out.sort(key=lambda g: (-g["size"], g["between"]))
    return out


# ── predicted front ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PredictedPoint:
    levels: dict
    coded: dict
    predicted: dict
    se: dict
    status: str  # nondominated | possibly_nondominated

    def as_dict(self) -> dict:
        return {"levels": self.levels, "predicted": self.predicted,
                "se": self.se, "status": self.status}


def predicted_front(cands, models: dict, objectives, *, delta: float,
                    eps: dict | None = None) -> tuple[list[PredictedPoint], int]:
    """The predicted front over ``cands`` (``decide.Candidate`` list).

    ``models[metric]`` is an ``ObjectiveModel``. Each objective's prediction
    gets a one-sided bound at ``delta / K``. ``c`` is CONFIDENTLY DOMINATED
    when some ``d``'s pessimistic bound is at least ``c``'s optimistic bound on
    every objective and strictly better on one; an objective with no standard
    error (no pure error) makes every bound infinite, so nothing is confidently
    dominated through it. Returns ``(front, n_nondominated)`` where ``front``
    lists every point-nondominated candidate (``nondominated``) followed by up
    to ``MAX_POSSIBLE_STORED`` further ``possibly_nondominated`` ones, nearest
    to the point front first.
    """
    import numpy as np

    from orchestrator.optimize.constraint_models import predicted_with_se

    if not cands:
        return [], 0
    K = len(objectives)
    preds, ses = [], []
    for c in cands:
        p, s = {}, {}
        for o in objectives:
            m = models.get(o.metric)
            if m is None or m.fit is None:
                p[o.metric], s[o.metric] = float("nan"), None
                continue
            y, se = predicted_with_se(m.fit, c.coded)
            p[o.metric] = y
            s[o.metric] = se if m.has_se else None
        preds.append(p)
        ses.append(s)
    signs = np.array([sign(o.direction) for o in objectives])
    Y = np.array([[pr[o.metric] for o in objectives] for pr in preds], dtype=float) * signs
    T = np.array([tcrit(delta / K, models[o.metric].fit.pure_error_df)
                  if models.get(o.metric) is not None and models[o.metric].has_se
                  else np.inf for o in objectives])
    S = np.array([[s[o.metric] if s[o.metric] is not None else np.inf
                   for o in objectives] for s in ses], dtype=float)
    with np.errstate(invalid="ignore"):
        half = np.where(np.isinf(T) | np.isinf(S), np.inf, S * T)
    pess = Y - half
    opt = Y + half
    finite = np.all(np.isfinite(Y), axis=1)
    n = len(cands)
    conf_dom = np.zeros(n, dtype=bool)
    for i in range(n):
        if not finite[i]:
            conf_dom[i] = True
            continue
        ge = np.all(pess >= opt[i], axis=1)
        gt = np.any(pess > opt[i], axis=1)
        d = ge & gt & finite
        d[i] = False
        conf_dom[i] = bool(d.any())
    Yf = [list(Y[i]) for i in range(n)]
    nd_local = nondominated_indices([Yf[i] for i in range(n) if finite[i]])
    finite_idx = [i for i in range(n) if finite[i]]
    nd = sorted(finite_idx[j] for j in nd_local)
    nd_set = set(nd)
    possible = [i for i in range(n) if not conf_dom[i] and i not in nd_set and finite[i]]
    if possible and nd:
        ndY = Y[nd]
        span = np.where(np.ptp(Y[finite], axis=0) > 0, np.ptp(Y[finite], axis=0), 1.0)

        def gap(i):
            # How far the point front is ahead of i (L-inf, normalised): the
            # smallest per-point max shortfall.
            return float(np.min(np.max((ndY - Y[i]) / span, axis=1)))

        possible.sort(key=lambda i: (gap(i), i))
    possible = possible[:MAX_POSSIBLE_STORED]
    out = []
    for i in nd + possible:
        c = cands[i]
        out.append(PredictedPoint(
            levels=dict(c.levels), coded=dict(c.coded), predicted=preds[i],
            se=ses[i], status="nondominated" if i in nd_set else "possibly_nondominated"))
    return out, len(nd)


# ── measured front ───────────────────────────────────────────────────────────


@dataclass
class MeasuredPoint:
    levels: dict
    samples: dict  # metric -> list[float]
    source: str

    def n(self, metric: str) -> int:
        return len(self.samples.get(metric) or [])

    def mean(self, metric: str) -> float | None:
        v = self.samples.get(metric) or []
        return sum(v) / len(v) if v else None

    def means(self) -> dict:
        return {m: self.mean(m) for m in self.samples}


def pooled_variance(points, metric: str) -> tuple[float | None, int]:
    """One-way ANOVA within-configuration mean square and its df."""
    ss, df = 0.0, 0
    for p in points:
        v = p.samples.get(metric) or []
        if len(v) < 2:
            continue
        mu = sum(v) / len(v)
        ss += sum((x - mu) ** 2 for x in v)
        df += len(v) - 1
    if df <= 0:
        return None, 0
    return ss / df, df


def _upper(objective, d: MeasuredPoint, c: MeasuredPoint, pooled: dict,
           alpha: float) -> float | None:
    """One-sided upper bound on ``sign * (mu_d - mu_c)`` at level ``alpha``."""
    m = objective.metric
    md, mc = d.mean(m), c.mean(m)
    var, df = pooled.get(m, (None, 0))
    if md is None or mc is None or var is None or df <= 0:
        return None
    est = sign(objective.direction) * (md - mc)
    se = math.sqrt(var * (1.0 / d.n(m) + 1.0 / c.n(m)))
    return est + tcrit(alpha, df) * se


@dataclass
class FrontEntry:
    index: int  # into the measured point list
    status: str
    dominated_by: list


def measured_front(points: list[MeasuredPoint], objectives, eps: dict, *,
                   delta: float, pooled: dict,
                   predicted: list[PredictedPoint] | None = None) -> list[FrontEntry]:
    """The measured front and each member's status (spec step 5).

    ``points`` are the measured admissible configurations (means over their
    complete rows). Membership: not eps-dominated in point estimate by any
    other measured point. Status ``confidently_nondominated`` iff, for EVERY
    other measured point ``d``, some objective's one-sided upper bound on
    ``d - c`` is below that objective's epsilon (so ``d`` is confidently NOT
    ahead of ``c`` by epsilon on every objective) -- at level
    ``delta / ((N - 1) * K)`` (Bonferroni over rivals and objectives) -- AND no
    ``predicted`` candidate's point prediction beats ``c``'s measured mean by at
    least epsilon on every objective. ``dominated_by`` names each rival that
    could not be ruled out.
    """
    K = len(objectives)
    N = len(points)
    metrics = [o.metric for o in objectives]
    vec = [[sign(o.direction) * (p.mean(o.metric) if p.mean(o.metric) is not None
                                 else float("nan")) for o in objectives] for p in points]
    e = [eps.get(m) or 0.0 for m in metrics]
    usable = [i for i in range(N) if all(math.isfinite(x) for x in vec[i])]
    members = [i for i in usable
               if not any(j != i and eps_dominates(vec[j], vec[i], e) for j in usable)]
    alpha = float(delta) / max(1, (len(usable) - 1) * K)
    out = []
    for i in members:
        unresolved = []
        for j in usable:
            if j == i:
                continue
            resolved = False
            for o, ek in zip(objectives, e):
                u = _upper(o, points[j], points[i], pooled, alpha)
                if u is not None and u < ek:
                    resolved = True
                    break
            if not resolved:
                unresolved.append({"levels": dict(points[j].levels), "kind": "measured"})
        for pp in predicted or ():
            if pp.levels == points[i].levels:
                # The model's prediction AT c is not a rival of c's own
                # measurement; the measurement is the better evidence there.
                continue
            if all(isinstance(pp.predicted.get(m), (int, float))
                   and math.isfinite(pp.predicted[m]) for m in metrics) and all(
                    sign(o.direction) * (pp.predicted[o.metric] - points[i].mean(o.metric))
                    >= ek and ek > 0 for o, ek in zip(objectives, e)):
                unresolved.append({"levels": dict(pp.levels), "kind": "predicted"})
                break
        out.append(FrontEntry(i, "possibly_dominated" if unresolved
                              else "confidently_nondominated", unresolved))
    return out


def scalar_regret(objectives, points: list[MeasuredPoint], chosen: int,
                  rivals: list[int], a: list[float], frame: Frame, pooled: dict, *,
                  delta: float) -> tuple[float | None, str]:
    """One-sided ``1 - delta`` bound on ``max_r g(r) - g(chosen)``, Bonferroni
    over the rivals, where ``g`` is the linear scalarisation ``a`` in
    normalised units. ``None`` when any needed variance is unknown."""
    others = [r for r in rivals if r != chosen]
    if not others:
        return 0.0, "trivial: no rival"
    c = points[chosen]
    best = 0.0
    dfs = [pooled.get(o.metric, (None, 0))[1] for o, ak in zip(objectives, a) if ak]
    if any(d <= 0 for d in dfs):
        return None, "no pooled pure-error variance for a weighted objective"
    df = min(dfs) if dfs else 1
    t = tcrit(float(delta) / len(others), df)
    for r in others:
        z = points[r]
        est, var = 0.0, 0.0
        for o, ak in zip(objectives, a):
            if not ak:
                continue
            m = o.metric
            v, _ = pooled[m]
            if z.mean(m) is None or c.mean(m) is None:
                return None, f"rival lacks a measurement of {m}"
            rg = frame.range[m]
            est += ak * sign(o.direction) * (z.mean(m) - c.mean(m)) / rg
            var += ak * ak * v * (1.0 / z.n(m) + 1.0 / c.n(m)) / (rg * rg)
        best = max(best, est + t * math.sqrt(var))
    return best, (f"bonferroni_one_sided_t_pooled_pure_error over {len(others)} "
                  f"rival(s), df={df}, t={t:.3f}")


def min_improvement_regret(objectives, points: list[MeasuredPoint], chosen: int,
                           rivals: list[int], frame: Frame, ref_z: list[float],
                           pooled: dict, *, delta: float) -> tuple[float | None, str]:
    """Regret bound for the K > 2 knee, ``g(p) = min_k (z_k(p) - ref_k)``.

    ``g`` is not linear, so the bound is built from simultaneous one-sided
    bounds on each normalised MEAN rather than on differences: with
    probability ``1 - delta`` (Bonferroni over every rival-objective upper bound
    and the chosen point's K lower bounds), ``g(r) <= min_k U_k(r)`` and
    ``g(c) >= min_k L_k(c)``, so ``max_r g(r) - g(c) <= max_r min_k U_k(r) -
    min_k L_k(c)``. Bounding one fixed coordinate of the difference instead is
    also valid but loose by the whole spread of the other objectives.
    """
    others = [r for r in rivals if r != chosen]
    if not others:
        return 0.0, "trivial: no rival"
    K = len(objectives)
    m_count = (len(others) + 1) * K
    dfs = [pooled.get(o.metric, (None, 0))[1] for o in objectives]
    if any(d <= 0 for d in dfs):
        return None, "no pooled pure-error variance for an objective"
    t = tcrit(float(delta) / m_count, min(dfs))

    def bound(p: MeasuredPoint, k: int, side: float) -> float:
        o = objectives[k]
        v, _ = pooled[o.metric]
        rg = frame.range[o.metric]
        z = sign(o.direction) * (p.mean(o.metric) - frame.worst[o.metric]) / rg
        return z - ref_z[k] + side * t * math.sqrt(v / p.n(o.metric)) / rg

    g_c = min(bound(points[chosen], k, -1.0) for k in range(K))
    worst = max(min(bound(points[r], k, +1.0) for k in range(K)) for r in others)
    return max(0.0, worst - g_c), (
        f"simultaneous one-sided t on normalised means, pooled pure error, "
        f"Bonferroni over {m_count} bounds, df={min(dfs)}, t={t:.3f}")


def spread_order(pool_z: list[list[float]], seated_z: list[list[float]]) -> list[int]:
    """Greedy maximin order of ``pool_z``: each next pick maximises its minimum
    Euclidean distance (normalised) to everything already seated."""
    chosen: list[int] = []
    seated = [list(s) for s in seated_z]
    remaining = [i for i, z in enumerate(pool_z) if all(math.isfinite(x) for x in z)]
    while remaining:
        if seated:
            i = max(remaining, key=lambda r: (min(math.dist(pool_z[r], s) for s in seated), -r))
        else:
            i = remaining[0]
        chosen.append(i)
        seated.append(pool_z[i])
        remaining.remove(i)
    return chosen


def in_gap(z: list[float], za: list[float], zb: list[float], tol: float = 1e-9) -> bool:
    """Is ``z`` inside the bounding box spanned by front points ``za``/``zb``
    and not dominated by either (it would then fill nothing)?"""
    for k in range(len(z)):
        lo, hi = min(za[k], zb[k]), max(za[k], zb[k])
        if not (lo - tol <= z[k] <= hi + tol):
            return False
    return not strictly_dominates(za, z) and not strictly_dominates(zb, z)

