"""Tests for the orchestrator state machine engine."""
import json
import os
from unittest.mock import patch

import pytest

from orchestrator.engine import Engine, TRANSITIONS, Phase, ALL_STATES


class TestPhaseEnum:
    def test_all_transition_keys_are_valid_phases(self):
        for state in TRANSITIONS:
            assert state in ALL_STATES

    def test_all_transition_targets_are_valid_phases(self):
        for targets in TRANSITIONS.values():
            for target in targets:
                assert target in ALL_STATES

    def test_done_is_terminal(self):
        assert "DONE" not in TRANSITIONS

    def test_transitions_are_immutable(self):
        with pytest.raises(TypeError):
            TRANSITIONS["NEW_STATE"] = frozenset({"INIT"})

    def test_every_non_terminal_phase_has_transitions_entry(self):
        """Every phase except DONE must have outgoing transitions."""
        for phase in Phase:
            if phase == Phase.DONE:
                continue
            assert phase.value in TRANSITIONS, (
                f"Non-terminal phase {phase.value} has no TRANSITIONS entry"
            )


class TestEngineLoadErrors:
    def test_missing_state_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Engine(tmp_path)

    def test_corrupt_state_file_raises(self, tmp_path):
        (tmp_path / "state.json").write_text("{invalid json")
        with pytest.raises(ValueError, match="Corrupt state.json"):
            Engine(tmp_path)

    def test_missing_keys_raises(self, tmp_path):
        (tmp_path / "state.json").write_text('{"phase": "INIT"}')
        with pytest.raises(ValueError, match="missing required keys"):
            Engine(tmp_path)

    def test_unknown_phase_rejected_at_load(self, tmp_path):
        """Invalid phase is caught at load time, not deferred to transition."""
        state = {
            "phase": "BOGUS",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        with pytest.raises(ValueError, match="unrecognized phase"):
            Engine(tmp_path)

    def test_transition_updates_timestamp(self, tmp_path):
        state = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)
        old_ts = engine.state["timestamp"]
        engine.transition("FRAMING")
        assert engine.state["timestamp"] != old_ts


class TestEngine:
    @pytest.fixture
    def work_dir(self, tmp_path):
        state = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test-001",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        return tmp_path

    def test_load_state(self, work_dir):
        engine = Engine(work_dir)
        assert engine.phase == "INIT"

    def test_state_property_returns_copy(self, work_dir):
        engine = Engine(work_dir)
        state_copy = engine.state
        state_copy["phase"] = "BOGUS"
        assert engine.phase == "INIT"  # original unmodified

    def test_phase_property(self, work_dir):
        engine = Engine(work_dir)
        assert engine.phase == "INIT"
        engine.transition("FRAMING")
        assert engine.phase == "FRAMING"

    def test_iteration_property(self, work_dir):
        engine = Engine(work_dir)
        assert engine.iteration == 0

    def test_run_id_property(self, work_dir):
        engine = Engine(work_dir)
        assert engine.run_id == "test-001"

    def test_transition_init_to_framing(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        assert engine.phase == "FRAMING"
        saved = json.loads((work_dir / "state.json").read_text())
        assert saved["phase"] == "FRAMING"

    def test_invalid_transition_rejected(self, work_dir):
        engine = Engine(work_dir)
        with pytest.raises(ValueError, match="Invalid transition"):
            engine.transition("RUNNING")

    def test_typo_in_transition_target_rejected(self, work_dir):
        """Typos are caught at the call site before checking TRANSITIONS."""
        engine = Engine(work_dir)
        with pytest.raises(ValueError, match="not a recognized phase"):
            engine.transition("FRAMNG")

    def test_checkpoint_resume(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        engine2 = Engine(work_dir)
        assert engine2.phase == "FRAMING"

    def test_full_happy_path(self, work_dir):
        engine = Engine(work_dir)
        path = [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "TUNING", "EXTRACTION", "DONE",
        ]
        for next_state in path:
            engine.transition(next_state)
        assert engine.phase == "DONE"

    def test_refuted_path_skips_tuning(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
        ]:
            engine.transition(s)
        engine.transition("EXTRACTION")
        assert engine.phase == "EXTRACTION"

    def test_framing_to_design_does_not_increment(self, work_dir):
        """Only EXTRACTION -> DESIGN increments, not FRAMING -> DESIGN."""
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        engine.transition("DESIGN")
        assert engine.iteration == 0

    def test_iteration_increments_on_next_design(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "EXTRACTION",
        ]:
            engine.transition(s)
        assert engine.iteration == 0
        engine.transition("DESIGN")
        assert engine.iteration == 1

    def test_design_review_criticals_loop_back(self, work_dir):
        engine = Engine(work_dir)
        for s in ["FRAMING", "DESIGN", "DESIGN_REVIEW"]:
            engine.transition(s)
        engine.transition("DESIGN")  # criticals found, loop back
        assert engine.phase == "DESIGN"
        assert engine.iteration == 0  # must NOT increment

    def test_findings_review_criticals_loop_back(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW",
        ]:
            engine.transition(s)
        engine.transition("RUNNING")  # criticals found, loop back
        assert engine.phase == "RUNNING"

    def test_human_findings_gate_reject(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
        ]:
            engine.transition(s)
        engine.transition("RUNNING")  # human rejects
        assert engine.phase == "RUNNING"

    def test_done_cannot_transition(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "EXTRACTION", "DONE",
        ]:
            engine.transition(s)
        with pytest.raises(ValueError, match="already DONE"):
            engine.transition("INIT")

    def test_multi_iteration(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "EXTRACTION",
        ]:
            engine.transition(s)
        engine.transition("DESIGN")  # iter 0 -> 1
        assert engine.iteration == 1
        for s in [
            "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "EXTRACTION",
        ]:
            engine.transition(s)
        engine.transition("DESIGN")  # iter 1 -> 2
        assert engine.iteration == 2


class TestSaveStateAtomicity:
    def test_rename_failure_cleans_up_temp(self, tmp_path):
        state = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        with patch("os.rename", side_effect=OSError("cross-device link")):
            with pytest.raises(OSError, match="cross-device link"):
                engine.transition("FRAMING")

        # Original state.json is unchanged
        saved = json.loads((tmp_path / "state.json").read_text())
        assert saved["phase"] == "INIT"
        # No temp files left behind
        temps = list(tmp_path.glob("*.json.tmp"))
        assert temps == []

    def test_missing_required_state_field_rejected(self, tmp_path):
        """State without run_id should fail validation."""
        state = {
            "phase": "INIT",
            "iteration": 0,
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        with pytest.raises(ValueError, match="missing required keys"):
            Engine(tmp_path)

    def test_write_failure_cleans_up_fd(self, tmp_path):
        """If os.write fails, fd is closed and temp file removed."""
        state = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        with patch("os.write", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                engine.transition("FRAMING")

        # State unchanged
        assert engine.phase == "INIT"
        saved = json.loads((tmp_path / "state.json").read_text())
        assert saved["phase"] == "INIT"
        # No temp files
        assert list(tmp_path.glob("*.json.tmp")) == []
