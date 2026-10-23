"""Tests for orchestrator.cli — run-dir resolution and commands."""
import pytest
from unittest.mock import patch

from orchestrator.cli import resolve_work_dir


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
