"""Resolve a campaign's work_dir from `repo_path` and `run_id`, honoring
the ``NOUS_CAMPAIGN_PARENT`` environment variable.

Closes #239: campaign artifacts polluted target repo's working tree
because every campaign defaulted to ``<target_repo>/.nous/<run_id>/``.

Resolution rules (in order):

1. If ``NOUS_CAMPAIGN_PARENT`` is set in the environment, return
   ``$NOUS_CAMPAIGN_PARENT/<run_id>/``. The target repo is invisible
   to the resolver in this branch — campaigns live wholly outside it.

2. Else, fall back to legacy: ``<repo_path>/.nous/<run_id>/``. This is
   exactly today's behavior and preserves full backward-compat for
   existing campaigns / unset-env-var users.

3. If ``repo_path`` is also ``None``, return ``Path(run_id)`` (relative
   to CWD), matching the existing fallback in ``setup_work_dir``.

The resolver is also the single source of truth for "where would this
run_id live, given today's environment?" — used by ``setup_work_dir``,
the CLI's resolve_work_dir, and the in-progress-detection state-path
lookup. Keeping all three in sync prevents the silent
"work_dir-mismatch" trap (#184).

Worktree creation is **NOT** affected by ``NOUS_CAMPAIGN_PARENT``.
Worktrees live at ``<repo_path>/.nous-experiments/<run_id>/<arm>/``
regardless — they are code FOR the target repo and must share its
git history. See ``orchestrator/worktree.py`` for that path.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Environment variable name. When set, campaign work_dirs land at
#: ``$NOUS_CAMPAIGN_PARENT/<run_id>/`` instead of the legacy
#: ``<repo_path>/.nous/<run_id>/``.
ENV_VAR = "NOUS_CAMPAIGN_PARENT"


def resolve_work_dir(run_id: str, repo_path: str | Path | None) -> Path:
    """Return the absolute work_dir Path for ``run_id``.

    See module docstring for the resolution rules.

    Args:
        run_id: Campaign run identifier (e.g. "ea-control-stack").
        repo_path: Target repo path (from campaign.yaml's
            ``target_system.repo_path``). May be ``None``.

    Returns:
        Absolute Path where the campaign's artifacts (state.json,
        ledger.json, principles.json, per-iter findings, JSON results)
        should live.

    Examples:
        >>> import os; os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        >>> resolve_work_dir("my-run", "/some/repo")
        PosixPath('/some/repo/.nous/my-run')

        >>> os.environ["NOUS_CAMPAIGN_PARENT"] = "/home/sri/nous-campaigns"
        >>> resolve_work_dir("my-run", "/some/repo")
        PosixPath('/home/sri/nous-campaigns/my-run')
        >>> del os.environ["NOUS_CAMPAIGN_PARENT"]
    """
    parent = os.environ.get(ENV_VAR)
    if parent:
        return Path(parent).expanduser().resolve() / run_id
    if repo_path is not None:
        return Path(repo_path).resolve() / ".nous" / run_id
    return Path(run_id)
