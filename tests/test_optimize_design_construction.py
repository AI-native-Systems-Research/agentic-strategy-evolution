"""No factor count forces a full factorial: constructed Res III / IV / V designs.

Every claim here is read off the generated DESIGN MATRIX, never off the
generator words the construction chose, so a construction bug cannot certify
itself. The textbook table (k <= 8) is pinned unchanged, so existing
campaigns compile the same designs as before.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from orchestrator.optimize.design import (
    _GENERATORS,
    _runs_lower_bound,
    alias_pairs,
    central_composite,
    fractional_factorial,
    full_factorial,
    generators_for,
    is_tabulated,
    min_runs_for,
)


def _ids(k):
    return tuple(f"F{i:02d}" for i in range(k))


def _matrix(d):
    return np.array([p.coded for p in d.corners])


def _shortest_word(X, upto):
    """Length of the shortest defining word (a set of columns whose product
    is constant), searched up to ``upto``; ``upto + 1`` means none that short."""
    k = X.shape[1]
    for r in range(1, upto + 1):
        for S in itertools.combinations(range(k), r):
            prod = np.prod(X[:, S], axis=1)
            if np.all(prod == prod[0]):
                return r
    return upto + 1


CASES = [(k, r) for r in (3, 4, 5) for k in range(3, 25)
         if is_tabulated(k, r) and (k, r) not in _GENERATORS]


@pytest.mark.parametrize("k,res", CASES)
def test_every_constructed_design_has_at_least_its_resolution(k, res):
    d = fractional_factorial(_ids(k), res)
    X = _matrix(d)
    assert X.shape == (min_runs_for(k, res), k)
    # Resolution R <=> no defining word shorter than R.
    assert _shortest_word(X, res - 1) >= res
    if res >= 5:
        assert alias_pairs(d) == [], "resolution V aliases no main or 2fi"
    # Main effects are orthogonal to each other and to the mean.
    assert np.allclose(X.T @ X, len(X) * np.eye(k))


@pytest.mark.parametrize("res", [3, 4])
@pytest.mark.parametrize("k", [9, 12, 16, 17, 31, 32, 33, 64, 100])
def test_resolution_three_and_four_meet_the_theoretical_minimum(k, res):
    """III: N = the smallest power of two above k. IV: N = 2k rounded up
    to a power of two (the even / folded-over design). Both are optimal."""
    assert min_runs_for(k, res) == _runs_lower_bound(k, res)


@pytest.mark.parametrize("k", range(5, 31))
def test_resolution_five_matches_the_smallest_known_regular_design(k):
    """Known maxima: 8 / 11 / 17 / 23 / 33 resolution-V factors in
    64 / 128 / 256 / 512 / 1024 runs. Attained for every k up to 30."""
    assert min_runs_for(k, 5) == _runs_lower_bound(k, 5)


@pytest.mark.parametrize("k", [31, 40, 47, 64])
def test_resolution_five_beyond_thirty_is_within_one_doubling(k):
    assert min_runs_for(k, 5) <= 2 * _runs_lower_bound(k, 5)


def test_a_sixteen_knob_screen_is_a_fraction_not_sixty_five_thousand_runs():
    assert min_runs_for(16, 5) == 256 and min_runs_for(16, 4) == 32
    assert min_runs_for(16, 3) == 32
    assert 2 ** 16 == 65536


def test_construction_is_deterministic():
    for k, r in [(12, 5), (20, 4), (25, 5), (40, 3)]:
        assert generators_for(k, r) == generators_for(k, r)
        a, b = fractional_factorial(_ids(k), r), fractional_factorial(_ids(k), r)
        assert a.points == b.points


def test_the_textbook_table_is_unchanged():
    """Existing campaigns (k <= 8) must compile exactly the designs they did."""
    assert sorted(_GENERATORS) == sorted([
        (5, 5), (6, 5), (7, 5), (8, 5), (4, 4), (5, 4), (6, 4), (7, 4), (8, 4), (7, 3)])
    for key, entry in _GENERATORS.items():
        assert generators_for(*key) == entry


@pytest.mark.parametrize("k", [3, 4])
def test_where_the_full_factorial_is_minimal_it_is_used(k):
    assert not is_tabulated(k, 5)
    assert min_runs_for(k, 5) == 2 ** k
    assert len(full_factorial(_ids(k)).points) == 2 ** k


# ── the refine design: a small composite over a resolution-V cube ───────────

def _quadratic_model_matrix(d):
    X = np.array([p.coded for p in d.points])
    k = X.shape[1]
    cols = [np.ones(len(X))] + [X[:, i] for i in range(k)]
    cols += [X[:, i] * X[:, j] for i, j in itertools.combinations(range(k), 2)]
    cols += [X[:, i] ** 2 for i in range(k)]
    return np.column_stack(cols)


@pytest.mark.parametrize("k", [2, 3, 4, 5, 6, 8, 10, 12, 16])
def test_the_composite_design_estimates_a_full_quadratic(k):
    d = central_composite(_ids(k), center_points=4)
    M = _quadratic_model_matrix(d)
    p = 1 + k + k * (k - 1) // 2 + k
    assert np.linalg.matrix_rank(M) == p, "every quadratic term must be estimable"


@pytest.mark.parametrize("k", [2, 3, 4])
def test_a_small_composite_keeps_its_full_factorial_cube(k):
    """Unchanged for the refine stages existing campaigns run."""
    d = central_composite(_ids(k), center_points=4)
    assert len(d.corners) == 2 ** k
    axial = max(abs(c) for p in d.points if p.role == "axial" for c in p.coded)
    assert axial == pytest.approx((2 ** k) ** 0.25)


@pytest.mark.parametrize("k,cube", [(5, 16), (10, 128), (16, 256)])
def test_a_large_composite_uses_a_resolution_five_cube(k, cube):
    d = central_composite(_ids(k), center_points=4)
    assert len(d.corners) == cube < 2 ** k
    assert len(d.points) == cube + 2 * k + 4
    axial = max(abs(c) for p in d.points if p.role == "axial" for c in p.coded)
    assert axial == pytest.approx(cube ** 0.25), "rotatable for the cube it has"


# ── what the author sees: the design preview names the design and its cost ──

def _preview_screen_note(k, res):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview
    from orchestrator.optimize.synthetic import Surface, _numeric

    s = Surface(name="p", factors=tuple(_numeric(f"X{i:02d}") for i in range(k)),
                fn=lambda lv: 0.0)
    c = synthetic_campaign(s, design={"screen": {"resolution": res, "center_points": 4},
                                      "refine": {"kind": "central_composite",
                                                 "center_points": 4},
                                      "confirm": {"replicates": 3}})
    st = build_preview(c, noise_sd=1.0, mean=10.0, run_secs=[1.0]).stages[0]
    return st.runs, st.note


def test_the_preview_prices_a_sixteen_knob_screen_as_a_fraction():
    runs, note = _preview_screen_note(16, 5)
    assert runs == 256 + 4
    assert "resolution-V fraction" in note and "smallest known" in note
    assert "resolution-IV screen would take 32" in note


def test_the_preview_says_when_a_higher_resolution_is_free():
    runs, note = _preview_screen_note(16, 3)
    assert runs == 32 + 4 and "resolution IV costs the same here" in note


def test_the_preview_says_when_the_construction_is_above_the_known_minimum():
    _, note = _preview_screen_note(31, 5)
    assert "smallest known is 1024" in note


def test_resolution_five_at_a_hundred_knobs_is_within_two_doublings_and_cached():
    import time

    from orchestrator.optimize.design import _construct

    _construct.cache_clear()
    t = time.monotonic()
    first = min_runs_for(100, 5)
    cold = time.monotonic() - t
    t = time.monotonic()
    assert min_runs_for(100, 5) == first
    assert time.monotonic() - t < max(0.05, cold / 10), "the second ask is cached"
    assert first <= 4 * _runs_lower_bound(100, 5)
