"""Cross-campaign code reuse: cumulative patches + derived_from (#266 / F21).

Operationalizes the friction surfaced in paper-memorytime-realistic-K
follow-up: each new campaign on the same target repo previously had to
manually identify which iteration's patch was "the substantial one,"
verify it applies to current main, bake it into ``preflight_commands``,
and re-add any incremental fixes from later iterations. This module
makes that automatic.

Three primitives:

1. ``emit_cumulative_patch(repo_path, branch, iter_dir)`` — at iteration
   completion, capture ``git diff <main>..<branch>`` alongside the
   existing per-arm patches. The cumulative form applies to a fresh
   main checkout; the per-arm incremental patches do not (they're a
   delta from the prior iteration's branch state).

2. ``resolve_derived_from(campaign)`` — read ``campaign.derived_from``,
   locate the prior campaign's ``cumulative.patch``, return the path.

3. ``apply_derived_from_patch(repo_path, patch_path)`` — apply at
   experiment-worktree creation time as a preflight, before the agent
   runs. Best-effort with a clear error message when the patch fails
   to apply (target repo has moved past the patch's base).

Plus ``summarize_lineage(work_dir)`` for the ``nous lineage`` CLI.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


def _git_main_ref(repo_path: Path) -> str:
    """Best guess at the target's mainline ref. Order: origin/main →
    origin/master → main → master → HEAD. The first that resolves wins.
    """
    candidates = ("origin/main", "origin/master", "main", "master", "HEAD")
    for ref in candidates:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", ref],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if result.returncode == 0:
            return ref
    return "HEAD"


def emit_cumulative_patch(
    repo_path: Path, branch_name: str, iter_dir: Path,
) -> Path | None:
    """#266 (F21): write ``iter_dir/patches/cumulative.patch`` containing
    ``git diff <main>..<branch>``. Returns the path on success, None if
    the diff couldn't be captured (branch missing, git error, etc.).

    The cumulative form is what future campaigns reuse via
    ``derived_from``. The existing per-arm ``<arm>.patch`` files
    (incremental, branch-state-dependent) remain unchanged.
    """
    repo_path = Path(repo_path)
    iter_dir = Path(iter_dir)
    patches_dir = iter_dir / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    cumulative_path = patches_dir / "cumulative.patch"

    main_ref = _git_main_ref(repo_path)
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "diff", f"{main_ref}..{branch_name}"],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("emit_cumulative_patch: git diff failed (%s)", exc)
        return None
    if result.returncode != 0:
        logger.warning(
            "emit_cumulative_patch: git diff %s..%s failed: %s",
            main_ref, branch_name, result.stderr.strip(),
        )
        return None
    # Atomic write (PR #279 review): a truncated cumulative.patch would
    # still pass resolve_derived_from's "exists + non-empty" check and
    # `git apply --check` for complete hunks, then apply a partial patch —
    # running a derived campaign on the wrong code state silently. Atomic
    # write means the file is either complete or absent.
    atomic_write(cumulative_path, result.stdout)
    return cumulative_path


def _campaign_parent_dir() -> Path | None:
    """Return ``$NOUS_CAMPAIGN_PARENT`` resolved to a Path, or None."""
    raw = os.environ.get("NOUS_CAMPAIGN_PARENT")
    if not raw or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def _find_campaign_work_dir(
    campaign_id: str, repo_path: Path | None,
) -> Path | None:
    """Locate a prior campaign's work_dir. Mirrors the resolution rules
    from ``orchestrator.work_dir_resolver`` but without the strict
    creation/collision logic — read-only.
    """
    parent = _campaign_parent_dir()
    if parent and (parent / campaign_id).is_dir():
        return parent / campaign_id
    if repo_path:
        legacy = Path(repo_path) / ".nous" / campaign_id
        if legacy.is_dir():
            return legacy
    return None


def resolve_derived_from(
    campaign: dict, *, repo_path: Path | None = None,
) -> Path | None:
    """#266 (F21): translate ``campaign.derived_from`` into a path to
    the prior campaign's ``cumulative.patch``. Returns None when the
    campaign doesn't declare ``derived_from``, when the prior campaign
    isn't findable, or when the cumulative patch is missing.
    """
    derived = campaign.get("derived_from")
    if not isinstance(derived, dict):
        return None
    prior_campaign = derived.get("campaign")
    if not isinstance(prior_campaign, str) or not prior_campaign:
        return None
    iteration = derived.get("iteration", "final")

    work_dir = _find_campaign_work_dir(prior_campaign, repo_path)
    if work_dir is None:
        logger.warning(
            "derived_from: cannot locate prior campaign %s "
            "(NOUS_CAMPAIGN_PARENT=%s, repo_path=%s)",
            prior_campaign, _campaign_parent_dir(), repo_path,
        )
        return None

    runs_dir = work_dir / "runs"
    if not runs_dir.is_dir():
        return None

    if iteration == "final":
        candidates = sorted(
            (p for p in runs_dir.iterdir() if p.is_dir() and p.name.startswith("iter-")),
            key=lambda p: int(p.name.split("-", 1)[1]) if p.name.split("-", 1)[1].isdigit() else 0,
        )
        for iter_dir in reversed(candidates):
            patch = iter_dir / "patches" / "cumulative.patch"
            if patch.is_file() and patch.stat().st_size > 0:
                return patch
        return None

    iter_dir = runs_dir / f"iter-{iteration}"
    patch = iter_dir / "patches" / "cumulative.patch"
    if patch.is_file() and patch.stat().st_size > 0:
        return patch
    return None


def apply_derived_from_patch(
    repo_path: Path, patch_path: Path,
) -> tuple[bool, str]:
    """Apply ``patch_path`` to ``repo_path`` (or experiment worktree).

    Returns ``(ok, message)``. On failure, ``message`` includes the git
    stderr — typically a "patch does not apply" diagnostic the user can
    act on (the target has moved past the patch's base; rebase the
    prior campaign's branch or update ``derived_from.iteration``).
    """
    result = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--check", str(patch_path)],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode != 0:
        return False, (
            f"derived_from patch does not apply cleanly to {repo_path}:\n"
            f"{result.stderr.strip()}"
        )
    result = subprocess.run(
        ["git", "-C", str(repo_path), "apply", str(patch_path)],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode != 0:
        return False, (
            f"derived_from patch failed at apply time (check passed): "
            f"{result.stderr.strip()}"
        )
    return True, f"applied {patch_path}"


def summarize_lineage(work_dir: Path) -> dict:
    """``nous lineage <campaign>`` payload. Reads state.json + campaign.yaml
    + each iter's patches/cumulative.patch existence, returns a
    structured map suitable for human or JSON consumption.
    """
    work_dir = Path(work_dir)
    summary: dict = {
        "work_dir": str(work_dir),
        "derived_from": None,
        "iterations": [],
    }

    state_path = work_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            summary["run_id"] = state.get("run_id")
            summary["repo_path"] = state.get("repo_path")
            repro = state.get("reproducibility_metadata") or {}
            if isinstance(repro, dict):
                summary["repo_commit"] = repro.get("repo_commit")
        except (OSError, json.JSONDecodeError):
            pass

    # Look for campaign.yaml.copy or sibling campaign yaml for derived_from.
    for candidate in (work_dir / "campaign.yaml.copy", work_dir / "campaign.yaml"):
        if candidate.exists():
            try:
                import yaml as _yaml
                campaign = _yaml.safe_load(candidate.read_text()) or {}
                if isinstance(campaign.get("derived_from"), dict):
                    summary["derived_from"] = campaign["derived_from"]
                break
            except (OSError, Exception):  # noqa: BLE001 — best-effort
                pass

    runs_dir = work_dir / "runs"
    if runs_dir.is_dir():
        for entry in sorted(runs_dir.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("iter-"):
                continue
            iter_info: dict = {
                "iter_dir": str(entry),
                "iteration": entry.name,
            }
            cumulative = entry / "patches" / "cumulative.patch"
            iter_info["cumulative_patch"] = (
                str(cumulative) if cumulative.is_file() and cumulative.stat().st_size > 0
                else None
            )
            summary["iterations"].append(iter_info)
    return summary
