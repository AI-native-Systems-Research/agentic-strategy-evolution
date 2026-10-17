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

    def as_dict(self) -> dict:
        """The JSON shape written into ``recommendation.json`` / ``report.json``."""
        return {"value": self.value, "challenger": self.challenger,
                "delta": self.delta, "method": self.method, "detail": self.detail}


def _challenger_bounds(
    challengers: list,
    contrast: Callable[[object], tuple[float, float, float]],
    *,
    delta: float,
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
        tcrit = float(student_t.ppf(1 - delta / m, max(float(df), 1.0)))
        out[i] = est + tcrit * se
    return out


def model_regret_bound(fit: Fit, cands: list[Candidate], xhat: Candidate, *,
                       delta: float, direction: str,
                       profile: int = 0) -> RegretBound:
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

    bounds = _challenger_bounds(others, contrast, delta=delta)
    arg = max(bounds, key=lambda i: bounds[i])
    tcrit = float(student_t.ppf(1 - delta / len(others), fit.pure_error_df))
    out = RegretBound(max(0.0, bounds[arg]), others[arg].levels, delta,
                      "bonferroni_one_sided_t",
                      f"M={len(others)} challengers, df={fit.pure_error_df}, t={tcrit:.3f}")
    if profile:
        order = sorted(bounds, key=lambda i: -bounds[i])
        head, tail = order[:profile], order[profile:]
        out = dataclasses.replace(out, profile={
            "top": [{"levels": others[i].levels, "bound": bounds[i]} for i in head],
            "rest": max((bounds[i] for i in tail), default=None),
            "challengers": len(others)})
    return out


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
