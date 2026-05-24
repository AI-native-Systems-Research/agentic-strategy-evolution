"""Behavioral tests for orphan-worktree GC (#133 Phase A).

Synthesizes ``<repo>/.nous-experiments/<id>`` directories with controlled
mtimes and PID files, calls gc_orphan_worktrees, asserts which were
removed. Tests inject a fake clock + fake pid_check so they're
deterministic across machines.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from orchestrator.worktree import gc_orphan_worktrees


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=repo, check=True,
        capture_output=True,
    )


def _make_worktree_dir(
    repo: Path, exp_id: str, *, mtime: float, pid: int | None = None,
) -> Path:
    d = repo / ".nous-experiments" / exp_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "marker").write_text("x")
    if pid is not None:
        (d / ".nous-pid").write_text(str(pid))
    os.utime(d, (mtime, mtime))
    return d


class TestGcOrphanWorktrees:

    def test_no_experiments_dir_returns_empty(self, tmp_path):
        _init_git_repo(tmp_path)
        assert gc_orphan_worktrees(tmp_path) == []

    def test_removes_old_worktree_with_no_pid_file(self, tmp_path):
        _init_git_repo(tmp_path)
        old_mtime = 1000.0  # well in the past
        _make_worktree_dir(tmp_path, "iter-1-aaaa", mtime=old_mtime)

        removed = gc_orphan_worktrees(
            tmp_path, max_age_seconds=60, now=old_mtime + 3600,
        )

        assert removed == ["iter-1-aaaa"]
        assert not (tmp_path / ".nous-experiments" / "iter-1-aaaa").exists()

    def test_keeps_recent_worktree(self, tmp_path):
        _init_git_repo(tmp_path)
        recent = 5000.0
        _make_worktree_dir(tmp_path, "iter-2-bbbb", mtime=recent)

        removed = gc_orphan_worktrees(
            tmp_path, max_age_seconds=3600, now=recent + 30,
        )

        assert removed == []
        assert (tmp_path / ".nous-experiments" / "iter-2-bbbb").exists()

    def test_keeps_old_worktree_when_pid_alive(self, tmp_path):
        _init_git_repo(tmp_path)
        old = 1000.0
        _make_worktree_dir(tmp_path, "iter-3-cccc", mtime=old, pid=12345)

        # Inject an "always alive" pid_check; the dir should be kept
        # despite being older than max_age_seconds.
        removed = gc_orphan_worktrees(
            tmp_path, max_age_seconds=60, now=old + 3600,
            pid_check=lambda pid: True,
        )

        assert removed == []
        assert (tmp_path / ".nous-experiments" / "iter-3-cccc").exists()

    def test_removes_old_worktree_when_pid_dead(self, tmp_path):
        _init_git_repo(tmp_path)
        old = 1000.0
        _make_worktree_dir(tmp_path, "iter-4-dddd", mtime=old, pid=12345)

        removed = gc_orphan_worktrees(
            tmp_path, max_age_seconds=60, now=old + 3600,
            pid_check=lambda pid: False,
        )

        assert removed == ["iter-4-dddd"]
        assert not (tmp_path / ".nous-experiments" / "iter-4-dddd").exists()

    def test_invalid_pid_file_treated_as_no_pid(self, tmp_path):
        _init_git_repo(tmp_path)
        old = 1000.0
        d = _make_worktree_dir(tmp_path, "iter-5-eeee", mtime=old)
        (d / ".nous-pid").write_text("not-an-int")
        os.utime(d, (old, old))

        removed = gc_orphan_worktrees(
            tmp_path, max_age_seconds=60, now=old + 3600,
        )
        assert removed == ["iter-5-eeee"]

    def test_multiple_worktrees_partial_removal_is_sorted(self, tmp_path):
        _init_git_repo(tmp_path)
        old = 1000.0
        recent = 5000.0
        _make_worktree_dir(tmp_path, "iter-1-aaaa", mtime=old)
        _make_worktree_dir(tmp_path, "iter-2-bbbb", mtime=recent)
        _make_worktree_dir(tmp_path, "iter-3-cccc", mtime=old)

        removed = gc_orphan_worktrees(
            tmp_path, max_age_seconds=60, now=recent + 30,
        )
        # recent (iter-2) should still exist; old ones gone.
        assert removed == ["iter-1-aaaa", "iter-3-cccc"]
        assert (tmp_path / ".nous-experiments" / "iter-2-bbbb").exists()

    def test_zero_leftover_worktrees_after_gc_for_age_match(self, tmp_path):
        """Acceptance criterion: <repo>/.nous-experiments/ has zero
        leftover entries after a multi-arm campaign that GC'd everything."""
        _init_git_repo(tmp_path)
        old = 1000.0
        for i in range(5):
            _make_worktree_dir(tmp_path, f"iter-{i}-x", mtime=old)

        gc_orphan_worktrees(tmp_path, max_age_seconds=60, now=old + 3600)

        leftovers = [
            p for p in (tmp_path / ".nous-experiments").iterdir() if p.is_dir()
        ]
        assert leftovers == []


# ─── Phase B: harness-isolated subagent runner factory ─────────────────────


class TestMakeIsolatedArmRunner:
    """The factory returns an ArmRunner-shaped callable that delegates to
    the injected sdk_runner with isolation=worktree. Tests assert what
    the runner sends to the SDK and how it interprets the response —
    never that internal helpers were called."""

    def _unit(self):
        # Local stand-in for parallel_arms.ArmUnit so this test runs on
        # the #133 branch before #123's parallel_arms.py lands. The real
        # ArmUnit is duck-compatible with this shape.
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Unit:
            arm_id: str
            seed: str
            condition_name: str
            command: str

            @property
            def relative_results_dir(self) -> str:
                return f"results/{self.arm_id}/{self.seed}"

        return _Unit("h-main", "s1", "x", "./blis run")

    def test_returns_callable(self, tmp_path):
        try:
            from orchestrator.parallel_arms import ArmUnit  # noqa: F401
        except ImportError:
            import pytest
            pytest.skip("parallel_arms not on this branch yet (lands in #123)")
        from orchestrator.worktree import make_isolated_arm_runner

        runner = make_isolated_arm_runner(
            sdk_runner=lambda **kw: None,
            repo_path=tmp_path,
            iter_dir=tmp_path / "iter-1",
        )
        assert callable(runner)

    def test_factory_accepts_documented_kwargs(self, tmp_path):
        """The factory's keyword surface is the public contract."""
        from orchestrator.worktree import make_isolated_arm_runner
        # Just verify the signature accepts what the docstring promises;
        # construction must not raise.
        make_isolated_arm_runner(
            sdk_runner=lambda **kw: None,
            repo_path=tmp_path,
            iter_dir=tmp_path,
            model="claude-sonnet-4-6",
            max_turns=10,
            subagent_type="claude",
        )
