"""Git worktree management for experiment isolation."""
import logging
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def create_experiment_worktree(repo_path: Path, iteration: int) -> tuple[Path, str]:
    """Create a git worktree for running an experiment in isolation.

    Returns:
        Tuple of (worktree_path, experiment_id).
    """
    repo_path = Path(repo_path)
    if not repo_path.exists():
        raise FileNotFoundError(f"Target repo not found: {repo_path}")
    if not (repo_path / ".git").exists():
        raise FileNotFoundError(f"Not a git repository: {repo_path}")

    experiment_id = f"iter-{iteration}-{uuid.uuid4().hex[:8]}"
    worktree_dir = repo_path / ".nous-experiments" / experiment_id
    branch_name = f"nous-exp-{experiment_id}"

    subprocess.run(
        ["git", "worktree", "add", str(worktree_dir), "-b", branch_name],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    logger.info("Created experiment worktree: %s (branch: %s)", worktree_dir, branch_name)
    return worktree_dir, experiment_id


def remove_experiment_worktree(repo_path: Path, experiment_id: str) -> None:
    """Remove a previously created experiment worktree and its branch.

    Safe to call even if the worktree was already removed.
    """
    repo_path = Path(repo_path)
    worktree_dir = repo_path / ".nous-experiments" / experiment_id
    branch_name = f"nous-exp-{experiment_id}"

    if worktree_dir.exists():
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_dir), "--force"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Removed experiment worktree: %s", worktree_dir)

    # Clean up the branch (ignore errors if already gone)
    result = subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.debug("Branch cleanup for %s: %s", branch_name, result.stderr.strip())
