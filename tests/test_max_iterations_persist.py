"""Behavioral tests for max_iterations persistence across resume (#197).

Pre-#197 a kill + ``nous resume`` without --max-iterations silently
defaulted to 10, so a campaign launched with --max-iterations 1 would
quietly extend to 10 iterations on resume — major operational footgun.
After #197 the effective max_iterations is persisted into state.json
on first run and read back on resume when no CLI flag is supplied.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _state_with(max_iter: int | None = None, **extra) -> dict:
    state = {
        "phase": "INIT",
        "iteration": 0,
        "run_id": "demo",
        "family": "test",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    if max_iter is not None:
        state["max_iterations"] = max_iter
    state.update(extra)
    return state


class TestPersistMaxIterations:
    def test_persists_value_when_state_exists(self, tmp_path: Path) -> None:
        from orchestrator.campaign import _persist_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with()))
        _persist_max_iterations(tmp_path, 7)
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["max_iterations"] == 7

    def test_silently_skips_when_state_missing(self, tmp_path: Path) -> None:
        """Best-effort: no state.json means no-op (run_campaign sets up
        state via setup_work_dir before calling this in production)."""
        from orchestrator.campaign import _persist_max_iterations
        _persist_max_iterations(tmp_path, 7)  # must not raise
        assert not (tmp_path / "state.json").exists()

    def test_idempotent_when_value_unchanged(self, tmp_path: Path) -> None:
        from orchestrator.campaign import _persist_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with(max_iter=5)))
        before = (tmp_path / "state.json").stat().st_mtime_ns
        _persist_max_iterations(tmp_path, 5)
        after = (tmp_path / "state.json").stat().st_mtime_ns
        assert before == after, "no-op rewrite should not touch the file"


class TestReadPersistedMaxIterations:
    def test_returns_value_when_present(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with(max_iter=3)))
        assert read_persisted_max_iterations(tmp_path) == 3

    def test_returns_none_when_field_absent(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        (tmp_path / "state.json").write_text(json.dumps(_state_with()))
        assert read_persisted_max_iterations(tmp_path) is None

    def test_returns_none_when_state_missing(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        assert read_persisted_max_iterations(tmp_path) is None

    def test_returns_none_when_state_corrupt(self, tmp_path: Path) -> None:
        from orchestrator.campaign import read_persisted_max_iterations
        (tmp_path / "state.json").write_text("not valid json{")
        assert read_persisted_max_iterations(tmp_path) is None

    def test_returns_none_for_invalid_value(self, tmp_path: Path) -> None:
        """Defensive: max_iterations < 1 or non-int doesn't propagate as
        a usable value."""
        from orchestrator.campaign import read_persisted_max_iterations
        for bad in (0, -3, "ten", None, [3]):
            (tmp_path / "state.json").write_text(
                json.dumps({**_state_with(), "max_iterations": bad})
            )
            assert read_persisted_max_iterations(tmp_path) is None, bad


class TestResumeReadsPersistedCap:
    """End-to-end via _cmd_resume: a campaign launched with --max-iterations 1
    leaves max_iterations=1 in state.json; a resume without --max-iterations
    must use that cap rather than defaulting to 10.
    """

    def test_resume_uses_persisted_cap_when_cli_flag_absent(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        import argparse
        from orchestrator import cli as cli_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "demo"
        work_dir.mkdir(parents=True)
        # Mid-flight state with persisted cap.
        (work_dir / "state.json").write_text(json.dumps(
            _state_with(max_iter=1, phase="DESIGN")
        ))

        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            "run_id: demo\n"
            "max_iterations: 99\n"  # Different from persisted cap
            "research_question: q\n"
            f"target_system:\n  name: t\n  description: d\n  repo_path: {repo}\n"
            "prompts:\n  methodology_layer: p\n"
        )

        captured: dict = {}

        def fake_run_campaign(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(cli_mod, "_cmd_resume", cli_mod._cmd_resume)
        # Patch run_campaign at the import site inside _cmd_resume
        from orchestrator import campaign as campaign_mod
        monkeypatch.setattr(campaign_mod, "run_campaign", fake_run_campaign)

        args = argparse.Namespace(
            target=str(campaign_file), max_iterations=None, model=None,
            auto_approve=True, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        cli_mod._cmd_resume(args)

        # Persisted cap (1) wins over campaign.yaml's max_iterations (99).
        assert captured.get("max_iterations") == 1
        out = capsys.readouterr().out
        assert "persisted" in out

    def test_resume_falls_back_to_campaign_yaml_when_state_absent(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        """#197 resolution chain step 3: state.json has no max_iterations
        AND no CLI flag → fall back to campaign.yaml.max_iterations.
        Pre-#197 state files don't carry the field; this preserves their
        intended cap on resume."""
        import argparse
        from orchestrator import cli as cli_mod
        from orchestrator import campaign as campaign_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "demo"
        work_dir.mkdir(parents=True)
        # state.json from a pre-#197 run: no max_iterations field.
        (work_dir / "state.json").write_text(json.dumps(
            _state_with(phase="DESIGN")  # no max_iter
        ))
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            "run_id: demo\n"
            "max_iterations: 7\n"  # campaign.yaml's cap should be honoured
            "research_question: q\n"
            f"target_system:\n  name: t\n  description: d\n  repo_path: {repo}\n"
            "prompts:\n  methodology_layer: p\n"
        )
        captured: dict = {}
        monkeypatch.setattr(
            campaign_mod, "run_campaign",
            lambda *a, **kw: captured.update(kw),
        )

        args = argparse.Namespace(
            target=str(campaign_file), max_iterations=None, model=None,
            auto_approve=True, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        cli_mod._cmd_resume(args)
        assert captured.get("max_iterations") == 7
        out = capsys.readouterr().out
        assert "campaign.yaml" in out

    def test_resume_falls_back_to_default_10_when_neither_set(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        """#197 resolution chain step 4: state has no field, campaign.yaml
        has no field, no CLI flag → hardcoded default 10."""
        import argparse
        from orchestrator import cli as cli_mod
        from orchestrator import campaign as campaign_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "demo"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps(
            _state_with(phase="DESIGN")
        ))
        campaign_file = tmp_path / "campaign.yaml"
        # No max_iterations field at all.
        campaign_file.write_text(
            "run_id: demo\n"
            "research_question: q\n"
            f"target_system:\n  name: t\n  description: d\n  repo_path: {repo}\n"
            "prompts:\n  methodology_layer: p\n"
        )
        captured: dict = {}
        monkeypatch.setattr(
            campaign_mod, "run_campaign",
            lambda *a, **kw: captured.update(kw),
        )

        args = argparse.Namespace(
            target=str(campaign_file), max_iterations=None, model=None,
            auto_approve=True, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        cli_mod._cmd_resume(args)
        assert captured.get("max_iterations") == 10  # hardcoded default

    def test_resume_cli_flag_overrides_persisted(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        """Explicit --max-iterations on resume always wins."""
        import argparse
        from orchestrator import cli as cli_mod
        from orchestrator import campaign as campaign_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        work_dir = repo / ".nous" / "demo"
        work_dir.mkdir(parents=True)
        (work_dir / "state.json").write_text(json.dumps(
            _state_with(max_iter=1, phase="DESIGN")
        ))
        campaign_file = tmp_path / "campaign.yaml"
        campaign_file.write_text(
            "run_id: demo\n"
            "research_question: q\n"
            f"target_system:\n  name: t\n  description: d\n  repo_path: {repo}\n"
            "prompts:\n  methodology_layer: p\n"
        )

        captured: dict = {}
        monkeypatch.setattr(
            campaign_mod, "run_campaign",
            lambda *a, **kw: captured.update(kw),
        )

        args = argparse.Namespace(
            target=str(campaign_file), max_iterations=5, model=None,
            auto_approve=True, timeout=1800, max_cli_retries=10,
            agent="sdk", verbose=False,
        )
        cli_mod._cmd_resume(args)

        assert captured.get("max_iterations") == 5  # CLI wins
        out = capsys.readouterr().out
        assert "CLI override" in out
