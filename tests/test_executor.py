"""Tests for the deterministic experiment executor."""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator.executor import execute_plan, CommandError, _truncate


SIMPLE_PLAN = {
    "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
    "arms": [
        {
            "arm_id": "h-main",
            "conditions": [
                {"name": "baseline", "cmd": "echo hello"},
                {"name": "treatment", "cmd": "echo world"},
            ],
        },
    ],
}

PLAN_WITH_SETUP = {
    "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
    "setup": [
        {"cmd": "echo setting-up", "description": "build"},
    ],
    "arms": [
        {
            "arm_id": "h-main",
            "conditions": [{"name": "run1", "cmd": "echo done"}],
        },
    ],
}

PLAN_WITH_OUTPUT = {
    "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
    "arms": [
        {
            "arm_id": "h-main",
            "conditions": [
                {
                    "name": "metrics",
                    "cmd": "echo '{\"latency\": 42}' > metrics.json",
                    "output": "metrics.json",
                },
            ],
        },
    ],
}


class TestExecutePlanHappyPath:
    def test_all_commands_succeed(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        results = execute_plan(SIMPLE_PLAN, cwd=tmp_path, iter_dir=iter_dir)

        assert "arms" in results
        assert len(results["arms"]) == 1
        assert len(results["arms"][0]["conditions"]) == 2
        assert results["arms"][0]["conditions"][0]["exit_code"] == 0
        assert "hello" in results["arms"][0]["conditions"][0]["stdout_tail"]
        # execution_results.json written
        assert (iter_dir / "execution_results.json").exists()

    def test_setup_commands_run_first(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        results = execute_plan(PLAN_WITH_SETUP, cwd=tmp_path, iter_dir=iter_dir)

        assert len(results["setup_results"]) == 1
        assert results["setup_results"][0]["exit_code"] == 0
        assert "setting-up" in results["setup_results"][0]["stdout_tail"]

    def test_output_file_captured(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        results = execute_plan(PLAN_WITH_OUTPUT, cwd=tmp_path, iter_dir=iter_dir)

        cond = results["arms"][0]["conditions"][0]
        assert cond["output_content"] is not None
        assert "latency" in cond["output_content"]

    def test_stdout_stderr_saved_to_files(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        execute_plan(SIMPLE_PLAN, cwd=tmp_path, iter_dir=iter_dir)

        stdout_file = iter_dir / "results" / "h-main" / "baseline.stdout"
        assert stdout_file.exists()
        assert "hello" in stdout_file.read_text()

    def test_plan_ref_in_results(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        results = execute_plan(SIMPLE_PLAN, cwd=tmp_path, iter_dir=iter_dir)

        assert results["plan_ref"] == "runs/iter-1/experiment_plan.yaml"


class TestExecutePlanFailures:
    def test_arm_failure_raises_runtime_error(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [{"name": "bad", "cmd": "exit 1"}],
                },
            ],
        }
        with pytest.raises(RuntimeError, match="Command failed"):
            execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir)

    def test_setup_failure_raises_runtime_error(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "setup": [{"cmd": "exit 42", "description": "bad-setup"}],
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "x", "cmd": "echo x"}]},
            ],
        }
        with pytest.raises(RuntimeError, match="Command failed"):
            execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir)

    def test_timeout_raises_runtime_error(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [{"name": "slow", "cmd": "sleep 60"}],
                },
            ],
        }
        with pytest.raises(RuntimeError, match="Command failed"):
            execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir, timeout=1)


class TestExecutePlanRevisions:
    def test_revision_fn_called_on_failure(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()

        bad_plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "bad", "cmd": "exit 1"}]},
            ],
        }
        good_plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "good", "cmd": "echo ok"}]},
            ],
        }

        revision_fn = MagicMock(return_value=good_plan)
        results = execute_plan(
            bad_plan, cwd=tmp_path, iter_dir=iter_dir, revision_fn=revision_fn,
        )

        revision_fn.assert_called_once()
        assert results["arms"][0]["conditions"][0]["name"] == "good"
        # Revised plan saved
        assert (iter_dir / "experiment_plan_v2.yaml").exists()

    def test_max_revisions_exceeded_raises(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()

        bad_plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "bad", "cmd": "exit 1"}]},
            ],
        }
        # Revision always returns another bad plan
        revision_fn = MagicMock(return_value=bad_plan)
        with pytest.raises(RuntimeError, match="no more revisions"):
            execute_plan(
                bad_plan, cwd=tmp_path, iter_dir=iter_dir,
                revision_fn=revision_fn, max_revisions=2,
            )

        assert revision_fn.call_count == 2

    def test_no_revision_fn_raises_immediately(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()

        bad_plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "bad", "cmd": "exit 1"}]},
            ],
        }
        with pytest.raises(RuntimeError, match="Command failed"):
            execute_plan(bad_plan, cwd=tmp_path, iter_dir=iter_dir, revision_fn=None)


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", max_chars=100) == "hello"

    def test_long_text_truncated(self):
        text = "x" * 5000
        result = _truncate(text, max_chars=100)
        assert len(result) < 5000
        assert result.endswith("x" * 100)
        assert "truncated" in result

    def test_default_max_chars(self):
        text = "a" * 10000
        result = _truncate(text)
        assert "truncated" in result
        assert result.endswith("a" * 4000)


class TestCommandError:
    def test_attributes(self):
        err = CommandError(
            step="setup/build", cmd="make", exit_code=2,
            stdout="out", stderr="err",
        )
        assert err.step == "setup/build"
        assert err.cmd == "make"
        assert err.exit_code == 2
        assert err.stdout == "out"
        assert err.stderr == "err"
        assert "setup/build" in str(err)
