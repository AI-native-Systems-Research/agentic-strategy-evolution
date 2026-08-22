"""The certificate must COVER: over many replays the true gap exceeds R at
most a delta fraction of the time (paper eq. 2). Monte-Carlo on a correctly
specified synthetic surface; no work_dir, no LLM — fits are milliseconds.
"""
from __future__ import annotations

import math
import random

import pytest

from orchestrator.optimize.certificate import (
    _challenger_bounds,
    model_regret_bound,
    resolve_epsilon,
    terminal_regret_bound,
)
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


def _model_challenger_bounds(fit, cands, xhat, *, delta, direction="maximize"):
    """Every challenger's ``U(z, x_hat)`` from the SHIPPED arithmetic.

    Drives ``certificate._challenger_bounds`` with the same ``contrast``
    closure ``model_regret_bound`` builds, so a family-wise assertion below
    measures the code that ships rather than a local copy of it.

    This helper exists because the previous version of the simultaneity test
    reimplemented the whole contrast — estimate, variance sum over terms, and
    the Bonferroni quantile — inside the test body. That test would have
    passed with ``certificate.py`` deleted, which makes it a test of the
    reviewer's arithmetic and not of the certificate. Any change to how the
    bound is computed must now be visible here.
    """
    sign = 1.0 if direction != "minimize" else -1.0
    terms = list(fit.effects) + list(fit.quadratic)
    others = [c for c in cands if c.levels != xhat.levels]
    fx = predict(fit, xhat.coded)

    def contrast(z):
        est = sign * (predict(fit, z.coded) - fx)
        var = sum(
            (e.se or 0.0) ** 2
            * (math.prod(float(z.coded[t]) for t in e.terms)
               - math.prod(float(xhat.coded[t]) for t in e.terms)) ** 2
            for e in terms
        )
        return est, math.sqrt(var), float(fit.pure_error_df)

    raw = _challenger_bounds(others, contrast, delta=delta)
    return [(others[i], raw[i]) for i in sorted(raw)]


def test_the_bound_is_simultaneous_over_every_challenger():
    """What Bonferroni actually buys, asserted directly.

    ``R = max_z U(z, x_hat)`` is a valid bound on the true optimality gap only
    if, on the same draw, EVERY challenger's own ``U(z, x_hat)`` covers its
    true gap ``f(z) - f(x_hat)``: the true maximiser is one of them, and the
    max of the bounds dominates it only when its own bound holds. So the
    honest test is the FAMILY-wise error rate, not one bound at a time.

    Individual ``t_{1-delta}`` intervals would fail this: the max over M
    correlated intervals breaks as soon as any one does. Measured with the
    Bonferroni divisor removed from ``_challenger_bounds``: 169/500 replays at
    noise 0.5 and 284/500 at noise 2.0 contain at least one violated
    challenger, against a nominal 10% — and even the top-level R claim then
    misses 22/500 and 56/500, with no slack at all. With the divisor in place
    the same measurement gives 1/500 and 2/500.

    Driven through ``_challenger_bounds`` (the seam both flavours share), so
    removing the divisor from the shipped code is what makes this fail.
    """
    import dataclasses

    delta, n, families_violated = 0.10, 200, 0
    s = dataclasses.replace(SURFACES["additive"](), noise_sd=0.5)
    for seed in range(n):
        fit, cands = _fit_and_rank(s, seed)
        xhat = cands[0]
        f_true_x = s.fn(xhat.levels)
        for z, u in _model_challenger_bounds(fit, cands, xhat, delta=delta):
            if s.fn(z.levels) - f_true_x > u + 1e-12:
                families_violated += 1
                break
    assert families_violated / n <= delta, families_violated


def test_the_reported_R_is_the_max_of_the_shipped_challenger_bounds():
    """``model_regret_bound``'s number is exactly ``max_z`` of that family.

    Ties the two paths together: without this, the family-wise test above and
    the coverage tests could hold of ``_challenger_bounds`` while
    ``model_regret_bound`` reported something else entirely.

    ``max(0.0, ...)`` is the documented floor — the true gap to the optimum
    cannot be negative — and the challenger is named even when the floor wins,
    because "which challenger is closest" is useful either way.
    """
    import dataclasses
    s = dataclasses.replace(SURFACES["additive"](), noise_sd=0.5)
    fit, cands = _fit_and_rank(s, 7)
    b = model_regret_bound(fit, cands, cands[0], delta=0.10, direction="maximize")
    family = _model_challenger_bounds(fit, cands, cands[0], delta=0.10)
    assert b.value == pytest.approx(max(0.0, max(u for _z, u in family)))
    assert b.challenger == max(family, key=lambda p: p[1])[0].levels


def test_model_coverage_on_a_central_composite_fit():
    """The quadratic-term blind spot Task 8 acknowledged, measured.

    ``effects.py`` documents that pure-quadratic columns on a central
    composite are CORRELATED, so the variance sum in ``model_regret_bound``
    (which assumes uncorrelated coefficients) understates the true variance of
    a difference involving them — by ~1.46x on the designs this package
    builds. Task 8's coverage tests all ran on ``additive``, a plane, whose
    fit has no quadratic term at all, so nothing measured whether the
    optimism actually costs coverage.

    ``bowl`` is a genuine quadratic surface, and ``_fit_and_rank`` builds a
    full factorial with centre points over it — which is exactly the
    mis-specified case (no axial points, so the quadratic term is not
    estimable and the response class is wrong for the surface). Measured at
    ``noise_sd=1.0``: the argmax misses the true optimum on 300/300 replays
    with gaps up to 2.3, and coverage still holds at 0/300 misses. So the
    known optimism does not show up as under-coverage here — the
    conservatism Bonferroni buys dominates it.

    This does NOT retire the assumption: the bound still carries the response
    class, as spec §3.5 says. What it retires is the worry that the
    correlated-quadratic factor silently breaks the delta guarantee on the
    designs this package actually generates.
    """
    import dataclasses
    s = dataclasses.replace(SURFACES["bowl"](), noise_sd=1.0)
    delta, misses, n, nonzero = 0.10, 0, 300, 0
    for seed in range(n):
        bound, gap = _replay(s, seed, delta)
        assert bound.value is not None and bound.value >= 0
        if gap > 1e-9:
            nonzero += 1
        if gap > bound.value + 1e-12:
            misses += 1
    assert nonzero > n // 4, f"gap degenerate ({nonzero}/{n} nonzero)"
    assert misses / n <= delta, misses


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


# ─── the TERMINAL bound: model-free, from fresh finalist replicates ────────
#
# Spec §3.5's second flavour. Nothing below constructs a Fit: the whole point
# of the terminal stage (paper, §Design) is that the final comparison rests on
# measurements taken AT the finalists rather than on the fitted surface.


def test_terminal_bound_is_none_with_fewer_than_two_replicates():
    """One measurement gives no variance estimate, and unknown is not zero.

    Returning 0.0 here would certify a single-replicate confirm as
    epsilon-optimal on no evidence at all — the failure mode this whole module
    exists to refuse.
    """
    b = terminal_regret_bound({"x": [1.0], "y": [2.0]}, "y",
                              delta=0.05, direction="maximize", paired=False)
    assert b.value is None and b.method == "none"


def test_terminal_bound_certifies_a_clear_winner_and_not_a_close_race():
    clear = terminal_regret_bound({"x": [1.0, 1.1, 0.9, 1.0], "y": [5.0, 5.1, 4.9, 5.0]},
                                  "y", delta=0.05, direction="maximize", paired=False)
    close = terminal_regret_bound({"x": [4.9, 5.2, 4.8, 5.1], "y": [5.0, 5.1, 4.9, 5.0]},
                                  "y", delta=0.05, direction="maximize", paired=False)
    assert clear.value < 0.5 and close.value > 0.2 and clear.challenger == "x"


def test_terminal_bound_names_the_closest_finalist_even_when_it_certifies():
    """A floored value still names its challenger (spec §3.6 rung 2).

    With ``y`` five units clear of ``x`` every challenger bound is NEGATIVE, so
    ``value`` floors at 0.0 — and returning ``challenger=None`` alongside it
    would lose the one fact a reader of ``confirmation.json`` wants next: which
    finalist came closest. ``value`` is the bound; ``challenger`` is a pointer.
    """
    b = terminal_regret_bound({"x": [1.0, 1.1, 0.9, 1.0], "z": [0.1, 0.2, 0.0, 0.1],
                               "y": [5.0, 5.1, 4.9, 5.0]}, "y",
                              delta=0.05, direction="maximize", paired=False)
    assert b.value == 0.0
    assert b.challenger == "x", "the nearer of the two losers, not either at random"


def test_terminal_bound_respects_minimize():
    """With the sign ignored, a minimisation campaign certifies the WORST
    finalist: ``x`` (mean 1.0) is the winner under minimize, and ``y`` (5.0)
    is no threat to it."""
    b = terminal_regret_bound({"x": [1.0, 1.1, 0.9], "y": [5.0, 5.1, 4.9]}, "x",
                              delta=0.05, direction="minimize", paired=False)
    assert b.value < 0.5
    flipped = terminal_regret_bound({"x": [1.0, 1.1, 0.9], "y": [5.0, 5.1, 4.9]}, "y",
                                    delta=0.05, direction="minimize", paired=False)
    assert flipped.value > 3.5, "under minimize, y must look badly beatable by x"


def test_terminal_bound_with_a_single_finalist_is_trivially_zero():
    b = terminal_regret_bound({"only": [1.0, 2.0]}, "only",
                              delta=0.05, direction="maximize", paired=False)
    assert b.value == 0.0 and b.method == "trivial"


def test_terminal_bound_pairs_under_common_random_numbers():
    """Pairing removes the shared seed effect, so the bound shrinks (spec §3.8).

    Constructed so the two finalists move together run to run (a large shared
    per-seed component) while their DIFFERENCE is nearly constant. Welch sees
    two high-variance samples; the paired form sees a tight difference. That
    gap is what makes a noisy systems target measurable inside a realistic
    budget, and is why Task 14 turns pairing on.
    """
    xb = [10.0, 20.0, 30.0, 40.0]
    xk = [10.4, 20.5, 30.4, 40.5]           # +0.45 +/- 0.05, on a 30-wide spread
    unpaired = terminal_regret_bound({"b": xb, "k": xk}, "k", delta=0.05,
                                     direction="maximize", paired=False)
    pairedb = terminal_regret_bound({"b": xb, "k": xk}, "k", delta=0.05,
                                    direction="maximize", paired=True)
    assert pairedb.value < unpaired.value
    assert pairedb.method.endswith("_paired")
    assert unpaired.method == "bonferroni_one_sided_welch_t"


def test_terminal_pairing_falls_back_to_welch_on_ragged_replicate_counts():
    """A finalist excluded on one replicate leaves the samples unequal in
    length, and there is nothing left to pair — zip would silently DROP the
    extra measurements, computing a paired bound over an arbitrary prefix."""
    b = terminal_regret_bound({"b": [1.0, 2.0, 3.0], "k": [1.5, 2.5]}, "b",
                              delta=0.05, direction="maximize", paired=True)
    assert b.method == "bonferroni_one_sided_welch_t"


def _terminal_replay(truth: dict, *, seed: int, noise: float, reps: int,
                     delta: float):
    """One replay: measure every finalist ``reps`` times, bound the winner."""
    from statistics import mean as _mean
    rng = random.Random(seed)
    samples = {k: [v + rng.gauss(0, noise) for _ in range(reps)]
               for k, v in truth.items()}
    best = max(samples, key=lambda k: _mean(samples[k]))
    b = terminal_regret_bound(samples, best, delta=delta, direction="maximize",
                              paired=False)
    return b, max(truth.values()) - truth[best]


def test_terminal_coverage_over_replays():
    """The terminal certificate must COVER (paper eq. 2 at the terminal stage).

    Three DISTINCT true means with real separation, and noise large enough
    relative to the gaps that the argmax over four replicates genuinely misses
    sometimes — MEASURED, not assumed: 41 of 400 replays pick a finalist that
    is not the true best (gap 0.3), and 20 of those 400 have the true gap
    exceed the bound, a 5% miss rate inside the nominal 10%.

    The ``nonzero`` guard is the lesson from ``additive``'s degenerate
    coverage test (see ``test_coverage_when_x_hat_actually_misses_the_optimum``
    for the full account): a surface where the argmax never misses makes
    ``true_gap`` identically 0, and since R >= 0 by construction the assertion
    then passes for ANY implementation including a constant 0.0.
    """
    delta, misses, n, nonzero = 0.10, 0, 400, 0
    truth = {"a": 10.0, "b": 10.3, "c": 9.5}
    for seed in range(n):
        b, gap = _terminal_replay(truth, seed=seed, noise=0.3, reps=4, delta=delta)
        assert b.value is not None and b.value >= 0
        if gap > 1e-9:
            nonzero += 1
        if gap > b.value:
            misses += 1
    assert nonzero > 0, "the argmax never missed; coverage here is vacuous"
    assert misses / n <= delta + 0.03, misses


def test_terminal_coverage_is_discriminating_at_a_wider_spread():
    """The test above passes for a constant 0.0; this one does not.

    MEASURED on the three-mean surface at noise 0.3: a hypothetical
    ``value=0.0`` implementation misses on 41/400 = 10.25% of replays, which
    sits UNDER that test's ``delta + 0.03 = 13%`` threshold — so it would
    accept a certificate that certifies everything. The cause is that only two
    of the three finalists ever win there, so the true gap is either 0 or
    exactly 0.3, and the miss rate saturates just below the bar.

    Raising the noise to 0.5 spreads which finalist wins (136/600 replays now
    pick a loser, including the far-behind ``c``), and the degenerate
    implementation's miss rate rises to 22.7% — comfortably outside. The real
    bound measures 6.3%. Dropping the Bonferroni divisor measures 11.8%, which
    this threshold does NOT catch; that property is asserted family-wise
    instead, in ``test_the_bound_is_simultaneous_over_every_challenger``.

    Keep both tests: the tighter one pins the calibration, this one pins that
    a vacuous implementation is rejected.
    """
    delta, misses, n, nonzero, ever_zero = 0.10, 0, 600, 0, 0
    truth = {"a": 10.0, "b": 10.3, "c": 9.5}
    for seed in range(n):
        b, gap = _terminal_replay(truth, seed=seed, noise=0.5, reps=4, delta=delta)
        if gap > 1e-9:
            nonzero += 1
            if gap > b.value:
                misses += 1
        if b.value == 0.0:
            ever_zero += 1
    assert nonzero > n // 8, f"gap degenerate ({nonzero}/{n} nonzero)"
    # A constant-0.0 bound would miss on every one of those `nonzero` replays.
    assert nonzero / n > delta + 0.03, (
        f"a value=0.0 implementation would miss {nonzero}/{n} and still pass; "
        f"this scenario has lost its discriminating power"
    )
    assert misses / n <= delta, misses
