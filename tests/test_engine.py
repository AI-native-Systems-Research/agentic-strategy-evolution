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

    def test_done_can_only_reenter_design(self):
        """DONE is terminal within a campaign, but may re-enter DESIGN so a
        finished campaign can be resumed with a higher max_iterations."""
        assert TRANSITIONS["DONE"] == frozenset({"DESIGN"})

    def test_transitions_are_immutable(self):
        with pytest.raises(TypeError):
            TRANSITIONS["NEW_STATE"] = frozenset({"INIT"})

    def test_every_phase_has_transitions_entry(self):
        """Every phase must have outgoing transitions (DONE → DESIGN for resume)."""
        for phase in Phase:
            assert phase.value in TRANSITIONS, (
                f"Phase {phase.value} has no TRANSITIONS entry"
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
        engine.transition("DESIGN")
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
        engine.transition("DESIGN")
        assert engine.phase == "DESIGN"

    def test_iteration_property(self, work_dir):
        engine = Engine(work_dir)
        assert engine.iteration == 0

    def test_run_id_property(self, work_dir):
        engine = Engine(work_dir)
        assert engine.run_id == "test-001"

    def test_transition_init_to_design(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("DESIGN")
        assert engine.phase == "DESIGN"
        saved = json.loads((work_dir / "state.json").read_text())
        assert saved["phase"] == "DESIGN"

    def test_invalid_transition_rejected(self, work_dir):
        engine = Engine(work_dir)
        with pytest.raises(ValueError, match="Invalid transition"):
            engine.transition("DONE")

    def test_typo_in_transition_target_rejected(self, work_dir):
        """Typos are caught at the call site before checking TRANSITIONS."""
        engine = Engine(work_dir)
        with pytest.raises(ValueError, match="not a recognized phase"):
            engine.transition("DESGN")

    def test_checkpoint_resume(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("DESIGN")
        engine2 = Engine(work_dir)
        assert engine2.phase == "DESIGN"

    def test_full_happy_path(self, work_dir):
        engine = Engine(work_dir)
        path = [
            "DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE", "DONE",
        ]
        for next_state in path:
            engine.transition(next_state)
        assert engine.phase == "DONE"

    def test_human_design_gate_reject(self, work_dir):
        """Human rejects at design gate -> back to DESIGN without incrementing.

        #194: iteration ticks once on leaving INIT; rejecting at the gate
        and looping back to DESIGN must NOT tick it again.
        """
        engine = Engine(work_dir)
        for s in ["DESIGN", "HUMAN_DESIGN_GATE"]:
            engine.transition(s)
        # After INIT→DESIGN→GATE we're in iter-1.
        assert engine.iteration == 1
        engine.transition("DESIGN")  # human rejects
        assert engine.phase == "DESIGN"
        assert engine.iteration == 1  # still iter-1, must NOT re-increment

    def test_iteration_ticks_on_leaving_init(self, work_dir):
        """#194: state.iteration must equal 1 once iter-1 starts."""
        engine = Engine(work_dir)
        assert engine.iteration == 0  # INIT
        engine.transition("DESIGN")
        assert engine.iteration == 1  # iter-1 has begun

    def test_iteration_is_1_throughout_iter1_phases(self, work_dir):
        """#194: state.iteration stays at 1 across all of iter-1's phases.

        Pre-#194 the counter sat at 0 throughout iter-1, breaking
        ``nous status --line`` (which read state.iteration) while artifacts
        were correctly being written to runs/iter-1/. Pin it.
        """
        engine = Engine(work_dir)
        for phase in [
            "DESIGN", "HUMAN_DESIGN_GATE",
            "EXECUTE_ANALYZE", "HUMAN_FINDINGS_GATE",
        ]:
            engine.transition(phase)
            assert engine.iteration == 1, (
                f"after transitioning to {phase}, iteration should be 1 "
                f"(matching runs/iter-1/), got {engine.iteration}"
            )

    def test_iteration_ticks_on_leaving_init_via_pre_work(self, work_dir):
        """#194 + #167: PRE_WORK is on the INIT→DESIGN path; counter must
        tick on leaving INIT regardless of which path is taken."""
        engine = Engine(work_dir)
        engine.transition("PRE_WORK")
        assert engine.iteration == 1  # already in iter-1's pre-work
        engine.transition("DESIGN")
        assert engine.iteration == 1  # still iter-1; no double-tick

    def test_iteration_increments_on_done_to_design(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE", "DONE",
        ]:
            engine.transition(s)
        assert engine.iteration == 1  # iter-1 done; counter stable through phases
        engine.transition("DESIGN")
        assert engine.iteration == 2  # iter-2 begins

    def test_human_findings_gate_reject(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE",
        ]:
            engine.transition(s)
        engine.transition("EXECUTE_ANALYZE")  # human rejects, re-run
        assert engine.phase == "EXECUTE_ANALYZE"

    def test_done_can_only_transition_to_design(self, work_dir):
        engine = Engine(work_dir)
        for s in [
            "DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE", "DONE",
        ]:
            engine.transition(s)
        with pytest.raises(ValueError, match="Invalid transition"):
            engine.transition("INIT")
        engine.transition("DESIGN")
        assert engine.phase == "DESIGN"

    def test_done_to_design_increments_iteration(self, work_dir):
        """DONE -> DESIGN must increment iteration (start the next iter).

        #194: state.iteration is now 1 throughout iter-1, ticking to 2 on
        DONE→DESIGN. Pre-#194 it stayed at 0 throughout iter-1.
        """
        engine = Engine(work_dir)
        for s in [
            "DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE", "DONE",
        ]:
            engine.transition(s)
        assert engine.iteration == 1  # iter-1 done; counter has been 1 throughout
        engine.transition("DESIGN")
        assert engine.iteration == 2  # iter-2 begins

    def test_multi_iteration(self, work_dir):
        """#194: counter is 1 from leaving INIT, ticks to 2 on DONE→DESIGN."""
        engine = Engine(work_dir)
        for s in [
            "DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE", "DONE",
        ]:
            engine.transition(s)
        engine.transition("DESIGN")  # iter 1 -> 2
        assert engine.iteration == 2
        for s in [
            "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE",
            "HUMAN_FINDINGS_GATE", "DONE",
        ]:
            engine.transition(s)
        engine.transition("DESIGN")  # iter 2 -> 3
        assert engine.iteration == 3


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

        with patch("os.replace", side_effect=OSError("cross-device link")):
            with pytest.raises(OSError, match="cross-device link"):
                engine.transition("DESIGN")

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
                engine.transition("DESIGN")

        # State unchanged
        assert engine.phase == "INIT"
        saved = json.loads((tmp_path / "state.json").read_text())
        assert saved["phase"] == "INIT"
        # No temp files
        assert list(tmp_path.glob("*.json.tmp")) == []


class TestForcePhase:
    def test_force_phase_sets_phase_and_increments_iteration(self, tmp_path):
        state = {
            "phase": "EXECUTE_ANALYZE",
            "iteration": 1,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)
        engine.force_phase("DESIGN")
        assert engine.phase == "DESIGN"
        assert engine.iteration == 2

    def test_force_phase_rejects_invalid_phase(self, tmp_path):
        state = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)
        with pytest.raises(ValueError, match="not a recognized phase"):
            engine.force_phase("INVALID")

    def test_force_phase_persists_to_disk(self, tmp_path):
        state = {
            "phase": "HUMAN_DESIGN_GATE",
            "iteration": 3,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)
        engine.force_phase("DESIGN")
        saved = json.loads((tmp_path / "state.json").read_text())
        assert saved["phase"] == "DESIGN"
        assert saved["iteration"] == 4
