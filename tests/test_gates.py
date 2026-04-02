"""Tests for the human gate logic."""
import warnings

import pytest

from orchestrator.gates import HumanGate, VALID_DECISIONS, Decision


class TestDecisionEnum:
    def test_all_decisions_in_valid_set(self):
        for d in Decision:
            assert d.value in VALID_DECISIONS

    def test_valid_decisions_matches_enum(self):
        assert VALID_DECISIONS == {d.value for d in Decision}


class TestHumanGate:
    def test_auto_approve(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gate = HumanGate(auto_approve=True)
        decision = gate.prompt("Approve design?", artifact_path="runs/iter-1/hypothesis.md")
        assert decision == "approve"

    def test_auto_reject(self):
        gate = HumanGate(auto_response="reject")
        decision = gate.prompt("Approve design?")
        assert decision == "reject"

    def test_auto_abort(self):
        gate = HumanGate(auto_response="abort")
        decision = gate.prompt("Approve?")
        assert decision == "abort"

    def test_all_valid_decisions(self):
        for d in VALID_DECISIONS:
            gate = HumanGate(auto_response=d)
            assert gate.prompt("Q?") == d

    def test_invalid_auto_response_rejected(self):
        with pytest.raises(ValueError, match="Invalid auto_response"):
            HumanGate(auto_response="maybe")

    def test_auto_approve_with_auto_response_raises(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            HumanGate(auto_approve=True, auto_response="reject")

    def test_auto_approve_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            HumanGate(auto_approve=True)
            assert len(w) == 1
            assert "auto_approve=True" in str(w[0].message)
            assert "bypass" in str(w[0].message).lower()
