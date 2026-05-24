"""Behavioral tests for the status snapshot reader (#127 Phase A).

Tests synthesize a campaign work-dir on disk, set timestamps explicitly
(via os.utime), and assert on the returned ``StatusSnapshot`` and the
two formatter outputs. Determinism comes from injected ``now=`` and
explicit mtimes — no real wall-clock dependency.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from orchestrator.status import (
    StatusSnapshot,
    format_one_liner,
    format_watch_panel,
    read_status_snapshot,
)


def _write_state(work_dir: Path, *, run_id: str, phase: str, iteration: int) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "state.json").write_text(json.dumps({
        "run_id": run_id, "phase": phase, "iteration": iteration,
    }))


def _write_ledger(work_dir: Path, completed: int) -> None:
    rows = [{"iteration": i + 1, "outcome": "experiment_valid"}
            for i in range(completed)]
    (work_dir / "ledger.json").write_text(json.dumps({"iterations": rows}))


def _write_principles(work_dir: Path, principles: list[dict]) -> None:
    (work_dir / "principles.json").write_text(json.dumps({
        "principles": principles,
    }))


def _write_log(work_dir: Path, iteration: int, events: list[dict], mtime: float) -> Path:
    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    log = iter_dir / "executor_log.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    os.utime(log, (mtime, mtime))
    return log


# ─── Snapshot reader ────────────────────────────────────────────────────────

class TestReadSnapshot:

    def test_minimal_state_only(self, tmp_path):
        _write_state(tmp_path, run_id="r1", phase="DESIGN", iteration=1)

        snap = read_status_snapshot(tmp_path)
        assert snap.run_id == "r1"
        assert snap.phase == "DESIGN"
        assert snap.iteration == 1
        assert snap.completed_iterations == 0
        assert snap.last_event is None
        assert snap.stuck is False

    def test_completed_iterations_from_ledger(self, tmp_path):
        _write_state(tmp_path, run_id="r1", phase="DONE", iteration=3)
        _write_ledger(tmp_path, completed=3)

        snap = read_status_snapshot(tmp_path)
        assert snap.completed_iterations == 3

    def test_active_principles_excludes_retired(self, tmp_path):
        _write_state(tmp_path, run_id="r1", phase="DESIGN", iteration=2)
        _write_principles(tmp_path, [
            {"id": "p1", "status": "active"},
            {"id": "p2", "status": "retired"},
            {"id": "p3", "status": "active"},
        ])

        snap = read_status_snapshot(tmp_path)
        assert snap.active_principles == 2

    def test_last_event_picked_up_from_executor_log(self, tmp_path):
        _write_state(tmp_path, run_id="r1", phase="EXECUTE_ANALYZE", iteration=1)
        mtime = 1_000_000.0
        _write_log(tmp_path, 1, [
            {"tool_name": "Bash", "ts": "..."},
            {"tool_name": "Edit", "ts": "..."},
        ], mtime=mtime)

        snap = read_status_snapshot(tmp_path, now=mtime + 30)
        assert snap.last_event["tool_name"] == "Edit"
        assert 25 <= snap.elapsed_since_last_event <= 35
        assert snap.stuck is False

    def test_stuck_flag_set_after_threshold(self, tmp_path):
        _write_state(tmp_path, run_id="r1", phase="EXECUTE_ANALYZE", iteration=1)
        mtime = 1_000_000.0
        _write_log(tmp_path, 1, [{"tool_name": "Bash"}], mtime=mtime)

        snap = read_status_snapshot(tmp_path, now=mtime + 6 * 60)
        assert snap.stuck is True
        assert snap.elapsed_since_last_event > 5 * 60

    def test_corrupt_state_json_does_not_crash(self, tmp_path):
        (tmp_path / "state.json").write_text("not json")
        snap = read_status_snapshot(tmp_path)
        assert snap.run_id == "?"
        assert snap.stuck is False

    def test_corrupt_executor_log_lines_skipped(self, tmp_path):
        _write_state(tmp_path, run_id="r1", phase="EXECUTE_ANALYZE", iteration=1)
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        log = iter_dir / "executor_log.jsonl"
        log.write_text(
            json.dumps({"tool_name": "Bash"}) + "\n"
            "not json\n"
            + json.dumps({"tool_name": "Edit"}) + "\n"
        )
        os.utime(log, (1_000_000.0, 1_000_000.0))

        snap = read_status_snapshot(tmp_path, now=1_000_000.0 + 5)
        # The last *valid* event is what wins — the corrupt line in the
        # middle is skipped.
        assert snap.last_event["tool_name"] == "Edit"


# ─── #127 Phase B: SDK event tee wiring ────────────────────────────────────

class TestSDKEventTeeIntegration:
    """SDKDispatcher passes event_log_path to its runner so the runner
    can append every SDK message as a JSONL row that the status reader
    picks up. Verify the wiring contract."""

    def _campaign(self, repo_path: Path) -> dict:
        return {
            "research_question": "?",
            "target_system": {
                "name": "test", "description": "test",
                "repo_path": str(repo_path),
            },
        }

    def test_runner_receives_event_log_path_for_iteration(self, tmp_path):
        from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult

        captured: list[dict] = []

        def runner(**kwargs):
            captured.append(kwargs)
            return SDKResult(text="ok")

        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=self._campaign(tmp_path),
            sdk_runner=runner,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-3" / "design_log.md",
            iteration=3,
        )

        elp = captured[0]["event_log_path"]
        assert elp == tmp_path / "runs" / "iter-3" / "executor_log.jsonl"

    def test_each_iteration_gets_its_own_event_log(self, tmp_path):
        from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult

        captured: list[dict] = []

        def runner(**kwargs):
            captured.append(kwargs)
            return SDKResult(text="ok")

        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=self._campaign(tmp_path),
            sdk_runner=runner,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-2" / "design_log.md",
            iteration=2,
        )

        assert "iter-1" in str(captured[0]["event_log_path"])
        assert "iter-2" in str(captured[1]["event_log_path"])


# ─── Formatters ─────────────────────────────────────────────────────────────

class TestFormatOneLiner:

    def test_single_line_no_newlines(self):
        snap = StatusSnapshot(
            run_id="saturation-detect", phase="EXECUTE_ANALYZE", iteration=2,
            completed_iterations=1, active_principles=5,
            last_event={"tool_name": "Bash"},
        )
        out = format_one_liner(snap)
        assert "\n" not in out
        assert "saturation-detect" in out
        assert "EXECUTE_ANALYZE" in out
        assert "iter 2" in out
        assert "Bash" in out

    def test_stuck_marker_appears(self):
        snap = StatusSnapshot(
            run_id="r1", phase="EXECUTE_ANALYZE", iteration=1,
            stuck=True, last_event={"tool_name": "Bash"},
        )
        assert "STUCK" in format_one_liner(snap)

    def test_stable_when_no_new_events(self):
        snap = StatusSnapshot(
            run_id="r1", phase="DESIGN", iteration=1,
            completed_iterations=0, active_principles=0,
        )
        # Two consecutive renderings of the same snapshot — must match
        # exactly. This is the property prompt-embedders rely on.
        assert format_one_liner(snap) == format_one_liner(snap)


class TestFormatWatchPanel:

    def test_multi_line_panel_includes_phase_iter_principles(self):
        snap = StatusSnapshot(
            run_id="r1", phase="DESIGN", iteration=2,
            completed_iterations=1, active_principles=3,
        )
        out = format_watch_panel(snap)
        assert "Phase:" in out
        assert "DESIGN" in out
        assert "Iteration:" in out
        assert "Principles" in out

    def test_stuck_warning_rendered_distinctly(self):
        snap = StatusSnapshot(
            run_id="r1", phase="EXECUTE_ANALYZE", iteration=1,
            last_event={"tool_name": "Bash"},
            elapsed_since_last_event=400,
            stuck=True,
        )
        out = format_watch_panel(snap)
        assert "STUCK" in out

    def test_no_events_renders_placeholder(self):
        snap = StatusSnapshot(run_id="r1", phase="DESIGN", iteration=1)
        out = format_watch_panel(snap)
        assert "no events" in out.lower() or "(no events" in out
