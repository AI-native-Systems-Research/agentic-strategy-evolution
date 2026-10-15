"""Behavioral tests for the shared predicate vocabulary."""
from __future__ import annotations

import pytest

from orchestrator.optimize.predicates import Verdict, evaluate, is_trivial


def test_equality_on_a_dotted_observable_path():
    v = evaluate({"observable": "telemetry.queue_count", "op": "==", "value": 8},
                 {"telemetry": {"queue_count": 8}})
    assert v.ok is True and v.skipped is False


def test_failing_comparison_reports_both_sides_in_detail():
    v = evaluate({"observable": "telemetry.queue_count", "op": "==", "value": 8},
                 {"telemetry": {"queue_count": 2}})
    assert v.ok is False
    assert "2" in v.detail and "8" in v.detail


def test_level_token_is_interpolated_into_the_expected_value():
    v = evaluate({"observable": "config.escalate_low", "op": "==", "value": "{level}"},
                 {"config": {"escalate_low": 0.02}}, level=0.02)
    assert v.ok is True


def test_missing_observable_is_a_failure_not_a_crash():
    v = evaluate({"observable": "telemetry.absent", "op": "==", "value": 1},
                 {"telemetry": {}})
    assert v.ok is False
    assert "absent" in v.detail


def test_when_guard_skips_the_check_at_other_levels():
    pred = {"observable": "telemetry.mean_batch_size", "op": ">",
            "value": 1, "when": "on"}
    assert evaluate(pred, {"telemetry": {"mean_batch_size": 1}}, level="off").skipped is True
    assert evaluate(pred, {"telemetry": {"mean_batch_size": 4}}, level="on").ok is True


def test_when_not_guard_applies_everywhere_except_the_named_level():
    pred = {"observable": "telemetry.stop_events", "op": ">",
            "value": 0, "when_not": "off"}
    assert evaluate(pred, {"telemetry": {"stop_events": 0}}, level="off").skipped is True
    assert evaluate(pred, {"telemetry": {"stop_events": 3}}, level=0.004).ok is True


def test_guards_accept_a_list_of_levels():
    pred = {"observable": "x", "op": ">", "value": 0, "when": ["a", "b"]}
    assert evaluate(pred, {"x": 0}, level="c").skipped is True
    assert evaluate(pred, {"x": 5}, level="b").ok is True


def test_metric_key_is_accepted_as_an_alias_for_observable():
    v = evaluate({"metric": "degradation", "op": ">=", "value": -0.60},
                 {"degradation": -0.42})
    assert v.ok is True


@pytest.mark.parametrize("op,observed,expected,want", [
    (">", 5, 3, True), (">", 3, 5, False),
    (">=", 5, 5, True), ("<", 1, 2, True),
    ("<=", 2, 2, True), ("!=", 1, 2, True),
])
def test_operator_table(op, observed, expected, want):
    v = evaluate({"observable": "m", "op": op, "value": expected}, {"m": observed})
    assert v.ok is want


def test_unknown_operator_raises_with_the_allowed_set():
    with pytest.raises(ValueError, match="op"):
        evaluate({"observable": "m", "op": "=~", "value": 1}, {"m": 1})


@pytest.mark.parametrize("pred,want", [
    ({"observable": "throughput", "op": ">", "value": 0}, True),
    ({"observable": "x", "op": "!=", "value": None}, True),
    ({"observable": "telemetry.queue_count", "op": "==", "value": "{level}"}, False),
    ({"observable": "telemetry.transfer_path", "op": "==", "value": "p2p"}, False),
    ({"observable": "degradation", "op": ">=", "value": -0.60}, False),
])
def test_is_trivial_flags_predicates_that_cannot_fail(pred, want):
    assert is_trivial(pred) is want


def test_both_when_and_when_not_raises():
    pred = {"observable": "x", "op": ">", "value": 0, "when": "on", "when_not": "off"}
    with pytest.raises(ValueError, match="when"):
        evaluate(pred, {"x": 5}, level="on")


def test_missing_observable_sets_missing_flag():
    v = evaluate({"observable": "telemetry.absent", "op": "==", "value": 1},
                 {"telemetry": {}})
    assert v.missing is True
    assert v.ok is False


def test_genuine_comparison_failure_has_missing_false():
    v = evaluate({"observable": "telemetry.queue_count", "op": "==", "value": 8},
                 {"telemetry": {"queue_count": 2}})
    assert v.missing is False
    assert v.ok is False


# ───── a failed comparison names the SHAPE of its failure (issue #318) ─────
#
# Four shapes, four different author actions: an observable the target never
# emitted, one it emitted EMPTY (an adapter that reports a field only under some
# condition), one of the wrong TYPE (a bool echoed for a string level), and one
# of the right type and the wrong value. The hint must name exactly one.

from hypothesis import given, strategies as st  # noqa: E402

_PRED = {"observable": "config.knob", "op": "==", "value": "{level}"}
_HINT_MARKERS = {
    "absent": "did not emit",
    "empty": "PRESENT but EMPTY",
    "type": "Check the observable's TYPE",
    "value": "same type as the level",
}

_nonempty_text = st.text(min_size=1, max_size=8)
_scalar = st.one_of(st.booleans(), st.integers(), _nonempty_text,
                    st.floats(allow_nan=False))


def _shape_of(hint: str) -> list[str]:
    return [shape for shape, marker in _HINT_MARKERS.items() if marker in hint]


@given(level=_nonempty_text)
def test_an_absent_observable_gets_only_the_absent_hint(level):
    v = evaluate(_PRED, {"config": {}}, level=level)
    assert v.ok is False and _shape_of(v.hint) == ["absent"], v.hint


@given(level=_nonempty_text, observed=st.sampled_from(["", None]))
def test_an_empty_observable_gets_only_the_empty_hint(level, observed):
    v = evaluate(_PRED, {"config": {"knob": observed}}, level=level)
    assert v.ok is False and _shape_of(v.hint) == ["empty"], v.hint
    assert "not a type mismatch" in v.hint


@given(level=_nonempty_text, observed=st.one_of(st.booleans(), st.integers(),
                                                 st.floats(allow_nan=False)))
def test_a_non_string_observable_for_a_string_level_gets_only_the_type_hint(
    level, observed,
):
    v = evaluate(_PRED, {"config": {"knob": observed}}, level=level)
    assert v.ok is False and _shape_of(v.hint) == ["type"], v.hint


@given(pair=st.tuples(_scalar, _scalar).filter(
    lambda p: type(p[0]) is type(p[1]) and p[0] != p[1]))
def test_a_same_type_unequal_observable_gets_only_the_value_hint(pair):
    observed, level = pair
    v = evaluate(_PRED, {"config": {"knob": observed}}, level=level)
    assert v.ok is False and _shape_of(v.hint) == ["value"], v.hint


@given(level=_scalar)
def test_a_passing_comparison_carries_no_hint(level):
    v = evaluate(_PRED, {"config": {"knob": level}}, level=level)
    assert v.ok is True and v.hint == ""


def test_the_empty_hint_says_to_record_the_level_unconditionally():
    v = evaluate(_PRED, {"config": {"knob": ""}}, level="ag_rs")
    assert ("Record the level the design matrix asked for, unconditionally; "
            "what the knob DOES at that level is a finding, not a reason to "
            "omit it from the row.") in v.hint


# ── the hint depends on the OPERATOR (review of #318) ──────────────────────

from orchestrator.optimize.predicates import evaluate as _evaluate  # noqa: E402


def _hint(op, got, want):
    v = _evaluate({"observable": "x", "op": op, "value": want}, {"x": got})
    assert not v.ok
    return v.hint


def test_a_failed_not_equal_says_the_value_was_the_excluded_one():
    h = _hint("!=", "x", "x")
    assert "EQUALS" in h and "different value" not in h


@given(got=st.floats(-1e6, 1e6, allow_nan=False), gap=st.floats(0.5, 1e3))
def test_a_false_ordering_between_numbers_is_never_called_a_type_mismatch(got, gap):
    h = _hint(">=", got, got + gap)
    assert "TYPE" not in h and "was false" in h


def test_an_ordering_against_a_bool_is_a_type_problem():
    assert "TYPE" in _hint(">=", True, 8)
