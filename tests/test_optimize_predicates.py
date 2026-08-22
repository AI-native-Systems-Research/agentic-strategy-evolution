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
    v = evaluate({"observable": "config.tp_low", "op": "==", "value": "{level}"},
                 {"config": {"tp_low": 0.02}}, level=0.02)
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
    v = evaluate({"metric": "drawdown", "op": ">=", "value": -0.60},
                 {"drawdown": -0.42})
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
    ({"observable": "drawdown", "op": ">=", "value": -0.60}, False),
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
