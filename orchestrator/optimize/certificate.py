"""Residual-regret certificates: how much better could any challenger still be?

Spec §3.5, paper eq. (2). ``R_delta(x) = max_z U_delta(z, x)`` over every valid
configuration ``z``, where ``U_delta`` is a SIMULTANEOUS one-sided upper bound
on the true gap ``f(z) - f(x)``. Two flavours: MODEL-based (screen/refine —
depends on the registered response class; exact for orthogonal main/2fi
columns, optimistic for quadratic terms per ``effects.py``) and TERMINAL
(Task 9 — model free, from fresh replicates of the finalists). They rest on
different assumptions and are reported separately, never collapsed.

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
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import t as student_t

from orchestrator.optimize.decide import Candidate, predict
from orchestrator.optimize.effects import Fit


@dataclass(frozen=True)
class RegretBound:
    """``R_delta(x_hat)`` plus the challenger that keeps it large.

    ``challenger`` is the levels dict of the ``z`` attaining the max — the
    point the next experiment should be directed at (spec §3.6 rung 2), which
    is why it is carried alongside the number rather than recomputed later.
    """

    value: float | None
    challenger: dict | None
    delta: float
    method: str
    detail: str


def _to_dict(b: RegretBound) -> dict:
    return {"value": b.value, "challenger": b.challenger, "delta": b.delta,
            "method": b.method, "detail": b.detail}


def model_regret_bound(fit: Fit, cands: list[Candidate], xhat: Candidate, *,
                       delta: float, direction: str) -> RegretBound:
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
    """
    terms = list(fit.effects) + list(fit.quadratic)
    if fit.pure_error_df <= 0 or any(e.se is None for e in terms):
        return RegretBound(None, None, delta, "none",
                           "no pure-error estimate (no replicated centre points) — unknown is not zero")
    sign = 1.0 if direction != "minimize" else -1.0
    others = [c for c in cands if c.levels != xhat.levels]
    if not others:
        return RegretBound(0.0, None, delta, "trivial", "single candidate")
    tcrit = float(student_t.ppf(1 - delta / len(others), fit.pure_error_df))
    fx = predict(fit, xhat.coded)
    best_u, best_z = 0.0, None
    for z in others:
        est = sign * (predict(fit, z.coded) - fx)
        var = 0.0
        for e in terms:
            dz = (math.prod(float(z.coded[t]) for t in e.terms)
                  - math.prod(float(xhat.coded[t]) for t in e.terms))
            var += (e.se or 0.0) ** 2 * dz * dz
        u = est + tcrit * math.sqrt(var)
        if u > best_u:
            best_u, best_z = u, z.levels
    return RegretBound(best_u, best_z, delta, "bonferroni_one_sided_t",
                       f"M={len(others)} challengers, df={fit.pure_error_df}, t={tcrit:.3f}")


def resolve_epsilon(spec: dict, reference: float) -> float:
    """The indifference width, absolute or as a percentage of ``reference``.

    ``abs`` wins when present. A percentage is taken against ``abs(reference)``
    so a negative-valued objective (a latency the campaign minimises, reported
    as a negated response) still yields a positive width.
    """
    if "abs" in spec:
        return float(spec["abs"])
    return abs(float(reference)) * float(spec.get("pct", 2.0)) / 100.0
