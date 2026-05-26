"""Tests for orchestrator.cli — run-dir resolution and commands."""
import argparse
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from orchestrator.cli import resolve_work_dir, _cmd_run, _cmd_resume, _cmd_validate, _cmd_status, _cmd_cost, _cmd_report, _cmd_replay


class TestResolveWorkDir:
    def test_campaign_yaml_resolves_to_repo_path(self, tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase":"INIT"}')
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\ntarget_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
        )
        result = resolve_work_dir(str(campaign_file))
        assert result == work_dir

    def test_bare_run_id_resolves_from_cwd(self, tmp_path):
        nous_dir = tmp_path / ".nous" / "exp1"
        nous_dir.mkdir(parents=True)
        (nous_dir / "state.json").write_text('{"phase":"INIT"}')
        with patch("orchestrator.cli._find_repo_root", return_value=tmp_path):
            result = resolve_work_dir("exp1")
        assert result == nous_dir

    def test_bare_run_id_not_found_raises(self, tmp_path):
        with patch("orchestrator.cli._find_repo_root", return_value=tmp_path):
            with pytest.raises(SystemExit):
                resolve_work_dir("nonexistent")

    def test_full_path_accepted(self, tmp_path):
        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase":"INIT"}')
        result = resolve_work_dir(str(work_dir))
        assert result == work_dir

    def test_campaign_yaml_not_found_raises(self):
        with pytest.raises(SystemExit):
            resolve_work_dir("/no/such/campaign.yaml")

    def test_absolute_path_to_nonexistent_dir_reports_missing_workdir(
        self, tmp_path, capsys
    ):
        """An absolute path that doesn't exist must not be silently
        reinterpreted as a bare run-id — the user clearly intended a path,
        so the error should name that path, not 'no .nous/ in any parent'.
        Regression for #181."""
        missing = tmp_path / "inference-sim" / ".nous" / "paper-burst"
        with pytest.raises(SystemExit):
            resolve_work_dir(str(missing))
        err = capsys.readouterr().err
        assert "Work directory not found" in err
        assert str(missing) in err
        assert ".nous/ directory in any parent" not in err

    def test_absolute_path_to_dir_without_state_json_reports_missing_workdir(
        self, tmp_path, capsys
    ):
        """A directory that exists but lacks state.json (e.g. mid-bootstrap
        or wrong path) must produce the same path-shaped error, not the
        run-id walk-up error. Regression for #181."""
        half = tmp_path / ".nous" / "half-bootstrapped"
        half.mkdir(parents=True)
        with pytest.raises(SystemExit):
            resolve_work_dir(str(half))
        err = capsys.readouterr().err
        assert "Work directory not found" in err
        assert ".nous/ directory in any parent" not in err

    def test_relative_path_with_separator_treated_as_path(
        self, tmp_path, monkeypatch, capsys
    ):
        """A relative target containing a path separator is path-shaped —
        don't fall through to run-id resolution."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            resolve_work_dir("subdir/missing-run")
        err = capsys.readouterr().err
        assert "Work directory not found" in err
        assert ".nous/ directory in any parent" not in err


class TestCmdRun:
    def test_run_errors_if_state_beyond_init(self, tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({"phase": "DESIGN", "iteration": 1, "run_id": "exp1"}))

        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\nmax_iterations: 3\n"
            f"research_question: test question\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
            f"prompts:\n  methodology_layer: prompts/methodology.md\n"
        )
        args = argparse.Namespace(
            campaign=str(campaign_file), max_iterations=None, model=None,
            run_id=None, auto_approve=False, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        with pytest.raises(SystemExit):
            _cmd_run(args)

    def test_run_proceeds_if_fresh(self, tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: newexp\nmax_iterations: 3\n"
            f"research_question: test question\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
            f"prompts:\n  methodology_layer: prompts/methodology.md\n"
        )
        args = argparse.Namespace(
            campaign=str(campaign_file), max_iterations=None, model=None,
            run_id=None, auto_approve=False, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        with patch("orchestrator.campaign.run_campaign") as mock_run, \
             patch("orchestrator.iteration.setup_work_dir", return_value=tmp_path / "work") as mock_setup:
            (tmp_path / "work").mkdir()
            _cmd_run(args)
            mock_setup.assert_called_once()
            mock_run.assert_called_once()


class TestCmdResume:
    def test_resume_errors_if_no_state(self, tmp_path):
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: ghost\nmax_iterations: 3\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {tmp_path}\n"
        )
        args = argparse.Namespace(
            target=str(campaign_file), max_iterations=None, model=None,
            auto_approve=False, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        with pytest.raises(SystemExit):
            _cmd_resume(args)

    def test_resume_calls_run_campaign(self, tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DESIGN", "iteration": 2, "run_id": "exp1"
        }))

        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\nmax_iterations: 5\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
        )
        args = argparse.Namespace(
            target=str(campaign_file), max_iterations=None, model=None,
            auto_approve=False, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        with patch("orchestrator.campaign.run_campaign") as mock_run:
            _cmd_resume(args)
            mock_run.assert_called_once()


class TestCmdValidate:
    def test_validate_design_passes(self, tmp_path):
        import yaml as _yaml
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        (iter_dir / "problem.md").write_text("problem")
        (iter_dir / "handoff_snapshot.md").write_text("snapshot")
        bundle = {
            "metadata": {"iteration": 1, "family": "test", "research_question": "q"},
            "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m", "diagnostic": "d"}],
        }
        (iter_dir / "bundle.yaml").write_text(_yaml.dump(bundle))

        args = argparse.Namespace(phase="design", dir=iter_dir)
        _cmd_validate(args)

    def test_validate_execution_fails_missing_artifacts(self, tmp_path):
        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir()
        args = argparse.Namespace(phase="execution", dir=iter_dir)
        with pytest.raises(SystemExit):
            _cmd_validate(args)


class TestCmdStatus:
    def test_status_prints_campaign_state(self, tmp_path, capsys):
        import json
        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "EXECUTE_ANALYZE", "iteration": 3, "run_id": "exp1"
        }))
        (work_dir / "ledger.json").write_text(json.dumps({
            "iterations": [
                {"iteration": 1, "family": "routing"},
                {"iteration": 2, "family": "admission"},
            ]
        }))
        (work_dir / "principles.json").write_text(json.dumps({
            "principles": [{"id": "P-1", "statement": "X", "status": "active"}]
        }))

        args = argparse.Namespace(target=str(work_dir))
        _cmd_status(args)
        out = capsys.readouterr().out
        assert "exp1" in out
        assert "EXECUTE_ANALYZE" in out
        assert "3" in out
        assert "2 iteration(s)" in out
        assert "1 active" in out


class TestCmdCost:
    def test_cost_prints_summary(self, tmp_path, capsys):
        import json
        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase":"DONE","iteration":2,"run_id":"exp1"}')
        metrics = [
            {"phase": "design", "cost_usd": 0.05, "input_tokens": 1000, "output_tokens": 500, "duration_ms": 3000},
            {"phase": "execute-analyze", "cost_usd": 0.10, "input_tokens": 2000, "output_tokens": 800, "duration_ms": 5000},
        ]
        (work_dir / "llm_metrics.jsonl").write_text("\n".join(json.dumps(m) for m in metrics) + "\n")

        args = argparse.Namespace(target=str(work_dir))
        _cmd_cost(args)
        out = capsys.readouterr().out
        assert "2" in out
        assert "$0.1500" in out
        assert "design" in out

    def test_cost_no_metrics_file(self, tmp_path, capsys):
        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase":"INIT","iteration":0,"run_id":"exp1"}')

        args = argparse.Namespace(target=str(work_dir))
        _cmd_cost(args)
        out = capsys.readouterr().out
        assert "No metrics" in out


class TestCmdReport:
    def test_report_requires_yaml(self, tmp_path):
        work_dir = tmp_path / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text('{"phase":"DONE","iteration":2,"run_id":"exp1"}')

        args = argparse.Namespace(
            target=str(work_dir), model=None, timeout=1800, agent="sdk", verbose=False,
        )
        with pytest.raises(SystemExit):
            _cmd_report(args)

    def test_report_delegates_to_generate_report(self, tmp_path):
        import json
        repo = tmp_path / "myrepo"
        work_dir = repo / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DONE", "iteration": 2, "run_id": "exp1"
        }))
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\nmax_iterations: 3\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
        )
        args = argparse.Namespace(
            target=str(campaign_file), model=None, timeout=1800, agent="sdk", verbose=False,
        )
        with patch("orchestrator.campaign._generate_report") as mock_report:
            _cmd_report(args)
            mock_report.assert_called_once()


class TestCmdReplay:
    def test_replay_errors_if_iter_dir_missing(self, tmp_path):
        import json
        repo = tmp_path / "myrepo"
        work_dir = repo / ".nous" / "exp1"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DONE", "iteration": 2, "run_id": "exp1"
        }))
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\nmax_iterations: 3\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
        )
        args = argparse.Namespace(target=str(campaign_file), iter=5, verbose=False)
        with pytest.raises(SystemExit):
            _cmd_replay(args)

    def test_replay_runs_commands_mechanically(self, tmp_path):
        import json
        import yaml as _yaml
        repo = tmp_path / "myrepo"
        (repo / ".git").mkdir(parents=True)
        work_dir = repo / ".nous" / "exp1"
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        results_dir = iter_dir / "results" / "h-main"
        results_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DONE", "iteration": 1, "run_id": "exp1"
        }))
        plan = {
            "metadata": {"iteration": 1},
            "setup": [{"cmd": "echo setup", "description": "build"}],
            "arms": [{
                "arm_id": "h-main",
                "conditions": [{
                    "name": "baseline",
                    "cmd": f"echo ok > {results_dir}/baseline.json",
                    "output": str(results_dir / "baseline.json"),
                    "inputs": [],
                }],
            }],
        }
        (iter_dir / "experiment_plan.yaml").write_text(_yaml.dump(plan))
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\nmax_iterations: 3\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
        )
        args = argparse.Namespace(target=str(campaign_file), iter=1, verbose=False)
        with patch("orchestrator.worktree.create_experiment_worktree", return_value=(tmp_path / "wt", "exp-id")), \
             patch("orchestrator.worktree.remove_experiment_worktree") as mock_remove:
            (tmp_path / "wt").mkdir()
            _cmd_replay(args)
            mock_remove.assert_called_once()
        assert (results_dir / "baseline.json").exists()

    def test_replay_reports_failed_command(self, tmp_path, capsys):
        import json
        import yaml as _yaml
        repo = tmp_path / "myrepo"
        (repo / ".git").mkdir(parents=True)
        work_dir = repo / ".nous" / "exp1"
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "phase": "DONE", "iteration": 1, "run_id": "exp1"
        }))
        plan = {
            "metadata": {"iteration": 1},
            "setup": [],
            "arms": [{
                "arm_id": "h-main",
                "conditions": [{"name": "bad", "cmd": "exit 1", "output": "", "inputs": []}],
            }],
        }
        (iter_dir / "experiment_plan.yaml").write_text(_yaml.dump(plan))
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            f"run_id: exp1\nmax_iterations: 3\n"
            f"target_system:\n  name: test\n  description: t\n  repo_path: {repo}\n"
        )
        args = argparse.Namespace(target=str(campaign_file), iter=1, verbose=False)
        with patch("orchestrator.worktree.create_experiment_worktree", return_value=(tmp_path / "wt", "exp-id")), \
             patch("orchestrator.worktree.remove_experiment_worktree"):
            (tmp_path / "wt").mkdir()
            with pytest.raises(SystemExit):
                _cmd_replay(args)
        err = capsys.readouterr().err
        assert "h-main/bad" in err
