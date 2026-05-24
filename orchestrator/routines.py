"""Claude Code Routines integration for Nous (issue #134, Phase A).

Builds a JSON-serializable payload describing a Routine for a Nous
campaign — the bundle of (campaign config, schedule, MCP refs,
credentials placeholder) that gets posted to the Routines API to
register a recurring run.

Phase A ships the **payload builder + dry-run CLI** so users see exactly
what would be registered without needing the Routines API to be live.
Phase B (when the Routines API stabilizes) wires the actual POST to
that API and a return of the Routine ID.

Cron schedule: standard 5-field cron in UTC. The user's local timezone
is up to the Routines runtime; the orchestrator passes the string as-is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_routine_payload(
    campaign: dict,
    *,
    campaign_path: Path | None = None,
    schedule: str | None = None,
    pr_label: str | None = None,
    mcp_refs: list[str] | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Construct the Routines registration payload for a Nous campaign.

    Exactly one of ``schedule`` or ``pr_label`` should be set (Routines
    fire on either a cron string or a GitHub-event label).

    Args:
      campaign: parsed ``campaign.yaml`` dict.
      campaign_path: filesystem path to the YAML file (so the Routine can
        re-read it on each fire). Optional; when omitted, the payload
        embeds the campaign config inline.
      schedule: cron string (UTC). E.g. ``"0 2 * * *"`` for nightly at 2am.
      pr_label: GitHub PR label that triggers this Routine. E.g.
        ``"nous-experiment"``.
      mcp_refs: MCP resource URIs the Routine should subscribe to (e.g.
        ``["nous://campaigns"]``). The Routine writes findings via these
        references after each run.
      extra: caller-provided extra keys merged into the top level.
    """
    if not schedule and not pr_label:
        raise ValueError("schedule or pr_label is required")
    if schedule and pr_label:
        raise ValueError("specify schedule OR pr_label, not both")

    target = campaign.get("target_system", {})
    name = (
        campaign.get("run_id")
        or campaign.get("name")
        or target.get("name", "nous-routine")
    )

    payload: dict[str, Any] = {
        "name": name,
        "description": (
            campaign.get("research_question")
            or "Nous campaign — auto-registered Routine."
        ),
        "trigger": (
            {"type": "cron", "expression": schedule}
            if schedule
            else {"type": "pr_label", "label": pr_label}
        ),
        "command": _routine_command(campaign_path),
        "credentials": {
            "ANTHROPIC_API_KEY": "${secret:anthropic_api_key}",
        },
        "mcp": {
            "resources": list(mcp_refs or []),
        },
    }
    if campaign_path is not None:
        payload["campaign_path"] = str(Path(campaign_path).resolve())
    else:
        payload["campaign_inline"] = campaign

    if extra:
        for k, v in extra.items():
            payload[k] = v

    return payload


def _routine_command(campaign_path: Path | None) -> list[str]:
    """The shell command the Routine fires on each trigger."""
    if campaign_path is not None:
        return [
            "nous", "run",
            str(Path(campaign_path).resolve()),
            "--auto-approve",
            "--agent", "sdk",
        ]
    return [
        "nous", "run", "<inlined-campaign.yaml>",
        "--auto-approve",
        "--agent", "sdk",
    ]


# ─── Phase B: actual API submission ────────────────────────────────────────


import json as _json
import os as _os
import urllib.request as _urlreq
from typing import Callable as _Callable


_DEFAULT_ROUTINES_API_BASE = "https://api.anthropic.com/v1/routines"


def submit_routine(
    payload: dict,
    *,
    api_base: str | None = None,
    api_key: str | None = None,
    poster: _Callable[[str, bytes, dict, float], dict] | None = None,
    timeout: float = 30.0,
) -> dict:
    """Register the payload with the Routines API and return the response.

    Args:
      payload: result of build_routine_payload.
      api_base: override the default Routines API endpoint.
      api_key: override ANTHROPIC_API_KEY env var. Required for real calls.
      poster: dependency-injection seam for tests. Signature:
        ``(url, body_bytes, headers, timeout) -> response_dict``. When set,
        used instead of urllib.request.urlopen so tests don't touch the
        network. See tests/CLAUDE.md.
      timeout: per-request timeout in seconds.

    Returns:
      Response dict — typically contains a ``routine_id`` field that
      callers store for later management.
    """
    url = api_base or _os.environ.get("ROUTINES_API_BASE", _DEFAULT_ROUTINES_API_BASE)
    key = api_key or _os.environ.get("ANTHROPIC_API_KEY")
    if poster is None and not key:
        raise RuntimeError(
            "submit_routine requires ANTHROPIC_API_KEY (or pass api_key=). "
            "Tests must inject a poster — see tests/CLAUDE.md."
        )
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Nous-Source": "orchestrator.routines",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = _json.dumps(payload).encode("utf-8")

    if poster is not None:
        return poster(url, body, headers, timeout)

    req = _urlreq.Request(url, data=body, headers=headers, method="POST")
    with _urlreq.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        return {"raw_response": text, "status": resp.status}
