"""Nous's own directories inside a target repo never show up in its git status.

Without NOUS_CAMPAIGN_PARENT a campaign's work_dir is ``<target>/.nous/<run_id>/``;
every campaign writes ``<target>/.nous/repo/`` at its end; experiment worktrees
live in ``<target>/.nous-experiments/``. None of these was ignored, so the
target's ``git status`` filled with Nous output -- which ``git add .`` stages
and ``git stash -u`` sweeps up -- and the build oracle hashed it as "mechanism".
Each directory now carries a self-ignoring ``.gitignore`` (``*``), the same
convention ``.pytest_cache`` uses. Asserted through real git.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "target"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "app.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-qm", "init")
    return r


def test_a_legacy_work_dir_leaves_the_target_status_clean(repo, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    monkeypatch.delenv("NOUS_CAMPAIGN_PARENT", raising=False)
    wd = setup_work_dir("run-a", repo_path=str(repo))
    (Path(wd) / "runs.jsonl").write_text("{}\n")
    assert Path(wd).is_relative_to(repo)
    assert _git(repo, "status", "--porcelain") == ""


def test_the_repo_cache_leaves_the_target_status_clean(repo):
    from orchestrator.repo_cache import write_repo_cache
    write_repo_cache(repo, exploration="notes", knobs=None, metrics=None, build=None)
    assert _git(repo, "status", "--porcelain") == ""


def test_an_experiment_worktree_leaves_the_target_status_clean_and_works(repo):
    from orchestrator.worktree import create_experiment_worktree
    wt, _branch = create_experiment_worktree(repo, iteration=1)
    assert _git(repo, "status", "--porcelain") == ""
    # The ignore file must not hide the worktree's own edits from ITSELF.
    (wt / "app.py").write_text("x = 2\n")
    assert "app.py" in _git(wt, "status", "--porcelain")


def test_an_author_edit_beside_nous_output_is_still_visible(repo, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    monkeypatch.delenv("NOUS_CAMPAIGN_PARENT", raising=False)
    setup_work_dir("run-b", repo_path=str(repo))
    (repo / "app.py").write_text("x = 3\n")
    assert _git(repo, "status", "--porcelain").strip() == "M app.py"
