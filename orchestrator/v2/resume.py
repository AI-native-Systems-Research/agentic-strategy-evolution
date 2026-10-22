"""Nous v2 resume — session resume and fallback (spec 3.7).

Provides helpers for resuming a campaign from state.json, building
fallback priming messages from digest, and handling --note.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .validators import read_json


def load_campaign_state(work_dir: Path) -> dict | None:
    """Load state.json from work_dir. Returns None if missing or corrupt."""
    return read_json(work_dir / "state.json")


def update_state(work_dir: Path, **fields: Any) -> None:
    """Merge *fields* into work_dir/state.json with an atomic write."""
    state_path = work_dir / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_json(state_path)
    if not isinstance(existing, dict):
        existing = {}
    existing.update(fields)
    # Atomic write: tmp file in same dir, then rename
    fd, tmp = tempfile.mkstemp(dir=str(state_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(existing, f, indent=2)
            f.write("\n")
        os.replace(tmp, str(state_path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
