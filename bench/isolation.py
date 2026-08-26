"""Per-variant workspace setup. See plan §6 cross-cutting details."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def clone_target_repo(target_repo: str, target_ref: str, dest: Path) -> None:
    """Clone target_repo into dest and checkout target_ref.

    target_repo accepts a git URL or an absolute local path. Local paths
    are cloned via `git clone <abs_path>` (git uses hard links when possible,
    so this is fast and disk-cheap).
    """
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    source = target_repo
    local = Path(target_repo)
    if local.exists():
        source = str(local.resolve())

    subprocess.run(
        ["git", "clone", source, str(dest)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", target_ref],
        check=True,
        capture_output=True,
    )
