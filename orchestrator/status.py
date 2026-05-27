"""Live status surface for Nous campaigns (issue #127).

Phase A: a deterministic, no-LLM snapshot reader that the CLI uses for
``nous status`` (one-shot), ``nous status --line`` (single-line for shell
prompts), and ``nous status --watch`` (loop + redraw).

The snapshot reads three files:
  * ``state.json``        — current phase + iteration
  * ``ledger.json``       — completed iterations count
  * ``runs/iter-N/executor_log.jsonl`` — most recent SDK tool-call event
    (when present; empty before #127's SDK-tee path is wired)

Stuck detection: heartbeat absence > 5 minutes since the last logged
tool-call event surfaces a ``stuck`` flag that the watch panel renders
prominently.

Phase B (deferred): SDK event tee — sdk_dispatch.py teeing each
``--output-format stream-json`` row to ``executor_log.jsonl`` as the
session runs. Once that lands, ``nous status --watch`` lights up
without code changes here.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_STUCK_THRESHOLD_SECONDS = 5 * 60


@dataclass
class StatusSnapshot:
    run_id: str = "?"
    phase: str = "?"
    iteration: int = 0
    completed_iterations: int = 0
    # #217: separate counter for iterations that ran but ended in
    # failure (ledger row with ``status: "FAILED"``). Treating these as
    # "Completed" makes a botched run look identical to a clean refute.
    failed_iterations: int = 0
    active_principles: int = 0
    last_event: dict[str, Any] | None = None
    elapsed_since_last_event: float | None = None  # seconds; None if no event
    # #207: most recent event in the log that has a `tool_name`. Distinct
    # from `last_event` because the very last logged event is often a
    # SystemMessage / TaskNotificationMessage / pure ThinkingBlock that
    # carries no `tool_name`, even though a Bash/Read happened seconds
    # earlier. The reader walks backward to find the nearest tool-bearing
    # event so the operator sees a useful tool name in `nous status`.
    last_tool_name: str | None = None
    stuck: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "iteration": self.iteration,
            "completed_iterations": self.completed_iterations,
            "failed_iterations": self.failed_iterations,
            "active_principles": self.active_principles,
            "last_event": self.last_event,
            "elapsed_since_last_event": self.elapsed_since_last_event,
            "last_tool_name": self.last_tool_name,
            "stuck": self.stuck,
        }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _last_log_event(log_path: Path) -> tuple[dict | None, float | None]:
    """Return (last_event, mtime_seconds_since_epoch) from a JSONL log."""
    if not log_path.exists():
        return None, None
    last: dict | None = None
    try:
        for line in log_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
        mtime = log_path.stat().st_mtime
    except OSError:
        return None, None
    return last, mtime


# #207: walkback window. Most turns produce dozens of events between
# tool calls (thinking blocks, hook events, sub-task notifications); a
# bounded window keeps the cost cheap while still recovering the
# operator-useful tool name in practice.
_TOOL_WALKBACK_LIMIT = 200


def _walkback_for_tool_name(
    log_path: Path, *, limit: int = _TOOL_WALKBACK_LIMIT,
) -> str | None:
    """#207: walk backward through executor_log.jsonl looking for the
    nearest event with a populated ``tool_name``.

    Returns the tool name (e.g. ``"Bash"``) or ``None`` if no
    tool-bearing event exists within the walkback window. Reads at most
    ``limit`` recent lines so a 50k-event log doesn't dominate the cost
    of `nous status`.
    """
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text().splitlines()
    except OSError:
        return None
    # Walk newest-first; stop after `limit` candidate lines.
    inspected = 0
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        inspected += 1
        if inspected > limit:
            break
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        tool = evt.get("tool_name") or evt.get("tool")
        if isinstance(tool, str) and tool.strip():
            return tool.strip()
    return None


def read_status_snapshot(
    work_dir: Path,
    *,
    now: float | None = None,
    stuck_threshold_seconds: float = _STUCK_THRESHOLD_SECONDS,
) -> StatusSnapshot:
    """Build a snapshot from on-disk state + the latest executor log.

    Args:
      work_dir: campaign work-dir.
      now: override of ``time.time()`` for deterministic tests.
      stuck_threshold_seconds: how long without a logged event before the
        snapshot's ``stuck`` flag flips.
    """
    work_dir = Path(work_dir)
    snap = StatusSnapshot()

    state = _read_json(work_dir / "state.json")
    if isinstance(state, dict):
        snap.run_id = str(state.get("run_id", "?"))
        snap.phase = str(state.get("phase", "?"))
        snap.iteration = int(state.get("iteration", 0) or 0)
        snap.raw = state

    ledger = _read_json(work_dir / "ledger.json")
    if isinstance(ledger, dict):
        rows = ledger.get("iterations", [])
        if isinstance(rows, list):
            valid_rows = [
                r for r in rows
                if isinstance(r, dict)
                and isinstance(r.get("iteration"), int)
                and r["iteration"] >= 1
            ]
            # #217: split clean completions from failures so the operator
            # can tell a botched run apart from a clean refute. ``status``
            # is the field ``append_failed_row`` writes; clean rows omit it.
            snap.failed_iterations = sum(
                1 for r in valid_rows if r.get("status") == "FAILED"
            )
            snap.completed_iterations = len(valid_rows) - snap.failed_iterations

    principles = _read_json(work_dir / "principles.json")
    if isinstance(principles, dict):
        plist = principles.get("principles", [])
        if isinstance(plist, list):
            snap.active_principles = sum(
                1 for p in plist
                if isinstance(p, dict) and p.get("status", "active") == "active"
            )

    # #190: dispatcher writes the streaming log under inputs/. Fall back
    # to the legacy iter-root location so older campaigns keep rendering.
    iter_dir = work_dir / "runs" / f"iter-{snap.iteration}"
    log_path = iter_dir / "inputs" / "executor_log.jsonl"
    if not log_path.exists():
        legacy = iter_dir / "executor_log.jsonl"
        if legacy.exists():
            log_path = legacy
    last_event, mtime = _last_log_event(log_path)
    snap.last_event = last_event
    if mtime is not None:
        current = now if now is not None else time.time()
        snap.elapsed_since_last_event = max(0.0, current - mtime)
        snap.stuck = snap.elapsed_since_last_event >= stuck_threshold_seconds
    # #207: separate from `last_event` because the very last event often
    # has no `tool_name` even when a tool call happened moments before.
    snap.last_tool_name = _walkback_for_tool_name(log_path)

    return snap


def format_one_liner(snap: StatusSnapshot) -> str:
    """Single-line summary suitable for a shell prompt or CI log."""
    # #217: surface failed-iteration count so a clean refute (which would
    # show e.g. "1 done") is distinguishable from a botched run ("1 failed").
    done_segment = f"{snap.completed_iterations} done"
    if snap.failed_iterations:
        done_segment += f" / {snap.failed_iterations} failed"
    parts = [
        snap.run_id,
        snap.phase,
        f"iter {snap.iteration}",
        done_segment,
        f"{snap.active_principles} principles",
    ]
    # #207: prefer the walkback-resolved tool name; fall back to the very
    # last event's tool field for compat with logs that don't have any
    # tool-bearing event recently (rare).
    tool = snap.last_tool_name
    if not tool and snap.last_event:
        cand = snap.last_event.get("tool_name") or snap.last_event.get("tool") or ""
        if cand:
            tool = cand
    if tool:
        parts.append(f"last={tool}")
    if snap.stuck:
        parts.append("STUCK")
    return " · ".join(parts)


def format_watch_panel(snap: StatusSnapshot) -> str:
    """Multi-line panel suitable for ``nous status --watch``.

    Plain text — no rich/textual dependency in Phase A; the redraw cycle
    just clears and reprints. Phase B can swap in a fancier renderer.
    """
    lines = [
        f"Campaign:   {snap.run_id}",
        f"Phase:      {snap.phase}",
        f"Iteration:  {snap.iteration}",
        f"Completed:  {snap.completed_iterations} iteration(s)",
    ]
    # #217: only render the Failed line when there are actually failed
    # iterations — keeps the panel uncluttered for healthy campaigns.
    if snap.failed_iterations:
        lines.append(
            f"Failed:     {snap.failed_iterations} iteration(s) "
            f"— see ledger.json for details",
        )
    lines.append(f"Principles: {snap.active_principles} active")
    if snap.last_event:
        # #207: use the walkback-resolved tool name when available;
        # otherwise fall back to the last event's tool fields, then "?".
        tool = snap.last_tool_name
        if not tool:
            tool = snap.last_event.get("tool_name") or snap.last_event.get("tool") or "?"
        lines.append(f"Last tool:  {tool}")
        if snap.elapsed_since_last_event is not None:
            lines.append(f"Last seen:  {snap.elapsed_since_last_event:.0f}s ago")
    else:
        lines.append("Last tool:  (no events yet)")
    if snap.stuck:
        lines.append("")
        lines.append("⚠  STUCK?  no executor activity in the last 5 minutes.")
    return "\n".join(lines)
