"""Tests for git worktree experiment isolation."""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from orchestrator.iteration import (
    _declared_code_change_paths,
    _record_undeclared_writes_in_findings,
)
from orchestrator.worktree import (
    create_experiment_worktree,
    detect_undeclared_writes,
    remove_experiment_worktree,
)


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repo with one commit."""
    repo = tmp_path / "target-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


class TestCreateExperimentWorktree:
    def test_creates_worktree(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        assert worktree_dir.exists()
        assert worktree_dir.is_dir()
        assert "iter-1-" in experiment_id
        # Verify it's a valid git worktree
        result = subprocess.run(
            ["git", "worktree", "list"],
            cwd=temp_git_repo, capture_output=True, text=True,
        )
        assert str(worktree_dir) in result.stdout
        # Clean up
        remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_worktree_on_new_branch(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=worktree_dir, capture_output=True, text=True,
        )
        assert result.stdout.strip().startswith("nous-exp-iter-1-")
        remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_repo_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Target repo not found"):
            create_experiment_worktree(tmp_path / "nonexistent", 1)

    def test_not_a_git_repo(self, tmp_path):
        not_git = tmp_path / "not-git"
        not_git.mkdir()
        with pytest.raises(FileNotFoundError, match="Not a git repository"):
            create_experiment_worktree(not_git, 1)


class TestRemoveExperimentWorktree:
    def test_removes_worktree_and_branch(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        assert worktree_dir.exists()
        remove_experiment_worktree(temp_git_repo, experiment_id)
        assert not worktree_dir.exists()
        # Branch should be gone
        result = subprocess.run(
            ["git", "branch"],
            cwd=temp_git_repo, capture_output=True, text=True,
        )
        assert f"nous-exp-{experiment_id}" not in result.stdout

    def test_idempotent_remove(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        remove_experiment_worktree(temp_git_repo, experiment_id)
        # Second call should not raise
        remove_experiment_worktree(temp_git_repo, experiment_id)


class TestWorktreeExtras:
    """#229 — `target_system.worktree_extras` symlinks gitignored deps
    from main into each experiment worktree, so the executor doesn't
    have to ``cd`` to the parent repo. Behavioral tests use a real
    on-disk git repo in tmp_path."""

    def _add_gitignored_dep(self, repo: Path, rel: str, content: str = "x") -> Path:
        """Create a gitignored file/dir at ``rel`` under ``repo``."""
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        gi = repo / ".gitignore"
        existing = gi.read_text() if gi.exists() else ""
        gi.write_text(existing + rel.split("/")[0] + "\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"ignore {rel.split('/')[0]}"],
            cwd=repo, check=True, capture_output=True,
        )
        return target

    def test_extras_creates_symlinks_into_worktree(self, temp_git_repo):
        # Two gitignored deps: a file and a directory.
        venv = temp_git_repo / "py" / ".venv"
        venv.mkdir(parents=True)
        (venv / "marker").write_text("VENV_OK")
        data_file = temp_git_repo / "data.bin"
        data_file.write_text("DATA_OK")
        # gitignore both
        (temp_git_repo / ".gitignore").write_text("py/.venv/\ndata.bin\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ignore"],
            cwd=temp_git_repo, check=True, capture_output=True,
        )

        worktree_dir, experiment_id = create_experiment_worktree(
            temp_git_repo, 1, extras=["py/.venv", "data.bin"],
        )
        try:
            link_venv = worktree_dir / "py" / ".venv"
            link_data = worktree_dir / "data.bin"
            assert link_venv.is_symlink(), "py/.venv should be a symlink in the worktree"
            assert link_data.is_symlink(), "data.bin should be a symlink in the worktree"
            # Resolves to the main repo's path → marker is readable through the link.
            assert (link_venv / "marker").read_text() == "VENV_OK"
            assert link_data.read_text() == "DATA_OK"
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_extras_creates_intermediate_parent_dirs(self, temp_git_repo):
        # Source at nested path; parent dir does NOT exist in worktree yet.
        nested = temp_git_repo / "deep" / "nested" / "asset.txt"
        nested.parent.mkdir(parents=True)
        nested.write_text("OK")
        (temp_git_repo / ".gitignore").write_text("deep/\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ignore deep"],
            cwd=temp_git_repo, check=True, capture_output=True,
        )

        worktree_dir, experiment_id = create_experiment_worktree(
            temp_git_repo, 1, extras=["deep/nested/asset.txt"],
        )
        try:
            link = worktree_dir / "deep" / "nested" / "asset.txt"
            assert link.is_symlink()
            assert link.read_text() == "OK"
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_extras_source_must_exist(self, temp_git_repo):
        with pytest.raises(FileNotFoundError, match="worktree_extras source not found"):
            create_experiment_worktree(temp_git_repo, 1, extras=["does/not/exist"])

    def test_extras_rejects_absolute_path(self, temp_git_repo):
        with pytest.raises(ValueError, match="non-empty relative paths"):
            create_experiment_worktree(temp_git_repo, 1, extras=["/etc/passwd"])

    def test_extras_rejects_path_escaping_repo(self, temp_git_repo, tmp_path):
        # Create a file outside the repo, then point a relative ``..``
        # extra at it — the resolver must reject it.
        outside = tmp_path / "outside.txt"
        outside.write_text("OUTSIDE")
        with pytest.raises(ValueError, match="resolves outside repo_path"):
            create_experiment_worktree(temp_git_repo, 1, extras=["../outside.txt"])

    def test_extras_failure_cleans_up_partial_worktree(self, temp_git_repo):
        # When an extras entry fails validation, the half-built worktree
        # must not leak — neither the directory nor the branch.
        with pytest.raises(FileNotFoundError):
            create_experiment_worktree(temp_git_repo, 1, extras=["does/not/exist"])
        # No experiment dirs left behind.
        experiments = temp_git_repo / ".nous-experiments"
        if experiments.exists():
            assert list(experiments.iterdir()) == [], (
                "create_experiment_worktree leaked a worktree on extras failure"
            )
        # No nous-exp-* branches left behind.
        result = subprocess.run(
            ["git", "branch"],
            cwd=temp_git_repo, capture_output=True, text=True,
        )
        assert "nous-exp-" not in result.stdout

    def test_extras_leaves_existing_path_untouched(self, temp_git_repo):
        # README.md is tracked in main → it exists in the worktree checkout.
        # Declaring it as an extra should warn (not overwrite).
        worktree_dir, experiment_id = create_experiment_worktree(
            temp_git_repo, 1, extras=["README.md"],
        )
        try:
            link = worktree_dir / "README.md"
            assert not link.is_symlink(), "tracked path must not be replaced by a symlink"
            assert link.read_text() == "# Test repo\n"
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_extras_skipped_by_undeclared_write_detection(self, temp_git_repo):
        # Symlinks created by extras must not be flagged as undeclared
        # writes — they're orchestrator-managed inputs (#230 cross-#229).
        venv = temp_git_repo / ".venv"
        venv.mkdir()
        (venv / "bin").mkdir()
        (temp_git_repo / ".gitignore").write_text(".venv/\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ignore venv"],
            cwd=temp_git_repo, check=True, capture_output=True,
        )

        worktree_dir, experiment_id = create_experiment_worktree(
            temp_git_repo, 1, extras=[".venv"],
        )
        try:
            assert detect_undeclared_writes(worktree_dir) == []
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_extras_none_or_empty_is_noop(self, temp_git_repo):
        # Backward-compat: omitting extras (or passing empty list) yields the
        # current behavior — fresh worktree, no symlinks.
        worktree_dir, experiment_id = create_experiment_worktree(
            temp_git_repo, 1, extras=None,
        )
        try:
            entries = sorted(p.name for p in worktree_dir.iterdir() if not p.name.startswith("."))
            assert entries == ["README.md"]
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

        worktree_dir, experiment_id = create_experiment_worktree(
            temp_git_repo, 1, extras=[],
        )
        try:
            entries = sorted(p.name for p in worktree_dir.iterdir() if not p.name.startswith("."))
            assert entries == ["README.md"]
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)


class TestDetectUndeclaredWrites:
    """#230 — pre-cleanup tripwire that surfaces executor writes the
    bundle never declared as ``code_changes``."""

    def test_untracked_file_flagged(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            (worktree_dir / "executor_added.py").write_text("# new code\n")
            assert detect_undeclared_writes(worktree_dir) == ["executor_added.py"]
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_modified_tracked_file_flagged(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            (worktree_dir / "README.md").write_text("# Modified\n")
            assert "README.md" in detect_undeclared_writes(worktree_dir)
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_declared_path_filtered_out(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            (worktree_dir / "executor_added.py").write_text("# declared\n")
            (worktree_dir / "executor_other.py").write_text("# undeclared\n")
            undeclared = detect_undeclared_writes(
                worktree_dir, declared_paths={"executor_added.py"},
            )
            assert undeclared == ["executor_other.py"]
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_clean_worktree_returns_empty(self, temp_git_repo):
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            assert detect_undeclared_writes(worktree_dir) == []
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_missing_worktree_returns_empty(self, tmp_path):
        # Detection runs in cleanup paths that may also fire after
        # remove_experiment_worktree — must not raise.
        assert detect_undeclared_writes(tmp_path / "does-not-exist") == []

    def test_symlinks_excluded(self, temp_git_repo, tmp_path):
        # Symlinks (typically from `worktree_extras`) are not undeclared writes.
        external = tmp_path / "external_dep"
        external.mkdir()
        (external / "marker").write_text("x")
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            os.symlink(external, worktree_dir / "external_dep")
            # The symlink shows up in `git status --porcelain` but
            # detect_undeclared_writes filters it.
            assert detect_undeclared_writes(worktree_dir) == []
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_modify_then_stage_flagged(self, temp_git_repo):
        # Porcelain code "MM": modified-staged-AND-modified-unstaged.
        # The earlier substring filter (`"M" in status`) caught this by
        # accident; the new explicit-status filter must continue to.
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            (worktree_dir / "README.md").write_text("# Once\n")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=worktree_dir, check=True, capture_output=True,
            )
            (worktree_dir / "README.md").write_text("# Twice\n")
            assert "README.md" in detect_undeclared_writes(worktree_dir)
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_added_staged_file_flagged(self, temp_git_repo):
        # Porcelain code "A ": added (staged), no working-tree diff. The
        # branch-and-its-staged-content gets destroyed on cleanup just
        # like an untracked file, so this must surface.
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            (worktree_dir / "executor_added.py").write_text("# new\n")
            subprocess.run(
                ["git", "add", "executor_added.py"],
                cwd=worktree_dir, check=True, capture_output=True,
            )
            assert "executor_added.py" in detect_undeclared_writes(worktree_dir)
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_renamed_file_reports_destination(self, temp_git_repo):
        # Porcelain v1 renames: "R  orig -> new". The destination path
        # is what matters; the parser must extract it (not record
        # "orig -> new" as one path).
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            subprocess.run(
                ["git", "mv", "README.md", "RENAMED.md"],
                cwd=worktree_dir, check=True, capture_output=True,
            )
            undeclared = detect_undeclared_writes(worktree_dir)
            # Destination present, not the "orig -> new" composite.
            assert "RENAMED.md" in undeclared
            assert not any(" -> " in p for p in undeclared)
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_deleted_file_not_flagged(self, temp_git_repo):
        # Deletions aren't "writes" — surfacing them would turn `git rm`
        # between conditions into noise. Documented in the helper.
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            (worktree_dir / "README.md").unlink()
            assert detect_undeclared_writes(worktree_dir) == []
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_renamed_destination_can_be_declared(self, temp_git_repo):
        # The destination of a rename must round-trip through the
        # declared_paths filter — i.e. declaring "RENAMED.md" suppresses it.
        worktree_dir, experiment_id = create_experiment_worktree(temp_git_repo, 1)
        try:
            subprocess.run(
                ["git", "mv", "README.md", "RENAMED.md"],
                cwd=worktree_dir, check=True, capture_output=True,
            )
            assert detect_undeclared_writes(
                worktree_dir, declared_paths={"RENAMED.md"},
            ) == []
        finally:
            remove_experiment_worktree(temp_git_repo, experiment_id)

    def test_git_failure_logs_warning(self, tmp_path, caplog):
        # When `git status --porcelain` exits non-zero, the function
        # returns [] but logs at WARNING — silent loss is exactly what
        # the helper exists to prevent, so a diagnostic-failure must
        # not be quiet.
        import logging
        # tmp_path exists but isn't a git repo → git status will exit non-zero.
        (tmp_path / "marker").write_text("x")
        with caplog.at_level(logging.WARNING, logger="orchestrator.worktree"):
            result = detect_undeclared_writes(tmp_path)
        assert result == []
        assert any(
            "git status failed" in r.getMessage() and r.levelname == "WARNING"
            for r in caplog.records
        )


class TestDeclaredCodeChangePaths:
    """#230 — read declared paths from bundle.arms[].code_changes[].file."""

    def test_extracts_file_paths_from_arms(self, tmp_path):
        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump({
            "arms": [
                {"type": "h-main", "code_changes": [
                    {"file": "src/foo.py", "intent": "x", "rationale": "y"},
                    {"file": "src/bar.py", "intent": "x", "rationale": "y"},
                ]},
                {"type": "h-ablation", "code_changes": [
                    {"file": "src/baz.py", "intent": "x", "rationale": "y"},
                ]},
            ],
        }))
        assert _declared_code_change_paths(bundle_path) == {
            "src/foo.py", "src/bar.py", "src/baz.py",
        }

    def test_no_arms_returns_empty(self, tmp_path):
        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump({"metadata": {}}))
        assert _declared_code_change_paths(bundle_path) == set()

    def test_arm_without_code_changes_skipped(self, tmp_path):
        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text(yaml.safe_dump({
            "arms": [{"type": "h-main", "prediction": "..."}],
        }))
        assert _declared_code_change_paths(bundle_path) == set()

    def test_missing_file_returns_empty(self, tmp_path):
        # Bundle missing → empty set, never raises (#230 must not block cleanup).
        assert _declared_code_change_paths(tmp_path / "missing.yaml") == set()

    def test_malformed_yaml_returns_empty(self, tmp_path):
        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text("not: valid: yaml: [")
        assert _declared_code_change_paths(bundle_path) == set()


class TestRecordUndeclaredWritesInFindings:
    """#230 — merge worktree_uncommitted_writes into findings.json without
    breaking schema or losing existing keys."""

    def _make_findings(self, tmp_path: Path) -> Path:
        findings_path = tmp_path / "findings.json"
        findings_path.write_text(json.dumps({
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [{
                "arm_type": "h-main", "predicted": "...", "observed": "...",
                "status": "CONFIRMED", "error_type": None,
                "diagnostic_note": None,
            }],
            "experiment_valid": True,
            "discrepancy_analysis": "...",
        }))
        return findings_path

    def test_writes_sorted_unique_paths(self, tmp_path):
        findings_path = self._make_findings(tmp_path)
        _record_undeclared_writes_in_findings(
            findings_path,
            ["b.py", "a.py", "b.py", "c.py"],
        )
        loaded = json.loads(findings_path.read_text())
        assert loaded["worktree_uncommitted_writes"] == ["a.py", "b.py", "c.py"]
        # Other keys preserved.
        assert loaded["experiment_valid"] is True
        assert loaded["arms"][0]["arm_type"] == "h-main"

    def test_findings_remains_schema_valid(self, tmp_path):
        import jsonschema
        findings_path = self._make_findings(tmp_path)
        _record_undeclared_writes_in_findings(findings_path, ["a.py"])
        loaded = json.loads(findings_path.read_text())
        schema_path = (
            Path(__file__).resolve().parent.parent
            / "orchestrator" / "schemas" / "findings.schema.json"
        )
        schema = json.loads(schema_path.read_text())
        jsonschema.validate(loaded, schema)  # raises on failure

    def test_empty_undeclared_is_noop(self, tmp_path):
        findings_path = self._make_findings(tmp_path)
        original = findings_path.read_text()
        _record_undeclared_writes_in_findings(findings_path, [])
        assert findings_path.read_text() == original

    def test_missing_findings_no_raise(self, tmp_path):
        # If findings.json wasn't produced (bad iteration), don't blow up.
        _record_undeclared_writes_in_findings(
            tmp_path / "missing.json", ["a.py"],
        )

    def test_malformed_findings_no_raise(self, tmp_path):
        findings_path = tmp_path / "findings.json"
        findings_path.write_text("{not valid json")
        _record_undeclared_writes_in_findings(findings_path, ["a.py"])
        # Original unchanged.
        assert findings_path.read_text() == "{not valid json"

    def test_malformed_findings_logs_error_with_paths(self, tmp_path, caplog):
        # Refused-to-write must be loud, not silent — the undeclared
        # paths still need to appear somewhere the operator can recover.
        import logging
        findings_path = tmp_path / "findings.json"
        findings_path.write_text("{not valid json")
        with caplog.at_level(logging.ERROR, logger="orchestrator.iteration"):
            _record_undeclared_writes_in_findings(
                findings_path, ["lost1.py", "lost2.py"],
            )
        msg = " ".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")
        assert "lost1.py" in msg
        assert "lost2.py" in msg
        assert "not valid JSON" in msg

    def test_corrupted_bundle_logs_error(self, tmp_path, caplog):
        # YAML parse failure surfaces — bundle.yaml is a system boundary.
        import logging
        bundle_path = tmp_path / "bundle.yaml"
        bundle_path.write_text("not: valid: yaml: [")
        with caplog.at_level(logging.ERROR, logger="orchestrator.iteration"):
            assert _declared_code_change_paths(bundle_path) == set()
        msg = " ".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")
        assert "bundle.yaml parse failed" in msg
        assert str(bundle_path) in msg
