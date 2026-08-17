"""The certificate must COVER: over many replays the true gap exceeds R at
most a delta fraction of the time (paper eq. 2). Monte-Carlo on a correctly
specified synthetic surface; no work_dir, no LLM — fits are milliseconds.
"""
from __future__ import annotations

import math
import random

import pytest

from orchestrator.optimize.certificate import model_regret_bound, resolve_epsilon
from orchestrator.optimize.decide import predict, ranked
from orchestrator.optimize.design import full_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import expand
from orchestrator.optimize.synthetic import SURFACES, true_optimum


def _fit_and_rank(surface, seed):
    factors = parse_factors(list(surface.factors))
    ids = [f.id for f in factors]
    d = with_center_points(full_factorial(ids), 4)
    rng = random.Random(seed)
    rows = expand(d, factors)
    ys = [surface.fn(r.levels) + rng.gauss(0, surface.noise_sd) for r in rows]
    fit = fit_effects(d, ys, factor_ids=ids)
    scored = ranked(fit, factors, direction="maximize", fitted_ids=ids,
                    held_fixed={}, top=None)
    return fit, scored


def _replay(surface, seed, delta):
    _fit, top = _fit_and_rank(surface, seed)
    xhat = top[0]
    bound = model_regret_bound(_fit, top, xhat, delta=delta, direction="maximize")
    _, best = true_optimum(surface)
    true_gap = best - surface.fn(xhat.levels)
    return bound, true_gap


def test_bound_is_none_without_a_pure_error_estimate():
    s = SURFACES["additive"]()
    factors = parse_factors(list(s.factors)); ids = [f.id for f in factors]
    d = full_factorial(ids)                                     # no centre points
    fit = fit_effects(d, [s.fn(r.levels) for r in expand(d, factors)], factor_ids=ids)
    top = ranked(fit, factors, direction="maximize", fitted_ids=ids, held_fixed={})
    b = model_regret_bound(fit, top, top[0], delta=0.05, direction="maximize")
    assert b.value is None and b.method == "none"


def test_coverage_on_a_correctly_specified_surface():
    s = SURFACES["additive"]()
    delta, misses, n = 0.10, 0, 300
    for seed in range(n):
        bound, gap = _replay(s, seed, delta)
        assert bound.value is not None and bound.value >= 0
        if gap > bound.value + 1e-12:
            misses += 1
    assert misses / n <= delta + 0.03, misses


def test_coverage_when_x_hat_actually_misses_the_optimum():
    """The test above, made non-degenerate.

    On ``additive`` at its declared ``noise_sd=0.05`` the argmax lands on the
    true optimum in all 300 replays — measured, and reproducibly so out to
    3000 seeds. That makes ``true_gap`` identically 0, and since ``R >= 0`` by
    construction the coverage assertion passes for ANY implementation,
    including a constant ``0.0``: verified by rerunning that test at
    ``delta=0.999`` (t ~ 0, so R collapses to ~0) — still zero misses. It is a
    necessary regression test, but on its own it demonstrates nothing about
    coverage.

    Turning the noise up to 2.0 makes the argmax miss on roughly half the
    replays (measured: 152/300 with a gap up to 3.5), so a bound that is too
    narrow is now caught. Coverage still holds well inside delta.
    """
    import dataclasses
    s = dataclasses.replace(SURFACES["additive"](), noise_sd=2.0)
    delta, misses, n, nonzero = 0.10, 0, 300, 0
    for seed in range(n):
        bound, gap = _replay(s, seed, delta)
        assert bound.value is not None and bound.value >= 0
        if gap > 1e-9:
            nonzero += 1
        if gap > bound.value + 1e-12:
            misses += 1
    assert nonzero > n // 4, f"gap degenerate again ({nonzero}/{n} nonzero)"
    assert misses / n <= delta, misses


def test_the_bound_is_simultaneous_over_every_challenger():
    """What Bonferroni actually buys, asserted directly.

    ``R = max_z U(z, x_hat)`` is a valid bound on the true optimality gap only
    if, on the same draw, EVERY challenger's own ``U(z, x_hat)`` covers its
    true gap ``f(z) - f(x_hat)``: the true maximiser is one of them, and the
    max of the bounds dominates it only when its own bound holds. So the
    honest test is the FAMILY-wise error rate, not one bound at a time.

    Individual ``t_{1-delta}`` intervals would fail this: the max over M
    correlated intervals breaks as soon as any one does. Measured with the
    Bonferroni divisor removed from ``model_regret_bound``'s ``tcrit``:
    169/500 replays at noise 0.5 and 284/500 at noise 2.0 contain at least one
    violated challenger, against a nominal 10% — and even the top-level R
    claim then misses 22/500 and 56/500, with no slack at all. With the
    divisor in place the same measurement gives 1/500 and 2/500.
    """
    import dataclasses

    from scipy.stats import t as student_t

    delta, n, families_violated = 0.10, 200, 0
    s = dataclasses.replace(SURFACES["additive"](), noise_sd=0.5)
    for seed in range(n):
        fit, cands = _fit_and_rank(s, seed)
        xhat = cands[0]
        others = [c for c in cands if c.levels != xhat.levels]
        terms = list(fit.effects) + list(fit.quadratic)
        tcrit = float(student_t.ppf(1 - delta / len(others), fit.pure_error_df))
        fx = predict(fit, xhat.coded)
        f_true_x = s.fn(xhat.levels)
        for z in others:
            var = sum(
                (e.se or 0.0) ** 2
                * (math.prod(float(z.coded[t]) for t in e.terms)
                   - math.prod(float(xhat.coded[t]) for t in e.terms)) ** 2
                for e in terms
            )
            u = (predict(fit, z.coded) - fx) + tcrit * math.sqrt(var)
            if s.fn(z.levels) - f_true_x > u + 1e-12:
                families_violated += 1
                break
    assert families_violated / n <= delta, families_violated


def test_bound_shrinks_with_less_noise():
    import dataclasses
    s = SURFACES["additive"]()
    loud, _ = _replay(dataclasses.replace(s, noise_sd=0.5), 1, 0.05)
    quiet, _ = _replay(dataclasses.replace(s, noise_sd=0.01), 1, 0.05)
    assert quiet.value < loud.value


def test_bound_names_the_challenger_keeping_it_large():
    """Spec §3.6 rung 2 directs the next experiment at that challenger, so the
    number alone is not enough — the configuration has to come with it."""
    import dataclasses
    s = dataclasses.replace(SURFACES["additive"](), noise_sd=0.5)
    fit, cands = _fit_and_rank(s, 3)
    b = model_regret_bound(fit, cands, cands[0], delta=0.05, direction="maximize")
    assert b.value > 0 and b.method == "bonferroni_one_sided_t"
    assert b.challenger in [c.levels for c in cands]
    assert b.challenger != cands[0].levels
    assert f"M={len(cands) - 1}" in b.detail


def test_a_single_candidate_space_has_no_challenger():
    s = SURFACES["additive"]()
    fit, cands = _fit_and_rank(s, 0)
    b = model_regret_bound(fit, cands[:1], cands[0], delta=0.05, direction="maximize")
    assert b.value == 0.0 and b.challenger is None and b.method == "trivial"


def test_minimize_uses_the_other_sign():
    """``direction`` must flip which challengers look threatening. With the sign
    ignored, a minimisation campaign would certify the WORST configuration."""
    s = SURFACES["additive"]()
    fit, cands = _fit_and_rank(s, 0)
    worst = min(cands, key=lambda c: c.predicted)
    # `worst` IS the argmax under minimize, so its bound should be the small
    # one; the maximize-argmax should look badly beatable under minimize.
    b_worst = model_regret_bound(fit, cands, worst, delta=0.05, direction="minimize")
    b_best = model_regret_bound(fit, cands, cands[0], delta=0.05, direction="minimize")
    assert b_worst.value < b_best.value


def test_resolve_epsilon_abs_and_pct():
    assert resolve_epsilon({"abs": 0.5}, 100.0) == 0.5
    assert resolve_epsilon({"pct": 2.0}, 50.0) == pytest.approx(1.0)
