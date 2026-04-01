"""Tests for the orchestrator state machine engine."""
import json

import pytest

from orchestrator.engine import Engine, TRANSITIONS


class TestStateTransitions:
    def test_valid_transitions_defined(self):
        for state in [
            "INIT", "FRAMING", "DESIGN", "DESIGN_REVIEW",
            "HUMAN_DESIGN_GATE", "RUNNING", "FINDINGS_REVIEW",
            "HUMAN_FINDINGS_GATE", "TUNING", "EXTRACTION",
        ]:
            assert state in TRANSITIONS

    def test_done_is_terminal(self):
        assert "DONE" not in TRANSITIONS


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

    def test_transition_from_unknown_state_raises(self, tmp_path):
        state = {
            "phase": "BOGUS",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)
        with pytest.raises(ValueError, match="Unknown state"):
            engine.transition("FRAMING")

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
        assert engine.state["phase"] == "INIT"

    def test_transition_init_to_framing(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        assert engine.state["phase"] == "FRAMING"
        saved = json.loads((work_dir / "state.json").read_text())
        assert saved["phase"] == "FRAMING"

    def test_invalid_transition_rejected(self, work_dir):
        engine = Engine(work_dir)
        with pytest.raises(ValueError, match="Invalid transition"):
            engine.transition("RUNNING")

    def test_checkpoint_resume(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        engine2 = Engine(work_dir)
        assert engine2.state["phase"] == "FRAMING"

    def test_full_happy_path(self, work_dir):
        engine = Engine(work_dir)
        path = [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "TUNING", "EXTRACTION", "DONE",
        ]
        for next_state in path:
            engine.transition(next_state)
        assert engine.state["phase"] == "DONE"

    def test_refuted_path_skips_tuning(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
        ]:
            engine.transition(s)
        engine.transition("EXTRACTION")
        assert engine.state["phase"] == "EXTRACTION"

    def test_iteration_increments_on_next_design(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "EXTRACTION",
        ]:
            engine.transition(s)
        assert engine.state["iteration"] == 0
        engine.transition("DESIGN")
        assert engine.state["iteration"] == 1

    def test_design_review_criticals_loop_back(self, work_dir):
        engine = Engine(work_dir)
        for s in ["FRAMING", "DESIGN", "DESIGN_REVIEW"]:
            engine.transition(s)
        engine.transition("DESIGN")  # criticals found, loop back
        assert engine.state["phase"] == "DESIGN"
        assert engine.state["iteration"] == 0  # must NOT increment

    def test_findings_review_criticals_loop_back(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW",
        ]:
            engine.transition(s)
        engine.transition("RUNNING")  # criticals found, loop back
        assert engine.state["phase"] == "RUNNING"

    def test_human_findings_gate_reject(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
        ]:
            engine.transition(s)
        engine.transition("RUNNING")  # human rejects
        assert engine.state["phase"] == "RUNNING"

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
        assert engine.state["iteration"] == 1
        for s in [
            "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "EXTRACTION",
        ]:
            engine.transition(s)
        engine.transition("DESIGN")  # iter 1 -> 2
        assert engine.state["iteration"] == 2
