"""Channel notification for human gates (issue #130, Phase A).

Posts a markdown rendering of the gate summary to each configured channel
webhook so reviewers see the gate on Slack/Telegram/etc. without needing
to be at the terminal.

Phase A scope: outbound notification only — the campaign still blocks on
terminal input for the actual decision. Phase B (a follow-up) wires reply
parsing so an "approve" reply on Slack advances the campaign.

Configuration shape in campaign.yaml::

    channels:
      - kind: slack
        webhook_url: https://hooks.slack.com/services/...
      - kind: webhook
        url: https://example.com/nous/gate
        headers:
          Authorization: Bearer ...

Failures are best-effort: a webhook timeout or 5xx logs at warning and
does NOT break the gate. The campaign keeps running.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SECONDS = 10


def _summary_to_markdown(summary: dict, *, gate_type: str, iter_dir: Path) -> str:
    """Render a gate_summary dict as a compact markdown card."""
    lines = [
        f"### Nous gate: **{gate_type}**",
        "",
        summary.get("summary", "(no summary)"),
        "",
    ]
    points = summary.get("key_points") or []
    if points:
        lines.append("**Key points**")
        for p in points:
            lines.append(f"- {p}")
        lines.append("")
    lines.append(f"_iter dir: `{iter_dir}`_")
    lines.append("")
    lines.append("Reply with `approve`, `reject`, or `abort`.")
    return "\n".join(lines)


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
    """Single HTTP POST. Returns status code; raises on transport error."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def _post_slack(channel: dict, markdown: str, timeout: float) -> int:
    url = channel.get("webhook_url")
    if not url:
        raise ValueError("slack channel missing webhook_url")
    body = json.dumps({"text": markdown}).encode("utf-8")
    return _post(url, body, {"Content-Type": "application/json"}, timeout)


def _post_generic(channel: dict, markdown: str, timeout: float) -> int:
    url = channel.get("url")
    if not url:
        raise ValueError("webhook channel missing url")
    headers = {"Content-Type": "application/json"}
    headers.update(channel.get("headers") or {})
    body = json.dumps({"markdown": markdown}).encode("utf-8")
    return _post(url, body, headers, timeout)


_DISPATCHERS: dict[str, Callable[[dict, str, float], int]] = {
    "slack": _post_slack,
    "webhook": _post_generic,
}


def notify_gate(
    channels: Iterable[dict] | None,
    *,
    summary: dict,
    gate_type: str,
    iter_dir: Path,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    poster: Callable[[str, bytes, dict[str, str], float], int] | None = None,
) -> list[dict[str, Any]]:
    """POST a gate summary to every configured channel.

    Args:
      channels: list of channel configs from campaign.yaml. ``None`` or an
        empty list is a no-op.
      summary: parsed gate_summary_<phase>.json contents.
      gate_type: ``design`` | ``findings`` | ``continue`` etc.
      iter_dir: iteration directory (shown in the markdown card).
      timeout: per-request timeout in seconds.
      poster: dependency-injection seam for tests. When set, used instead
        of the real urllib.request.urlopen path. Signature matches ``_post``.

    Returns:
      A list of result dicts — one per channel — with keys
      ``kind``, ``ok``, ``status_code`` (or ``error``). The campaign uses
      this to decide what to log, but never raises on individual failures.
    """
    if not channels:
        return []

    markdown = _summary_to_markdown(summary, gate_type=gate_type, iter_dir=iter_dir)

    results: list[dict[str, Any]] = []
    for channel in channels:
        kind = channel.get("kind", "webhook")
        result: dict[str, Any] = {"kind": kind, "ok": False}
        try:
            if poster is not None:
                # Test path: bypass dispatcher, post directly.
                if kind == "slack":
                    body = json.dumps({"text": markdown}).encode("utf-8")
                    url = channel.get("webhook_url", "")
                    headers = {"Content-Type": "application/json"}
                else:
                    body = json.dumps({"markdown": markdown}).encode("utf-8")
                    url = channel.get("url", "")
                    headers = {"Content-Type": "application/json"}
                    headers.update(channel.get("headers") or {})
                status = poster(url, body, headers, timeout)
            else:
                dispatcher = _DISPATCHERS.get(kind)
                if dispatcher is None:
                    raise ValueError(f"unknown channel kind: {kind!r}")
                status = dispatcher(channel, markdown, timeout)
            result["status_code"] = status
            result["ok"] = 200 <= status < 300
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            logger.warning(
                "channel %r notify failed: %s", kind, exc,
            )
            result["error"] = str(exc)
        results.append(result)
    return results
