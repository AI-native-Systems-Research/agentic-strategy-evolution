"""Oracle 2(b) binds only the factors the build is authoring.

"A declared correctness test that already passed before the build proves
nothing" is right for the mechanism being built, and wrong for a knob the
target already had: that knob's relation test passing pre-build is the expected
state. Unscoped, every campaign that tunes existing knobs ALONGSIDE a built
mechanism aborted at verify (found authoring a real one against
python-diskcache: three relation tests for existing SQLite settings).
"""
from __future__ import annotations

import json

import pytest

from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.stage_runner import (
    OptimizationAborted,
    _check_tests_failed_before_build,
)

OLD = "nous_bench/test_rel.py::test_pages_applied"
NEW = "tests/test_new.py::test_interval_every_nth"
NEW_OLD_STYLE = "tests/test_core.py::test_interval_existing"


def _factor(fid, tests):
    return {"id": fid, "name": fid.lower(), "type": "choice", "levels": ["a", "b"],
            "apply": f"--{fid}={{level}}",
            "manipulation": {"observable": f"cfg.{fid}", "op": "==", "value": "{level}"},
            "relations": [{"id": f"{fid}-R{i}", "kind": "correctness", "statement": "s",
                           "native_test": t} for i, t in enumerate(tests)]}


def _check(tmp_path, factors_raw, *, ran, passed):
    (tmp_path / "pre_build_tests.json").write_text(
        json.dumps({"ran": sorted(ran), "passed": sorted(passed)}))
    factors = parse_factors(factors_raw)
    all_tests = {r["native_test"] for f in factors_raw for r in f["relations"]}
    results = {t: True for t in all_tests}          # everything passes post-build
    _check_tests_failed_before_build({"optimization": {}}, tmp_path, factors, results)


def test_an_existing_knob_beside_a_built_one_is_not_a_vacuous_test(tmp_path):
    _check(tmp_path, [_factor("PAGES", [OLD]), _factor("AUI", [NEW])],
           ran={OLD}, passed={OLD})                 # NEW did not exist yet


def test_a_built_factors_test_that_already_passed_still_aborts(tmp_path):
    with pytest.raises(OptimizationAborted, match=NEW_OLD_STYLE.split("::")[1]):
        _check(tmp_path, [_factor("PAGES", [OLD]), _factor("AUI", [NEW, NEW_OLD_STYLE])],
               ran={OLD, NEW_OLD_STYLE}, passed={OLD, NEW_OLD_STYLE})


def test_with_no_authored_test_the_rule_stays_strict(tmp_path):
    with pytest.raises(OptimizationAborted, match="test_pages_applied"):
        _check(tmp_path, [_factor("PAGES", [OLD])], ran={OLD}, passed={OLD})
