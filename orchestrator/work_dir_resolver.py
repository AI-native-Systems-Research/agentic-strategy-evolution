"""Resolve a campaign's work_dir from `repo_path` and `run_id`, honoring
the ``NOUS_CAMPAIGN_PARENT`` environment variable.

Closes #239: campaign artifacts polluted target repo's working tree
because every campaign defaulted to ``<target_repo>/.nous/<run_id>/``.

This module is the **single source of truth** for campaign-location
resolution. Three call sites (``setup_work_dir``,
``cli.resolve_work_dir``, ``cli._cmd_run``) all delegate here. If
you add a fourth resolution rule, update the docstrings of those
three call sites + ``create_campaign.py:_TEMPLATE`` + ``README.md``
to match. Search for the marker comment ``# RESOLUTION RULES``.

API
---

* ``resolve_work_dir(run_id, repo_path) -> Path`` — the canonical
  location for a NEW campaign with the current environment. Raises
  ``ValueError`` if ``NOUS_CAMPAIGN_PARENT`` is set to empty/whitespace
  (a common bash typo: ``export NOUS_CAMPAIGN_PARENT=$UNSET``).
  Raises ``FileNotFoundError`` if ``repo_path`` is given but doesn't
  exist.

* ``find_existing_work_dir(run_id, repo_path) -> Path | None`` —
  best-effort lookup of an EXISTING campaign that may have been
  created under a different environment. Checks both the env-var
  location and the legacy ``<repo>/.nous/<run>`` location, then
  consults state.json's recorded ``work_dir`` field to handle
  campaigns that have been moved post-creation. Returns the campaign
  directory if found, else ``None``.

Worktree creation is **NOT** affected by ``NOUS_CAMPAIGN_PARENT``.
Worktrees live at ``<repo_path>/.nous-experiments/<run_id>/<arm>/``
regardless — they are code FOR the target repo and must share its
git history. See ``orchestrator/worktree.py`` for that path.
"""

# RESOLUTION RULES (canonical):
#   1. If NOUS_CAMPAIGN_PARENT is set (non-empty/non-whitespace), the
#      work_dir is $NOUS_CAMPAIGN_PARENT/<run_id>/. Empty values raise
#      ValueError instead of silently falling through.
#   2. Else if repo_path is provided, work_dir is
#      <repo_path>/.nous/<run_id>/. (Legacy default.)
#   3. Else, work_dir is <CWD>/<run_id>/.

from __future__ import annotations

import json
import os
from pathlib import Path

#: Environment variable name. When set (non-empty), campaign work_dirs
#: land at ``$NOUS_CAMPAIGN_PARENT/<run_id>/`` instead of the legacy
#: ``<repo_path>/.nous/<run_id>/``.
ENV_VAR = "NOUS_CAMPAIGN_PARENT"


def _read_env_var() -> str | None:
    """Read NOUS_CAMPAIGN_PARENT, treating empty/whitespace as a hard error.

    Empty values are commonly produced by bash interpolation of unset
    vars (``export NOUS_CAMPAIGN_PARENT=$SOMETHING_UNSET``) or by direnv
    when expansion fails. Silently treating them as "env var unset"
    would defeat the user's intent — they explicitly wanted to opt out
    of the legacy ``<repo>/.nous/`` default. We surface the error
    loudly instead.

    Returns:
        The env var value (stripped) if set and non-empty; ``None`` if
        the var is not in the environment.

    Raises:
        ValueError: env var is set but empty or whitespace-only.
    """
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        raise ValueError(
            f"{ENV_VAR} is set but empty/whitespace ({raw!r}). "
            f"Either unset it to use the legacy <repo>/.nous/<run_id>/ "
            f"default, or set it to an absolute directory path."
        )
    return stripped


def _resolve_repo_path(repo_path: str | Path) -> Path:
    """Validate and resolve a target repo path.

    Raises FileNotFoundError if the path doesn't exist, since a campaign
    derived from a typo'd repo_path silently creates state at a wrong
    location and then fails confusingly during worktree creation. Better
    to fail at resolution time with a clear message.
    """
    rp = Path(repo_path).expanduser()
    if not rp.exists():
        raise FileNotFoundError(
            f"target_system.repo_path does not exist: {repo_path!r}. "
            f"Fix campaign.yaml, or set NOUS_CAMPAIGN_PARENT to use a "
            f"location independent of repo_path."
        )
    return rp.resolve()


def resolve_work_dir(run_id: str, repo_path: str | Path | None) -> Path:
    """Return the canonical absolute work_dir Path for ``run_id``.

    See module docstring for the resolution rules.

    This returns the location where a NEW campaign would be created
    given the current environment. To find an EXISTING campaign that
    may live at a different location (e.g., predates the env var),
    use :func:`find_existing_work_dir` instead.

    Args:
        run_id: Campaign run identifier (e.g. "ea-control-stack").
        repo_path: Target repo path. May be ``None``.

    Returns:
        Absolute Path where the campaign's artifacts should live.

    Raises:
        ValueError: ``NOUS_CAMPAIGN_PARENT`` is set but empty/whitespace.
        FileNotFoundError: ``repo_path`` is provided but doesn't exist.
    """
    env_parent = _read_env_var()
    if env_parent is not None:
        return Path(env_parent).expanduser().resolve() / run_id
    if repo_path is not None:
        return _resolve_repo_path(repo_path) / ".nous" / run_id
    return Path(run_id).resolve()


def find_existing_work_dir(
    run_id: str, repo_path: str | Path | None
) -> Path | None:
    """Best-effort lookup of an existing campaign's work_dir.

    Checks all plausible locations:

      1. The env-var-resolved location (if ``NOUS_CAMPAIGN_PARENT`` set).
      2. The legacy ``<repo_path>/.nous/<run_id>/`` location (if
         ``repo_path`` provided).

    For each candidate that contains a state.json, prefer the absolute
    path recorded in state.json's ``work_dir`` field if it points to an
    existing directory with state.json — this lets a campaign that's
    been moved post-creation still be found. Falls back to the
    candidate path itself for legacy / pre-#239 campaigns where state
    .json predates the field.

    Used by ``cli._cmd_run`` for in-progress detection (must check
    both legacy and env-var paths to avoid silently allowing a parallel
    run when env var is toggled between invocations) and by
    ``cli.resolve_work_dir`` for resume/status lookup.

    Args:
        run_id: Campaign run identifier.
        repo_path: Target repo path. May be ``None``.

    Returns:
        The found campaign directory (absolute Path), or ``None`` if no
        state.json is found at any candidate. Bad env-var values surface
        the same ``ValueError`` as :func:`resolve_work_dir`.
    """
    candidates: list[Path] = []

    env_parent = _read_env_var()
    if env_parent is not None:
        candidates.append(Path(env_parent).expanduser().resolve() / run_id)

    if repo_path is not None:
        rp = Path(repo_path).expanduser()
        if rp.exists():
            candidates.append(rp.resolve() / ".nous" / run_id)

    for candidate in candidates:
        state_path = candidate / "state.json"
        if not state_path.exists():
            continue
        # Prefer state.json's recorded path if it points to a real
        # campaign elsewhere (handles a post-creation `mv`).
        try:
            recorded = json.loads(state_path.read_text()).get("work_dir")
        except (json.JSONDecodeError, OSError):
            return candidate
        if recorded:
            recorded_path = Path(recorded)
            if (recorded_path / "state.json").exists():
                return recorded_path.resolve()
        return candidate
    return None
