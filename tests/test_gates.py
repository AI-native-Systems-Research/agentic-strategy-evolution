"""Tests for the human gate logic."""
import pytest

from orchestrator.gates import HumanGate, VALID_DECISIONS


class TestHumanGate:
    def test_auto_approve(self):
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
