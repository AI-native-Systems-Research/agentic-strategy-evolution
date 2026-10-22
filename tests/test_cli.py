"""Tests for orchestrator.cli — run-dir resolution and commands."""
import argparse
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from orchestrator.cli import resolve_work_dir, _cmd_reports


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


class TestCmdReports:
    """`nous reports` re-emits meta_findings.json on demand (#242)."""

    def test_emits_meta_findings_against_workdir(
            self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Against a work_dir directly (run_id with no yaml in scope),
        the command emits a meta_findings.json with empty target_system
        context. Useful for triaging legacy or aborted campaigns.
        """
        work_dir = tmp_path / ".nous" / "legacy-run"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "run_id": "legacy-run",
            "iteration": 1,
            "last_entered_phase": "DONE",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({
            "iterations": [{"iteration": 1, "status": "FAILED",
                            "error": "SDK returned error after 1 attempt(s): None"}],
        }))

        args = argparse.Namespace(target=str(work_dir))
        _cmd_reports(args)
        out = capsys.readouterr().out

        # Output one-liner reports the artifact path + counts.
        assert "meta_findings.json" in out
        assert "nous ask" in out

        # Artifact must exist on disk and be schema-valid.
        mf_path = work_dir / "meta_findings.json"
        assert mf_path.exists()
        payload = json.loads(mf_path.read_text())
        assert payload["schema_version"] == "1"
        # The acceptance fixture from #242: ledger FAILED row → ≥ 1 nous_ask.
        assert payload["nous_asks"], payload

    def test_marks_partial_when_workdir_not_terminal(
            self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A campaign whose state.json shows phase != DONE/STOPPED is
        emitted with a `notes` field flagging partial state, so triage
        tooling doesn't conflate on-demand emission with a clean
        terminal record.
        """
        work_dir = tmp_path / ".nous" / "midflight"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "run_id": "midflight",
            "iteration": 1,
            "last_entered_phase": "EXECUTE_ANALYZE",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({
            "iterations": [{"iteration": 1, "status": "FAILED",
                            "error": "abort"}],
        }))

        args = argparse.Namespace(target=str(work_dir))
        _cmd_reports(args)

        payload = json.loads((work_dir / "meta_findings.json").read_text())
        assert "notes" in payload
        assert "non-terminal" in payload["notes"].lower()
        err = capsys.readouterr().err
        assert "non-terminal" in err.lower()

    def test_does_not_mark_partial_when_terminal(
            self, tmp_path: Path) -> None:
        """A campaign at phase=DONE must NOT be flagged as non-terminal."""
        work_dir = tmp_path / ".nous" / "done-run"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "run_id": "done-run",
            "iteration": 1,
            "last_entered_phase": "DONE",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({
            "iterations": [{"iteration": 1, "status": "completed"}],
        }))
        # Build a complete iter-1 finding so the heuristic streams stay quiet.
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "findings.json").write_text(json.dumps({
            "iteration": 1, "bundle_ref": "stub", "arms": [],
            "experiment_valid": True, "discrepancy_analysis": "stub",
        }))

        args = argparse.Namespace(target=str(work_dir))
        _cmd_reports(args)

        payload = json.loads((work_dir / "meta_findings.json").read_text())
        notes = payload.get("notes") or ""
        assert "non-terminal" not in notes.lower(), notes

    def test_yaml_target_loads_full_campaign_context(
            self, tmp_path: Path) -> None:
        """When target is a campaign.yaml, target_system fields drive the
        instrumentation/documentation heuristics. Absence of declared
        observable_metrics should still surface a target_system_ask.
        """
        import yaml as _yaml

        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "yaml-run"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps({
            "run_id": "yaml-run",
            "iteration": 1,
            "last_entered_phase": "DONE",
        }))
        (work_dir / "ledger.json").write_text(json.dumps({
            "iterations": [{"iteration": 1, "status": "completed"}],
        }))
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "findings.json").write_text(json.dumps({
            "iteration": 1, "bundle_ref": "stub", "arms": [],
            "experiment_valid": True, "discrepancy_analysis": "stub",
        }))

        campaign_yaml = tmp_path / "campaign.yaml"
        campaign_yaml.write_text(_yaml.dump({
            "run_id": "yaml-run",
            "target_system": {
                "name": "demo",
                "repo_path": str(repo),
                # Intentionally no observable_metrics → instrumentation ask.
            },
        }))

        args = argparse.Namespace(target=str(campaign_yaml))
        _cmd_reports(args)

        payload = json.loads((work_dir / "meta_findings.json").read_text())
        kinds = {a.get("kind") for a in payload["target_system_asks"]}
        assert "instrumentation" in kinds, payload["target_system_asks"]
