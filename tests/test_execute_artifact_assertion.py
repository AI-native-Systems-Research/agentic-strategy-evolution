"""Behavioral tests for the EXECUTE_ANALYZE-incomplete diagnostic (#200).

Sister to #187 (DesignIncompleteError). When EXECUTE_ANALYZE exits
without producing experiment_plan.yaml / findings.json /
principle_updates.json, the orchestrator surfaces a structured
ExecuteAnalyzeIncompleteError naming what's missing and the four common
causes (max_turns exhaustion, subprocess hang, polling loop, API stall).

These tests exercise the helper + error directly without spawning real
LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─── _missing_execute_artifacts helper ────────────────────────────────────


class TestMissingExecuteArtifactsHelper:
    def test_all_present_returns_empty_list(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _missing_execute_artifacts
        for name in (
            "experiment_plan.yaml", "findings.json", "principle_updates.json",
        ):
            (tmp_path / name).write_text("ok")
        assert _missing_execute_artifacts(tmp_path) == []

    def test_some_missing_lists_only_those(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _missing_execute_artifacts
        (tmp_path / "experiment_plan.yaml").write_text("ok")
        # findings.json + principle_updates.json absent
        result = _missing_execute_artifacts(tmp_path)
        assert "experiment_plan.yaml" not in result
        assert "findings.json" in result
        assert "principle_updates.json" in result

    def test_all_missing_lists_all(self, tmp_path: Path) -> None:
        from orchestrator.iteration import _missing_execute_artifacts
        result = _missing_execute_artifacts(tmp_path)
        assert sorted(result) == [
            "experiment_plan.yaml", "findings.json", "principle_updates.json",
        ]


# ─── ExecuteAnalyzeIncompleteError shape ─────────────────────────────────


class TestExecuteAnalyzeIncompleteError:
    def test_message_names_each_missing_file(self, tmp_path: Path) -> None:
        from orchestrator.iteration import ExecuteAnalyzeIncompleteError
        err = ExecuteAnalyzeIncompleteError(
            missing=["findings.json", "principle_updates.json"],
            iter_dir=tmp_path,
            max_turns=120,
        )
        msg = str(err)
        assert "findings.json" in msg
        assert "principle_updates.json" in msg

    def test_message_mentions_max_turns(self, tmp_path: Path) -> None:
        from orchestrator.iteration import ExecuteAnalyzeIncompleteError
        err = ExecuteAnalyzeIncompleteError(
            missing=["findings.json"], iter_dir=tmp_path, max_turns=137,
        )
        assert "137" in str(err)

    def test_message_lists_actionable_recovery_hints(self, tmp_path: Path) -> None:
        """All four common causes must be named so the operator can
        self-diagnose without grepping the source."""
        from orchestrator.iteration import ExecuteAnalyzeIncompleteError
        msg = str(ExecuteAnalyzeIncompleteError(
            missing=["findings.json"], iter_dir=tmp_path, max_turns=120,
        )).lower()
        assert "max_turns" in msg
        assert "subprocess" in msg or "hang" in msg
        assert "polling" in msg or "sleep" in msg
        assert "stall" in msg or "transport" in msg

    def test_message_points_at_executor_log_under_inputs(
        self, tmp_path: Path,
    ) -> None:
        """#190: streaming log lives at inputs/executor_log.jsonl."""
        from orchestrator.iteration import ExecuteAnalyzeIncompleteError
        msg = str(ExecuteAnalyzeIncompleteError(
            missing=["findings.json"], iter_dir=tmp_path, max_turns=120,
        ))
        assert "inputs/executor_log.jsonl" in msg or (
            "inputs" in msg and "executor_log.jsonl" in msg
        )

    def test_attributes_preserved_for_callers(self, tmp_path: Path) -> None:
        """The orchestrator inspects the exception to write retry_log
        entries; data must be reachable, not just baked into the string."""
        from orchestrator.iteration import ExecuteAnalyzeIncompleteError
        err = ExecuteAnalyzeIncompleteError(
            missing=["findings.json", "experiment_plan.yaml"],
            iter_dir=tmp_path,
            max_turns=120,
        )
        assert err.missing == ["findings.json", "experiment_plan.yaml"]
        assert err.iter_dir == tmp_path
        assert err.max_turns == 120


# ─── retry_log.jsonl integration ─────────────────────────────────────────


class TestRetryLogEntryShape:
    """When EXECUTE_ANALYZE incomplete fires, a structured retry entry
    must be appended so meta_findings (#170) and the operator can see it."""

    def test_log_retry_event_shape(self, tmp_path: Path) -> None:
        from orchestrator.metrics import log_retry_event
        metrics_path = tmp_path / "llm_metrics.jsonl"
        log_retry_event(metrics_path, {
            "iteration": 1,
            "phase": "execute-analyze",
            "failure_type": "execute_incomplete",
            "missing_artifacts": ["findings.json", "principle_updates.json"],
            "max_turns": 120,
        })
        retry_log = tmp_path / "retry_log.jsonl"
        assert retry_log.exists()
        rows = [
            json.loads(line)
            for line in retry_log.read_text().splitlines() if line
        ]
        assert len(rows) == 1
        row = rows[0]
        assert row["failure_type"] == "execute_incomplete"
        assert row["phase"] == "execute-analyze"
        assert row["missing_artifacts"] == [
            "findings.json", "principle_updates.json",
        ]
        assert "timestamp" in row  # auto-stamped


# ─── End-to-end: run_iteration EXECUTE_ANALYZE wiring ────────────────────


class TestRunIterationRaisesOnIncompleteExecute:
    """Pin the orchestrator glue (#200): when EXECUTE_ANALYZE's dispatch
    returns success but the required artifacts aren't on disk, the
    orchestrator (a) writes a structured retry_log row, (b) raises
    ExecuteAnalyzeIncompleteError, and (c) cleans up the experiment
    worktree before raising. A regression that silently swallowed the
    error or skipped the retry-log write would be invisible without
    this test."""

    def test_dispatcher_returns_success_but_no_artifacts_raises(
        self, tmp_path, monkeypatch,
    ) -> None:
        from orchestrator.inline_dispatch import InlineDispatcher
        from orchestrator.iteration import (
            ExecuteAnalyzeIncompleteError,
            run_iteration,
        )

        # Stub InlineDispatcher.dispatch so EXECUTE_ANALYZE returns
        # cleanly without writing the required artifacts — simulating
        # the actual paper-burst friction case (max_turns exhausted /
        # subprocess hang / polling-loop stall, no findings on disk).
        monkeypatch.setattr(
            InlineDispatcher, "dispatch", lambda self, *a, **kw: None,
        )

        # Set up a work_dir with state.json pointing past DESIGN so we
        # land in EXECUTE_ANALYZE on the first run_iteration call.
        repo = tmp_path / "repo"
        repo.mkdir()
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        # Pre-populate DESIGN artifacts so DESIGN doesn't fire.
        (iter_dir / "problem.md").write_text("p")
        (iter_dir / "bundle.yaml").write_text(
            "metadata:\n  iteration: 1\n  family: t\n  research_question: q\n"
            "arms:\n"
            "  - type: h-main\n"
            "    prediction: p\n    mechanism: m\n    diagnostic: d\n"
        )
        (iter_dir / "handoff_snapshot.md").write_text("h")
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "EXECUTE_ANALYZE",
            "iteration": 1,
            "run_id": "exp",
            "family": "test",
            "timestamp": "2026-01-01T00:00:00Z",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({"iterations": []}))
        (work_dir / "principles.json").write_text(
            json.dumps({"principles": []}),
        )

        campaign = {
            "research_question": "q?",
            "run_id": "exp",
            "max_iterations": 1,
            "target_system": {
                "name": "T", "description": "d",
                # No repo_path → no worktree to clean up. Keeps the test
                # focused on the raise + retry_log contract.
            },
            "prompts": {"methodology_layer": "p"},
        }

        with pytest.raises(ExecuteAnalyzeIncompleteError) as excinfo:
            run_iteration(
                campaign, work_dir, iteration=1, agent="inline",
                auto_approve=True,
            )
        # Error names every required artifact (none of them exist).
        assert sorted(excinfo.value.missing) == [
            "experiment_plan.yaml", "findings.json", "principle_updates.json",
        ]

        # retry_log entry shape pinned.
        retry_log = work_dir / "retry_log.jsonl"
        assert retry_log.exists()
        rows = [
            json.loads(line)
            for line in retry_log.read_text().splitlines() if line
        ]
        execute_rows = [
            r for r in rows if r.get("failure_type") == "execute_incomplete"
        ]
        assert len(execute_rows) == 1
        assert execute_rows[0]["phase"] == "execute-analyze"
        assert execute_rows[0]["iteration"] == 1
        assert sorted(execute_rows[0]["missing_artifacts"]) == [
            "experiment_plan.yaml", "findings.json", "principle_updates.json",
        ]
