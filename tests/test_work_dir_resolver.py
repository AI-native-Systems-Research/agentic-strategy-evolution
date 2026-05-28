"""Behavioral tests for the work_dir resolver (issue #239).

Closes the silent friction where campaign artifacts polluted the
target repo's working tree because every campaign defaulted to
``<target_repo>/.nous/<run_id>/``. The fix:

  1. Honor ``NOUS_CAMPAIGN_PARENT`` env var: when set, work_dir lives
     at ``$NOUS_CAMPAIGN_PARENT/<run_id>/``, fully outside the target.
  2. Record the resolved absolute work_dir in state.json's ``work_dir``
     field (per-campaign source of truth, robust to env var changes).
  3. Worktrees are NOT affected — they continue to live at
     ``<target_repo>/.nous-experiments/<run>/<arm>/`` per #133.

Test contract: pure file/path assertions. No subprocess, no live LLM,
no network — per CLAUDE.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orchestrator.iteration import setup_work_dir
from orchestrator.work_dir_resolver import ENV_VAR, resolve_work_dir


# ─── resolve_work_dir: pure path computation ─────────────────────────────


class TestResolveWorkDirEnvVarUnset:
    """When NOUS_CAMPAIGN_PARENT is unset, behavior is byte-identical
    to today's legacy: <repo_path>/.nous/<run_id>/. This is the
    backward-compatibility floor."""

    def test_with_repo_path_uses_legacy_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        repo = tmp_path / "target-repo"
        repo.mkdir()
        result = resolve_work_dir("my-run", repo)
        assert result == (repo / ".nous" / "my-run").resolve()

    def test_without_repo_path_uses_cwd_relative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        result = resolve_work_dir("my-run", repo_path=None)
        # No repo_path and no env var → bare run_id (relative to CWD)
        assert result == Path("my-run")


class TestResolveWorkDirEnvVarSet:
    """When NOUS_CAMPAIGN_PARENT is set, work_dir lives at
    $NOUS_CAMPAIGN_PARENT/<run_id>/, fully outside the target repo."""

    def test_env_var_overrides_legacy_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()
        # repo_path is provided but should be ignored when env var set.
        result = resolve_work_dir("my-run", repo)
        assert result == (parent / "my-run").resolve()
        # The legacy path is NOT what we get.
        assert result != (repo / ".nous" / "my-run").resolve()

    def test_env_var_works_without_repo_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        result = resolve_work_dir("my-run", repo_path=None)
        assert result == (parent / "my-run").resolve()

    def test_env_var_expanduser(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Tilde expansion should work for shell-rc-friendly configs.
        monkeypatch.setenv(ENV_VAR, "~/nous-campaigns")
        result = resolve_work_dir("my-run", repo_path=None)
        assert "~" not in str(result)
        assert str(result).endswith("nous-campaigns/my-run")


# ─── setup_work_dir: integration (creates dir, writes state.json) ────────


class TestSetupWorkDirEnvVarUnset:
    """Backward-compat: setup_work_dir still creates work_dir under
    <repo>/.nous/<run_id>/ when env var is not set."""

    def test_creates_legacy_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = setup_work_dir("legacy-run", repo_path=str(repo))
        assert work_dir.exists()
        assert (work_dir / "state.json").exists()
        assert work_dir == (repo / ".nous" / "legacy-run").resolve()

    def test_state_json_records_work_dir_field(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # #239: state.json must record its own absolute work_dir.
        monkeypatch.delenv(ENV_VAR, raising=False)
        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = setup_work_dir("legacy-run", repo_path=str(repo))
        state = json.loads((work_dir / "state.json").read_text())
        assert "work_dir" in state, "state.json must include work_dir field"
        assert state["work_dir"] == str(work_dir.resolve())


class TestSetupWorkDirEnvVarSet:
    """When NOUS_CAMPAIGN_PARENT is set, setup_work_dir creates
    $NOUS_CAMPAIGN_PARENT/<run_id>/ — the target repo's working tree
    is untouched."""

    def test_creates_under_env_var_parent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()

        work_dir = setup_work_dir("ext-run", repo_path=str(repo))

        # Created at the env-var location, NOT in the target.
        assert work_dir == (parent / "ext-run").resolve()
        assert work_dir.exists()
        # Crucially: target repo's .nous/ does NOT exist.
        assert not (repo / ".nous").exists(), (
            "When NOUS_CAMPAIGN_PARENT is set, target repo's working tree "
            "must remain untouched (no .nous/ created). Issue #239."
        )

    def test_state_json_records_external_work_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()

        work_dir = setup_work_dir("ext-run", repo_path=str(repo))
        state = json.loads((work_dir / "state.json").read_text())
        assert state["work_dir"] == str(work_dir.resolve())
        # Specifically: NOT the legacy path.
        legacy_path = str((repo / ".nous" / "ext-run").resolve())
        assert state["work_dir"] != legacy_path

    def test_state_json_run_id_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Existing behavior: setup_work_dir sets state.json's run_id.
        # Verify this still holds with the env var path.
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        work_dir = setup_work_dir("my-run", repo_path=None)
        state = json.loads((work_dir / "state.json").read_text())
        assert state["run_id"] == "my-run"

    def test_idempotent_on_repeat_setup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Calling setup_work_dir twice should be a no-op for the templates
        # but still update state.json's run_id and work_dir.
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        wd1 = setup_work_dir("my-run", repo_path=None)
        wd2 = setup_work_dir("my-run", repo_path=None)
        assert wd1 == wd2


class TestSetupWorkDirRobustnessToEnvVarChange:
    """state.json's ``work_dir`` field is the per-campaign source of
    truth. Even if NOUS_CAMPAIGN_PARENT changes between runs, the
    record persists.

    Note: this PR doesn't yet teach downstream tools to *prefer*
    state.json's recorded work_dir over re-derivation. That's a
    follow-up. This test asserts the record is present and accurate
    so that future tooling has a reliable source of truth."""

    def test_recorded_work_dir_survives_env_var_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()

        work_dir = setup_work_dir("my-run", repo_path=str(repo))
        recorded = json.loads((work_dir / "state.json").read_text())["work_dir"]

        # Now unset the env var. The state.json's recorded work_dir
        # is unchanged — it's the source of truth.
        monkeypatch.delenv(ENV_VAR, raising=False)
        # The directory still exists at the old location.
        assert Path(recorded).exists()
        # And its state.json still says it lives there.
        state = json.loads((Path(recorded) / "state.json").read_text())
        assert state["work_dir"] == recorded
