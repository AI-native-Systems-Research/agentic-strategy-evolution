"""Tests for git worktree experiment isolation."""
import subprocess
from pathlib import Path

import pytest

from orchestrator.worktree import create_experiment_worktree, remove_experiment_worktree


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
