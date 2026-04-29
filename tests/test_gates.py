"""Tests for the human gate logic."""
import json
import os
import warnings

import pytest

from orchestrator.gates import HumanGate, VALID_DECISIONS, Decision


class TestDecisionEnum:
    def test_all_decisions_in_valid_set(self):
        for d in Decision:
            assert d.value in VALID_DECISIONS

    def test_valid_decisions_matches_enum(self):
        assert VALID_DECISIONS == {d.value for d in Decision}


def _make_auto_gate():
    """Create an auto-approve gate with the required env var."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HumanGate(auto_approve=True)


@pytest.fixture(autouse=True)
def _allow_auto_approve(monkeypatch):
    """Set env var so auto_approve=True works in tests."""
    monkeypatch.setenv("NOUS_ALLOW_AUTO_APPROVE", "1")


class TestHumanGate:
    def test_auto_approve(self):
        gate = _make_auto_gate()
        decision, reason = gate.prompt("Approve design?", artifact_path="runs/iter-1/hypothesis.md")
        assert decision == "approve"
        assert reason is None

    def test_auto_reject(self):
        gate = HumanGate(auto_response="reject")
        decision, reason = gate.prompt("Approve design?")
        assert decision == "reject"

    def test_auto_abort(self):
        gate = HumanGate(auto_response="abort")
        decision, reason = gate.prompt("Approve?")
        assert decision == "abort"

    def test_all_valid_decisions(self):
        for d in VALID_DECISIONS:
            gate = HumanGate(auto_response=d)
            decision, reason = gate.prompt("Q?")
            assert decision == d

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

    def test_auto_approve_blocked_without_env_var(self, monkeypatch):
        monkeypatch.delenv("NOUS_ALLOW_AUTO_APPROVE", raising=False)
        with pytest.raises(RuntimeError, match="NOUS_ALLOW_AUTO_APPROVE"):
            HumanGate(auto_approve=True)

    def test_interactive_prompt_valid_input(self, monkeypatch):
        gate = HumanGate()
        monkeypatch.setattr("builtins.input", lambda _: "approve")
        decision, reason = gate.prompt("Approve?")
        assert decision == "approve"
        assert reason is None

    def test_interactive_prompt_reject(self, monkeypatch):
        gate = HumanGate()
        inputs = iter(["reject", "bad design"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        decision, reason = gate.prompt("Approve?")
        assert decision == "reject"
        assert reason == "bad design"

    def test_interactive_prompt_retries_on_invalid(self, monkeypatch):
        gate = HumanGate()
        responses = iter(["invalid", "bad", "approve"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        decision, reason = gate.prompt("Approve?")
        assert decision == "approve"
        assert reason is None

    def test_interactive_prompt_eof_raises(self, monkeypatch):
        gate = HumanGate()
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        with pytest.raises(RuntimeError, match="stdin reached EOF"):
            gate.prompt("Approve?")

    def test_interactive_prompt_keyboard_interrupt(self, monkeypatch):
        gate = HumanGate()
        monkeypatch.setattr(
            "builtins.input",
            lambda _: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        with pytest.raises(KeyboardInterrupt):
            gate.prompt("Approve?")


class TestSummarizedGate:
    """Gates show summaries when a summary file exists."""

    def test_gate_displays_summary_when_present(self, tmp_path, monkeypatch):
        gate = HumanGate(auto_response="approve")
        summary = {
            "gate_type": "design",
            "summary": "Testing batch overhead amortization.",
            "key_points": ["H-main: 20% latency reduction", "Control: no effect at 1"],
        }
        summary_path = tmp_path / "gate_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(" ".join(str(x) for x in a)))

        gate.prompt(
            "Approve?",
            artifact_path=str(tmp_path / "bundle.yaml"),
            summary_path=str(summary_path),
        )

        output = "\n".join(printed)
        assert "Testing batch overhead amortization" in output
        assert "H-main: 20% latency reduction" in output

    def test_gate_works_without_summary(self, monkeypatch):
        """Backwards compatible: gates work when no summary_path is given."""
        gate = HumanGate(auto_response="approve")
        decision, reason = gate.prompt("Approve?")
        assert decision == "approve"
