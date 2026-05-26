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
    active_principles: int = 0
    last_event: dict[str, Any] | None = None
    elapsed_since_last_event: float | None = None  # seconds; None if no event
    stuck: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "iteration": self.iteration,
            "completed_iterations": self.completed_iterations,
            "active_principles": self.active_principles,
            "last_event": self.last_event,
            "elapsed_since_last_event": self.elapsed_since_last_event,
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
            snap.completed_iterations = sum(
                1 for r in rows
                if isinstance(r, dict)
                and isinstance(r.get("iteration"), int)
                and r["iteration"] >= 1
            )

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

    return snap


def format_one_liner(snap: StatusSnapshot) -> str:
    """Single-line summary suitable for a shell prompt or CI log."""
    parts = [
        snap.run_id,
        snap.phase,
        f"iter {snap.iteration}",
        f"{snap.completed_iterations} done",
        f"{snap.active_principles} principles",
    ]
    if snap.last_event:
        tool = snap.last_event.get("tool_name") or snap.last_event.get("tool") or ""
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
        f"Principles: {snap.active_principles} active",
    ]
    if snap.last_event:
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
