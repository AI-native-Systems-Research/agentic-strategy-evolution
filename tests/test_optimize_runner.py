"""Behavioral tests for the tokenless per-config execution loop.

``execute_design`` is the module where the optimization campaign kind's cost
advantage actually comes from: every configuration in a design runs through
this loop with zero LLM calls. Both the config runner and the (optional)
integrity check arrive as INJECTED CALLABLES -- production wires them to
real subprocess invocations; these tests inject fakes, following the house
pattern in ``orchestrator/parallel_arms.py`` (``run_units``) and the
``_ScriptedRunner`` pattern in ``tests/test_sdk_dispatch.py``.

The failure taxonomy under test is deliberately asymmetric (spec Sec 6.4):

  * a ``design_space`` invariant violation or an above-``ceiling`` response
    is REJECTED -- the data is untrustworthy and must never reach the fitter.
  * a ``response.constraints`` violation is INFEASIBLE but RETAINED -- it is
    real, trustworthy data about the design space, just an inadmissible cell.
  * a manipulation-predicate failure retries once, then FAILS -- the lever
    never engaged.
  * a runner exception FAILS that one row without aborting the sweep.

No test in this file makes a live LLM call or a real subprocess call; both
seams (``runner``, ``integrity_check``) are fakes constructed in-process.
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.runner import (
    RunOutcome,
    build_cache_key,
    execute_design,
    parse_test_results,
)


def _row(row_index: int, levels: dict, *, role: str = "corner", replicate: int = 0) -> ConfigRow:
    return ConfigRow(row_index=row_index, levels=levels, role=role, replicate=replicate,
                      apply={"cli_args": [], "env": {}, "patches": []})


def _factor(fid: str = "L1", *, manipulation: dict | None = None) -> dict:
    return {
        "id": fid,
        "name": fid,
        "type": "choice",
        "levels": ["off", "on"],
        "apply": f"--{fid}={{level}}",
        "manipulation": manipulation or {
            "observable": f"telemetry.{fid}", "op": "==", "value": "{level}",
        },
        "relations": [
            {"id": f"{fid}-R1", "kind": "correctness",
             "statement": "noop at baseline", "native_test": f"tests/{fid}.py::test_noop"},
        ],
    }


class _RecordingRunner:
    """Dict-driven fake runner: ``{row_index: observation}``.

    Records every call's row for assertion without coupling to internal
    call shapes -- mirrors ``_ScriptedRunner`` in ``tests/test_sdk_dispatch.py``.
    An observation may instead be a ``BaseException`` instance, which is
    raised rather than returned, so tests can script a crashed run.

    When ``retry_observations`` names a row_index, the FIRST call for that
    row returns the primary observation and every subsequent call returns
    the retry observation -- this is how the manipulation-retry tests script
    "fails, then succeeds" or "fails, then fails again".
    """

    def __init__(self, observations: dict[int, object],
                 retry_observations: dict[int, object] | None = None):
        self._observations = observations
        self._retry_observations = retry_observations or {}
        self.calls: list[ConfigRow] = []
        self._seen: set[int] = set()

    def __call__(self, row: ConfigRow) -> dict:
        self.calls.append(row)
        if row.row_index in self._retry_observations and row.row_index in self._seen:
            outcome = self._retry_observations[row.row_index]
        else:
            outcome = self._observations[row.row_index]
        self._seen.add(row.row_index)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _response_spec(**kw) -> dict:
    base = {"primary": {"metric": "throughput", "direction": "maximize"}}
    base.update(kw)
    return base


# ─── 1. Runner called once per row; outcomes returned in row order ───

def test_runner_called_once_per_row_outcomes_in_row_order():
    rows = [_row(0, {"L1": "off"}), _row(1, {"L1": "on"}), _row(2, {"L1": "off"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "telemetry": {"L1": "off"}},
        1: {"throughput": 20.0, "telemetry": {"L1": "on"}},
        2: {"throughput": 15.0, "telemetry": {"L1": "off"}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors,
    )

    assert len(runner.calls) == 3
    assert [o.row_index for o in outcomes] == [0, 1, 2]
    assert all(o.status == "complete" for o in outcomes)


# ─── 2 & 3. Manipulation retry ───

def test_manipulation_failure_retried_once_then_failed():
    rows = [_row(0, {"L1": "on"})]
    factors = parse_factors([_factor()])
    # telemetry.L1 never matches "on" -> manipulation always fails.
    runner = _RecordingRunner({0: {"throughput": 10.0, "telemetry": {"L1": "off"}}})

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, max_retries=1,
    )

    assert len(runner.calls) == 2  # original + one retry
    assert outcomes[0].status == "failed"
    assert outcomes[0].manipulation and outcomes[0].manipulation[0]["ok"] is False


def test_manipulation_failure_then_success_on_retry_is_complete():
    rows = [_row(0, {"L1": "on"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner(
        observations={0: {"throughput": 10.0, "telemetry": {"L1": "off"}}},
        retry_observations={0: {"throughput": 10.0, "telemetry": {"L1": "on"}}},
    )

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, max_retries=1,
    )

    assert len(runner.calls) == 2
    assert outcomes[0].status == "complete"
    assert outcomes[0].manipulation[-1]["ok"] is True


# ─── 4. design_space invariant violation -> rejected, excluded from fitting ───

def test_invariant_violation_is_rejected_and_excluded_from_fitting():
    rows = [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})]
    factors = parse_factors([_factor()])
    invariants = [{"id": "I1", "statement": "single tier",
                    "observable": "config.tier_count", "op": "==", "value": 1}]
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "telemetry": {"L1": "off"}, "config": {"tier_count": 1}},
        1: {"throughput": 20.0, "telemetry": {"L1": "on"}, "config": {"tier_count": 2}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=invariants,
        factors=factors,
    )

    assert outcomes[0].status == "complete"
    assert outcomes[1].status == "rejected"
    assert outcomes[1].invariants and outcomes[1].invariants[0]["ok"] is False

    fitting_inputs = [o for o in outcomes if o.status not in ("rejected",)]
    assert [o.row_index for o in fitting_inputs] == [0]


# ─── 5. response.constraints violation -> infeasible, RETAINED ───

def test_constraint_violation_is_infeasible_and_retained():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    response_spec = _response_spec(constraints=[
        {"metric": "drawdown", "op": ">=", "value": -0.5},
    ])
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "drawdown": -0.9, "telemetry": {"L1": "off"}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=response_spec, invariants=[],
        factors=factors,
    )

    assert len(outcomes) == 1
    assert outcomes[0].status == "infeasible"


# ─── 6. response above ceiling -> rejected, error names the ceiling ───

def test_response_above_ceiling_is_rejected_naming_ceiling():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    response_spec = _response_spec(ceiling={"metric": "bandwidth_gbps", "value": 21.1})
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "bandwidth_gbps": 25.0, "telemetry": {"L1": "off"}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=response_spec, invariants=[],
        factors=factors,
    )

    assert outcomes[0].status == "rejected"
    assert "21.1" in outcomes[0].error


def test_response_at_or_below_ceiling_is_unaffected():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    response_spec = _response_spec(ceiling={"metric": "bandwidth_gbps", "value": 21.1})
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "bandwidth_gbps": 21.1, "telemetry": {"L1": "off"}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=response_spec, invariants=[],
        factors=factors,
    )

    assert outcomes[0].status == "complete"


# ─── 7. Runner raises -> failed, does not abort remaining rows ───

def test_runner_exception_yields_failed_and_continues():
    rows = [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({
        0: RuntimeError("build crashed"),
        1: {"throughput": 20.0, "telemetry": {"L1": "on"}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors,
    )

    assert outcomes[0].status == "failed"
    assert "RuntimeError" in outcomes[0].error
    assert outcomes[1].status == "complete"
    # A crashed run is failed immediately, without spending the manipulation-
    # retry budget on a build that will keep crashing the same way -- retries
    # are for manipulation-predicate transients (assertion 2), not for a
    # runner exception. One call for the crashing row, one for the healthy
    # row.
    assert len(runner.calls) == 2


# ─── 8. on_row callback fires once per completed row ───

def test_on_row_callback_fires_once_per_row():
    rows = [_row(0, {"L1": "off"}), _row(1, {"L1": "on"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "telemetry": {"L1": "off"}},
        1: {"throughput": 20.0, "telemetry": {"L1": "on"}},
    })
    seen: list[int] = []

    execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, on_row=lambda outcome: seen.append(outcome.row_index),
    )

    assert seen == [0, 1]


# ─── 9. build_cache_key ───

def test_build_cache_key_identical_for_same_levels_and_patch_hash():
    row_a = _row(0, {"L1": "off", "L2": 4})
    row_b = _row(1, {"L1": "off", "L2": 4})  # different row_index, same levels

    key_a = build_cache_key(row_a, patch_hash="abc123")
    key_b = build_cache_key(row_b, patch_hash="abc123")

    assert key_a == key_b


def test_build_cache_key_differs_when_level_changes():
    row_a = _row(0, {"L1": "off", "L2": 4})
    row_b = _row(0, {"L1": "on", "L2": 4})

    key_a = build_cache_key(row_a, patch_hash="abc123")
    key_b = build_cache_key(row_b, patch_hash="abc123")

    assert key_a != key_b


def test_build_cache_key_differs_when_patch_hash_changes():
    row = _row(0, {"L1": "off", "L2": 4})

    key_a = build_cache_key(row, patch_hash="abc123")
    key_b = build_cache_key(row, patch_hash="def456")

    assert key_a != key_b


# ─── 10. Held-out metric recorded but excluded from fitting inputs ───

def test_held_out_metric_recorded_but_not_in_fitting_inputs():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    response_spec = _response_spec(held_out=["held_out_return"])
    runner = _RecordingRunner({
        0: {"throughput": 10.0, "held_out_return": 0.42, "telemetry": {"L1": "off"}},
    })

    outcomes = execute_design(
        rows, runner=runner, response_spec=response_spec, invariants=[],
        factors=factors,
    )

    outcome = outcomes[0]
    assert outcome.status == "complete"
    # recorded in the outcome's response (belt-and-braces: caller can still
    # see it happened) ...
    assert math.isclose(outcome.response["held_out_return"], 0.42, rel_tol=1e-9, abs_tol=1e-12)
    # ... but never among the fitting inputs.
    assert "held_out_return" not in outcome.response.get("fitting_inputs", {})


# ─── 11-13. integrity_check ───

def test_integrity_command_runs_once_per_config_nonzero_exit_rejects():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({0: {"throughput": 10.0, "telemetry": {"L1": "off"}}})
    calls: list[ConfigRow] = []

    def integrity_check(row: ConfigRow) -> tuple[bool, str]:
        calls.append(row)
        return False, "checksum mismatch: expected abc got def"

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, integrity_check=integrity_check,
    )

    assert len(calls) == 1
    assert outcomes[0].status == "rejected"
    assert "checksum mismatch" in outcomes[0].error


def test_integrity_check_absent_rows_unaffected():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({0: {"throughput": 10.0, "telemetry": {"L1": "off"}}})

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, integrity_check=None,
    )

    assert outcomes[0].status == "complete"


def test_integrity_failure_is_rejected_not_infeasible():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({0: {"throughput": 10.0, "telemetry": {"L1": "off"}}})

    def integrity_check(row: ConfigRow) -> tuple[bool, str]:
        return False, "nonzero exit"

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, integrity_check=integrity_check,
    )

    assert outcomes[0].status == "rejected"
    assert outcomes[0].status != "infeasible"


def test_integrity_check_passing_leaves_row_complete():
    rows = [_row(0, {"L1": "off"})]
    factors = parse_factors([_factor()])
    runner = _RecordingRunner({0: {"throughput": 10.0, "telemetry": {"L1": "off"}}})

    def integrity_check(row: ConfigRow) -> tuple[bool, str]:
        return True, ""

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=factors, integrity_check=integrity_check,
    )

    assert outcomes[0].status == "complete"


# ─── RunOutcome shape sanity ───

def test_run_outcome_is_frozen_dataclass_with_expected_fields():
    outcome = RunOutcome(
        row_index=0, status="complete", response={}, manipulation=[],
        invariants=[], duration_ms=0, error="",
    )
    with pytest.raises(Exception):
        outcome.status = "failed"  # frozen -> AttributeError/FrozenInstanceError


# ─── parse_test_results: the None-input guard on relations.reconcile ───

def test_parse_test_results_none_becomes_empty_dict_not_typeerror():
    """The realistic crash path: test_command's subprocess dies before

    writing any parseable output, so the caller has nothing to hand
    reconcile(). relations.reconcile(factors, results) is declared
    results: dict[str, bool] and raises a bare TypeError on None -- out of
    contract, but this is the module that produces that input in practice.
    parse_test_results fails closed: no parseable results means every
    declared relation is "not executed", which is already reconcile's own
    failure semantics for an unmatched native_test id. It must never raise
    the stdlib TypeError that a bare `None not in results` would produce.
    """
    assert parse_test_results(None) == {}


def test_parse_test_results_unparseable_blob_becomes_empty_dict():
    assert parse_test_results("not json, not xml, just a crash dump") == {}
    assert parse_test_results(b"\x00\x01garbage") == {}


def test_parse_test_results_pytest_json_report_passthrough():
    payload = {"tests": [{"nodeid": "t.py::test_a", "outcome": "passed"}]}
    assert parse_test_results(payload) == {"t.py::test_a": True}


def test_parse_test_results_junit_xml_passthrough():
    xml = (
        '<testsuite><testcase classname="pkg.mod" name="test_a"/></testsuite>'
    )
    assert parse_test_results(xml) == {"pkg.mod.test_a": True}
