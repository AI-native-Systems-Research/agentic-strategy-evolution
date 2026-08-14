"""Behavioral tests for the relation-contract checker.

Nous never generates or interprets target-language test code. When a
campaign optimizes a target repo, the mechanism it adds gets property /
metamorphic tests in the target's own idiom -- ``hypothesis`` for Python,
``rapid`` / ``testing/quick`` for Go, ``proptest`` / ``quickcheck`` for
Rust, RapidCheck for C++. Those tests live in the target's own test tree
and run under the target's own runner. This module's entire job is to
verify a *contract*: each declared relation names a ``native_test``
identifier, the campaign's declared ``test_command`` ran, that identifier
appears in the results, and it passed. That is why parsing here is
limited to two generic test-runner output shapes (pytest JSON report,
JUnit XML) rather than anything language-specific -- the harness needs
zero knowledge of the target's language or property-testing library.

The load-bearing behavior: a relation that was DECLARED but does not
appear in the results must be a FAILURE, never a pass. Otherwise a
typo'd ``native_test`` identifier would silently disable a correctness
gate -- the campaign would believe a mechanism was verified when nothing
ever checked it.

The second load-bearing behavior is in ``classify_failures``: a failed
``behavioral`` relation must never land in the ``correctness`` bucket.
A monotonicity violation is a *discovery*, not a bug -- the motivating
case is a batching lever (L5) that measured -9.5% in isolation yet was
required for the winning combination. Correctness relations (conservation
laws, "disabled means byte-identical to baseline") hard-fail the
campaign when broken; behavioral relations become recorded findings and
the campaign continues. Conflating the two would make the campaign blind
to exactly the non-monotonic compounds it exists to find.
"""
from __future__ import annotations

import pytest

from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.relations import (
    RelationVerdict,
    classify_failures,
    parse_junit_xml,
    parse_pytest_json_report,
    reconcile,
    required_relations,
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
        "apply": {"kind": "env_var", "name": "CERTUS_BATCHING", "value": "{level}"},
        "manipulation": {"observable": "telemetry.mean_batch_size",
                         "op": ">", "value": 1, "when": "on"},
        "relations": [
            {"id": "R3", "kind": "correctness",
             "statement": "off is byte-identical to baseline",
             "native_test": "tests/prop_b.py::test_off_noop"},
            {"id": "R4", "kind": "behavioral",
             "statement": "throughput is monotonic in batch size",
             "native_test": "tests/prop_b.py::test_monotonic"},
        ],
    }
    raw.update(over)
    return raw


# --- 1. required_relations returns every relation, tagged with factor id ---

def test_required_relations_covers_every_relation_tagged_with_factor_id():
    factors = parse_factors([_numeric_raw(), _choice_raw()])

    pairs = required_relations(factors)

    assert len(pairs) == 3
    by_relation_id = {rel["id"]: fid for fid, rel in pairs}
    assert by_relation_id == {"R1": "L1", "R3": "L5", "R4": "L5"}


# --- 2. parse_pytest_json_report maps nodeid -> outcome == "passed" -------

def test_parse_pytest_json_report_maps_nodeid_to_passed_bool():
    payload = {
        "tests": [
            {"nodeid": "tests/prop_q.py::test_noop", "outcome": "passed"},
            {"nodeid": "tests/prop_b.py::test_off_noop", "outcome": "failed"},
            {"nodeid": "tests/prop_b.py::test_monotonic", "outcome": "passed"},
        ],
    }

    result = parse_pytest_json_report(payload)

    assert result == {
        "tests/prop_q.py::test_noop": True,
        "tests/prop_b.py::test_off_noop": False,
        "tests/prop_b.py::test_monotonic": True,
    }


# --- 3. parse_junit_xml: <failure> means not-passed, bare means passed ----

def test_parse_junit_xml_failure_element_marks_not_passed():
    xml = """<?xml version="1.0"?>
    <testsuite>
        <testcase classname="tests.prop_q" name="test_noop"></testcase>
        <testcase classname="tests.prop_b" name="test_off_noop">
            <failure message="assertion failed">boom</failure>
        </testcase>
    </testsuite>
    """

    result = parse_junit_xml(xml)

    assert result == {
        "tests.prop_q.test_noop": True,
        "tests.prop_b.test_off_noop": False,
    }


# --- 4. reconcile: declared-but-absent is a FAILURE with "not executed" ---

def test_reconcile_marks_declared_relation_absent_from_results_as_failed():
    factors = parse_factors([_numeric_raw()])
    results = {}  # native_test never ran -- e.g. a typo'd identifier

    verdicts = reconcile(factors, results)

    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.passed is False
    assert "not executed" in v.detail


# --- 5. reconcile matches on exact native_test identifier ------------------

def test_reconcile_matches_on_exact_native_test_identifier():
    factors = parse_factors([_numeric_raw(), _choice_raw()])
    results = {
        "tests/prop_q.py::test_noop": True,
        "tests/prop_b.py::test_off_noop": True,
        "tests/prop_b.py::test_monotonic": False,
        # a decoy that is a near-miss of a declared id must not match it
        "tests/prop_q.py::test_noop_extra": False,
    }

    verdicts = reconcile(factors, results)

    by_relation_id = {v.relation_id: v for v in verdicts}
    assert by_relation_id["R1"].passed is True
    assert by_relation_id["R3"].passed is True
    assert by_relation_id["R4"].passed is False
    assert by_relation_id["R4"].native_test == "tests/prop_b.py::test_monotonic"


# --- 6. classify_failures splits correctness vs behavioral failures -------

def test_classify_failures_splits_correctness_and_behavioral():
    factors = parse_factors([_numeric_raw(), _choice_raw()])
    results = {
        "tests/prop_q.py::test_noop": False,  # correctness -- R1
        "tests/prop_b.py::test_off_noop": True,  # correctness -- R3, passes
        "tests/prop_b.py::test_monotonic": False,  # behavioral -- R4
    }
    verdicts = reconcile(factors, results)

    correctness_failures, behavioral_failures = classify_failures(verdicts)

    assert [v.relation_id for v in correctness_failures] == ["R1"]
    assert [v.relation_id for v in behavioral_failures] == ["R4"]


# --- 7. classify_failures returns empty lists when everything passed ------

def test_classify_failures_returns_empty_lists_when_all_passed():
    factors = parse_factors([_numeric_raw(), _choice_raw()])
    results = {
        "tests/prop_q.py::test_noop": True,
        "tests/prop_b.py::test_off_noop": True,
        "tests/prop_b.py::test_monotonic": True,
    }
    verdicts = reconcile(factors, results)

    correctness_failures, behavioral_failures = classify_failures(verdicts)

    assert correctness_failures == []
    assert behavioral_failures == []


# --- 8. a behavioral failure never appears in the correctness list, ------
# --- even when it is the ONLY failure (the L5 discovery-not-bug case) ----

def test_behavioral_only_failure_never_lands_in_correctness_bucket():
    factors = parse_factors([_choice_raw()])
    results = {
        "tests/prop_b.py::test_off_noop": True,       # correctness passes
        "tests/prop_b.py::test_monotonic": False,     # behavioral fails alone
    }
    verdicts = reconcile(factors, results)

    correctness_failures, behavioral_failures = classify_failures(verdicts)

    assert correctness_failures == []
    assert len(behavioral_failures) == 1
    assert behavioral_failures[0].relation_id == "R4"
    assert behavioral_failures[0].kind == "behavioral"


# --- supporting coverage: unrecognized formats and RelationVerdict shape --

def test_reconcile_produces_relation_verdict_instances_with_expected_fields():
    factors = parse_factors([_numeric_raw()])
    results = {"tests/prop_q.py::test_noop": True}

    verdicts = reconcile(factors, results)

    assert len(verdicts) == 1
    v = verdicts[0]
    assert isinstance(v, RelationVerdict)
    assert v.relation_id == "R1"
    assert v.factor_id == "L1"
    assert v.kind == "correctness"
    assert v.native_test == "tests/prop_q.py::test_noop"
    assert v.passed is True


def test_parse_pytest_json_report_rejects_unrecognized_shape_naming_both_formats():
    with pytest.raises(ValueError) as excinfo:
        parse_pytest_json_report({"unexpected": "shape"})

    message = str(excinfo.value)
    assert "pytest" in message.lower()
    assert "junit" in message.lower()


def test_parse_junit_xml_rejects_unrecognized_shape_naming_both_formats():
    with pytest.raises(ValueError) as excinfo:
        parse_junit_xml("<not-a-junit-report/>")

    message = str(excinfo.value)
    assert "pytest" in message.lower()
    assert "junit" in message.lower()
