"""Warm-start campaigns from a prior campaign's knowledge (issue #83).

Each campaign on the same target repo today starts from scratch —
re-exploring, re-deriving principles a prior campaign already
established. Warm-start copies ``principles.json`` and ``handoff.md``
from a completed prior campaign, with drift detection that marks
inherited principles TENTATIVE when the target repo has changed.

Pairs with the repo cache (#156, merged via #161): repo_cache
persists *target-system facts* (knobs/metrics/build) across campaigns;
this module persists *learned knowledge* (principles + exploration
context). Together they let the next campaign focus on δ-learning.

Injection seam:
  ``warm_start_from_prior(..., drift_check_fn=...)`` lets tests
  substitute a deterministic stub. The default check returns
  "no drift detected" when no ``repo_path`` is supplied (test-safe);
  with a repo_path, a future implementation can shell out to git
  rev-parse + git diff. This module ships with the *no-repo*
  branch live and the *with-repo* branch as the seam.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DriftReport:
    """Outcome of comparing the target repo to its state at prior-campaign-start."""
    detected: bool
    summary: str | None


@dataclass(frozen=True)
class WarmStartResult:
    """Summary of what was copied from the prior campaign."""
    principles_copied: int
    handoff_copied: bool
    drift: DriftReport


DriftCheckFn = Callable[[Path, str | None], DriftReport]
"""Drift-check protocol: takes (prior_dir, repo_path) and returns DriftReport."""


def _default_drift_check(prior_dir: Path, repo_path: str | None) -> DriftReport:
    """Default drift check.

    With no ``repo_path``, returns "no drift detected" — there's no
    repo to compare against, so we can't detect drift. Tests reach
    this branch.

    With a ``repo_path``, this would shell out to ``git rev-parse``
    + ``git diff`` to compare the prior campaign's recorded HEAD SHA
    against the repo's current HEAD. That branch is left for a future
    Phase B follow-up — the seam (this function's signature) is the
    contract; tests inject deterministic stubs and don't depend on
    the production implementation.
    """
    if not repo_path:
        return DriftReport(detected=False, summary=None)
    # Phase B will implement git-based detection here. Until then,
    # be conservative: assume drift so users explicitly opt out.
    return DriftReport(
        detected=True,
        summary=(
            "Default drift check is not yet implemented for repo-based "
            "comparison; treating inherited knowledge as tentative. "
            "Inject drift_check_fn= to override."
        ),
    )


def _find_prior_dir(prior_run_id: str, search_paths: Iterable[Path]) -> Path:
    """Locate the prior campaign directory across candidate parents."""
    for parent in search_paths:
        candidate = Path(parent) / prior_run_id
        if candidate.is_dir():
            return candidate
    searched = ", ".join(str(p) for p in search_paths)
    raise FileNotFoundError(
        f"prior campaign directory {prior_run_id!r} not found "
        f"(searched: {searched})",
    )


def _load_state(prior_dir: Path) -> dict:
    state_path = prior_dir / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"prior state.json not found at {state_path}")
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"corrupt state.json at {state_path}: {exc}",
        ) from exc
    if not isinstance(state, dict):
        raise ValueError(f"state.json at {state_path} is not a JSON object")
    return state


def warm_start_from_prior(
    work_dir: Path,
    *,
    prior_run_id: str,
    prior_search_paths: Iterable[Path] | None = None,
    repo_path: str | None = None,
    drift_check_fn: DriftCheckFn | None = None,
) -> WarmStartResult:
    """Seed a new campaign with knowledge from a completed prior campaign.

    Args:
        work_dir: New campaign's working directory.
        prior_run_id: Run id of the prior campaign to inherit from.
        prior_search_paths: Where to look for the prior dir. Defaults to
            ``[Path('.nous'), Path.cwd()]`` — both common locations.
        repo_path: Optional path to the target system git repo. Used by
            the default drift check; tests may pass None and inject a
            drift_check_fn.
        drift_check_fn: Optional injected drift detector. When None,
            the module-level default is used.

    Returns:
        WarmStartResult summarizing what was copied.

    Raises:
        FileNotFoundError: prior dir missing.
        RuntimeError: prior campaign isn't in DONE state.
        ValueError: corrupt prior artifacts.
    """
    work_dir = Path(work_dir)
    if prior_search_paths is None:
        prior_search_paths = [Path(".nous"), Path.cwd()]

    prior_dir = _find_prior_dir(prior_run_id, prior_search_paths)
    state = _load_state(prior_dir)

    if state.get("phase") != "DONE":
        raise RuntimeError(
            f"prior campaign {prior_run_id!r} is not complete "
            f"(phase={state.get('phase')!r}); only DONE campaigns can "
            f"be warm-started from",
        )

    drift = (drift_check_fn or _default_drift_check)(prior_dir, repo_path)

    # Copy + tag principles.json
    principles_copied = 0
    prior_principles = prior_dir / "principles.json"
    if prior_principles.exists():
        try:
            store = json.loads(prior_principles.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"corrupt principles.json at {prior_principles}: {exc}",
            ) from exc
        principles_list = store.get("principles", []) if isinstance(store, dict) else []
        if not isinstance(principles_list, list):
            principles_list = []
        tagged = []
        for p in principles_list:
            if not isinstance(p, dict):
                continue
            tagged_p = dict(p)
            tagged_p["inherited_from"] = prior_run_id
            tagged_p["confidence"] = (
                "tentative" if drift.detected else "inherited"
            )
            tagged.append(tagged_p)
        atomic_write(
            work_dir / "principles.json",
            json.dumps({"principles": tagged}, indent=2) + "\n",
        )
        principles_copied = len(tagged)

    # Copy + (maybe) prepend warning to handoff.md
    handoff_copied = False
    prior_handoff = prior_dir / "handoff.md"
    if prior_handoff.exists():
        content = prior_handoff.read_text()
        if drift.detected:
            content = (
                "⚠️ INHERITED HANDOFF (drift detected)\n"
                "The target repo has changed since this handoff was written.\n"
                f"Drift summary: {drift.summary or '(no detail)'}\n"
                "Verify all claims below before relying on them.\n\n"
                "---\n\n"
            ) + content
        atomic_write(work_dir / "handoff.md", content)
        handoff_copied = True

    return WarmStartResult(
        principles_copied=principles_copied,
        handoff_copied=handoff_copied,
        drift=drift,
    )
