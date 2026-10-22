"""Engine state-machine regression for search-continuation past REFUTE (issue #169).

The engine has no REFUTE -> DONE shortcut; only HUMAN_FINDINGS_GATE -> DONE.
"""
from __future__ import annotations

from orchestrator.engine import TRANSITIONS


# ─── Engine state-machine regression ──────────────────────────────────────


class TestEngineDoesNotAutoTerminateOnRefute:
    def test_human_findings_gate_can_loop_back_to_execute_analyze(self) -> None:
        """The redesign loop is intact — REFUTE flows back through this path."""
        assert "EXECUTE_ANALYZE" in TRANSITIONS["HUMAN_FINDINGS_GATE"]

    def test_human_findings_gate_can_reach_done(self) -> None:
        """DONE remains reachable from HUMAN_FINDINGS_GATE — the human
        gate exists precisely so a human can end the campaign. The
        important property is that REFUTE doesn't bypass that gate."""
        assert "DONE" in TRANSITIONS["HUMAN_FINDINGS_GATE"]

    def test_no_state_offers_a_direct_path_to_done_other_than_findings_gate(
        self,
    ) -> None:
        """Audit: the only state allowed to transition to DONE is
        HUMAN_FINDINGS_GATE. No automatic short-circuit."""
        states_with_done = {
            from_state for from_state, dests in TRANSITIONS.items()
            if "DONE" in dests
        }
        assert states_with_done == {"HUMAN_FINDINGS_GATE"}
