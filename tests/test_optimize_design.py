"""Behavioral tests for design generation.

The oracles here are external: published fractional-factorial generators
and the defining relations they imply. Tests assert the alias structure the
textbook predicts, never "what my generator produced".
"""
from __future__ import annotations

import itertools
import math

import pytest

from orchestrator.optimize.design import (
    _GENERATORS,
    alias_pairs,
    central_composite,
    fractional_factorial,
    full_factorial,
    is_orthogonal,
    min_runs_for,
    with_center_points,
)

FIVE = ("A", "B", "C", "D", "E")
SEVEN = ("A", "B", "C", "D", "E", "F", "G")


def _corners(design):
    return [p for p in design.points if p.role == "corner"]


def _column(design, idx):
    return [p.coded[idx] for p in _corners(design)]


def _product_column(design, idxs):
    return [math.prod(p.coded[i] for i in idxs) for p in _corners(design)]


def test_full_factorial_run_count_is_two_to_the_k():
    d = full_factorial(("A", "B", "C"))
    assert len(_corners(d)) == 8
    assert d.factor_ids == ("A", "B", "C")


def test_full_factorial_columns_are_balanced():
    d = full_factorial(("A", "B", "C"))
    for j in range(3):
        assert sum(_column(d, j)) == 0


def test_full_factorial_is_orthogonal():
    assert is_orthogonal(full_factorial(("A", "B", "C", "D"))) is True


def test_resolution_v_for_five_factors_needs_sixteen_runs():
    # Published: 2^(5-1) with E = ABCD is the minimum res-V design.
    assert min_runs_for(5, 5) == 16
    d = fractional_factorial(FIVE, resolution=5)
    assert len(_corners(d)) == 16


def test_min_runs_for_is_exact_only_for_tabulated_cells():
    # Tabulated: exact, from _GENERATORS' n_base.
    assert min_runs_for(5, 5) == 16
    # Untabulated (k=6, resolution=3 has no _GENERATORS entry): the
    # fallback is 2**k, a conservative upper bound, not a claim that 64
    # is the true minimum run count achievable at resolution 3 for 6
    # factors -- it may well be smaller and simply isn't tabulated here.
    assert (6, 3) not in _GENERATORS
    assert min_runs_for(6, 3) == 2 ** 6


def test_resolution_v_design_has_no_aliasing_among_mains_and_two_factor_terms():
    d = fractional_factorial(FIVE, resolution=5)
    assert alias_pairs(d) == []


def test_resolution_v_main_effect_columns_are_mutually_orthogonal():
    d = fractional_factorial(FIVE, resolution=5)
    n = len(_corners(d))
    for i, j in itertools.combinations(range(5), 2):
        dot = sum(a * b for a, b in zip(_column(d, i), _column(d, j)))
        assert dot == 0, f"columns {i},{j} not orthogonal"
    assert all(sum(_column(d, j)) == 0 for j in range(5))
    assert n == 16


def test_resolution_three_for_seven_factors_is_eight_runs():
    # Box-Hunter-Hunter saturated design: D=AB, E=AC, F=BC, G=ABC.
    d = fractional_factorial(SEVEN, resolution=3)
    assert len(_corners(d)) == 8


def test_resolution_three_aliases_two_factor_terms_onto_main_effects():
    d = fractional_factorial(SEVEN, resolution=3)
    pairs = alias_pairs(d)
    # Every 2fi in a saturated 2^(7-4) is confounded with something.
    assert pairs, "res III must report aliasing"
    labels = {"".join(sorted(a)) + "=" + b for a, b in pairs}
    assert "AB=D" in labels or "D=AB" in {f"{b}={''.join(sorted(a))}" for a, b in pairs}


def test_requesting_an_unachievable_resolution_fails_loudly():
    with pytest.raises(ValueError, match="resolution"):
        fractional_factorial(("A", "B"), resolution=7)


def test_center_points_sit_at_the_origin():
    d = with_center_points(full_factorial(("A", "B")), 3)
    centers = [p for p in d.points if p.role == "center"]
    assert len(centers) == 3
    assert all(all(c == 0 for c in p.coded) for p in centers)


def test_center_point_replicate_indices_are_distinct():
    d = with_center_points(full_factorial(("A", "B")), 4)
    centers = [p for p in d.points if p.role == "center"]
    assert sorted(p.replicate for p in centers) == [0, 1, 2, 3]


def test_central_composite_has_corners_center_and_axial_points():
    d = central_composite(("A", "B"), center_points=4)
    roles = {p.role for p in d.points}
    assert roles == {"corner", "center", "axial"}
    # 2 factors -> 4 corners + 2*2 axial + 4 center
    assert len(_corners(d)) == 4
    assert len([p for p in d.points if p.role == "axial"]) == 4
    assert len([p for p in d.points if p.role == "center"]) == 4


def test_central_composite_axial_distance_is_rotatable_by_default():
    d = central_composite(("A", "B"), center_points=2)
    want = (2 ** 2) ** 0.25  # = sqrt(2) for k=2
    axial = [p for p in d.points if p.role == "axial"]
    for p in axial:
        nonzero = [c for c in p.coded if c != 0]
        assert len(nonzero) == 1
        assert math.isclose(abs(nonzero[0]), want, rel_tol=1e-9, abs_tol=1e-12)


def test_central_composite_axial_points_vary_one_factor_at_a_time():
    d = central_composite(("A", "B", "C"), center_points=2)
    for p in [q for q in d.points if q.role == "axial"]:
        assert sum(1 for c in p.coded if c != 0) == 1


def test_designs_are_deterministic_across_calls():
    a = fractional_factorial(FIVE, resolution=5)
    b = fractional_factorial(FIVE, resolution=5)
    assert [p.coded for p in a.points] == [p.coded for p in b.points]


@pytest.mark.parametrize("key", sorted(_GENERATORS))
def test_every_tabulated_generator_actually_achieves_its_claimed_resolution(key):
    """Audit the whole table, not just the two spot-checked oracles.

    A generator entry that claims resolution R but doesn't deliver it is
    the worst kind of bug here: the campaign would report tight confidence
    intervals on terms that are actually confounded, and nothing downstream
    can detect it. This test regenerates the alias structure from first
    principles for every entry so a future addition is audited
    automatically rather than trusted on the strength of a comment.
    """
    k, resolution = key
    n_base, gens = _GENERATORS[key]

    # n_base must be consistent with the generators: every generator is a
    # product of base columns, so no index may reach outside [0, n_base).
    max_idx = max((i for g in gens for i in g), default=-1)
    assert max_idx < n_base, (
        f"{key}: generator references column {max_idx} but n_base={n_base}"
    )

    ids = tuple(chr(ord("A") + i) for i in range(k))
    d = fractional_factorial(ids, resolution=resolution)
    corners = _corners(d)

    # Every entry: columns balanced, main effects mutually orthogonal.
    for j in range(k):
        assert sum(_column(d, j)) == 0, f"{key}: column {j} unbalanced"
    assert is_orthogonal(d), f"{key}: main effects not mutually orthogonal"

    pairs = alias_pairs(d)
    two_fi_on_main = [p for p in pairs if len(p[1]) == 1]
    two_fi_on_two_fi = [p for p in pairs if len(p[1]) == 2]

    if resolution == 5:
        assert two_fi_on_main == [], f"{key}: claims res V but has 2fi-on-main aliasing"
        assert two_fi_on_two_fi == [], f"{key}: claims res V but has 2fi-on-2fi aliasing"
    elif resolution == 4:
        assert two_fi_on_main == [], f"{key}: claims res IV but has 2fi-on-main aliasing"
    elif resolution == 3:
        assert two_fi_on_main, f"{key}: claims res III but has no main-effect aliasing"
