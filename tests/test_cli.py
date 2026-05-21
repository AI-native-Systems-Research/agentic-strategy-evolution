"""Tests for orchestrator.cli — run-dir resolution and commands."""
import argparse
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from orchestrator.cli import resolve_work_dir, _cmd_run, _cmd_resume, _cmd_validate, _cmd_status, _cmd_cost


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
            agent="api", verbose=False,
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
            agent="api", verbose=False,
        )
        with patch("orchestrator.cli.run_campaign") as mock_run, \
             patch("orchestrator.cli.setup_work_dir", return_value=tmp_path / "work") as mock_setup:
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
            agent="api", verbose=False,
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
            agent="api", verbose=False,
        )
        with patch("orchestrator.cli.run_campaign") as mock_run:
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
