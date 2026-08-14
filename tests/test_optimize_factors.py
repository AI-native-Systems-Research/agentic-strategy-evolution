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
