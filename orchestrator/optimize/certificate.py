"""Residual-regret certificates: how much better could any challenger still be?

Spec §3.5, paper eq. (2). ``R_delta(x) = max_z U_delta(z, x)`` over every valid
configuration ``z``, where ``U_delta`` is a SIMULTANEOUS one-sided upper bound
on the true gap ``f(z) - f(x)``. Two flavours: MODEL-based (screen/refine —
depends on the registered response class; exact for orthogonal main/2fi
columns, optimistic for quadratic terms per ``effects.py``) and TERMINAL
(``terminal_regret_bound`` — model free, from fresh replicates of the
finalists). They rest on different assumptions and are reported separately,
never collapsed: spec §3.5 gives ``Pr(wrong global decision) <= delta_s +
delta_t``, which is only meaningful while the two numbers stay apart.

Why Bonferroni, and why the word "simultaneous" is load-bearing
---------------------------------------------------------------
For ONE challenger ``z``, ``est_z +/- t_{1-delta,df} * se(est_z)`` is a
one-sided interval that covers ``f(z) - f(x)`` with probability ``1 - delta``.
Reporting ``max_z`` of those individual bounds would NOT be a bound at level
delta: the max over M random quantities fails as soon as ANY ONE of them
fails, so the failure probability of the maximum is up to M*delta, not delta.
That is precisely the multiple-comparisons trap, and a certificate that fell
into it would be advertising 95% while delivering 5% per challenger over
hundreds of challengers — i.e. essentially no guarantee at all.

The union bound fixes it: if each of M individual bounds is built at level
``delta / M``, then

    Pr(any one fails) <= sum_z Pr(bound_z fails) = M * (delta / M) = delta,

so with probability at least ``1 - delta`` EVERY challenger's bound holds at
once. Only then is ``max_z U_delta(z, x)`` itself a valid upper bound on the
true optimality gap ``max_z (f(z) - f(x))`` — because the true maximiser is
one of the M challengers, and on the (probability >= 1 - delta) event where all
bounds hold, its own bound holds, hence the max of the bounds dominates it.
Bonferroni is conservative (the challengers' estimates are strongly
correlated — they share the same fitted coefficients — so the true
simultaneous quantile is smaller than ``t_{1-delta/M}``), which errs on the
safe side for a certificate and is stated honestly in the method string.

Per-challenger variance
-----------------------
Under the registered linear/quadratic response class, both predictions are
linear in the fitted coefficients, so the DIFFERENCE

    f_hat(z) - f_hat(x_hat) = sum_e beta_e * (col_e(z) - col_e(x_hat))

has variance ``sum_e Var(beta_e) * (col_e(z) - col_e(x_hat))^2`` when the
coefficients are uncorrelated — true for the main-effect and two-factor
interaction columns of every design this package builds (see ``effects.py``).
The intercept cancels in the difference, which is why its known-correlated
column never enters. Pure-quadratic columns on a central composite ARE
correlated, so their contribution is optimistic by the same factor
``effects.py`` documents; the model bound therefore carries the response-class
assumption, as spec §3.5 says it does.

No pure-error df (no replicated centre points, or a deterministic target
returning bit-identical centre values) means there is no variance estimate at
all, and an unknown is not a zero: ``value=None, method="none"``.

One arithmetic, two callers
---------------------------
``_challenger_bounds`` is the single place the per-challenger upper bound is
computed, for BOTH flavours; ``model_regret_bound`` and
``terminal_regret_bound`` differ only in how they supply the estimate and the
standard error for one challenger. It is exposed (module-private but stable)
so a test asserting the SIMULTANEITY property can drive the shipped code
rather than reimplementing the arithmetic locally. Task 8 shipped a
family-wise test that did reimplement it, which meant the test would have
passed with this module deleted — a test decoupled from its subject measures
nothing.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from statistics import mean, variance
from typing import Callable

from scipy.stats import f as fisher_f
from scipy.stats import t as student_t

from orchestrator.optimize.decide import Candidate, predict
from orchestrator.optimize.effects import Fit


@dataclass(frozen=True)
class RegretBound:
    """``R_delta(x_hat)`` plus the challenger that keeps it large.

    ``challenger`` is the ``z`` whose own bound is the LARGEST — the point the
    next experiment should be directed at (spec §3.6 rung 2), which is why it
    is carried alongside the number rather than recomputed later. It is named
    even when ``value`` has floored at 0.0 (every challenger's bound came out
    negative, i.e. the winner is clear): "which finalist is closest" is the
    useful fact either way, and only ``value`` is claimed to be a bound.
    ``None`` means there was no challenger at all — a single candidate, or no
    bound computable.

    At the terminal stage the challenger is a finalist KEY (``"f2"``) rather
    than a levels dict: ``confirmation.json`` already records every finalist's
    levels against its key, so carrying the dict again would give the same
    fact two representations that could drift apart.
    """

    value: float | None
    challenger: dict | str | None
    delta: float
    method: str
    detail: str
    #: Model flavour only, on request: the largest per-challenger bounds and
    #: the max over the rest (``model_bound_outside``). Not part of as_dict.
    profile: dict | None = None
    #: Model flavour only: which simultaneous critical value was used and the
    #: two it was chosen between (``simultaneous_critical``), plus, for a
    #: SEARCHED space, how the bound over the unevaluated candidates was got.
    critical: dict | None = None

    def as_dict(self) -> dict:
        """The JSON shape written into ``recommendation.json`` / ``report.json``."""
        out = {"value": self.value, "challenger": self.challenger,
               "delta": self.delta, "method": self.method, "detail": self.detail}
        if self.critical is not None:
            out["critical"] = dict(self.critical)
        return out


def simultaneous_critical(delta: float, m: int, q: int, df: float) -> dict:
    """The model family's critical value: ``min(Bonferroni, Scheffe)`` (#321 H3).

    Both constants give a one-sided bound ``est + c * se`` on every contrast
    ``d'beta`` of the family SIMULTANEOUSLY at level ``1 - delta``, under the
    registered response class with independent normal errors and the
    pure-error variance estimate on ``df`` degrees of freedom (independent of
    the coefficients: the fitted coefficients are functions of the design-point
    means, pure error of the within-point deviations).

    * Bonferroni over the ``m`` challengers: ``t_{1 - delta/m, df}``.
    * Scheffe (1953; the Working-Hotelling band is its regression case) over
      the q-dimensional space spanned by the differences ``x(z) - x(x_hat)``:
      ``sqrt(q F_{q, df, 1 - delta})``, valid for EVERY ``d`` in that space at
      once (two-sided, so each one-sided bound too) -- hence for any number of
      candidates, enumerated or not. The intercept cancels in a difference, so
      ``q`` is the number of non-intercept model terms (an upper bound on the
      span's dimension, which is conservative).

    Taking the smaller of two valid simultaneous constants is valid because the
    choice is a function of ``(delta, m, q, df)`` only: it is fixed before the
    response values are read (the family's event is then the chosen one's,
    whose probability is >= 1 - delta). ``m`` is the DECLARED candidate count
    (the product of the axes), not the count left after data-driven
    exclusions. Returns the record ``RegretBound.critical`` carries.
    """
    df = max(float(df), 1.0)
    m = max(1, int(m))
    q = max(1, int(q))
    c_b = float(student_t.ppf(1.0 - delta / m, df))
    c_s = math.sqrt(q * float(fisher_f.ppf(1.0 - delta, q, df)))
    used = "scheffe" if c_s < c_b else "bonferroni"
    return {"used": used, "value": min(c_b, c_s), "bonferroni": c_b,
            "scheffe": c_s, "m": m, "q": q, "df": df,
            "rule": "min(t_{1-delta/m,df}, sqrt(q F_{q,df,1-delta})), both "
                    "simultaneous at 1 - delta; chosen from (delta, m, q, df) "
                    "only, before the responses are read"}


def _challenger_bounds(
    challengers: list,
    contrast: Callable[[object], tuple[float, float, float]],
    *,
    delta: float,
    crit: float | None = None,
) -> dict:
    """Every challenger's one-sided upper bound on its true gain, at level
    ``delta / M`` (Bonferroni), keyed by the challenger itself.

    ``contrast(z)`` returns ``(estimate, standard_error, df)`` for that one
    challenger — the ONLY thing the model and terminal flavours disagree
    about. Everything the certificate's guarantee depends on lives here: the
    divisor ``M = len(challengers)``, so ``Pr(any bound fails) <= delta``, and
    the per-challenger quantile.

    Returned in ``challengers`` order, unkeyed by any dict, because a levels
    dict is unhashable. Callers take the max; a test asserting the
    family-wise property checks every entry.
    """
    m = len(challengers)
    out: dict = {}
    for i, z in enumerate(challengers):
        est, se, df = contrast(z)
        tcrit = (float(crit) if crit is not None
                 else float(student_t.ppf(1 - delta / m, max(float(df), 1.0))))
        out[i] = est + tcrit * se
    return out


def model_regret_bound(fit: Fit, cands: list[Candidate], xhat: Candidate, *,
                       delta: float, direction: str,
                       profile: int = 0,
                       m_declared: int | None = None) -> RegretBound:
    """``max_z U_delta(z, x_hat)`` under the fitted response model.

    ``cands`` should be the WHOLE valid candidate space (``decide.ranked(...,
    top=None)``), not a shortlist: the max in eq. (2) is over ``X_valid``, and
    a bound computed over the top five would be silent about a sixth candidate
    whose interval still reaches above ``x_hat``. M (the Bonferroni divisor) is
    the number of challengers actually considered, so the reported level is
    honest about the set it was taken over either way.

    The returned value is never negative: ``x_hat`` is the argmax of the
    fitted response, so ``est <= 0`` for every challenger, and the running max
    starts at ``0.0`` — which is the correct floor, since the gap to the true
    optimum cannot be below zero.

    ``profile > 0`` also records the ``profile`` largest per-challenger bounds
    (levels and value) and the max over the rest, so a later stage can take
    the max over the challengers OUTSIDE a shortlist (``model_bound_outside``)
    without the fit.

    THE CRITICAL VALUE (#321 H3) is ``simultaneous_critical``: the smaller of
    Bonferroni over ``m_declared`` challengers and Scheffe over the model's
    ``q`` non-intercept terms. ``m_declared`` is the DECLARED candidate count
    minus one (the product of the axis sizes) and defaults to the challengers
    passed. It is not the count left after data-driven exclusions (measured-
    inadmissible, confidently infeasible): Bonferroni over a subset chosen by
    data correlated with the primary has no stated level, and the declared
    count makes the constant a function of the design alone.
    """
    terms = list(fit.effects) + list(fit.quadratic)
    if fit.pure_error_df <= 0 or any(e.se is None for e in terms):
        return RegretBound(None, None, delta, "none",
                           "no pure-error estimate (no replicated centre points) — unknown is not zero")
    sign = 1.0 if direction != "minimize" else -1.0
    others = [c for c in cands if c.levels != xhat.levels]
    if not others:
        return RegretBound(0.0, None, delta, "trivial", "single candidate")
    fx = predict(fit, xhat.coded)

    from orchestrator.optimize.effects import prediction_variance

    def contrast(z) -> tuple[float, float, float]:
        est = sign * (predict(fit, z.coded) - fx)
        exact = prediction_variance(fit, z.coded, xhat.coded)
        if exact is not None:
            # A mixed-level fit (non-orthogonal by construction): the exact
            # s^2 d'(X'X)^-1 d, covariances between coefficients included.
            return est, math.sqrt(exact), float(fit.pure_error_df)
        var = 0.0
        for e in terms:
            dz = (math.prod(float(z.coded[t]) for t in e.terms)
                  - math.prod(float(xhat.coded[t]) for t in e.terms))
            var += (e.se or 0.0) ** 2 * dz * dz
        return est, math.sqrt(var), float(fit.pure_error_df)

    m = max(len(others), int(m_declared or 0))
    crit = simultaneous_critical(delta, m, len(terms), fit.pure_error_df)
    bounds = _challenger_bounds(others, contrast, delta=delta, crit=crit["value"])
    arg = max(bounds, key=lambda i: bounds[i])
    if crit["used"] == "bonferroni":
        method = "bonferroni_one_sided_t"
        detail = (f"M={m} challengers, df={fit.pure_error_df}, t={crit['value']:.3f}"
                  f" (Scheffe would be {crit['scheffe']:.3f})")
    else:
        method = "scheffe_one_sided"
        detail = (f"Scheffe over q={crit['q']} terms, df={fit.pure_error_df}, "
                  f"sqrt(qF)={crit['value']:.3f} (Bonferroni over M={m} would be "
                  f"t={crit['bonferroni']:.3f}); {len(others)} challenger(s) evaluated")
    out = RegretBound(max(0.0, bounds[arg]), others[arg].levels, delta,
                      method, detail, critical=crit)
    if profile:
        order = sorted(bounds, key=lambda i: -bounds[i])
        head, tail = order[:profile], order[profile:]
        out = dataclasses.replace(out, profile={
            "top": [{"levels": others[i].levels, "bound": bounds[i]} for i in head],
            "rest": max((bounds[i] for i in tail), default=None),
            "challengers": len(others)})
    return out


#: Boxes ``region_bound`` may open before stopping with a looser (still valid)
#: bound. Measured on a quadratic bowl in k knobs (9-point axes, CCD, 6 centre
#: points, noise 0.4): k = 4 (6561 points) converges in 895 boxes / 0.04 s;
#: k = 6 (531k points) in 56,508 boxes / 5.2 s; k = 8 (43M points) does not
#: converge at 200,000 boxes (36 s, bound 3.8 vs 9.5 at 4,000). A constant,
#: recorded in provenance's analysis constants like CANDIDATE_CAP.
REGION_NODE_BUDGET = 60_000

#: Each box costs O(p^2) (the interval quadratic form), so the box budget
#: shrinks with the model size: ``min(REGION_NODE_BUDGET, REGION_WORK_BUDGET /
#: p^2)``. 2e8 keeps every fit up to p = 57 at the full 60,000 boxes (k = 6
#: knobs converge there) and holds a 16-knob refine (p = 152, measured 56-73 s
#: CPU per stage at 60,000 boxes, never converging) to ~8,700 boxes / ~9 s.
#: The bound is valid at any budget; a smaller one is only looser.
REGION_WORK_BUDGET = 200_000_000


def region_bound(fit: Fit, factors, fitted_ids, xhat: Candidate, *, crit: float,
                 direction: str, skip_coded=(), node_budget: int = REGION_NODE_BUDGET) -> dict:
    """An upper bound on ``max_z U(z, x_hat)`` over the WHOLE axis grid, without
    enumerating it (#321 H3) -- the searched-space half of the model bound.

    ``U(z) = sign (f_hat(z) - f_hat(x_hat)) + crit * se(z - x_hat)`` with the
    simultaneous ``crit`` of ``simultaneous_critical``: under Scheffe the
    family covers every ``z`` of the grid, evaluated or not, so ``max_z U``
    over the grid bounds ``max_z f(z) - f(x_hat)`` on the family's event. The
    grid is the product of the fitted factors' axes (``decide._axes``), i.e.
    exactly the space enumeration would score; a configuration excluded from
    the ranking (measured inadmissible, confidently infeasible) stays in it,
    which is conservative.

    BRANCH AND BOUND over sub-boxes (a subset of axis values per factor). On a
    sub-box every model column lies in a known interval, so by interval
    arithmetic (Moore 1966) the estimate is bounded by the sum of each term's
    interval maximum, and ``se^2 = d' V d`` by
    ``sum_i V_ii max d_i^2 + sum_{i != j} max(V_ij d_i d_j)``, ``d_i`` the
    interval of column i minus x_hat's value. Both are exact on a singleton
    box. The largest-bound box is split on its widest axis; a singleton is
    evaluated exactly, and one in ``skip_coded`` (the EVALUATED candidates,
    bounded per challenger by the caller) is dropped. It stops when the
    largest open bound is at or below the best exact singleton (converged:
    the max over the unevaluated grid) or after ``node_budget`` boxes; the
    bound is then the largest open box's, still a valid upper bound, only
    looser (``node_budget`` is capped at ``REGION_WORK_BUDGET / p^2``). ``V`` is ``s^2 (X'X)^-1`` when the fit carries the covariance,
    else ``diag(se_j^2)`` -- the per-term arithmetic the enumerated bound uses
    for two-level fits (exact for their orthogonal columns).

    Returns ``{"value", "converged", "nodes", "grid_size"}``; ``value`` is
    floored at 0.0 and is ``None`` when the fit has no variance estimate.
    """
    import heapq

    from orchestrator.optimize.decide import _axes, _flat
    from orchestrator.optimize.factors import model_columns

    terms = list(fit.effects) + list(fit.quadratic)
    if fit.pure_error_df <= 0 or any(e.se is None for e in terms):
        return {"value": None, "converged": False, "nodes": 0, "grid_size": None}
    sign = 1.0 if direction != "minimize" else -1.0
    by_id = {f.id: f for f in factors}
    ids, axes = _axes(fitted_ids, factors)
    # column -> (axis j, component); each axis value's coded vector
    col_of: dict[str, tuple[int, int]] = {}
    vals: list[list[tuple[float, ...]]] = []
    for j, fid in enumerate(ids):
        cols = model_columns(by_id[fid])
        for c_i, c in enumerate(cols):
            col_of[c] = (j, c_i)
        vals.append([tuple(v for _c, v in _flat(by_id[fid], c)) for c, _lv in axes[j]])
    grid = math.prod(len(a) for a in axes)
    beta = [float(e.estimate) for e in terms]
    tts = [tuple(e.terms) for e in terms]
    p = len(terms)
    if fit.covariance is not None and fit.pure_error_var:
        s2 = float(fit.pure_error_var)
        V = [[s2 * float(fit.covariance[i + 1][j + 1]) for j in range(p)] for i in range(p)]
    else:
        V = [[(float(terms[i].se) ** 2 if i == j else 0.0) for j in range(p)]
             for i in range(p)]
    gx = [math.prod(float(xhat.coded[t]) for t in ts) for ts in tts]
    skip = {tuple(sorted((k, round(float(v), 12)) for k, v in sc.items()))
            for sc in skip_coded}

    def imul(a, b):
        ps = (a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1])
        return (min(ps), max(ps))

    def col_iv(box, c):
        j, ci = col_of[c]
        xs = [vals[j][k][ci] for k in box[j]]
        return (min(xs), max(xs))

    def term_iv(box, ts):
        if len(ts) == 2 and ts[0] == ts[1]:
            lo, hi = col_iv(box, ts[0])
            sq = (lo * lo, hi * hi)
            return (0.0 if lo <= 0.0 <= hi else min(sq), max(sq))
        iv = (1.0, 1.0)
        for t in ts:
            iv = imul(iv, col_iv(box, t))
        return iv

    def upper(box) -> float:
        g = [term_iv(box, ts) for ts in tts]
        est = sum(max(sign * beta[i] * g[i][0], sign * beta[i] * g[i][1])
                  for i in range(p))
        est -= sign * sum(beta[i] * gx[i] for i in range(p))
        d = [(g[i][0] - gx[i], g[i][1] - gx[i]) for i in range(p)]
        q = 0.0
        for i in range(p):
            if V[i][i]:
                q += V[i][i] * max(d[i][0] ** 2, d[i][1] ** 2)
            for j in range(i + 1, p):
                if V[i][j]:
                    lo, hi = imul(d[i], d[j])
                    q += 2.0 * max(V[i][j] * lo, V[i][j] * hi)
        return est + crit * math.sqrt(max(q, 0.0))

    def singleton_key(box):
        out = {}
        for j, fid in enumerate(ids):
            for c, v in _flat(by_id[fid], axes[j][box[j][0]][0]):
                out[c] = v
        return tuple(sorted((k, round(float(v), 12)) for k, v in out.items()))

    root = tuple(tuple(range(len(a))) for a in axes)
    node_budget = max(1, min(int(node_budget), REGION_WORK_BUDGET // max(1, p * p)))
    heap = [(-upper(root), 0, root)]
    best, nodes, tick = -math.inf, 0, 1
    while heap and nodes < node_budget:
        ub = -heap[0][0]
        if ub <= best:
            break
        _, _, box = heapq.heappop(heap)
        nodes += 1
        if all(len(b) == 1 for b in box):
            if singleton_key(box) not in skip:
                best = max(best, ub)        # exact on a singleton
            continue
        j = max(range(len(box)), key=lambda a: len(box[a]))
        order = sorted(box[j], key=lambda k: vals[j][k])
        half = len(order) // 2
        for part in (tuple(order[:half]), tuple(order[half:])):
            child = box[:j] + (part,) + box[j + 1:]
            heapq.heappush(heap, (-upper(child), tick, child))
            tick += 1
    open_ub = -heap[0][0] if heap else -math.inf
    converged = (not heap) or open_ub <= best
    value = best if converged else max(best, open_ub)
    return {"value": max(0.0, value) if math.isfinite(value) else 0.0,
            "converged": bool(converged), "nodes": nodes, "grid_size": grid}


def model_bound_outside(profile: dict | None, inside: list[dict]) -> float | None:
    """``max_{z not in S} U_m(z, x_hat)`` from a recorded model-bound profile.

    Every member of the model family holds SIMULTANEOUSLY (Bonferroni over all
    ``M`` challengers), so restricting the max to the challengers OUTSIDE a
    data-chosen set ``S`` keeps its level: the family's coverage event does not
    depend on which members are read. Challengers inside ``S`` are measured
    freshly and bounded by the terminal family instead (spec
    2026-10-17-certification-soundness.md section 2). Floors at 0 like the
    full bound. ``None`` when no profile was recorded.
    """
    if not profile:
        return None

    def _same(a, b):
        return set(a) == set(b) and all(
            (isinstance(a[k], (int, float)) and isinstance(b[k], (int, float))
             and not isinstance(a[k], bool) and math.isclose(float(a[k]), float(b[k]),
                                                             rel_tol=1e-9, abs_tol=1e-12))
            or a[k] == b[k] for k in a)

    vals = [float(e["bound"]) for e in profile.get("top") or []
            if not any(_same(dict(e["levels"]), dict(s)) for s in inside)]
    if profile.get("rest") is not None:
        vals.append(float(profile["rest"]))
    return max([0.0] + vals)


def terminal_regret_bound(samples: dict[str, list[float]], best: str, *,
                          delta: float, direction: str,
                          paired: bool) -> RegretBound:
    """``R_delta^term`` — model-free, from fresh replicates of the finalists.

    Spec §3.5's second flavour and the paper's terminal stage: screening
    produces a shortlist ``S``, fresh measurements compare its members
    DIRECTLY, so this number carries no response-model assumption at all. Its
    inputs are sample means and sample variances of measurements taken at the
    finalists themselves; nothing here consults a ``Fit``.

    One-sided upper bounds on each challenger's true improvement over
    ``best``, Bonferroni over the ``M = |S| - 1`` challengers so the max is a
    valid bound on the gap to the best member of ``S`` (the same union-bound
    argument the module docstring gives for the model flavour). Welch's
    unequal-variance t by default; PAIRED differences when the finalists share
    a workload seed set (common random numbers, spec §3.8) and the replicate
    counts match — pairing removes the shared seed effect from the variance,
    which is what makes a noisy systems target measurable within a realistic
    budget.

    ``value=None`` when any finalist has fewer than two replicates: a single
    measurement gives no variance estimate, and an unknown is not a zero.
    Callers must treat ``None`` as "cannot certify" — ``policy.step`` already
    does, since a ``None`` observation never matches a guard.

    The bound floors at ``0.0``: ``best`` is the argmax of the observed means,
    so every challenger's point estimate is ``<= 0`` and the true gap to the
    best member of ``S`` cannot be negative.
    """
    others = [k for k in samples if k != best]
    if not others:
        return RegretBound(0.0, None, delta, "trivial", "single finalist")
    if any(len(v) < 2 for v in samples.values()):
        return RegretBound(None, None, delta, "none",
                           "need >= 2 replicates per finalist for a variance estimate")
    bounds, not_estimable, use_paired = _terminal_family(
        samples, best, delta=delta, direction=direction, paired=paired)
    if not_estimable:
        return RegretBound(
            None, None, delta, "none",
            f"no variance estimate for challenger(s) "
            f"{sorted(set(not_estimable))}: the replicates carry zero spread "
            f"(a deterministic target, or a constant offset between finalists), "
            f"so a t-interval would collapse to its point estimate and report "
            f"exact epsilon-optimality from no information. An unknown is not a "
            f"zero -- the report's fallback ladder names the winner as "
            f"`terminal_best` instead of certifying it.",
        )
    arg = max(bounds, key=lambda i: bounds[i])
    return RegretBound(
        max(0.0, bounds[arg]), others[arg], delta,
        "bonferroni_one_sided_t_paired" if use_paired
        else "bonferroni_one_sided_welch_t",
        f"M={len(others)} challengers over fresh replicates "
        f"(n={ {k: len(v) for k, v in samples.items()} })",
    )


def simultaneous_gain_interval(samples: dict[str, list[float]], winner: str,
                               reference: str, *, delta: float,
                               paired: bool) -> dict | None:
    """Two-sided CI on ``f(winner) - f(reference)``, valid AFTER selection.

    ``winner`` was chosen as the argmax of these same replicates, so a plain
    interval for it would not cover at its nominal level. Bonferroni over
    every finalist other than ``reference`` (``M``) at two-sided level
    ``delta / M`` covers ALL of ``f(i) - f(reference)`` simultaneously with
    probability ``>= 1 - delta``, hence the data-selected one too
    (simultaneous inference is selection-proof; Hsu 1996, ch. 1). The point
    estimate is the winner's selection-biased mean difference and is
    labelled as such by the caller. Paired t on CRN differences when the
    replicate counts match, Welch otherwise. ``None`` when not estimable.
    """
    if winner not in samples or reference not in samples:
        return None
    m = max(1, sum(1 for k in samples if k != reference))
    xw, xr = samples[winner], samples[reference]
    if winner == reference:
        return {"estimate": 0.0, "low": 0.0, "high": 0.0, "method": "identity",
                "simultaneous_over": m}
    if len(xw) < 2 or len(xr) < 2:
        return None
    if paired and len(xw) == len(xr):
        d = [a - b for a, b in zip(xw, xr)]
        vd = variance(d)
        if not vd > 0.0:
            return None
        est, se, df, method = mean(d), math.sqrt(vd / len(d)), float(len(d) - 1), "paired_t"
    else:
        vw, vr = variance(xw) / len(xw), variance(xr) / len(xr)
        den = vw ** 2 / (len(xw) - 1) + vr ** 2 / (len(xr) - 1)
        if not den > 0.0:
            return None
        est, se = mean(xw) - mean(xr), math.sqrt(vw + vr)
        df, method = (vw + vr) ** 2 / den, "welch_t"
    tcrit = float(student_t.ppf(1 - delta / (2 * m), max(df, 1.0)))
    return {"estimate": est, "low": est - tcrit * se, "high": est + tcrit * se,
            "method": method, "simultaneous_over": m}


def _terminal_family(samples, best, *, delta, direction, paired):
    """The simultaneous terminal family: ``({i: U_i}, not_estimable, paired)``."""
    others = [k for k in samples if k != best]
    sign = 1.0 if direction != "minimize" else -1.0
    xb = samples[best]
    use_paired = paired and all(len(samples[k]) == len(xb) for k in others)

    # NOT ESTIMABLE means None, including when the arithmetic would produce a
    # number. Two ways a contrast carries zero information while still returning
    # a finite value, and both used to certify:
    #
    #   * Every replicate of every finalist identical (`[5,5,5]` vs `[4,4,4]`) --
    #     spec §3.5's MEASURED deterministic-target case. The paired differences
    #     are then a constant, `variance(d) == 0`, `se == 0`, and the t-interval
    #     collapses to the point estimate: `value=0.0` labelled
    #     `bonferroni_one_sided_t_paired`, i.e. exact epsilon-optimality asserted
    #     from no variance at all, wearing a real certificate's name. Note it is
    #     the CONSTANT OFFSET that does it, not three equal numbers -- any two
    #     finalists differing by a fixed amount reach it, which is why a count
    #     check on replicates cannot catch it.
    #   * Subnormal variances in the Welch branch. The guard was `(vk + vb) > 0`,
    #     but `vk ** 2` UNDERFLOWS to exactly 0.0 long before `vk` does, so the
    #     guard passed while the df denominator was zero. Minimal reproducer:
    #     replicates `[-3.117993501313441e-82, 0.0]`, which raised
    #     ZeroDivisionError straight out of the certification path. A campaign
    #     reporting a normalized rate can reach it.
    #
    # `model_regret_bound` already returns None when `pure_error_df <= 0`; the
    # asymmetry between the two bounds was the defect. An unknown is not a zero,
    # and a deterministic target's honest answer is "this instrument cannot
    # produce a variance estimate", which the fallback ladder already handles --
    # `terminal_best` names the winner without claiming a bound.
    not_estimable: list[str] = []

    def contrast(k: str) -> tuple[float, float, float]:
        xk = samples[k]
        if use_paired:
            d = [sign * (b - a) for a, b in zip(xb, xk)]
            n = len(d)
            vd = variance(d)
            if not vd > 0.0:
                not_estimable.append(k)
                return mean(d), 0.0, float(n - 1)
            return mean(d), math.sqrt(vd / n), float(n - 1)
        est = sign * (mean(xk) - mean(xb))
        vk, vb = variance(xk) / len(xk), variance(xb) / len(xb)
        se = math.sqrt(vk + vb)
        # Guard the DENOMINATOR itself, not a quantity that merely implies it.
        den = (vk ** 2) / (len(xk) - 1) + (vb ** 2) / (len(xb) - 1)
        if not den > 0.0:
            not_estimable.append(k)
            return est, se, 1.0
        df = (vk + vb) ** 2 / den
        return est, se, df

    bounds = _challenger_bounds(others, contrast, delta=delta)
    return bounds, not_estimable, use_paired


def resolve_epsilon(spec: dict, reference: float) -> float:
    """The indifference width, absolute or as a percentage of ``reference``.

    ``abs`` wins when present. A percentage is taken against ``abs(reference)``
    so a negative-valued objective (a latency the campaign minimises, reported
    as a negated response) still yields a positive width.
    """
    if "abs" in spec:
        return float(spec["abs"])
    return abs(float(reference)) * float(spec.get("pct", 2.0)) / 100.0


# ── multi-objective: the model half of a front certificate (#321 item 4) ────


def fit_to_record(fit: Fit) -> dict:
    """What ``front_model_half`` needs of a fitted objective model, as JSON:
    the coefficients, their per-term SEs, the exact ``(X'X)^-1`` when the fit
    kept it, and the pure error. Persisted at the fitting stage because the
    Fit is gone by confirm (as ``model_adequate`` is persisted)."""
    def eff(e):
        return {"terms": list(e.terms), "estimate": float(e.estimate),
                "se": None if e.se is None else float(e.se)}
    return {"intercept": float(fit.intercept),
            "effects": [eff(e) for e in fit.effects],
            "quadratic": [eff(e) for e in fit.quadratic],
            "pure_error_var": fit.pure_error_var, "pure_error_df": int(fit.pure_error_df),
            "term_terms": [list(t) for t in fit.term_terms],
            "covariance": (None if fit.covariance is None
                           else [list(r) for r in fit.covariance]),
            "n_runs": int(fit.n_runs)}


def fit_from_record(d: dict) -> Fit:
    """The inverse of ``fit_to_record`` (only the fields prediction and its
    variance read)."""
    from orchestrator.optimize.effects import Effect

    def eff(e):
        return Effect(label="".join(e["terms"]), terms=tuple(e["terms"]),
                      estimate=float(e["estimate"]), se=e.get("se"))
    return Fit(intercept=float(d["intercept"]),
               effects=tuple(eff(e) for e in d.get("effects") or []),
               quadratic=tuple(eff(e) for e in d.get("quadratic") or []),
               n_runs=int(d.get("n_runs") or 0),
               pure_error_var=d.get("pure_error_var"),
               pure_error_df=int(d.get("pure_error_df") or 0),
               term_terms=tuple(tuple(t) for t in d.get("term_terms") or []),
               covariance=(None if d.get("covariance") is None
                           else tuple(tuple(float(x) for x in r) for r in d["covariance"])))


def _contrast(fit: Fit, za: dict, zb: dict) -> tuple[float, float]:
    """``(f_hat(za) - f_hat(zb), se)`` -- the exact ``s^2 d'(X'X)^-1 d`` when
    the fit carries the covariance, else the per-term sum (exact for the
    orthogonal columns of a two-level fit), as ``model_regret_bound`` does."""
    from orchestrator.optimize.effects import prediction_variance

    est = predict(fit, za) - predict(fit, zb)
    exact = prediction_variance(fit, za, zb)
    if exact is not None:
        return est, math.sqrt(exact)
    var = 0.0
    for e in list(fit.effects) + list(fit.quadratic):
        dz = (math.prod(float(za[t]) for t in e.terms)
              - math.prod(float(zb[t]) for t in e.terms))
        var += (e.se or 0.0) ** 2 * dz * dz
    return est, math.sqrt(var)


def front_model_half(fits: dict, objectives, eps: dict, chosen: dict, *,
                     factors, fitted_ids, held_fixed: dict, delta: float,
                     exclude: list[dict] = (), cap: int | None = None) -> dict:
    """Can a configuration nobody measured epsilon-dominate the chosen front
    point ``w``? (#321 item 4: the model half of a front certificate.)

    For every objective k and every grid point ``z``, a one-sided bound
    ``U_k(z, w) = s_k (f_k_hat(z) - f_k_hat(w)) + c_k se_k(z - w)`` on
    ``s_k (f_k(z) - f_k(w))`` (``s_k`` the objective's sign). ``z``
    epsilon-dominates ``w`` only if ``s_k (f_k(z) - f_k(w)) >= eps_k`` for
    EVERY k, so on the event that every bound holds, ``z`` cannot dominate
    once ``min_k (U_k(z, w) - eps_k) < 0``. The statistic is
    ``D = max_z min_k (U_k(z, w) - eps_k)``; the front certificate needs
    ``D < 0``.

    The level. ``w`` is chosen FROM the data and need not lie on the grid (a
    measured axial point), so the family must cover ``x(z) - x(w)`` for every
    ``z`` and every possible ``w``: ``c_k = sqrt(q_k F_{q_k, df_k, 1 -
    delta/K})``, Scheffe over objective k's q_k model terms, which covers
    every contrast in the model space at once and is therefore
    selection-proof. Bonferroni over the K objectives makes the whole family
    hold with probability >= 1 - delta (``delta`` = delta_screen). Bonferroni
    over grid pairs is NOT used here: it would not cover an off-grid ``w``.
    The constants depend on (delta, K, q_k, df_k) only.

    The grid is the fitting stage's: the fitted factors' axes with
    ``held_fixed``. ``exclude`` (the MEASURED configurations, whose rivalry the
    measured front's statuses already settle at delta_terminal) are left out;
    a model family that holds simultaneously holds on any subset. Enumerated at
    or below ``cap`` (``decide.CANDIDATE_CAP``). Above it the bound is
    ``min_k max_z (U_k - eps_k)`` with each inner max taken by
    ``region_bound`` -- a valid upper bound on D (max-min <= min-max), looser.

    Returns ``{"value", "computable", "reason", "critical", "method",
    "dominator"}``. Not computable (``value None``) when an objective model has
    no variance estimate, an epsilon is unknown, ``w`` lies outside the fitted
    slice (a held factor at another level), or no fit was recorded.
    """
    from orchestrator.optimize.decide import CANDIDATE_CAP, _axes, _flat
    from orchestrator.optimize.factors import code_vector, model_columns

    cap = CANDIDATE_CAP if cap is None else int(cap)
    out = {"value": None, "computable": False, "reason": "", "critical": {},
           "method": "", "dominator": None, "delta": float(delta)}
    metrics = [o.metric for o in objectives]
    if not fits or any(m not in fits or fits[m] is None for m in metrics):
        out["reason"] = "no objective model fit recorded for every objective"
        return out
    if any(eps.get(m) is None for m in metrics):
        out["reason"] = "an objective's epsilon is unknown"
        return out
    by_id = {f.id: f for f in factors}
    if any(k in chosen and chosen[k] != v for k, v in held_fixed.items()):
        out["reason"] = ("the chosen point sits at another level of a factor the "
                         "fitting stage held fixed, so its model says nothing about it")
        return out
    for o in objectives:
        f_ = fits[o.metric]
        if f_.pure_error_df <= 0 or any(e.se is None for e in
                                        list(f_.effects) + list(f_.quadratic)):
            out["reason"] = f"objective {o.metric!r} has no pure-error variance estimate"
            return out

    def coded(levels):
        c = {}
        for fid in fitted_ids:
            for col, v in zip(model_columns(by_id[fid]), code_vector(by_id[fid], levels[fid])):
                c[col] = v
        return c

    try:
        w = coded(chosen)
    except (KeyError, TypeError, ValueError) as exc:
        out["reason"] = f"the chosen point cannot be coded in the fitted space ({exc})"
        return out
    ids, axes = _axes(fitted_ids, factors)
    size = math.prod(len(a) for a in axes)
    K = len(objectives)
    crit = {}
    for o in objectives:
        f_ = fits[o.metric]
        q = len(f_.effects) + len(f_.quadratic)
        c = simultaneous_critical(delta / K, 1, q, f_.pure_error_df)
        crit[o.metric] = dict(c, used="scheffe", value=c["scheffe"], m=None,
                              rule="Scheffe sqrt(q F_{q,df,1-delta/K}): covers every "
                                   "contrast x(z) - x(w), w data-chosen and possibly "
                                   "off the grid; Bonferroni over the K objectives")
    out["critical"] = crit
    sgn = {o.metric: (1.0 if o.direction != "minimize" else -1.0) for o in objectives}

    def key(lv):
        return tuple(sorted((k, repr(lv.get(k))) for k in fitted_ids))

    # A measured configuration masks a grid point only when it sits in this
    # slice (every held factor at its held level).
    in_slice = [lv for lv in list(exclude) + [chosen]
                if all(lv.get(k) == v for k, v in held_fixed.items())]
    skip = {key(lv) for lv in in_slice if all(fid in lv for fid in fitted_ids)}
    if size <= cap:
        import itertools

        best, arg = -math.inf, None
        for combo in itertools.product(*axes):
            lv = {fid: lev for fid, (_c, lev) in zip(ids, combo)}
            if key(lv) in skip:
                continue
            z = {}
            for fid, (c, _lev) in zip(ids, combo):
                z.update(_flat(by_id[fid], c))
            g = math.inf
            for o in objectives:
                est, se = _contrast(fits[o.metric], z, w)
                g = min(g, sgn[o.metric] * est + crit[o.metric]["value"] * se
                        - float(eps[o.metric]))
                if g < best:
                    break                      # cannot raise the max
            if g > best:
                best, arg = g, {**dict(held_fixed), **lv}
        out.update(value=None if arg is None else best, computable=arg is not None,
                   dominator=arg, method="enumerated: max_z min_k (U_k(z, w) - eps_k)",
                   reason="" if arg is not None else "no unmeasured grid point")
        if arg is None:
            out.update(value=-math.inf, computable=True)
        return out
    xw = Candidate(levels=dict(chosen), coded=w, predicted=float("nan"))
    per = {}
    for o in objectives:
        rg = region_bound(fits[o.metric], factors, fitted_ids, xw,
                          crit=crit[o.metric]["value"], direction=o.direction)
        per[o.metric] = rg
    vals = [per[m]["value"] - float(eps[m]) for m in metrics if per[m]["value"] is not None]
    if len(vals) != K:
        out["reason"] = "the region bound was not computable"
        return out
    out.update(value=min(vals), computable=True, critical=crit,
               method=("searched: min_k max_z (U_k(z, w) - eps_k) by branch and "
                       "bound, an upper bound on max_z min_k"),
               region={m: {k: per[m][k] for k in ("value", "converged", "nodes")}
                       for m in metrics})
    return out



# ── A5 (#321 P3 item 2): the robust terminal family ─────────────────────────


def robust_terminal_bound(samples: dict[str, list[float]], best: str, *,
                          delta: float, direction: str, paired: bool,
                          rule: dict) -> tuple["RegretBound", dict]:
    """The terminal family made robust to small-n non-normality, with its
    diagnostics: ``(bound, record)``.

    Each challenger's upper bound is ``max(U_t, U_robust)`` at the same
    per-challenger level ``delta / M`` (Bonferroni over the ``M`` challengers,
    as ``terminal_regret_bound``), so the family's level is at least that of
    either member's when its assumptions hold, and taking the larger of two
    valid bounds is valid. ``U_robust`` is

    * PAIRED (CRN): Hartigan's (1969) exact sign-flip bound on the paired
      differences (``noise.sign_flip_upper``): valid for independent
      differences SYMMETRIC about their centre, no normality;
    * UNPAIRED: the bootstrap-t (Hall 1988; ``noise.bootstrap_t_upper``),
      second-order accurate under skew; not exact at small n.

    The certificate is withheld, named, when

    * any admissible finalist has fewer than ``rule.floor`` replicates
      (``replicates_below_floor``): below it the sign-flip bound does not
      exist at the per-challenger level, and the Monte Carlo in the spec
      (§7) shows no small-n bound holds its level under skewed,
      heteroscedastic noise;
    * the skewness pretest rejects at ``rule.skew_alpha``
      (``noise_skewed``): pooled over the finalists' independent replicate
      groups (unpaired), or pooled over the challengers' paired-difference
      vectors (paired; they share the best's replicates, so that null is
      approximate). A veto: it removes
      certificates only, spends no delta, and is the guard against the
      asymmetric paired differences the sign-flip bound assumes away;
    * a robust bound cannot be computed (``robust_bound_not_computable``).

    The record holds per-finalist n, variance and skewness, the variance
    ratio (largest over smallest finalist variance), the pretest and the
    reasons. Every constant is in the policy or provenance; nothing is
    chosen from the data.
    """
    from orchestrator.optimize import noise as noise_mod

    others = [k for k in samples if k != best]
    sign = 1.0 if direction != "minimize" else -1.0
    m = max(1, len(others))
    a = delta / m
    floor = int(rule.get("floor", 1))
    skew_alpha = float(rule.get("skew_alpha", 0.0))
    var = {k: (variance(v) if len(v) >= 2 else None) for k, v in samples.items()}
    pos = [v for v in var.values() if v is not None and v > 0.0]
    rec: dict = {
        "floor": floor, "skew_alpha": skew_alpha, "per_challenger_level": a,
        "finalists": {k: {"n": len(v), "variance": var[k],
                          "skewness": noise_mod.sample_skewness(v)}
                      for k, v in sorted(samples.items())},
        "variance_ratio": (max(pos) / min(pos)) if len(pos) >= 2 else None,
        "withheld": [],
    }
    t_bounds, not_est, use_paired = _terminal_family(
        samples, best, delta=delta, direction=direction, paired=paired)
    rec["paired"] = bool(use_paired)
    n_min = min(len(v) for v in samples.values())
    rec["n_min"] = n_min
    if n_min < floor:
        rec["withheld"].append("replicates_below_floor")
    # The skewness pretest.
    if use_paired:
        diffs = [[sign * (c - b) for b, c in zip(samples[best], samples[k])]
                 for k in others]
        # Pooled over the challengers' paired-difference vectors. They share
        # the best's replicates, so they are not independent and the null is
        # approximate; the pretest is a VETO, so a miscalibrated null costs
        # power, never validity. Measured more sensitive than Bonferroni over
        # per-challenger tests (spec §7).
        t = noise_mod.skewness_test(diffs)
        p = t["p"]
        rec["skewness_test"] = {"method": t["method"] + "_paired_differences_pooled",
                                "p": p, "stat": t["stat"], "sizes": t["sizes"],
                                "null": "approximate: the difference vectors "
                                        "share the best finalist's replicates"}
    else:
        t = noise_mod.skewness_test(list(samples.values()))
        p = t["p"]
        rec["skewness_test"] = {"method": t["method"], "p": p, "stat": t["stat"],
                                "sizes": t["sizes"]}
    if p is not None and p < skew_alpha:
        rec["withheld"].append("noise_skewed")
    if not others:
        return RegretBound(0.0, None, delta, "trivial", "single finalist"), rec
    if not_est:
        rec["withheld"].append("robust_bound_not_computable")
        return RegretBound(None, None, delta, "none",
                           "zero-spread contrast: no variance estimate"), rec
    rob: dict = {}
    for i, k in enumerate(others):
        if use_paired:
            # challenger minus best, in the campaign's direction
            d = [sign * (c - b) for b, c in zip(samples[best], samples[k])]
            u = noise_mod.sign_flip_upper(d, a)
        else:
            u = noise_mod.bootstrap_t_upper(
                [sign * v for v in samples[k]], [sign * v for v in samples[best]], a)
        rob[i] = u
    if any(u is None for u in rob.values()):
        if "replicates_below_floor" not in rec["withheld"]:
            rec["withheld"].append("robust_bound_not_computable")
        return RegretBound(None, None, delta, "none",
                           "robust bound not computable (below the replicate "
                           "floor, or zero spread)"), rec
    both = {i: max(t_bounds[i], rob[i]) for i in t_bounds}
    rec["per_challenger"] = {others[i]: {"t": t_bounds[i], "robust": rob[i]}
                             for i in t_bounds}
    arg = max(both, key=lambda i: both[i])
    method = ("bonferroni_max_t_paired_sign_flip" if use_paired
              else "bonferroni_max_welch_bootstrap_t")
    return RegretBound(
        max(0.0, both[arg]), others[arg], delta, method,
        f"M={len(others)} challengers, each at delta/M={a:.4g}: max of the "
        f"{'paired t' if use_paired else 'Welch t'} and the "
        f"{'exact sign-flip (Hartigan 1969)' if use_paired else 'bootstrap-t (Hall 1988)'}"
        f" bound (n={ {k: len(v) for k, v in samples.items()} })"), rec
