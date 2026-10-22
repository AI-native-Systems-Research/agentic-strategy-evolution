"""Tests for orchestrator.v2.hooks — in-process hook callbacks (spec 3.3)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pytest

from orchestrator.v2.hooks import (
    DEFAULT_EXPERIMENT_COMMANDS,
    HookState,
    build_hooks,
    is_experiment_command,
    make_post_tool_use_hook,
    make_post_tool_use_failure_hook,
    make_precompact_hook,
    make_stop_hook,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_state(
    tmp_path: Path,
    *,
    phase: str = "BASELINE",
    iteration: int = 0,
    secrets: dict[str, str] | None = None,
    experiment_commands: list[str] | None = None,
) -> HookState:
    work_dir = tmp_path / "campaign"
    work_dir.mkdir(parents=True, exist_ok=True)
    return HookState(
        work_dir=work_dir,
        phase=phase,
        iteration=iteration,
        secrets=secrets or {},
        experiment_commands=experiment_commands or [],
        now=lambda: 1000.0,
    )


def _post_tool_input(
    *,
    tool_name: str = "Bash",
    command: str = "echo hello",
    tool_response: str = "hello",
    tool_use_id: str = "tu-1",
    session_id: str = "ses-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "tool_response": tool_response,
        "tool_use_id": tool_use_id,
    }


def _post_tool_failure_input(
    *,
    tool_name: str = "Bash",
    command: str = "false",
    error: str = "Exit code 1",
    tool_use_id: str = "tu-2",
    session_id: str = "ses-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUseFailure",
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "tool_response": "",
        "error": error,
        "tool_use_id": tool_use_id,
    }


def _stop_input(*, session_id: str = "ses-1") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "hook_event_name": "Stop",
        "stop_hook_active": True,
    }


def _precompact_input(*, session_id: str = "ses-1") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "hook_event_name": "PreCompact",
    }


def _read_runs(work_dir: Path) -> list[dict]:
    path = work_dir / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


# ── PostToolUse tests ────────────────────────────────────────────────────


class TestPostToolUseHook:
    def test_appends_row_to_runs_jsonl(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(command="ls -la", tool_response="file.txt"), None, None)

        rows = _read_runs(state.work_dir)
        assert len(rows) == 1
        row = rows[0]
        assert row["command"] == "ls -la"
        assert row["exit_code"] == 0
        assert row["tool_use_id"] == "tu-1"
        assert row["phase"] == "BASELINE"
        assert row["iter"] == 0
        assert "ts" in row

    def test_records_output_bytes(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_hook(state)

        response = "a" * 500
        hook(_post_tool_input(tool_response=response), None, None)

        rows = _read_runs(state.work_dir)
        assert rows[0]["output_bytes"] == 500

    def test_background_command(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_hook(state)

        inp = _post_tool_input(command="sleep 100 &")
        inp["tool_input"]["run_in_background"] = True
        hook(inp, None, None)

        rows = _read_runs(state.work_dir)
        assert rows[0]["exit_code"] is None
        assert rows[0]["background"] is True

    def test_non_background_not_flagged(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(), None, None)

        rows = _read_runs(state.work_dir)
        assert rows[0]["background"] is False

    def test_non_bash_tool_ignored(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(tool_name="Read"), None, None)

        rows = _read_runs(state.work_dir)
        assert len(rows) == 0

    def test_masks_secrets(self, tmp_path):
        state = _make_state(tmp_path, secrets={"DB_PASS": "hunter2"})
        hook = make_post_tool_use_hook(state)

        hook(
            _post_tool_input(
                command="curl -u admin:hunter2 http://db",
                tool_response="connected with hunter2",
            ),
            None,
            None,
        )

        rows = _read_runs(state.work_dir)
        assert "hunter2" not in rows[0]["command"]
        assert "<secret:DB_PASS>" in rows[0]["command"]
        assert "hunter2" not in json.dumps(rows[0])

    def test_experiment_command_tagged(self, tmp_path):
        state = _make_state(
            tmp_path,
            experiment_commands=[r"\bblis\s+run\b"],
        )
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(command="blis run --config x.yaml"), None, None)

        rows = _read_runs(state.work_dir)
        assert rows[0]["experiment"] is True

    def test_non_experiment_not_tagged(self, tmp_path):
        state = _make_state(
            tmp_path,
            experiment_commands=[r"\bblis\s+run\b"],
        )
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(command="ls -la"), None, None)

        rows = _read_runs(state.work_dir)
        assert rows[0]["experiment"] is False

    def test_resets_consecutive_blocks(self, tmp_path):
        state = _make_state(tmp_path)
        state.consecutive_blocks = 5
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(), None, None)

        assert state.consecutive_blocks == 0

    def test_multiple_rows_appended(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_hook(state)

        hook(_post_tool_input(command="cmd1", tool_use_id="tu-1"), None, None)
        hook(_post_tool_input(command="cmd2", tool_use_id="tu-2"), None, None)

        rows = _read_runs(state.work_dir)
        assert len(rows) == 2
        assert rows[0]["command"] == "cmd1"
        assert rows[1]["command"] == "cmd2"


# ── PostToolUseFailure tests ─────────────────────────────────────────────


class TestPostToolUseFailureHook:
    def test_records_exit_code_from_error(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_failure_hook(state)

        hook(
            _post_tool_failure_input(error="Exit code 42"),
            None,
            None,
        )

        rows = _read_runs(state.work_dir)
        assert len(rows) == 1
        assert rows[0]["exit_code"] == 42

    def test_exit_code_defaults_to_minus_1(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_failure_hook(state)

        hook(
            _post_tool_failure_input(error="Some random error"),
            None,
            None,
        )

        rows = _read_runs(state.work_dir)
        assert rows[0]["exit_code"] == -1

    def test_non_bash_tool_ignored(self, tmp_path):
        state = _make_state(tmp_path)
        hook = make_post_tool_use_failure_hook(state)

        hook(
            _post_tool_failure_input(tool_name="Write"),
            None,
            None,
        )

        rows = _read_runs(state.work_dir)
        assert len(rows) == 0

    def test_masks_secrets_in_failure(self, tmp_path):
        state = _make_state(tmp_path, secrets={"TOKEN": "abc123"})
        hook = make_post_tool_use_failure_hook(state)

        hook(
            _post_tool_failure_input(
                command="curl -H 'Auth: abc123'",
                error="Exit code 1: abc123 rejected",
            ),
            None,
            None,
        )

        rows = _read_runs(state.work_dir)
        assert "abc123" not in json.dumps(rows[0])
        assert "<secret:TOKEN>" in rows[0]["command"]

    def test_resets_consecutive_blocks(self, tmp_path):
        state = _make_state(tmp_path)
        state.consecutive_blocks = 3
        hook = make_post_tool_use_failure_hook(state)

        hook(_post_tool_failure_input(), None, None)

        assert state.consecutive_blocks == 0


# ── Stop hook tests ──────────────────────────────────────────────────────


class TestStopHook:
    def test_blocks_when_baseline_missing(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE")
        hook = make_stop_hook(state)

        result = hook(_stop_input(), None, None)

        assert result is not None
        assert result["decision"] == "block"
        assert "baseline" in result["reason"].lower() or "error" in result["reason"].lower()

    def test_allows_when_baseline_valid(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE")
        # Write a valid baseline.json
        baseline = {
            "task_type": "debug",
            "command": "make test",
            "git_sha": "abc1234",
            "observation": {
                "reproduced": True,
                "symptom": "crash",
                "expected": 0,
                "actual": 1,
            },
            "metrics_path": "results/metrics.json",
            "noise": {"deterministic": True},
        }
        (state.work_dir / "baseline.json").write_text(json.dumps(baseline))

        hook = make_stop_hook(state)
        result = hook(_stop_input(), None, None)

        assert result is None or result.get("decision") != "block"

    def test_increments_consecutive_blocks(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE")
        hook = make_stop_hook(state)

        assert state.consecutive_blocks == 0
        hook(_stop_input(), None, None)
        assert state.consecutive_blocks == 1
        hook(_stop_input(), None, None)
        assert state.consecutive_blocks == 2

    def test_allows_after_6_consecutive_blocks(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE")
        state.consecutive_blocks = 6
        hook = make_stop_hook(state)

        result = hook(_stop_input(), None, None)

        assert result is None or result.get("decision") != "block"

    def test_blocks_on_invalid_findings_in_execute(self, tmp_path):
        state = _make_state(tmp_path, phase="EXECUTE", iteration=1)
        iter_dir = state.work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        # Write a bundle but no findings — Stop should block
        bundle = {
            "hypotheses": [
                {
                    "id": "h1",
                    "role": "main",
                    "family": "f1",
                    "mechanism": "m1",
                    "prediction": {"metric": "x", "direction": "increase"},
                    "control": "ctrl",
                    "falsified_if": "decrease",
                    "claim_ids": [],
                }
            ],
            "single_family_reason": "testing",
        }
        (iter_dir / "bundle.json").write_text(json.dumps(bundle))

        hook = make_stop_hook(state)
        result = hook(_stop_input(), None, None)

        assert result is not None
        assert result["decision"] == "block"

    def test_reason_includes_error_details(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE")
        hook = make_stop_hook(state)

        result = hook(_stop_input(), None, None)

        assert result is not None
        assert len(result["reason"]) > 10


# ── PreCompact hook tests ────────────────────────────────────────────────


class TestPreCompactHook:
    def test_writes_digest_json(self, tmp_path):
        state = _make_state(tmp_path, phase="DESIGN", iteration=1)

        # Write a baseline for digest content
        baseline = {
            "task_type": "debug",
            "command": "make test",
            "git_sha": "abc1234",
            "observation": {"reproduced": True, "symptom": "crash"},
            "metrics_path": "results/metrics.json",
            "noise": {"deterministic": True},
        }
        (state.work_dir / "baseline.json").write_text(json.dumps(baseline))

        # Write principles
        (state.work_dir / "principles.json").write_text(
            json.dumps([{"id": "p1", "text": "Use mocks", "confidence": 0.8}])
        )

        hook = make_precompact_hook(state)
        hook(_precompact_input(), None, None)

        digest_path = state.work_dir / "state" / "digest.json"
        assert digest_path.exists()
        digest = json.loads(digest_path.read_text())
        assert digest["phase"] == "DESIGN"
        assert "baseline" in digest

    def test_digest_is_secret_masked(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE", secrets={"KEY": "s3cr3t"})

        baseline = {
            "task_type": "debug",
            "command": "curl -H 'Key: s3cr3t'",
            "git_sha": "abc1234",
            "observation": {"reproduced": True, "symptom": "s3cr3t error"},
            "metrics_path": "results/metrics.json",
            "noise": {"deterministic": True},
        }
        (state.work_dir / "baseline.json").write_text(json.dumps(baseline))

        hook = make_precompact_hook(state)
        hook(_precompact_input(), None, None)

        digest_path = state.work_dir / "state" / "digest.json"
        text = digest_path.read_text()
        assert "s3cr3t" not in text
        assert "<secret:KEY>" in text

    def test_digest_includes_principles(self, tmp_path):
        state = _make_state(tmp_path, phase="EXECUTE", iteration=2)

        (state.work_dir / "baseline.json").write_text(
            json.dumps({
                "task_type": "optimize",
                "command": "bench",
                "git_sha": "def5678",
                "observation": {"score": 42.0},
                "metrics_path": "m.json",
                "noise": {"deterministic": True},
            })
        )
        (state.work_dir / "principles.json").write_text(
            json.dumps([
                {"id": "p1", "text": "Parallel is better", "confidence": 0.9},
                {"id": "p2", "text": "Cache helps", "confidence": 0.7},
            ])
        )

        hook = make_precompact_hook(state)
        hook(_precompact_input(), None, None)

        digest = json.loads(
            (state.work_dir / "state" / "digest.json").read_text()
        )
        assert "principles" in digest
        assert len(digest["principles"]) == 2

    def test_digest_without_optional_files(self, tmp_path):
        state = _make_state(tmp_path, phase="BASELINE")
        # No baseline, no principles — should still write a digest
        hook = make_precompact_hook(state)
        hook(_precompact_input(), None, None)

        digest_path = state.work_dir / "state" / "digest.json"
        assert digest_path.exists()
        digest = json.loads(digest_path.read_text())
        assert digest["phase"] == "BASELINE"


# ── Experiment command matching tests ────────────────────────────────────


class TestExperimentCommandMatching:
    def test_blis_run_matches(self):
        assert is_experiment_command("blis run --config x.yaml", DEFAULT_EXPERIMENT_COMMANDS)

    def test_python_bench_matches(self):
        assert is_experiment_command("python3 run_bench.py", DEFAULT_EXPERIMENT_COMMANDS)

    def test_python_search_matches(self):
        assert is_experiment_command("python search.py --n 10", DEFAULT_EXPERIMENT_COMMANDS)

    def test_make_bench_matches(self):
        assert is_experiment_command("make bench", DEFAULT_EXPERIMENT_COMMANDS)

    def test_ls_does_not_match(self):
        assert not is_experiment_command("ls -la", DEFAULT_EXPERIMENT_COMMANDS)

    def test_echo_does_not_match(self):
        assert not is_experiment_command("echo hello", DEFAULT_EXPERIMENT_COMMANDS)

    def test_custom_pattern(self):
        patterns = [r"\bcargo\s+bench\b"]
        assert is_experiment_command("cargo bench --release", patterns)
        assert not is_experiment_command("cargo build", patterns)

    def test_empty_patterns(self):
        assert not is_experiment_command("blis run", [])

    def test_python_sweep_matches(self):
        assert is_experiment_command("python sweep_params.py", DEFAULT_EXPERIMENT_COMMANDS)

    def test_python_run_matches(self):
        assert is_experiment_command("python run.py", DEFAULT_EXPERIMENT_COMMANDS)


# ── build_hooks integration tests ────────────────────────────────────────


class TestBuildHooks:
    def test_returns_hook_dict_with_expected_keys(self, tmp_path):
        state = _make_state(tmp_path)
        hooks = build_hooks(state)

        assert "PostToolUse" in hooks
        assert "PostToolUseFailure" in hooks
        assert "Stop" in hooks
        assert "PreCompact" in hooks

    def test_no_pre_tool_use_hook(self, tmp_path):
        state = _make_state(tmp_path)
        hooks = build_hooks(state)

        assert "PreToolUse" not in hooks

    def test_stop_hook_has_120s_timeout(self, tmp_path):
        state = _make_state(tmp_path)
        hooks = build_hooks(state)

        stop_matchers = hooks["Stop"]
        assert len(stop_matchers) == 1
        assert stop_matchers[0]["timeout"] == 120.0

    def test_precompact_hook_has_60s_timeout(self, tmp_path):
        state = _make_state(tmp_path)
        hooks = build_hooks(state)

        precompact_matchers = hooks["PreCompact"]
        assert len(precompact_matchers) == 1
        assert precompact_matchers[0]["timeout"] == 60.0
