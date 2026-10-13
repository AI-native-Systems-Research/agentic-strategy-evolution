"""Carry the best measured arm forward into the target repo (``design_profile: v5``).

Each iteration's experiment worktree branches from the target repo HEAD. Without this, every iteration
starts from the original code and spends turns rebuilding the previous best from its patch. Before the
next EXECUTE, the patch of the best arm so far (``best_found.json``) is committed to the target, so the new
worktree starts from it. Patches are relative to the HEAD their iteration ran on, which is always the last
carried-forward commit, so they apply cleanly in order.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)
STATE_FILE = "carry_forward.json"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _patch_for(work_dir: Path, candidate_id: str) -> Path | None:
    parts = candidate_id.split("/")
    if len(parts) < 2:
        return None
    patches = work_dir / "runs" / parts[0] / "patches"
    exact = patches / f"{parts[1]}.patch"
    return exact if exact.is_file() and exact.stat().st_size > 0 else None


def carry_forward_best(work_dir: Path, repo_path: Path) -> str | None:
    """Commit the best arm's patch to ``repo_path`` if it is new. Returns a status message, or None."""
    work_dir, repo_path = Path(work_dir), Path(repo_path)
    try:
        top = (json.loads((work_dir / "best_found.json").read_text()).get("top_k") or [])[0]
    except (OSError, ValueError, IndexError, AttributeError):
        return None
    cid = str(top.get("candidate_id") or "")
    state_path = work_dir / STATE_FILE
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {"applied": [], "failed": []}
    if not cid or cid in state["applied"] or cid in state["failed"]:
        return None
    if _git(repo_path, "diff", "--cached", "--quiet").returncode != 0:
        logger.warning("carry-forward skipped: the target repo has staged changes")
        return None
    patch = _patch_for(work_dir, cid)
    ok = patch is not None and _git(repo_path, "apply", "--check", str(patch)).returncode == 0
    if ok:
        ok = _git(repo_path, "apply", "--index", str(patch)).returncode == 0
    if ok:
        res = _git(repo_path, "-c", "user.email=nous@local", "-c", "user.name=nous",
                   "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify",
                   "-m", f"nous: carry forward {cid} (score {top.get('score')})")
        ok = res.returncode == 0
        if not ok:  # leave the repo as it was so later patches still apply
            _git(repo_path, "apply", "-R", "--index", str(patch))
    state["applied" if ok else "failed"].append(cid)
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    msg = (f"carried forward best {cid} (score {top.get('score')}) from {patch}" if ok
           else f"could not carry forward {cid} (patch {patch}); next iteration starts from the previous base")
    (logger.info if ok else logger.warning)(msg)
    return msg
