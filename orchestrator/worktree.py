"""Git worktree management for experiment isolation.

Phase A of #133: ship orphan-worktree garbage collection alongside the
existing per-iteration lifecycle. The harness-managed
``Agent(isolation="worktree")`` switch (Phase B) lands with the
parallel-arm subagents in #123 — at that point most of this file goes
away. Until then, GC at run start cleans up the ghost-worktree pattern
observed on 5/18 where ``--max-cli-retries 10`` spawned a second worktree
while the first was still alive.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


_EXPERIMENTS_DIRNAME = ".nous-experiments"
_DEFAULT_ORPHAN_AGE_SECONDS = 60 * 60  # 1 hour


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
    worktree_dir = repo_path / _EXPERIMENTS_DIRNAME / experiment_id
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
    worktree_dir = repo_path / _EXPERIMENTS_DIRNAME / experiment_id
    branch_name = f"nous-exp-{experiment_id}"

    if worktree_dir.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_dir), "--force"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Removed experiment worktree: %s", worktree_dir)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Failed to remove experiment worktree %s: %s",
                worktree_dir,
                exc.stderr.strip() if exc.stderr else str(exc),
            )

    # Clean up the branch (ignore errors if already gone)
    result = subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.debug("Branch cleanup for %s: %s", branch_name, result.stderr.strip())


def gc_orphan_worktrees(
    repo_path: Path,
    *,
    max_age_seconds: float = _DEFAULT_ORPHAN_AGE_SECONDS,
    pid_check: Callable[[int], bool] | None = None,
    now: float | None = None,
) -> list[str]:
    """Remove stale experiment worktrees with no live owning process.

    Run at ``nous run`` startup. Walks ``<repo>/.nous-experiments/`` and
    deletes any worktree directory that is older than ``max_age_seconds``
    and whose owning PID (if recorded under ``.nous-pid``) is no longer
    alive. The 1-hour default matches the issue's GC threshold; the
    rationale is that any legitimate iteration completes within an hour
    of its last write, so anything older with no live process is genuinely
    orphaned.

    Args:
      repo_path: target repo root.
      max_age_seconds: only consider worktrees older than this.
      pid_check: callable ``(pid: int) -> bool`` returning True when the
        process is still alive. Defaults to ``os.kill(pid, 0)``-style
        check. Tests inject a deterministic fake.
      now: override of ``time.time()`` for deterministic tests.

    Returns:
      List of experiment_ids removed (sorted by directory name).
    """
    repo_path = Path(repo_path)
    experiments_dir = repo_path / _EXPERIMENTS_DIRNAME
    if not experiments_dir.is_dir():
        return []

    pid_alive = pid_check or _pid_alive_default
    current_time = now if now is not None else time.time()

    removed: list[str] = []
    for entry in sorted(experiments_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        age = current_time - mtime
        if age < max_age_seconds:
            continue

        # If a PID is recorded under .nous-pid, skip when alive.
        pid_file = entry / ".nous-pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                if pid_alive(pid):
                    continue
            except (ValueError, OSError):
                pass

        # Untrack the worktree from git (best-effort), then rm -rf the dir.
        subprocess.run(
            ["git", "worktree", "remove", str(entry), "--force"],
            cwd=repo_path, capture_output=True, text=True, check=False,
        )
        if entry.exists():
            shutil.rmtree(entry, ignore_errors=True)

        # Best-effort branch cleanup.
        branch = f"nous-exp-{entry.name}"
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=repo_path, capture_output=True, text=True, check=False,
        )

        logger.info("GC'd orphan worktree: %s", entry)
        removed.append(entry.name)
    return removed


def _pid_alive_default(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — still alive.
        return True
    except OSError:
        return False


# ─── Phase B: harness-isolated subagent runner (#133 + #123 bridge) ────────


def make_isolated_arm_runner(
    *,
    sdk_runner: Callable,
    repo_path: Path,
    iter_dir: Path,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 25,
    subagent_type: str = "claude",
) -> Callable:
    """Build an ArmRunner backed by a worktree-isolated SDK subagent.

    The returned callable matches the ``ArmRunner`` Protocol from
    :mod:`orchestrator.parallel_arms` — takes one ``ArmUnit`` and returns
    one ``ArmUnitResult``. Per the no-live-LLM policy, this function does
    not call the SDK directly: it uses the injected ``sdk_runner`` from
    :mod:`orchestrator.sdk_dispatch`, so tests pass a recording fake.

    Each subagent is dispatched with ``isolation="worktree"`` and
    ``subagent_type`` set so the harness creates a fresh worktree,
    runs the unit's planned command inside it, and tears the worktree
    down on exit. The post-run patch (``git diff`` inside the worktree)
    is captured by the subagent and written to
    ``iter_dir/patches/<arm>.patch`` — matching the existing convention.

    This is the harness-managed replacement for the manual lifecycle
    in ``create_experiment_worktree`` / ``remove_experiment_worktree``;
    once #123 wires this runner into the parallel-arm path, the manual
    code becomes vestigial.
    """
    repo_path = Path(repo_path)
    iter_dir = Path(iter_dir)

    def _run(unit):
        # Imported lazily so the factory itself works on branches where
        # parallel_arms hasn't landed yet (it stacks on this PR).
        from orchestrator.parallel_arms import ArmUnitResult
        results_dir = iter_dir / unit.relative_results_dir
        results_dir.mkdir(parents=True, exist_ok=True)
        patches_dir = iter_dir / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patches_dir / f"{unit.arm_id}.patch"

        prompt = (
            f"# Arm: {unit.arm_id} (seed {unit.seed})\n\n"
            f"You are a subagent running one experiment unit in an isolated\n"
            f"git worktree. **Do not modify files outside this worktree.**\n\n"
            f"## Command\n```\n{unit.command}\n```\n\n"
            f"## Results destination\n"
            f"Write all output files to: `{results_dir}`\n\n"
            f"## Patch capture\n"
            f"Before exiting, run `git diff` in this worktree and write the\n"
            f"output to `{patch_path}`. If there are no changes, create an\n"
            f"empty file at that path.\n"
        )

        try:
            result = sdk_runner(
                prompt=prompt,
                model=model,
                cwd=repo_path,
                max_turns=max_turns,
                system_prompt=None,
                settings_path=None,
                event_log_path=None,
                isolation="worktree",
                subagent_type=subagent_type,
            )
        except TypeError:
            # Older runners don't accept isolation/subagent_type kwargs;
            # fall back to the basic call signature.
            result = sdk_runner(
                prompt=prompt, model=model, cwd=repo_path, max_turns=max_turns,
            )

        if getattr(result, "is_error", False):
            return ArmUnitResult(
                unit=unit, status="failed",
                duration_ms=int(getattr(result, "duration_ms", 0) or 0),
                error=str(getattr(result, "error_message", "") or "sdk reported error"),
            )

        output_files = sorted(
            str(p.relative_to(iter_dir))
            for p in results_dir.rglob("*") if p.is_file()
        )
        return ArmUnitResult(
            unit=unit,
            status="complete",
            duration_ms=int(getattr(result, "duration_ms", 0) or 0),
            output_files=output_files,
        )

    return _run
