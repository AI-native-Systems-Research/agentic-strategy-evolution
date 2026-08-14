"""Behavioral tests for effect estimation.

The oracle is a planted linear model: synthesize responses from known
coefficients, fit them, and assert the recovered values match the planted
ones. That is independent of this module's implementation — a wrong fitter
cannot fake it.

Every float assertion uses math.isclose: the closed form carries ~1e-16
representation error and `==` would be flaky (verified).
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize.design import (
    central_composite,
    fractional_factorial,
    full_factorial,
    with_center_points,
)
from orchestrator.optimize.effects import (
    dropped_factors,
    fit_effects,
    pure_error,
    solve_stationary_point,
)

TOL = {"rel_tol": 1e-9, "abs_tol": 1e-9}


def _synth(design, factor_ids, intercept, mains, inter=None):
    """Response values from a known linear model over the design's corners."""
    inter = inter or {}
    out = []
    for p in design.points:
        if p.role != "corner":
            out.append(intercept)          # center/axial at the model's center
            continue
        y = intercept
        for j, fid in enumerate(factor_ids):
            y += mains.get(fid, 0.0) * p.coded[j]
        for (a, b), coef in inter.items():
            ia, ib = factor_ids.index(a), factor_ids.index(b)
            y += coef * p.coded[ia] * p.coded[ib]
        out.append(y)
    return out


def test_recovers_planted_main_effects_on_a_full_factorial():
    ids = ("A", "B", "C")
    d = full_factorial(ids)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.5})
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=False)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(fit.intercept, 10.0, **TOL)
    assert math.isclose(got["A"], -0.95, **TOL)
    assert math.isclose(got["B"], 2.0, **TOL)
    assert math.isclose(got["C"], 0.5, **TOL)


def test_recovers_the_l5_sign_flip_negative_main_positive_interaction():
    """The motivating case: batching is -9.5% alone but required for the
    winning compound. A fitter that cannot separate these is useless here.
    """
    ids = ("A", "B", "C")
    d = full_factorial(ids)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.5},
                {("A", "B"): 1.6})
    fit = fit_effects(d, ys, factor_ids=ids)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(got["A"], -0.95, **TOL), "main effect must stay negative"
    assert math.isclose(got["AB"], 1.6, **TOL), "interaction must stay positive"
    assert got["A"] < 0 < got["AB"]
    # the compound beats the sum of the parts at the (+1,+1) corner
    assert got["A"] + got["B"] + got["AB"] > got["B"]


def test_recovers_planted_effects_on_a_resolution_v_fractional_design():
    ids = ("A", "B", "C", "D", "E")
    d = fractional_factorial(ids, resolution=5)
    ys = _synth(d, ids, 5.0,
                {"A": 1.0, "B": -0.4, "C": 0.0, "D": 0.25, "E": 0.75},
                {("A", "B"): 0.9})
    fit = fit_effects(d, ys, factor_ids=ids)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(got["A"], 1.0, **TOL)
    assert math.isclose(got["B"], -0.4, **TOL)
    assert math.isclose(got["E"], 0.75, **TOL)
    assert math.isclose(got["AB"], 0.9, **TOL)
    assert math.isclose(got["C"], 0.0, **TOL)


def test_a_null_factor_is_estimated_at_zero():
    ids = ("A", "B")
    d = full_factorial(ids)
    ys = _synth(d, ids, 3.0, {"A": 1.5, "B": 0.0})
    fit = fit_effects(d, ys, factor_ids=ids)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(got["B"], 0.0, **TOL)


def test_pure_error_from_replicated_center_points():
    reps = [10.02, 9.97, 10.05, 9.99, 10.01]
    var, df = pure_error(reps)
    assert df == 4
    assert math.isclose(var, 0.00092, rel_tol=1e-6)


def test_pure_error_needs_at_least_two_replicates():
    var, df = pure_error([10.0])
    assert var is None and df == 0


def test_confidence_interval_excludes_zero_for_a_real_effect():
    ids = ("A", "B", "C", "D", "E")
    d = with_center_points(fractional_factorial(ids, resolution=5), 5)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.0, "D": 0.0, "E": 0.0})
    # perturb the center replicates so pure error is non-zero
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.02, -0.03, 0.05, -0.01, 0.01], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    by = {e.label: e for e in fit.effects}
    assert by["A"].ci_high is not None and by["A"].ci_high < 0
    assert by["A"].significant is True
    assert by["C"].significant is False


def test_significance_uses_the_terms_own_column_not_the_total_row_count():
    """Regression for the per-term SE bug: SE must come from that term's own
    column sum of squares (corners only, for a two-level design), not from
    pe_var / n_total_rows. Center points add rows but contribute 0 to a
    +/-1 column's sum of squares, so an n-based scalar SE is too small and
    a borderline null effect reads as falsely significant.

    On this res-V 5-factor + 5-center design (16 corners, 21 rows total),
    the wrong scalar SE gives a CI half-width of ~0.0184; the correct
    per-column SE gives ~0.0211. A planted main effect of 0.0200 sits
    between the two: the buggy formula calls it significant, the correct
    one does not.
    """
    ids = ("A", "B", "C", "D", "E")
    d = with_center_points(fractional_factorial(ids, resolution=5), 5)
    ys = _synth(d, ids, 10.0, {"A": 0.02, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.02, -0.03, 0.05, -0.01, 0.01], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    by = {e.label: e for e in fit.effects}
    assert by["A"].significant is False, (
        "0.02 sits inside the correct (per-column) CI half-width ~0.0211 "
        "but outside the buggy (total-row-count) half-width ~0.0184 -- "
        "significant=True here would mean the total-row-count SE regressed"
    )
    assert math.isclose(by["A"].se, math.sqrt(fit.pure_error_var / 16), rel_tol=1e-9)


def test_dropped_factors_are_those_whose_interval_contains_zero():
    ids = ("A", "B", "C", "D", "E")
    d = with_center_points(fractional_factorial(ids, resolution=5), 5)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.0, "D": 0.0, "E": 0.0})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.02, -0.03, 0.05, -0.01, 0.01], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    dropped = dropped_factors(fit, ids)
    assert "A" not in dropped and "B" not in dropped
    assert {"C", "D", "E"} <= set(dropped)


def test_lack_of_fit_is_reported_when_center_points_exist():
    ids = ("A", "B")
    d = with_center_points(full_factorial(ids), 4)
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.01, -0.01, 0.02, -0.02], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.pure_error_df == 3
    assert fit.lack_of_fit_p is not None


def test_strong_curvature_is_detected_as_lack_of_fit():
    """Center response far from the corner mean means the linear model is
    inadequate — the trigger that escalates to the model (spec 6.3).
    """
    ids = ("A", "B")
    d = with_center_points(full_factorial(ids), 4)
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    # large, consistent curvature with small distinct perturbations so pure
    # error is non-zero (identical replicates give pe_var == 0, which
    # correctly disables the F test rather than dividing by zero)
    for offset, i in zip([0.0, -0.02, 0.02, -0.01], centers):
        ys[i] = 14.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.lack_of_fit_p is not None and fit.lack_of_fit_p < 0.05


def test_no_center_points_means_no_lack_of_fit_verdict():
    ids = ("A", "B")
    d = full_factorial(ids)
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.pure_error_var is None
    assert fit.lack_of_fit_p is None
    assert all(e.significant is None for e in fit.effects)


def test_response_length_must_match_the_design():
    ids = ("A", "B")
    d = full_factorial(ids)
    with pytest.raises(ValueError, match="length"):
        fit_effects(d, [1.0, 2.0], factor_ids=ids)


def test_aliases_are_carried_onto_the_fit_as_a_caveat():
    ids = ("A", "B", "C", "D", "E", "F", "G")
    d = fractional_factorial(ids, resolution=3)
    ys = _synth(d, ids, 1.0, {"A": 1.0})
    # 8 runs cannot estimate 1 + 7 mains + 21 two-factor interactions (29
    # terms); the property under test — that aliasing is carried forward as
    # a caveat — does not require fitting interactions at all.
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=False)
    assert fit.aliases, "a res-III fit must carry its aliasing forward"


def test_stationary_point_of_a_known_quadratic():
    """y = 10 - 2*(a-0.5)^2 peaks at a=0.5 in coded space."""
    ids = ("A", "B")
    d = central_composite(ids, center_points=3)
    ys = []
    for p in d.points:
        a, b = p.coded
        ys.append(10.0 - 2.0 * (a - 0.5) ** 2 - 1.0 * b ** 2)
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=True)
    sp = solve_stationary_point(fit, ids)
    assert sp is not None
    assert math.isclose(sp["A"], 0.5, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(sp["B"], 0.0, rel_tol=1e-6, abs_tol=1e-6)


def test_stationary_point_is_none_without_curvature_terms():
    ids = ("A", "B")
    d = full_factorial(ids)          # no axial points -> no quadratic terms
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    fit = fit_effects(d, ys, factor_ids=ids)
    assert solve_stationary_point(fit, ids) is None
