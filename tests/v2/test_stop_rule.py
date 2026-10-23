"""Tests for orchestrator.v2.stop_rule — campaign stop decisions (spec 3.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from orchestrator.v2.stop_rule import (
    check_stop,
    claims_changed,
    best_changed,
    principles_changed,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _findings(
    *,
    hypotheses: list[dict] | None = None,
    best: dict | None = None,
    question_answered: bool = True,
    reason: str = "confirmed",
) -> dict:
    """Build a minimal valid findings dict."""
    if hypotheses is None:
        hypotheses = [
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [],
                "noise_unmeasured": True,
                "noise_reason": "single run",
                "claims": [
                    {"claim_id": "c1", "metric": "latency", "condition": "default", "value": 10},
                ],
            },
        ]
    result: dict[str, Any] = {
        "hypotheses": hypotheses,
        "question_answered": question_answered,
        "reason": reason,
    }
    if best is not None:
        result["best"] = best
    return result


def _principle_updates(*, count: int = 0) -> dict:
    """Build a principle_updates dict with *count* updates."""
    return {
        "updates": [
            {"id": f"p{i}", "text": f"principle {i}", "finding_ref": "h1", "action": "add"}
            for i in range(count)
        ]
    }


def _ledger_entry(
    *,
    iteration: int = 1,
    claims_changed: bool = False,
    best_changed: bool = False,
    principles_changed: bool = False,
) -> dict:
    return {
        "iteration": iteration,
        "claims_changed": claims_changed,
        "best_changed": best_changed,
        "principles_changed": principles_changed,
    }


# ── claims_changed tests ────────────────────────────────────────────────


class TestClaimsChanged:
    def test_different_claims_returns_true(self):
        prev = _findings(hypotheses=[{
            "id": "h1", "status": "CONFIRMED", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [{"claim_id": "c1", "metric": "m", "condition": "default", "value": 10}],
        }])
        curr = _findings(hypotheses=[{
            "id": "h1", "status": "CONFIRMED", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [{"claim_id": "c1", "metric": "m", "condition": "default", "value": 20}],
        }])
        assert claims_changed(prev, curr) is True

    def test_same_claims_returns_false(self):
        findings = _findings()
        assert claims_changed(findings, findings) is False

    def test_no_prev_returns_true(self):
        assert claims_changed(None, _findings()) is True

    def test_added_claim_returns_true(self):
        prev = _findings(hypotheses=[{
            "id": "h1", "status": "CONFIRMED", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [{"claim_id": "c1", "metric": "m", "condition": "a", "value": 1}],
        }])
        curr = _findings(hypotheses=[{
            "id": "h1", "status": "CONFIRMED", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [
                {"claim_id": "c1", "metric": "m", "condition": "a", "value": 1},
                {"claim_id": "c2", "metric": "n", "condition": "b", "value": 2},
            ],
        }])
        assert claims_changed(prev, curr) is True


# ── best_changed tests ──────────────────────────────────────────────────


class TestBestChanged:
    def test_improved_returns_true(self):
        prev = _findings(best={"metric": "score", "value": 50})
        curr = _findings(best={"metric": "score", "value": 60})
        assert best_changed(prev, curr, direction="increase", min_improvement=0) is True

    def test_no_improvement_returns_false(self):
        prev = _findings(best={"metric": "score", "value": 50})
        curr = _findings(best={"metric": "score", "value": 50})
        assert best_changed(prev, curr, direction="increase", min_improvement=0) is False

    def test_decrease_direction(self):
        prev = _findings(best={"metric": "latency", "value": 100})
        curr = _findings(best={"metric": "latency", "value": 80})
        assert best_changed(prev, curr, direction="decrease", min_improvement=0) is True

    def test_min_improvement_threshold(self):
        prev = _findings(best={"metric": "score", "value": 50})
        curr = _findings(best={"metric": "score", "value": 51})
        assert best_changed(prev, curr, direction="increase", min_improvement=5) is False
        curr2 = _findings(best={"metric": "score", "value": 56})
        assert best_changed(prev, curr2, direction="increase", min_improvement=5) is True

    def test_no_prev_best_returns_true(self):
        curr = _findings(best={"metric": "score", "value": 50})
        assert best_changed(None, curr, direction="increase", min_improvement=0) is True

    def test_no_curr_best_returns_false(self):
        prev = _findings(best={"metric": "score", "value": 50})
        curr = _findings()
        assert best_changed(prev, curr, direction="increase", min_improvement=0) is False


# ── principles_changed tests ────────────────────────────────────────────


class TestPrinciplesChanged:
    def test_has_updates_returns_true(self):
        assert principles_changed(_principle_updates(count=1)) is True

    def test_no_updates_returns_false(self):
        assert principles_changed(_principle_updates(count=0)) is False

    def test_none_returns_false(self):
        assert principles_changed(None) is False


# ── check_stop tests ────────────────────────────────────────────────────


class TestCheckStop:
    def test_question_answered(self, tmp_path):
        findings = _findings()
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result == "answered"

    def test_question_not_answered_continues(self, tmp_path):
        findings = _findings(
            question_answered=False, reason="unclear",
            hypotheses=[{
                "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
                "evidence": [],
                "noise_unmeasured": True, "noise_reason": "n/a",
                "claims": [],
            }],
        )
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result is None

    def test_max_iterations(self, tmp_path):
        findings = _findings(
            question_answered=False, reason="unclear",
            hypotheses=[{
                "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
                "evidence": [],
                "noise_unmeasured": True, "noise_reason": "n/a",
                "claims": [],
            }],
        )
        result = check_stop(
            iteration=5,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result == "max_iterations"

    def test_stall_two_quiet_iterations(self, tmp_path):
        ledger = [
            _ledger_entry(iteration=1),
            _ledger_entry(iteration=2),
        ]
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=3,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=ledger,
            max_iterations=10,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result == "stall"

    def test_one_quiet_iter_not_stall(self, tmp_path):
        """Only 1 consecutive quiet iteration (current) → not enough for stall=2."""
        ledger = [
            _ledger_entry(iteration=1, principles_changed=True),
        ]
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=2,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=ledger,
            max_iterations=10,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result is None

    def test_halt_file(self, tmp_path):
        halt = tmp_path / "halt.json"
        halt.write_text('{"fingerprint": "test"}')
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=10,
            stall_iterations=2,
            halt_path=halt,
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result == "halt"

    def test_stop_sentinel(self, tmp_path):
        sentinel = tmp_path / "STOP"
        sentinel.write_text("")
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=10,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=sentinel,
        )
        assert result == "stop_sentinel"

    def test_answered_requires_non_inconclusive(self, tmp_path):
        findings = _findings(hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [{"claim_id": "c1", "metric": "m", "condition": "a", "value": 1}],
        }])
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result is None

    def test_stall_iteration_2_with_default(self, tmp_path):
        """Stall check starts from iteration 2 (needs >= stall_iterations of quiet)."""
        ledger = [_ledger_entry(iteration=1)]
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=2,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=ledger,
            max_iterations=10,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        # Only 1 quiet iteration (iter 1) - not enough for stall_iterations=2
        # Plus current iter makes 2 quiet, should stall
        # Wait - stall check: the current iteration's changes will be computed by the caller.
        # The ledger has iter 1 quiet. If the current (iter 2) is also quiet, that's 2.
        # check_stop receives the *current* iteration's principle_updates, so it can tell.
        # Let me check: stall needs stall_iterations consecutive quiet iterations.
        # Iteration 1: quiet (from ledger). Iteration 2: quiet (current has no updates).
        # That's 2 consecutive → stall.
        assert result == "stall"

    def test_stall_not_triggered_when_claims_changed(self, tmp_path):
        """If current iteration has claims_changed, it's not quiet."""
        ledger = [_ledger_entry(iteration=1)]
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=2,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=ledger,
            max_iterations=10,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
            current_claims_changed=True,
        )
        assert result is None

    def test_stall_not_triggered_when_best_changed(self, tmp_path):
        """If current iteration has best_changed, it's not quiet."""
        ledger = [_ledger_entry(iteration=1)]
        findings = _findings(question_answered=False, hypotheses=[{
            "id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [],
        }])
        result = check_stop(
            iteration=2,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=ledger,
            max_iterations=10,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
            current_best_changed=True,
        )
        assert result is None

    def test_answered_requires_claims_needed_met(self, tmp_path):
        """If claims_needed has an id not in findings, not answered."""
        findings = _findings(hypotheses=[{
            "id": "h1", "status": "CONFIRMED", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [{"claim_id": "c1", "metric": "m", "condition": "a", "value": 1}],
        }])
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
            claims_needed=[{"id": "c1"}, {"id": "c2"}],
        )
        assert result is None

    def test_answered_when_all_claims_met(self, tmp_path):
        findings = _findings(hypotheses=[{
            "id": "h1", "status": "CONFIRMED", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [
                {"claim_id": "c1", "metric": "m", "condition": "a", "value": 1},
                {"claim_id": "c2", "metric": "m2", "condition": "b", "value": 2},
            ],
        }])
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
            claims_needed=[{"id": "c1"}, {"id": "c2"}],
        )
        assert result == "answered"

    def test_answered_rejects_none_status(self, tmp_path):
        """A hypothesis with missing status should not count as non-INCONCLUSIVE."""
        findings = _findings(hypotheses=[{
            "id": "h1", "error_type": "none",
            "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a",
            "claims": [{"claim_id": "c1", "metric": "m", "condition": "a", "value": 1}],
        }])
        result = check_stop(
            iteration=1,
            findings=findings,
            principle_updates=_principle_updates(count=0),
            ledger=[],
            max_iterations=5,
            stall_iterations=2,
            halt_path=tmp_path / "halt.json",
            stop_sentinel_path=tmp_path / "STOP",
        )
        assert result is None


class TestBestChangedNonNumeric:
    def test_non_numeric_values_return_false(self):
        prev = {"best": {"value": "fast"}}
        curr = {"best": {"value": 2.0}}
        assert best_changed(prev, curr) is False
        assert best_changed({"best": {"value": 1.0}}, {"best": {"value": "x"}}) is False


# ── R11e: answered requires status ok and declared claims_needed reqs ─


def _claim_findings(claims: list[dict]) -> dict:
    return _findings(hypotheses=[{
        "id": "h1", "status": "CONFIRMED", "error_type": "none", "evidence": [],
        "noise_unmeasured": True, "noise_reason": "n/a", "claims": claims,
    }])


def _stop(tmp_path, findings, claims_needed=None, status="ok"):
    return check_stop(
        iteration=1, findings=findings, principle_updates=None, ledger=[],
        max_iterations=5, stall_iterations=2,
        halt_path=tmp_path / "halt.json", stop_sentinel_path=tmp_path / "STOP",
        claims_needed=claims_needed, status=status,
    )


def _c(cond="a", **kw):
    return {"claim_id": "c1", "metric": "m", "condition": cond, "value": 1, **kw}


class TestAnsweredRequirements:
    def test_partial_status_not_answered(self, tmp_path):
        assert _stop(tmp_path, _claim_findings([_c()]), status="partial") is None

    def test_partial_with_malformed_seeds_does_not_crash(self, tmp_path):
        need = [{"id": "c1", "min_seeds": 5}]
        assert _stop(tmp_path, _claim_findings([_c(seeds=5)]), need, status="partial") is None

    def test_min_seeds_unmet(self, tmp_path):
        need = [{"id": "c1", "min_seeds": 5}]
        assert _stop(tmp_path, _claim_findings([_c(seeds=[1])]), need) is None

    def test_min_seeds_unmet_when_no_seeds_reported(self, tmp_path):
        need = [{"id": "c1", "min_seeds": 2}]
        assert _stop(tmp_path, _claim_findings([_c()]), need) is None

    def test_min_seeds_met_across_claims(self, tmp_path):
        need = [{"id": "c1", "min_seeds": 3}]
        f = _claim_findings([_c("a", seeds=[1, 2]), _c("b", seeds=[2, 3])])
        assert _stop(tmp_path, f, need) == "answered"

    def test_needs_ci_unmet(self, tmp_path):
        need = [{"id": "c1", "needs_ci": True}]
        assert _stop(tmp_path, _claim_findings([_c()]), need) is None

    def test_needs_ci_met(self, tmp_path):
        need = [{"id": "c1", "needs_ci": True}]
        f = _claim_findings([_c(ci=[0.9, 1.1])])
        assert _stop(tmp_path, f, need) == "answered"

    def test_conditions_unmet(self, tmp_path):
        need = [{"id": "c1", "conditions": ["wl-a", "wl-b"]}]
        assert _stop(tmp_path, _claim_findings([_c("wl-a")]), need) is None

    def test_conditions_met(self, tmp_path):
        need = [{"id": "c1", "conditions": ["wl-a", "wl-b"]}]
        f = _claim_findings([_c("wl-a"), _c("wl-b")])
        assert _stop(tmp_path, f, need) == "answered"

    def test_undeclared_requirements_not_added(self, tmp_path):
        assert _stop(tmp_path, _claim_findings([_c()]), [{"id": "c1"}]) == "answered"


class TestNonScalarClaimValues:
    """Valid agent output (e.g. a Pareto front as a list) must never crash bookkeeping."""

    def _f(self, value, cond="a"):
        return {"hypotheses": [{"id": "h1", "status": "CONFIRMED", "claims": [
            {"claim_id": "c1", "metric": "m", "condition": cond, "value": value, "seeds": [[1, 2]]}]}]}

    def test_list_and_dict_values_compare(self):
        assert claims_changed(None, self._f([[1, 2], [3, 4]])) is True
        assert claims_changed(self._f([1, 2]), self._f([1, 2])) is False
        assert claims_changed(self._f({"a": 1}), self._f({"a": 2})) is True

    def test_unhashable_condition_and_seeds(self, tmp_path):
        f = self._f([1], cond=["x", "y"])
        assert claims_changed(None, f) is True
        need = [{"id": "c1", "min_seeds": 1, "conditions": ["z"]}]
        assert _stop(tmp_path, f, need) is None
