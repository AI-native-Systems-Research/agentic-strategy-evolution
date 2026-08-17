"""recommend() is the paper's x-hat: argmax of the fitted response over X_valid.

Built on real Fit objects from fit_effects over synthetic designs, so these
tests assert the ANSWER against a known surface, not the arithmetic.
"""
from __future__ import annotations

import pytest

from orchestrator.optimize.decide import candidates, predict, ranked, recommend
from orchestrator.optimize.design import central_composite, full_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import expand
from orchestrator.optimize.synthetic import SURFACES


def _fit(surface, design, ids):
    factors = parse_factors(list(surface.factors))
    ys = [surface.fn(r.levels) for r in expand(design, factors)]     # noiseless
    return fit_effects(design, ys, factor_ids=ids), factors


def test_predict_reproduces_the_fitted_corners_of_an_additive_surface():
    """A saturated orthogonal fit is exact at its own corners.

    NO CENTRE POINTS here, deliberately. ``matrix._decode_level`` runs a
    ``choice`` factor at its LOW level on a ``role="center"`` row (nothing
    runnable lives between "off" and "on"), while the design matrix records
    that row's coding as 0.0 for every factor. The C column therefore does
    not sum to zero over the design, the fit is no longer orthogonal in C,
    and the corner prediction is pulled off the measured corner by 0.33 on
    this surface — measured, not assumed. That is a pre-existing property of
    coding a categorical centre point, not of ``predict``: over the bare
    factorial the same call reproduces the corner to machine precision.
    """
    s = SURFACES["additive"]()
    d = full_factorial(["A", "B", "C"])
    fit, _factors = _fit(s, d, ["A", "B", "C"])
    assert predict(fit, {"A": 1.0, "B": 1.0, "C": 1.0}) == pytest.approx(
        s.fn({"A": 16, "B": 16, "C": "on"}), abs=1e-6,
    )


def test_saddle_recommendation_is_a_corner_and_beats_the_stationary_point():
    s = SURFACES["saddle"]()
    d = central_composite(["A", "B"], center_points=4)
    fit, factors = _fit(s, d, ["A", "B"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "B"],
                    held_fixed={})
    assert rec.levels["A"] in (2, 16)
    assert s.fn(rec.levels) > s.fn({"A": 9, "B": 11})


def test_choice_factor_is_part_of_the_argmax():
    s = SURFACES["choice_x_numeric"]()
    d = with_center_points(full_factorial(["A", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "C"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "C"],
                    held_fixed={})
    assert rec.levels == {"A": 16, "C": "on"}


def test_held_fixed_levels_are_carried_into_every_candidate():
    """C is held fixed rather than fitted, so it enters levels but not coded.

    No fit is built: ``candidates`` enumerates the space and knows nothing
    about a model. (The brief's draft fitted a design over A alone here,
    which cannot be evaluated — ``choice_x_numeric.fn`` reads C, so a design
    that omits C hands the surface an incomplete configuration.)
    """
    s = SURFACES["choice_x_numeric"]()
    factors = parse_factors(list(s.factors))
    cands = candidates(["A"], factors, held_fixed={"C": "on"})
    assert all(c.levels["C"] == "on" for c in cands)
    assert any(c.levels["A"] == 9 for c in cands)          # interior grid point present
    assert all("C" not in c.coded for c in cands), (
        "a held-fixed factor has no fitted term, so giving it a coding would "
        "let predict() read a coordinate no effect was estimated against"
    )


def test_measured_infeasible_levels_are_excluded():
    s = SURFACES["sla"]()
    d = with_center_points(full_factorial(["A", "B"]), 4)
    fit, factors = _fit(s, d, ["A", "B"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "B"],
                    held_fixed={}, exclude_levels=[{"A": 16, "B": 16}])
    assert rec.levels != {"A": 16, "B": 16}


def test_minimize_direction_picks_the_smallest_prediction():
    s = SURFACES["additive"]()
    d = with_center_points(full_factorial(["A", "B", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "B", "C"])
    rec = recommend(fit, factors, direction="minimize", fitted_ids=["A", "B", "C"],
                    held_fixed={})
    assert rec.levels == {"A": 16, "B": 2, "C": "off"}


def test_excluding_every_candidate_raises_rather_than_returning_none():
    """An empty X_valid is a campaign-level fact, not a None to propagate.

    ``candidates`` filters, so a broad enough exclusion set can empty it. A
    silent None would reach ``recommendation.json`` as a null ``levels`` and
    ``confirm`` would then replicate nothing; raising names the cause at the
    point it is knowable.
    """
    s = SURFACES["choice_x_numeric"]()
    d = with_center_points(full_factorial(["A", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "C"])
    with pytest.raises(ValueError, match="no valid candidate"):
        recommend(fit, factors, direction="maximize", fitted_ids=["A", "C"],
                  held_fixed={}, exclude_levels=[{"C": "on"}, {"C": "off"}])


def test_ranked_returns_the_top_candidates_in_order_and_starts_with_recommend():
    """``top_candidates`` in recommendation.json is this list; its head must
    agree with ``recommend`` or the artifact would contradict itself."""
    s = SURFACES["additive"]()
    d = with_center_points(full_factorial(["A", "B", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "B", "C"])
    top = ranked(fit, factors, direction="maximize", fitted_ids=["A", "B", "C"],
                 held_fixed={}, top=5)
    assert len(top) == 5
    assert [c.predicted for c in top] == sorted(
        (c.predicted for c in top), reverse=True,
    )
    best = recommend(fit, factors, direction="maximize",
                     fitted_ids=["A", "B", "C"], held_fixed={})
    assert top[0].levels == best.levels
    assert top[0].predicted == pytest.approx(best.predicted)


def test_an_undeclared_fitted_id_names_itself_rather_than_raising_a_bare_keyerror():
    """``fitted_ids`` must match the design's columns; a mismatch is a wiring
    bug, and a bare ``KeyError: 'ZZZ'`` says nothing about which contract broke.
    """
    s = SURFACES["additive"]()
    factors = parse_factors(list(s.factors))
    with pytest.raises(ValueError, match="no such factor was declared"):
        candidates(["A", "ZZZ"], factors, held_fixed={})


def test_ranked_with_top_none_returns_the_whole_scored_space():
    """``stage_runner`` asks for the shortlist AND the size of the space it
    came from, and must not enumerate twice to get both."""
    s = SURFACES["additive"]()
    d = with_center_points(full_factorial(["A", "B", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "B", "C"])
    kwargs = dict(direction="maximize", fitted_ids=["A", "B", "C"], held_fixed={})
    every = ranked(fit, factors, top=None, **kwargs)
    space = candidates(["A", "B", "C"], factors, held_fixed={})
    assert len(every) == len(space)
    assert every[:5] == ranked(fit, factors, top=5, **kwargs)


def test_a_refinable_numeric_axis_offers_interior_levels_a_screen_pair_cannot():
    """The candidate space is the point of the change: a two-level screen pair
    can only ever recommend a corner, so an interior optimum is unreachable."""
    s = SURFACES["bowl"]()
    d = central_composite(["A", "B"], center_points=4)
    fit, factors = _fit(s, d, ["A", "B"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "B"],
                    held_fixed={})
    assert rec.levels["A"] not in (2, 16), rec.levels
    assert abs(rec.levels["A"] - 9) <= 2 and abs(rec.levels["B"] - 11) <= 2
