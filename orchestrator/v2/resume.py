"""Nous v2 resume — session resume and fallback (spec 3.7).

Provides helpers for resuming a campaign from state.json, building
fallback priming messages from digest, and handling --note.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_campaign_state(work_dir: Path) -> dict | None:
    """Load state.json from work_dir. Returns None if missing or corrupt."""
    state_path = work_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("corrupt or unreadable state.json in %s", work_dir)
        return None


def resume_phase(state: dict) -> tuple[str, int]:
    """Return (phase, iteration) to resume from based on saved state."""
    phase = state.get("phase", "BASELINE")
    iteration = state.get("iteration", 0)
    return phase, iteration


def build_fallback_message(
    *,
    phase: str,
    iteration: int,
    digest: dict | None,
    note: str | None,
) -> str:
    """Build the priming message for a fresh-session fallback.

    Includes the digest summary and any --note text.
    """
    parts = [
        f"Resuming campaign at {phase} phase, iteration {iteration}.",
        "Read state/digest.json for the campaign context so far.",
    ]

    if digest:
        digest_summary = json.dumps(digest, indent=2)
        parts.append(f"Current digest:\n{digest_summary}")

    if note:
        parts.append(f"Human note: {note}")

    return "\n\n".join(parts)
