"""Second-order fits carry the exact (X'X)^-1 (final expert audit H1).

The certificate's model regret bound is gated on contrasts between candidates,
which on a refine (composite) fit involve the correlated pure quadratics. The
per-column SE understated those contrasts by 1.3-1.5x, so the model half's
union bound sat near 0.11 against its stated 0.05. Checked against numpy.
"""

from __future__ import annotations

import numpy as np
import pytest

from orchestrator.optimize.design import central_composite
from orchestrator.optimize.effects import fit_effects, prediction_variance


@pytest.mark.parametrize("k", [2, 3])
def test_a_second_order_fit_uses_the_exact_covariance(k):
    ids = tuple("ABC"[:k])
    d = central_composite(list(ids), center_points=3)
    rng = np.random.default_rng(0)
    ys = [float(rng.normal()) for _ in d.points]
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.covariance is not None, "a composite fit must keep (X'X)^-1"
    X = np.array([[1.0] + [np.prod([p.coded[ids.index(t)] for t in ts])
                           for ts in fit.term_terms[1:]] for p in d.points])
    exact = np.linalg.inv(X.T @ X)
    assert np.allclose(np.array(fit.covariance), exact, atol=1e-9)
    # A contrast between two points involving the quadratics: the reported
    # variance equals s^2 d'(X'X)^-1 d -- the quantity the certificate uses.
    xa = {t: 1.0 for t in ids}
    xb = {t: 0.0 for t in ids}
    row = lambda x: np.array([1.0] + [np.prod([x[t] for t in ts])
                                      for ts in fit.term_terms[1:]])
    dvec = row(xa) - row(xb)
    want = fit.pure_error_var * float(dvec @ exact @ dvec)
    assert prediction_variance(fit, xa, xb) == pytest.approx(want, rel=1e-9)


def test_a_first_order_fit_is_unchanged():
    from orchestrator.optimize.design import fractional_factorial, with_center_points

    d = with_center_points(fractional_factorial(list("ABCDE"), 5), 4)
    rng = np.random.default_rng(1)
    fit = fit_effects(d, [float(rng.normal()) for _ in d.points], factor_ids=tuple("ABCDE"))
    assert fit.covariance is None


# ── P8 audit: a two-level fit that LOST rows is non-orthogonal ───────────────
#
# Found by the P8 expert audit (the P2 review's L6). The per-column SE
# sigma / sqrt(sum x^2) is exact only on the full balanced design. With corners
# lost (failed, rejected, censored, infeasible-excluded) the main-effect and
# 2fi columns are correlated, and the model bound's contrast SE was too small:
# on a 2^3 screen with 4 centres and the two opposite corners lost, the model
# family's worst-case Pr(E_s fails) was 0.085 against a nominal 0.05.

import dataclasses
import itertools
import math
import random


def _screen_without(k: int, lost: str):
    from orchestrator.optimize.design import full_factorial, with_center_points

    ids = [chr(65 + i) for i in range(k)]
    d = with_center_points(full_factorial(ids), 4)
    pts = list(d.points)
    corners = [i for i, p in enumerate(pts) if p.role != "center"]
    lo = next(i for i in corners if all(c < 0 for c in pts[i].coded))
    hi = next(i for i in corners if all(c > 0 for c in pts[i].coded))
    drop = {"opposite": {lo, hi}, "one": {hi}}[lost]
    return ids, dataclasses.replace(
        d, points=tuple(p for i, p in enumerate(pts) if i not in drop))


@pytest.mark.parametrize("k,lost", [(3, "opposite"), (3, "one"), (2, "one")])
def test_a_two_level_fit_that_lost_rows_uses_the_exact_covariance(k, lost):
    ids, d = _screen_without(k, lost)
    rng = np.random.default_rng(3)
    fit = fit_effects(d, [float(rng.normal()) for _ in d.points], factor_ids=ids)
    assert fit.covariance is not None, "a non-orthogonal fit must keep (X'X)^-1"
    X = np.array([[1.0] + [np.prod([p.coded[ids.index(t)] for t in ts])
                           for ts in fit.term_terms[1:]] for p in d.points])
    exact = np.linalg.inv(X.T @ X)
    assert np.allclose(np.array(fit.covariance), exact, atol=1e-9)
    for e, j in zip(fit.effects, range(1, X.shape[1])):
        assert e.se == pytest.approx(math.sqrt(fit.pure_error_var * exact[j, j]), rel=1e-9)
    # Every corner-vs-corner contrast the model bound uses: s^2 d'(X'X)^-1 d.
    grid = [dict(zip(ids, c)) for c in itertools.product([-1.0, 1.0], repeat=k)]
    row = lambda x: np.array([1.0] + [np.prod([x[t] for t in ts])
                                      for ts in fit.term_terms[1:]])
    for a, b in itertools.combinations(grid, 2):
        dv = row(a) - row(b)
        assert prediction_variance(fit, a, b) == pytest.approx(
            fit.pure_error_var * float(dv @ exact @ dv), rel=1e-9)


def test_the_model_family_holds_its_level_after_two_opposite_corners_are_lost():
    """Truth-free: under the registered class est - f is pure noise, so E_s's
    failure rate is the worst case over surfaces. Pinned seeds; pre-fix
    0.085 +- 0.004 on 4000 fits, 0.031 exact (nous-e2e/audit/p8)."""
    from orchestrator.optimize.certificate import model_regret_bound
    from orchestrator.optimize.decide import Candidate, predict

    ids, d = _screen_without(3, "opposite")
    grid = [dict(zip(ids, c)) for c in itertools.product([-1.0, 1.0], repeat=3)]
    n, delta = 1500, 0.05
    fails = [0] * len(grid)
    for s in range(n):
        r = random.Random(7000 + s)
        fit = fit_effects(d, [r.gauss(0, 1) for _ in d.points], factor_ids=ids)
        cands = [Candidate(levels=dict(g), coded=dict(g), predicted=predict(fit, g))
                 for g in grid]
        for a, xs in enumerate(cands):
            # x* = xs: E_s fails when some z's bound against x* is below 0
            # (truth is flat, so every true gain is 0).
            b = model_regret_bound(fit, cands, xs, delta=delta, direction="maximize",
                                   profile=len(grid))
            # The event is "some challenger's est + c se < 0 while its true
            # gain is 0" -- the mirror of e(z) - e(x*) > c se, the same law.
            fails[a] += any(e["bound"] < 0.0 for e in b.profile["top"])
    worst = max(fails) / n
    se = math.sqrt(delta * (1 - delta) / n)
    assert worst <= delta + 2 * se, (worst, fails)


def _lost_opposite_corners():
    from orchestrator.optimize.synthetic import Surface, _numeric

    # Four two-level numerics (none refinable, so screen -> confirm and
    # model_class_unchecked does not apply). The target fails to measure the
    # all-low and the all-high corner: a loss spread over both levels of every
    # factor, so exclusion_balance does NOT flag it as level-correlated and
    # nothing else withholds on it.
    return Surface(
        name="lost_opposite_corners", noise_sd=0.05,
        factors=tuple(_numeric(f, levels=(2, 16)) for f in "ABCD"),
        fn=lambda lv: 10 + 0.05 * lv["A"] - 0.03 * lv["B"] + 0.02 * lv["C"] - 0.01 * lv["D"],
        fails_at=lambda lv: (len({lv["A"], lv["B"], lv["C"], lv["D"]}) == 1
                             and lv["A"] in (2, 16)))


def test_a_campaign_that_lost_two_opposite_corners_bounds_with_the_exact_covariance(tmp_path):
    """End to end: the recorded model bound equals the one computed from the
    exact (X'X)^-1 of the rows the screen actually fitted. Pre-fix, seed 1
    CERTIFIED on the per-column SE, which is too small on this design."""
    import json

    from orchestrator.optimize.harness import run_synthetic_campaign

    r = run_synthetic_campaign(_lost_opposite_corners(), seed=1, parent_dir=tmp_path,
                               campaign_overrides={"stages": ["verify", "screen", "confirm"]})
    it = next(p for p in sorted((r.work_dir / "runs").iterdir())
              if (p / "effects.json").exists())
    eff = json.loads((it / "effects.json").read_text())
    rec = json.loads((it / "recommendation.json").read_text())
    assert rec["exclusion_balance"]["n_excluded"] == 2
    assert rec["exclusion_balance"]["level_correlated"] is False
    ids = eff["fit_coordinates"]["factor_ids"]
    rows = [x["fitted"] for x in eff["fit_coordinates"]["rows"]
            if x["status"] in ("complete", "infeasible")]
    terms = [tuple(e["terms"]) for e in eff["effects"]]
    beta = np.array([eff["intercept"]] + [e["estimate"] for e in eff["effects"]])
    feat = lambda x: np.array([1.0] + [np.prod([x[ids.index(t)] for t in ts]) for ts in terms])
    X = np.array([feat(x) for x in rows])
    C = np.linalg.inv(X.T @ X)
    s2 = eff["pure_error_var"]
    crit = rec["residual_regret_model"]["critical"]["value"]
    xh = [rec["coded"][f] for f in ids]
    grid = [list(c) for c in itertools.product([-1.0, 1.0], repeat=len(ids))]
    want = max(0.0, max(float((feat(z) - feat(xh)) @ beta)
                        + crit * math.sqrt(s2 * float((feat(z) - feat(xh)) @ C
                                                      @ (feat(z) - feat(xh))))
                        for z in grid if z != xh))
    assert rec["residual_regret_model"]["value"] == pytest.approx(want, rel=1e-9)
