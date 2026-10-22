"""Nous v2 robustness: repair loop, failure breaker, wait_for polling (spec 3.5, 3.2 step 4)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Failure fingerprint ──────────────────────────────────────────────────

_NUMBERS_RE = re.compile(r"\d+(\.\d+)?")
_PATH_RE = re.compile(r"(/[\w./-]+|[A-Za-z]:\\[\w.\\-]+)")


def failure_fingerprint(exc_type: str, phase: str, message: str) -> str:
    """Normalize an error into a stable fingerprint for the breaker."""
    normalized = _NUMBERS_RE.sub("N", message)
    normalized = _PATH_RE.sub("PATH", normalized)
    raw = f"{exc_type}:{phase}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Failure breaker ──────────────────────────────────────────────────────


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


# ── Wait-for polling (3.2 step 4) ───────────────────────────────────────


def poll_wait_for(
    wait_spec: str,
    *,
    poll_interval: float = 60.0,
    timeout: float = 14400.0,
    sleep_fn=time.sleep,
) -> bool:
    """Poll a wait_for spec until satisfied or timeout.

    wait_spec is either a file path (must exist) or "cmd:<command>" (must exit 0).
    No model calls are made during polling.
    """
    is_command = wait_spec.startswith("cmd:")
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if is_command:
            cmd = wait_spec[4:]
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, timeout=30,
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("wait_for command error: %s", exc)
        else:
            if Path(wait_spec).exists():
                return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep_fn(min(poll_interval, remaining))

    return False
