"""Behavioral tests for the work_dir resolver (issue #239).

Closes the silent friction where campaign artifacts polluted the
target repo's working tree because every campaign defaulted to
``<target_repo>/.nous/<run_id>/``. The fix:

  1. Honor ``NOUS_CAMPAIGN_PARENT`` env var: when set, work_dir lives
     at ``$NOUS_CAMPAIGN_PARENT/<run_id>/``, fully outside the target.
  2. Record the resolved absolute work_dir + repo_path in state.json
     (per-campaign source of truth, robust to env var changes).
  3. ``find_existing_work_dir`` consults both candidate locations so
     resume / in-progress detection works across env-var toggles
     (closes the #184-class silent-mismatch trap re-introduced by
     a naive resolver-only approach).
  4. Worktrees are NOT affected — they continue to live at
     ``<target_repo>/.nous-experiments/<run>/<arm>/`` per #133.

Test contract: pure file/path assertions. No subprocess, no live LLM,
no network — per CLAUDE.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.iteration import setup_work_dir
from orchestrator.work_dir_resolver import (
    ENV_VAR,
    find_existing_work_dir,
    resolve_work_dir,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_state_schema() -> dict:
    return json.loads((SCHEMAS_DIR / "state.schema.json").read_text())


# ─── resolve_work_dir: pure path computation (no I/O) ────────────────────


class TestResolveWorkDirEnvVarUnset:
    """Backward-compat: unset env var produces the legacy
    ``<repo_path>/.nous/<run_id>/`` path."""

    def test_with_repo_path_uses_legacy_default(self, tmp_path: Path) -> None:
        repo = tmp_path / "target-repo"
        repo.mkdir()
        result = resolve_work_dir("my-run", repo)
        assert result == (repo / ".nous" / "my-run").resolve()

    def test_without_repo_path_uses_cwd_resolved(self) -> None:
        result = resolve_work_dir("my-run", repo_path=None)
        assert result == (Path.cwd() / "my-run").resolve()


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
        result = resolve_work_dir("my-run", repo)
        assert result == (parent / "my-run").resolve()
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
        monkeypatch.setenv(ENV_VAR, "~/nous-campaigns")
        result = resolve_work_dir("my-run", repo_path=None)
        assert "~" not in str(result)
        assert str(result).endswith("nous-campaigns/my-run")

    def test_env_var_with_trailing_slash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent) + "/")
        result = resolve_work_dir("my-run", repo_path=None)
        assert result == (parent / "my-run").resolve()


class TestResolveWorkDirEnvVarErrors:
    """Empty/whitespace env vars are common bash typos
    (``export NOUS_CAMPAIGN_PARENT=$UNSET``). Surfacing them loudly
    prevents silent fallback to the legacy default — the user
    explicitly tried to opt out."""

    def test_empty_env_var_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "")
        repo = tmp_path / "repo"
        repo.mkdir()
        with pytest.raises(ValueError, match="empty/whitespace"):
            resolve_work_dir("my-run", repo)

    def test_whitespace_env_var_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "   ")
        repo = tmp_path / "repo"
        repo.mkdir()
        with pytest.raises(ValueError, match="empty/whitespace"):
            resolve_work_dir("my-run", repo)

    def test_repo_path_does_not_exist_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="does not exist"):
            resolve_work_dir("my-run", "/nonexistent/path/to/repo")


# ─── setup_work_dir: integration (creates dir, writes state.json) ────────


class TestSetupWorkDirEnvVarUnset:
    """Backward-compat: setup_work_dir still creates work_dir under
    <repo>/.nous/<run_id>/ when env var is not set."""

    def test_creates_legacy_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = setup_work_dir("legacy-run", repo_path=str(repo))
        assert work_dir.exists()
        assert (work_dir / "state.json").exists()
        assert work_dir == (repo / ".nous" / "legacy-run").resolve()

    def test_state_json_records_work_dir_and_repo_path(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = setup_work_dir("legacy-run", repo_path=str(repo))
        state = json.loads((work_dir / "state.json").read_text())
        assert state["work_dir"] == str(work_dir.resolve())
        assert state["repo_path"] == str(repo.resolve())

    def test_state_json_validates_against_schema(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "target-repo"
        repo.mkdir()
        work_dir = setup_work_dir("legacy-run", repo_path=str(repo))
        state = json.loads((work_dir / "state.json").read_text())
        jsonschema.validate(state, _load_state_schema())


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

        assert work_dir == (parent / "ext-run").resolve()
        assert work_dir.exists()
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
        assert state["work_dir"] != str((repo / ".nous" / "ext-run").resolve())
        assert state["repo_path"] == str(repo.resolve())
        jsonschema.validate(state, _load_state_schema())

    def test_state_json_run_id_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        work_dir = setup_work_dir("my-run", repo_path=None)
        state = json.loads((work_dir / "state.json").read_text())
        assert state["run_id"] == "my-run"

    def test_idempotent_on_repeat_setup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        wd1 = setup_work_dir("my-run", repo_path=None)
        wd2 = setup_work_dir("my-run", repo_path=None)
        assert wd1 == wd2


class TestSetupWorkDirCollisionDetection:
    """Under NOUS_CAMPAIGN_PARENT, two campaigns with the same run_id
    targeting different repos would silently collide and corrupt each
    other. setup_work_dir detects this and refuses (#239 D1)."""

    def test_collision_with_different_repo_path_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()

        # First campaign targets repo-a.
        setup_work_dir("shared-run", repo_path=str(repo_a))

        # Second campaign with same run_id targets a different repo
        # (typical accident: forgot to rename run_id when copying yaml).
        with pytest.raises(ValueError, match="run_id collision"):
            setup_work_dir("shared-run", repo_path=str(repo_b))

    def test_resume_with_same_repo_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()

        wd1 = setup_work_dir("my-run", repo_path=str(repo))
        wd2 = setup_work_dir("my-run", repo_path=str(repo))
        assert wd1 == wd2


class TestSetupWorkDirEnvVarChangeRecord:
    """state.json's recorded ``work_dir`` is the per-campaign source of
    truth. Even if NOUS_CAMPAIGN_PARENT changes between runs, the
    record persists for the original location."""

    def test_recorded_work_dir_is_absolute_and_resolved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()

        work_dir = setup_work_dir("my-run", repo_path=str(repo))
        recorded = json.loads((work_dir / "state.json").read_text())["work_dir"]
        assert Path(recorded).is_absolute()
        assert Path(recorded) == work_dir

    def test_env_var_change_creates_separate_workdirs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pin current behavior: changing NOUS_CAMPAIGN_PARENT between
        setup_work_dir calls creates two campaign directories, each
        with its own state.json. A future PR that teaches setup_work_dir
        to consult state.json's recorded work_dir BEFORE creating a
        new directory will need to update or delete this test — that's
        the signal."""
        parent_a = tmp_path / "a"
        parent_a.mkdir()
        parent_b = tmp_path / "b"
        parent_b.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent_a))
        wd1 = setup_work_dir("my-run", repo_path=None)
        monkeypatch.setenv(ENV_VAR, str(parent_b))
        wd2 = setup_work_dir("my-run", repo_path=None)
        assert wd1 != wd2
        assert wd1.exists() and wd2.exists()
        assert json.loads((wd1 / "state.json").read_text())["work_dir"] == str(wd1)
        assert json.loads((wd2 / "state.json").read_text())["work_dir"] == str(wd2)


class TestSetupWorkDirErrorMessages:
    """Errors must surface env-var context so users with stale config
    aren't left guessing at PermissionError stack traces."""

    def test_unwritable_parent_raises_with_env_var_context(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir(mode=0o555)  # read-only
        monkeypatch.setenv(ENV_VAR, str(parent))

        try:
            with pytest.raises(OSError) as excinfo:
                setup_work_dir("my-run", repo_path=None)
            # Error must mention the env var so users know what config
            # drove the wrong path.
            assert ENV_VAR in str(excinfo.value) or "campaign work_dir" in str(excinfo.value)
        finally:
            parent.chmod(0o755)  # cleanup so tmp_path can be removed


# ─── find_existing_work_dir: discovery across all plausible locations ────


class TestFindExistingWorkDirNothingExists:
    def test_returns_none_when_no_candidate_has_state_json(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        assert find_existing_work_dir("my-run", repo) is None


class TestFindExistingWorkDirAtLegacy:
    """Pre-#239 campaigns live at <repo>/.nous/<run>/ even when the
    user later sets NOUS_CAMPAIGN_PARENT. find_existing_work_dir must
    still locate them."""

    def test_finds_legacy_when_env_var_unset(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        legacy = repo / ".nous" / "my-run"
        legacy.mkdir(parents=True)
        (legacy / "state.json").write_text('{"run_id": "my-run"}')

        result = find_existing_work_dir("my-run", repo)
        assert result == legacy.resolve()

    def test_finds_legacy_when_env_var_set_but_parent_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Critical: a user with pre-#239 campaigns who sets the env
        var must still be able to find their existing campaigns at the
        legacy path. This is the migration-grace behavior."""
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))

        repo = tmp_path / "repo"
        repo.mkdir()
        legacy = repo / ".nous" / "my-run"
        legacy.mkdir(parents=True)
        (legacy / "state.json").write_text('{"run_id": "my-run"}')

        result = find_existing_work_dir("my-run", repo)
        assert result == legacy.resolve()


class TestFindExistingWorkDirAtEnvVar:
    def test_finds_env_var_location(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))

        ext = parent / "my-run"
        ext.mkdir()
        (ext / "state.json").write_text('{"run_id": "my-run"}')

        result = find_existing_work_dir("my-run", repo_path=None)
        assert result == ext.resolve()


class TestFindExistingWorkDirPrefersRecordedPath:
    """When state.json's ``work_dir`` field points to a different
    existing directory (a moved campaign), prefer it over the
    candidate's own location."""

    def test_recorded_path_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))

        # Real campaign location (e.g., user `mv`d it here).
        real = tmp_path / "actually-here" / "my-run"
        real.mkdir(parents=True)
        (real / "state.json").write_text(
            json.dumps({"run_id": "my-run", "work_dir": str(real)})
        )

        # State.json at the env-var candidate path points to `real`.
        ext = parent / "my-run"
        ext.mkdir()
        (ext / "state.json").write_text(
            json.dumps({"run_id": "my-run", "work_dir": str(real)})
        )

        result = find_existing_work_dir("my-run", repo_path=None)
        assert result == real.resolve()

    def test_recorded_path_nonexistent_falls_back_to_candidate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))

        ext = parent / "my-run"
        ext.mkdir()
        (ext / "state.json").write_text(
            json.dumps({"run_id": "my-run", "work_dir": "/no/such/path"})
        )

        result = find_existing_work_dir("my-run", repo_path=None)
        assert result == ext.resolve()


class TestFindExistingWorkDirCorruptStateJson:
    """A corrupt state.json (truncated, invalid JSON, etc.) shouldn't
    crash discovery — fall back to using the candidate path."""

    def test_corrupt_state_json_falls_back_to_candidate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))

        ext = parent / "my-run"
        ext.mkdir()
        (ext / "state.json").write_text("{ this is not valid json")

        result = find_existing_work_dir("my-run", repo_path=None)
        assert result == ext.resolve()


# ─── CLI helpers honor env var consistently ──────────────────────────────


class TestCliResolveWorkDir:
    """cli.resolve_work_dir delegates to find_existing_work_dir, so
    yaml + bare-run-id inputs find campaigns at either legacy or
    env-var locations."""

    def test_yaml_with_env_var_finds_external_campaign(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from orchestrator.cli import resolve_work_dir as cli_resolve

        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()
        ext = parent / "my-run"
        ext.mkdir()
        (ext / "state.json").write_text('{"run_id": "my-run"}')

        yaml_path = tmp_path / "campaign.yaml"
        yaml_path.write_text(
            f'run_id: my-run\ntarget_system:\n  repo_path: "{repo}"\n'
        )

        result = cli_resolve(str(yaml_path))
        assert result == ext.resolve()

    def test_yaml_with_env_var_finds_legacy_campaign(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """User has pre-#239 campaign at legacy path AND has set env
        var. cli.resolve_work_dir should still find the legacy one
        (migration grace)."""
        from orchestrator.cli import resolve_work_dir as cli_resolve

        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()
        legacy = repo / ".nous" / "my-run"
        legacy.mkdir(parents=True)
        (legacy / "state.json").write_text('{"run_id": "my-run"}')

        yaml_path = tmp_path / "campaign.yaml"
        yaml_path.write_text(
            f'run_id: my-run\ntarget_system:\n  repo_path: "{repo}"\n'
        )

        result = cli_resolve(str(yaml_path))
        assert result == legacy.resolve()

    def test_bare_run_id_with_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from orchestrator.cli import resolve_work_dir as cli_resolve

        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        ext = parent / "my-run"
        ext.mkdir()
        (ext / "state.json").write_text('{"run_id": "my-run"}')

        result = cli_resolve("my-run")
        assert result == ext.resolve()

    def test_yaml_missing_campaign_exits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When neither the env-var nor legacy location has a
        state.json, cli.resolve_work_dir should sys.exit(1) with a
        helpful message."""
        from orchestrator.cli import resolve_work_dir as cli_resolve

        parent = tmp_path / "nous-campaigns"
        parent.mkdir()
        monkeypatch.setenv(ENV_VAR, str(parent))
        repo = tmp_path / "target-repo"
        repo.mkdir()

        yaml_path = tmp_path / "campaign.yaml"
        yaml_path.write_text(
            f'run_id: missing-run\ntarget_system:\n  repo_path: "{repo}"\n'
        )

        with pytest.raises(SystemExit):
            cli_resolve(str(yaml_path))
