"""Tests for bench/isolation.py — clone_target_repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bench.isolation import clone_target_repo


def _make_local_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(
        [
            "git", "-c", "user.email=a@b", "-c", "user.name=a",
            "add", "README.md",
        ],
        cwd=path, check=True,
    )
    subprocess.run(
        [
            "git", "-c", "user.email=a@b", "-c", "user.name=a",
            "commit", "-m", "init", "-q",
        ],
        cwd=path, check=True,
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True)
    return path


def test_clone_local_path_creates_workspace(tmp_path):
    src = _make_local_repo(tmp_path / "src")
    dest = tmp_path / "dest"
    clone_target_repo(str(src), "main", dest)

    assert (dest / ".git").is_dir()
    assert (dest / "README.md").read_text() == "hello\n"


def test_clone_overwrites_existing_dest(tmp_path):
    src = _make_local_repo(tmp_path / "src")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "stale.txt").write_text("stale")

    clone_target_repo(str(src), "main", dest)

    assert not (dest / "stale.txt").exists()
    assert (dest / "README.md").read_text() == "hello\n"


def test_clone_invalid_source_raises(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        clone_target_repo("/nonexistent/path/to/repo", "main", tmp_path / "dest")
