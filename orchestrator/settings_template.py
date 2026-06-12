"""Per-campaign Claude Code permission policy generator (issue #135).

Replaces ``--dangerously-skip-permissions`` with a fine-grained
``.claude/settings.json`` written into the campaign work-dir at init.
The settings file declares:

  * ``allowOnly`` paths — typically the campaign work-dir and the target
    repo's worktree root. Anything else is denied.
  * an allowlist of binaries (Bash) drawn from the experiment plan
    when one is present at init, with conservative defaults otherwise.
  * best-effort egress-reduction deny rules for the common ``curl``/``wget``
    exfil one-liners (http and https). This is NOT a hard network sandbox:
    the allowlisted language runtimes (``python``/``node``/``npm``) can still
    reach the network, so campaigns needing true isolation must add an
    OS/container-level firewall. The deny list reduces accidental egress; it
    does not guarantee its absence.
  * (optional) a Stop hook pointing at ``bin/nous-execute-stop`` (#129).

The file's *contents* are the contract. The dispatcher passes
``--settings <path>`` and drops ``--dangerously-skip-permissions`` —
that's how the contents take effect.

This module is deliberately a pure renderer: ``render_campaign_settings``
takes inputs and returns a dict; ``write_campaign_settings`` writes it
to disk via :func:`atomic_write`. No side effects beyond the disk write.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.util import atomic_write


# Bash commands that are safe across virtually every Nous campaign.
# Campaign-specific binaries (./blis, simulators, custom tools) come from
# the experiment plan when present.
_DEFAULT_BIN_ALLOWLIST: tuple[str, ...] = (
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "rg",
    "git",
    "python",
    "python3",
    "pip",
    "pytest",
    "go",
    "cargo",
    "node",
    "npm",
    "make",
)


def _binaries_from_plan(plan: dict | None) -> list[str]:
    """Pull binaries out of an ``experiment_plan.yaml``-shaped dict.

    Returns a sorted list of unique binary basenames referenced in the
    plan's arms/conditions. Empty when the plan is None or shapeless.
    """
    if not isinstance(plan, dict):
        return []
    seen: set[str] = set()
    for arm in plan.get("arms", []) or []:
        for cond in arm.get("conditions", []) or []:
            cmd = cond.get("command") or cond.get("cmd")
            if not isinstance(cmd, str) or not cmd.strip():
                continue
            head = cmd.strip().split()[0]
            # Strip any "./" prefix and path separators to match against
            # the binary's basename in the allowlist.
            seen.add(head.split("/")[-1])
    return sorted(seen)


def render_campaign_settings(
    *,
    work_dir: Path,
    repo_path: Path | None = None,
    experiment_plan: dict | None = None,
    extra_bin_allowlist: list[str] | None = None,
    stop_hook_path: Path | None = None,
    pre_tool_use_hook_path: Path | None = None,
) -> dict[str, Any]:
    """Build the settings.json contents for one campaign.

    Args:
      work_dir: Campaign work-dir (e.g. ``<repo>/.nous/<run-id>``). Always allowed.
      repo_path: Target repo root, when set. Allowed read+write.
      experiment_plan: Parsed ``experiment_plan.yaml`` contents, if available
        at init. Binaries referenced in arm conditions extend the allowlist.
      extra_bin_allowlist: Caller-provided binaries to allow (e.g. simulator).
      stop_hook_path: Absolute path to the Stop hook (e.g. ``bin/nous-execute-stop``
        from #129). When set, registered under ``hooks.Stop``.
      pre_tool_use_hook_path: Absolute path to the PreToolUse hook (#128).
        When set, registered under ``hooks.PreToolUse``.

    Returns:
      A dict ready to be JSON-serialized as ``.claude/settings.json``.
    """
    allow_only = [str(Path(work_dir).resolve())]
    if repo_path is not None:
        allow_only.append(str(Path(repo_path).resolve()))

    bin_set: set[str] = set(_DEFAULT_BIN_ALLOWLIST)
    bin_set.update(_binaries_from_plan(experiment_plan))
    if extra_bin_allowlist:
        bin_set.update(extra_bin_allowlist)
    bin_allowlist = sorted(bin_set)

    settings: dict[str, Any] = {
        "permissions": {
            "allowOnly": allow_only,
            "allow": [f"Bash({b}:*)" for b in bin_allowlist],
            # Best-effort egress reduction — NOT a hard network sandbox.
            # These rules stop the obvious ``curl``/``wget`` exfil one-liners
            # (both https and plain http), but they cannot stop egress via
            # the language runtimes in the allowlist: ``python``/``python3``
            # (``urllib``/``requests``), ``node`` (``fetch``), or ``npm``
            # (registry fetches), nor DNS-based exfil via ``dig``/``nslookup``
            # if those binaries are allowed. Campaigns that require true
            # network isolation must run under an OS/container-level firewall
            # (e.g. network namespace, egress proxy). See module docstring.
            "deny": [
                "Bash(curl http://*)",
                "Bash(curl https://*)",
                "Bash(wget http://*)",
                "Bash(wget https://*)",
                "Bash(rm -rf /*)",
            ],
        },
    }

    hooks: dict[str, list[dict[str, Any]]] = {}
    if stop_hook_path is not None:
        hooks["Stop"] = [{
            "hooks": [{
                "type": "command",
                "command": str(Path(stop_hook_path).resolve()),
            }],
        }]
    if pre_tool_use_hook_path is not None:
        hooks["PreToolUse"] = [{
            "matcher": "Bash",
            "hooks": [{
                "type": "command",
                "command": str(Path(pre_tool_use_hook_path).resolve()),
            }],
        }]
    if hooks:
        settings["hooks"] = hooks

    return settings


def write_campaign_settings(
    settings_path: Path,
    contents: dict[str, Any],
) -> Path:
    """Atomically write the settings dict to ``settings_path``.

    Returns the absolute path to the written file.
    """
    settings_path = Path(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(settings_path, json.dumps(contents, indent=2) + "\n")
    return settings_path.resolve()


def settings_path_for(work_dir: Path) -> Path:
    """Return the canonical location of a campaign's settings file."""
    return Path(work_dir) / ".claude" / "settings.json"
