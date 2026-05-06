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
    def test_arm_failure_recorded_not_raised(self, tmp_path):
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
        results = execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir)
        assert results is not None
        assert results["arms"][0]["conditions"][0]["exit_code"] == 1

    def test_failed_arm_does_not_block_other_arms(self, tmp_path):
        """Arms are independent — failure in one doesn't stop others."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "bad", "cmd": "exit 1"}]},
                {"arm_id": "h-robustness", "conditions": [{"name": "good", "cmd": "echo ok"}]},
            ],
        }
        results = execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir)
        # Both arms present in results
        assert len(results["arms"]) == 2
        assert results["arms"][0]["arm_id"] == "h-main"
        assert results["arms"][0]["conditions"][0]["exit_code"] == 1
        assert results["arms"][1]["arm_id"] == "h-robustness"
        assert results["arms"][1]["conditions"][0]["exit_code"] == 0
        assert "ok" in results["arms"][1]["conditions"][0]["stdout_tail"]

    def test_setup_failure_returns_empty_results(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "setup": [{"cmd": "exit 42", "description": "bad-setup"}],
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "x", "cmd": "echo x"}]},
            ],
        }
        results = execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir)
        assert results is not None
        assert results["arms"] == []

    def test_timeout_recorded_as_failure(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "slow", "cmd": "sleep 60"}]},
                {"arm_id": "h-other", "conditions": [{"name": "fast", "cmd": "echo done"}]},
            ],
        }
        results = execute_plan(plan, cwd=tmp_path, iter_dir=iter_dir, timeout=1)
        # Timeout arm recorded with exit_code=-1, other arm still ran
        assert results["arms"][0]["conditions"][0]["exit_code"] == -1
        assert results["arms"][1]["conditions"][0]["exit_code"] == 0


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
        assert results["arms"][0]["conditions"][0]["exit_code"] == 0
        # Revised plan saved
        assert (iter_dir / "experiment_plan_v2.yaml").exists()

    def test_revision_only_retries_failed_arms(self, tmp_path):
        """Successful arms are preserved; only failed arms are retried."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()

        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "ok", "cmd": "echo success"}]},
                {"arm_id": "h-ablation", "conditions": [{"name": "bad", "cmd": "exit 1"}]},
            ],
        }
        fixed_plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "ok", "cmd": "echo success"}]},
                {"arm_id": "h-ablation", "conditions": [{"name": "fixed", "cmd": "echo fixed"}]},
            ],
        }

        revision_fn = MagicMock(return_value=fixed_plan)
        results = execute_plan(
            plan, cwd=tmp_path, iter_dir=iter_dir, revision_fn=revision_fn,
        )

        # h-main succeeded on first run, h-ablation was retried
        assert results["arms"][0]["arm_id"] == "h-main"
        assert results["arms"][0]["conditions"][0]["exit_code"] == 0
        assert results["arms"][1]["arm_id"] == "h-ablation"
        assert results["arms"][1]["conditions"][0]["name"] == "fixed"
        assert results["arms"][1]["conditions"][0]["exit_code"] == 0

    def test_max_revisions_exceeded_returns_partial(self, tmp_path):
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
        results = execute_plan(
            bad_plan, cwd=tmp_path, iter_dir=iter_dir,
            revision_fn=revision_fn, max_revisions=2,
        )

        assert revision_fn.call_count == 2
        assert results is not None
        assert results["arms"][0]["conditions"][0]["exit_code"] == 1

    def test_no_revision_fn_returns_results_with_failures(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()

        bad_plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {"arm_id": "h-main", "conditions": [{"name": "bad", "cmd": "exit 1"}]},
            ],
        }
        results = execute_plan(bad_plan, cwd=tmp_path, iter_dir=iter_dir, revision_fn=None)
        assert results is not None
        assert results["arms"][0]["conditions"][0]["exit_code"] == 1


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
        text = "a" * 20000
        result = _truncate(text)
        assert "truncated" in result
        assert result.endswith("a" * 12000)


class TestResetBetweenConditions:
    def test_reset_cmd_runs_before_each_condition(self, tmp_path):
        """reset_cmd should run before every condition in every arm."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        marker = tmp_path / "marker.txt"

        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [
                        {"name": "a", "cmd": "echo a >> log.txt"},
                        {"name": "b", "cmd": "echo b >> log.txt"},
                    ],
                },
                {
                    "arm_id": "h-other",
                    "conditions": [{"name": "c", "cmd": "echo c >> log.txt"}],
                },
            ],
        }

        results = execute_plan(
            plan, cwd=tmp_path, iter_dir=iter_dir,
            reset_cmd=f"echo tick >> {marker}",
        )

        # 3 conditions -> reset_cmd ran 3 times
        assert marker.read_text().count("tick") == 3
        for arm in results["arms"]:
            for cond in arm["conditions"]:
                assert cond["exit_code"] == 0

    def test_reset_cmd_failure_records_condition_failure(self, tmp_path):
        """If reset_cmd fails, condition is recorded as failed and user cmd is skipped."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        sentinel = tmp_path / "should_not_exist.txt"

        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [{"name": "a", "cmd": f"touch {sentinel}"}],
                },
            ],
        }
        results = execute_plan(
            plan, cwd=tmp_path, iter_dir=iter_dir,
            reset_cmd="exit 7",
        )

        cond = results["arms"][0]["conditions"][0]
        assert cond["exit_code"] == 7
        assert not sentinel.exists()  # user cmd was skipped
        assert "RESET FAILED" in cond["stderr_tail"]

    def test_no_reset_cmd_does_not_invoke_subprocess_for_reset(self, tmp_path):
        """Strong assertion: reset_cmd=None must not call _run_cmd with an empty/None cmd."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        from orchestrator import executor as executor_mod
        real_run = executor_mod._run_cmd
        calls = []

        def spy(cmd, cwd, timeout):
            calls.append(cmd)
            return real_run(cmd, cwd, timeout)

        with patch.object(executor_mod, "_run_cmd", side_effect=spy):
            execute_plan(SIMPLE_PLAN, cwd=tmp_path, iter_dir=iter_dir)

        # Only the two user cmds ran, no reset_cmd invocation at all.
        assert calls == ["echo hello", "echo world"]

    def test_reset_cmd_applies_on_revision_retry(self, tmp_path):
        """Regression guard: reset_cmd must also be honored on retry of a revised plan."""
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        marker = tmp_path / "reset_count.txt"

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

        execute_plan(
            bad_plan, cwd=tmp_path, iter_dir=iter_dir,
            revision_fn=revision_fn,
            reset_cmd=f"echo tick >> {marker}",
        )

        # 1 reset for the bad run + 1 reset for the retry = 2
        assert marker.read_text().count("tick") == 2

    def test_reset_cmd_runs_in_real_git_worktree(self, tmp_path):
        """End-to-end: git checkout -- . undoes a tracked edit and leaves untracked files."""
        import shutil
        import subprocess as sp
        if shutil.which("git") is None:
            pytest.skip("git not installed")

        sp.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        sp.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "src.txt").write_text("baseline\n")
        sp.run(["git", "add", "."], cwd=tmp_path, check=True)
        sp.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
        (tmp_path / "patches").mkdir()
        (tmp_path / "patches" / "note.txt").write_text("keep me\n")

        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()

        plan = {
            "metadata": {"iteration": 1, "bundle_ref": "x"},
            "arms": [
                {
                    "arm_id": "h-main",
                    "conditions": [
                        {"name": "dirty", "cmd": "echo mutated > src.txt"},
                        {"name": "check", "cmd": "cat src.txt"},
                    ],
                },
            ],
        }
        results = execute_plan(
            plan, cwd=tmp_path, iter_dir=iter_dir,
            reset_cmd="git checkout -- .",
        )

        check_cond = results["arms"][0]["conditions"][1]
        assert "baseline" in check_cond["stdout_tail"]
        assert "mutated" not in check_cond["stdout_tail"]
        assert (tmp_path / "patches" / "note.txt").exists()


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
