"""Tests for orchestrator.cli — run-dir resolution."""
import json
import pytest
from pathlib import Path
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
