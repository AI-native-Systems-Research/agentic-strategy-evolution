"""Behavioral tests for optimization factor parsing (kind: optimization).

Asserts the parsed data, not internal calls. Float comparisons use
math.isclose — the closed-form arithmetic carries ~1e-16 representation
error and `==` would be flaky.
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize.factors import (
    Factor,
    code_level,
    decode_coded,
    is_refinable,
    parse_factors,
    screen_pair,
    snap_to_grid,
)


def _numeric_raw(**over):
    raw = {
        "id": "L1", "name": "queue_count", "type": "numeric",
        "levels": [2, 4, 8, 16], "grid": 1,
        "apply": "--queues={level}",
        "manipulation": {"observable": "telemetry.queue_count",
                         "op": "==", "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness",
                       "statement": "baseline reproduces baseline",
                       "native_test": "tests/prop_q.py::test_noop"}],
    }
    raw.update(over)
    return raw


def _choice_raw(**over):
    raw = {
        "id": "L5", "name": "batching", "type": "choice",
        "levels": ["off", "on"],
        "apply": {"kind": "env_var", "name": "B", "value": "{level}"},
        "manipulation": {"observable": "telemetry.mean_batch_size",
                         "op": ">", "value": 1, "when": "on"},
        "relations": [{"id": "R3", "kind": "correctness",
                       "statement": "off is byte-identical to baseline",
                       "native_test": "tests/prop_b.py::test_off_noop"}],
    }
    raw.update(over)
    return raw


def test_parses_numeric_and_choice_factors():
    fs = parse_factors([_numeric_raw(), _choice_raw()])
    assert [f.id for f in fs] == ["L1", "L5"]
    assert fs[0].type == "numeric" and fs[0].levels == (2, 4, 8, 16)
    assert fs[1].type == "choice" and fs[1].levels == ("off", "on")


def test_screen_pair_defaults_to_first_and_last():
    f = parse_factors([_numeric_raw()])[0]
    assert screen_pair(f) == (2, 16)


def test_explicit_screen_levels_override_the_extremes():
    f = parse_factors([_numeric_raw(screen_levels=[4, 8])])[0]
    assert screen_pair(f) == (4, 8)


def test_screen_levels_must_be_members_of_levels():
    with pytest.raises(ValueError, match="screen_levels"):
        parse_factors([_numeric_raw(screen_levels=[3, 16])])


def test_coding_maps_low_to_minus_one_and_high_to_plus_one():
    f = parse_factors([_numeric_raw()])[0]
    assert code_level(f, 2) == -1
    assert code_level(f, 16) == +1


def test_coding_rejects_a_level_outside_the_screen_pair():
    f = parse_factors([_numeric_raw()])[0]
    with pytest.raises(ValueError):
        code_level(f, 4)


def test_choice_factor_codes_by_position():
    f = parse_factors([_choice_raw()])[0]
    assert code_level(f, "off") == -1
    assert code_level(f, "on") == +1


@pytest.mark.parametrize("value,grid,want", [
    (4.7, 1, 5.0),
    (4.2, 1, 4.0),
    (6.3, 2, 6.0),
    (7.1, 2, 8.0),
    (0.0273, None, 0.0273),
])
def test_snap_to_grid(value, grid, want):
    assert math.isclose(snap_to_grid(value, grid), want, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_snaps_numeric_to_the_grid():
    f = parse_factors([_numeric_raw()])[0]
    # midpoint of the screen pair (2, 16) is 9; grid=1 keeps it integral
    assert math.isclose(decode_coded(f, 0.0), 9.0, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_without_grid_keeps_the_interpolated_value():
    f = parse_factors([_numeric_raw(levels=[0.75, 0.95], grid=None)])[0]
    assert math.isclose(decode_coded(f, 0.0), 0.85, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_on_choice_returns_a_declared_level():
    f = parse_factors([_choice_raw()])[0]
    assert decode_coded(f, -1) == "off"
    assert decode_coded(f, +1) == "on"


def test_only_multilevel_numeric_factors_are_refinable():
    numeric_multi = parse_factors([_numeric_raw()])[0]
    numeric_two = parse_factors([_numeric_raw(levels=[2, 16])])[0]
    choice = parse_factors([_choice_raw()])[0]
    assert is_refinable(numeric_multi) is True
    assert is_refinable(numeric_two) is False
    assert is_refinable(choice) is False


def test_retired_type_vocabulary_is_rejected_with_a_helpful_message():
    with pytest.raises(ValueError, match="numeric.*choice"):
        parse_factors([_numeric_raw(type="ordinal")])


def test_bare_string_apply_is_normalised_to_a_cli_flag_spec():
    f = parse_factors([_numeric_raw()])[0]
    assert f.apply_spec == {"kind": "cli_flag", "template": "--queues={level}"}


def test_fewer_than_two_levels_is_rejected():
    with pytest.raises(ValueError, match="at least 2"):
        parse_factors([_numeric_raw(levels=[4])])


def test_duplicate_factor_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        parse_factors([_numeric_raw(), _numeric_raw()])


def test_missing_correctness_relation_is_rejected():
    only_behavioral = [{"id": "R9", "kind": "behavioral", "statement": "monotone",
                        "native_test": "t.py::test_m"}]
    with pytest.raises(ValueError, match="correctness"):
        parse_factors([_numeric_raw(relations=only_behavioral)])


def test_missing_manipulation_is_rejected():
    raw = _numeric_raw()
    del raw["manipulation"]
    with pytest.raises(ValueError, match="manipulation"):
        parse_factors([raw])


def test_manipulation_with_both_when_and_when_not_is_rejected():
    bad = {"observable": "x", "op": "==", "value": 1, "when": "on", "when_not": "off"}
    with pytest.raises(ValueError, match="when"):
        parse_factors([_numeric_raw(manipulation=bad)])


def test_decode_coded_clamps_axial_points_to_the_declared_range():
    """A central composite places axial points OUTSIDE |coded| = 1.

    For k=3 the rotatable alpha is (2^3)^(1/4) = 1.68, so linear
    extrapolation walks past the levels the author declared. Verified on a
    live campaign against BLIS: a factor declared [64, 256] produced
    MAXRUN=-1 and MAXRUN=-112 — a negative request cap — and the target
    rejected 16 of 80 refine runs with a usage error.

    Clamping is the honest repair rather than widening the range: the author
    declared these bounds, and a value outside them is a configuration they
    never said was legal, possibly a physically meaningless one.
    """
    f = parse_factors([_numeric_raw(levels=[64, 256], grid=1)])[0]
    for coded in (-2.5, -1.68, -1.0, 0.0, 1.0, 1.68, 2.5):
        value = decode_coded(f, coded)
        assert 64 <= value <= 256, (
            f"coded={coded} produced {value}, outside the declared [64, 256]"
        )
    # the interior still interpolates rather than collapsing to an edge
    assert math.isclose(decode_coded(f, 0.0), 160.0, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_clamps_without_breaking_the_grid():
    """A clamped value must still land on the declared grid step."""
    f = parse_factors([_numeric_raw(levels=[1000, 4096], grid=2)])[0]
    for coded in (-3.0, -1.68, 1.68, 3.0):
        value = decode_coded(f, coded)
        assert 1000 <= value <= 4096
        assert math.isclose(value % 2, 0.0, abs_tol=1e-9) or value in (1000, 4096)


def test_snap_to_grid_returns_int_for_an_integral_grid():
    """The value is rendered straight into the target's command line.

    Verified on a live campaign: a factor declared [64, 256] with grid: 1
    produced 160.0, and BLIS rejected `--max-num-running-reqs=160.0` as a
    usage error — failing 16 of 80 refine runs even though the value was in
    range and on the grid. `grid: 1` means integral steps, so an integral
    result must render as an integer.
    """
    assert snap_to_grid(160.4, 1) == 160
    assert isinstance(snap_to_grid(160.4, 1), int)
    assert isinstance(snap_to_grid(7.2, 2), int)
    # a fractional grid keeps returning a float — that is what was asked for
    assert isinstance(snap_to_grid(0.0273, 0.005), float)
    assert snap_to_grid(4.5, None) == 4.5


def test_decoded_levels_render_as_integers_for_an_integral_grid():
    f = parse_factors([_numeric_raw(levels=[64, 256], grid=1)])[0]
    for coded in (-1.68, -1.0, 0.0, 1.0, 1.68):
        value = decode_coded(f, coded)
        assert isinstance(value, int), (
            f"coded={coded} produced {value!r}; a float renders as "
            f"'--flag=160.0', which many targets reject"
        )


# ── integral points of an all-integer factor render as integers ─────────────
#
# Found by a real end-to-end campaign: levels [8, 20, 32] with no `grid` put the
# generated centre point on the command line as `--batch-size=20.0`, which an
# argparse `type=int` target rejects. The same trap failed 16 of 80 refine runs
# on an earlier live target. An all-integer level list says what the knob takes.

from hypothesis import given, strategies as st  # noqa: E402

from orchestrator.optimize.matrix import render_apply  # noqa: E402


def _int_factor(levels, **over):
    raw = _numeric_raw(levels=list(levels), **over)
    raw.pop("grid", None)
    raw.update(over)
    return parse_factors([raw])[0]


def test_the_centre_of_an_all_integer_factor_renders_as_an_integer_flag():
    f = _int_factor([8, 20, 32], apply="--batch-size={level}")
    centre = decode_coded(f, 0.0)
    assert centre == 20 and isinstance(centre, int)
    assert render_apply([f], {f.id: centre})["cli_args"] == ["--batch-size=20"]


@given(lo=st.integers(-50, 50), span=st.integers(2, 100),
       coded=st.floats(-2.0, 2.0, allow_nan=False))
def test_an_integral_decoded_value_of_an_integer_factor_is_an_int(lo, span, coded):
    f = _int_factor([lo, lo + span])
    v = decode_coded(f, coded)
    if float(v).is_integer():
        assert isinstance(v, int), f"{v!r} is integral but rendered as {type(v).__name__}"


def test_a_fractional_point_of_an_integer_factor_is_left_alone_without_a_grid():
    # Without `grid`, Nous does not decide the knob is integer-only: a threshold
    # declared [2, 4] may legitimately run at 3.5. The validator warns instead.
    f = _int_factor([2, 4])
    assert decode_coded(f, 0.5) == 3.5


def test_a_float_level_list_keeps_float_points():
    f = _int_factor([0.5, 1.5])
    v = decode_coded(f, 0.0)
    assert v == 1.0 and isinstance(v, float)
