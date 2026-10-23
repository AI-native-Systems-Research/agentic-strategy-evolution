"""Nous v2 robustness: failure breaker and wait_for polling (spec 3.5, 3.2 step 4)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


_NUMBERS_RE = re.compile(r"\d+(\.\d+)?")
_PATH_RE = re.compile(r"(/[\w./-]+|[A-Za-z]:\\[\w.\\-]+)")


def failure_fingerprint(exc_type: str, phase: str, message: str) -> str:
    """Normalize an error into a stable fingerprint for the breaker."""
    normalized = _NUMBERS_RE.sub("N", message)
    normalized = _PATH_RE.sub("PATH", normalized)
    raw = f"{exc_type}:{phase}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class FailureBreaker:
    """Track consecutive identical failures; trigger halt after threshold."""

    def __init__(self, threshold: int = 3):
        self._threshold = threshold
        self._recent: list[str] = []

    def record(self, exc_type: str, phase: str, message: str) -> str | None:
        """Record a failure. Returns the fingerprint if breaker triggers, else None."""
        fp = failure_fingerprint(exc_type, phase, message)
        self._recent.append(fp)
        if len(self._recent) > self._threshold:
            self._recent = self._recent[-self._threshold:]
        if len(self._recent) >= self._threshold and len(set(self._recent)) == 1:
            return fp
        return None

    def reset(self) -> None:
        """A success breaks the run of consecutive failures."""
        self._recent = []


def write_halt(work_dir: Path, fingerprint: str, phase: str, message: str) -> None:
    """Write halt.json to trigger stop rule."""
    halt = {
        "fingerprint": fingerprint,
        "phase": phase,
        "message": message,
    }
    path = work_dir / "halt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(halt, indent=2) + "\n")


def check_wait_condition(wait_spec: str, cwd: str | None = None) -> bool:
    """Check a single wait_for condition (file exists or cmd exits 0).

    Relative paths and commands resolve against *cwd* (the target repo).
    """
    if wait_spec.startswith("cmd:"):
        try:
            result = subprocess.run(
                wait_spec[4:], shell=True, capture_output=True, timeout=30, cwd=cwd,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("wait_for command error: %s", exc)
            return False
    return (Path(cwd or ".") / wait_spec).exists()


async def poll_and_resume(
    pending_waits: list[dict],
    iteration: int,
    breaker: FailureBreaker,
    turn_fn: Callable,
    cwd: str | None = None,
) -> list[str]:
    """Poll all wait_for conditions; call turn_fn to resume the agent.

    Returns list of timed-out run ids.
    """
    if not pending_waits:
        return []

    remaining = {r["id"]: r["wait_for"] for r in pending_waits}
    max_polls = 240
    ev_loop = asyncio.get_event_loop()

    for _ in range(max_polls):
        done = [rid for rid, wf in remaining.items() if check_wait_condition(wf, cwd)]
        for rid in done:
            del remaining[rid]
        if done:
            ids_str = ", ".join(done)
            logger.info("wait_for satisfied for runs: %s", ids_str)
            if remaining:
                await turn_fn(
                    f"Runs {ids_str} finished; continue EXECUTE. "
                    f"Runs still pending: {', '.join(remaining)}.",
                )
            else:
                await turn_fn(
                    f"Runs {ids_str} finished; continue EXECUTE. "
                    f"Write runs/iter-{iteration}/findings.json "
                    f"and runs/iter-{iteration}/principle_updates.json.",
                )
        if not remaining:
            break
        await ev_loop.run_in_executor(None, time.sleep, 60.0)
    else:
        timed_out = list(remaining)
        for rid in timed_out:
            logger.warning("wait_for timed out for run %s", rid)
            breaker.record("TimeoutError", "EXECUTE", f"wait_for timed out: {rid}")
        await turn_fn(
            f"Runs {', '.join(timed_out)} timed out. "
            f"Write findings for completed runs only.",
        )
        return timed_out

    return []
