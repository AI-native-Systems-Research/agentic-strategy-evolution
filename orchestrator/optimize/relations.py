"""Relation contracts: verifying target-native property tests actually ran.

Nous never generates or interprets target-language test code. When a
campaign optimizes a target repo, the mechanism it adds gets property /
metamorphic tests written in the target's own idiom -- ``hypothesis`` for
a Python target, ``rapid`` / ``testing/quick`` for Go, ``proptest`` /
``quickcheck`` for Rust, RapidCheck for C++. Those tests live in the
target repo's own test tree and run under the target's own runner.

This module's entire job is to verify a *contract*: each relation a
factor declares (see ``factors.Factor.relations``) names a ``native_test``
identifier; the campaign's declared ``test_command`` runs that identifier
somewhere; the identifier appears in the results; and it passed. That is
why parsing here is limited to two generic test-runner output shapes
(pytest's JSON report, JUnit XML) rather than anything language-specific
-- the harness needs zero knowledge of the target's language or
property-testing library.

The load-bearing rule: a relation that was DECLARED but does not appear
in the results is a FAILURE, never a pass. A typo'd ``native_test``
identifier must not silently disable a correctness gate -- if nothing
ever ran it, the mechanism was never actually verified.

The second load-bearing rule lives in ``classify_failures``: a failed
``behavioral`` relation must never be folded into the ``correctness``
bucket. A monotonicity violation is a *discovery*, not a bug -- e.g. a
batching lever that measures worse in isolation yet is required for the
winning combination. Correctness relations (conservation laws, "disabled
means byte-identical to baseline") hard-fail the campaign when broken;
behavioral relations become recorded findings and the campaign
continues.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from orchestrator.optimize.factors import Factor

_UNRECOGNIZED_FORMAT_MSG = (
    "unrecognized test-result format: expected either a pytest JSON report "
    "(a dict with a 'tests' list of {{'nodeid', 'outcome'}} entries) or "
    "JUnit XML (a <testsuite>/<testsuites> document with <testcase "
    "classname=... name=...> elements); got {got!r}"
)


@dataclass(frozen=True)
class RelationVerdict:
    """The pass/fail contract outcome for one declared relation."""

    relation_id: str
    factor_id: str
    kind: str
    native_test: str
    passed: bool
    detail: str


def required_relations(factors: list[Factor]) -> list[tuple[str, dict]]:
    """Every ``(factor_id, relation)`` pair across all factors.

    Order follows the factors list, then each factor's own relation
    order -- stable so verdicts and reports are reproducible.
    """
    pairs: list[tuple[str, dict]] = []
    for factor in factors:
        for relation in factor.relations:
            pairs.append((factor.id, relation))
    return pairs


def parse_pytest_json_report(payload: dict) -> dict[str, bool]:
    """Map ``tests[].nodeid`` to ``outcome == "passed"``.

    This is the shape produced by ``pytest --json-report`` (via the
    ``pytest-json-report`` plugin) in a target repo -- Nous only reads
    the two fields it needs and ignores everything else (durations,
    tracebacks, etc.).
    """
    tests = payload.get("tests")
    if not isinstance(tests, list):
        raise ValueError(_UNRECOGNIZED_FORMAT_MSG.format(got=payload))
    return {
        str(t["nodeid"]): t.get("outcome") == "passed"
        for t in tests
    }


def parse_junit_xml(text: str) -> dict[str, bool]:
    """Map ``classname.name`` to passed, from a JUnit XML report.

    A ``<testcase>`` with a nested ``<failure>`` (or ``<error>``) is not
    passed; a bare ``<testcase>`` is passed. ``<skipped>`` is treated as
    not passed -- a skipped property test verified nothing, which is
    exactly the "declared but not executed" failure mode this module
    exists to catch.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError(_UNRECOGNIZED_FORMAT_MSG.format(got=text[:200])) from exc

    testcases = root.findall(".//testcase")
    if not testcases:
        raise ValueError(_UNRECOGNIZED_FORMAT_MSG.format(got=text[:200]))

    results: dict[str, bool] = {}
    for tc in testcases:
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        key = f"{classname}.{name}" if classname else name
        not_passed = (
            tc.find("failure") is not None
            or tc.find("error") is not None
            or tc.find("skipped") is not None
        )
        results[key] = not not_passed
    return results


def reconcile(factors: list[Factor], results: dict[str, bool]) -> list[RelationVerdict]:
    """Check every declared relation's ``native_test`` against ``results``.

    Matching is on the exact ``native_test`` string. A relation whose
    identifier does not appear in ``results`` at all is ``passed=False``
    with a detail noting it was declared but not executed -- this is
    the load-bearing case: a relation nobody ran must never look
    satisfied, since that is exactly how a typo'd identifier would
    otherwise silently disable a correctness gate.
    """
    verdicts: list[RelationVerdict] = []
    for factor_id, relation in required_relations(factors):
        native_test = relation["native_test"]
        if native_test not in results:
            verdicts.append(RelationVerdict(
                relation_id=relation["id"],
                factor_id=factor_id,
                kind=relation["kind"],
                native_test=native_test,
                passed=False,
                detail=(
                    f"relation {relation['id']!r} declared native_test "
                    f"{native_test!r} but it was not executed (not found in "
                    f"the test-command results)"
                ),
            ))
            continue

        passed = bool(results[native_test])
        verdicts.append(RelationVerdict(
            relation_id=relation["id"],
            factor_id=factor_id,
            kind=relation["kind"],
            native_test=native_test,
            passed=passed,
            detail="passed" if passed else f"native_test {native_test!r} failed",
        ))
    return verdicts


def classify_failures(
    verdicts: list[RelationVerdict],
) -> tuple[list[RelationVerdict], list[RelationVerdict]]:
    """Split failed verdicts into ``(correctness_failures, behavioral_failures)``.

    Correctness failures hard-fail the campaign. Behavioral failures are
    recorded as findings and never fail the campaign -- a monotonicity
    violation is a discovery, not a bug, and conflating the two buckets
    would make the campaign blind to exactly the non-monotonic compounds
    it exists to find.
    """
    correctness_failures = [
        v for v in verdicts if not v.passed and v.kind == "correctness"
    ]
    behavioral_failures = [
        v for v in verdicts if not v.passed and v.kind == "behavioral"
    ]
    return correctness_failures, behavioral_failures
