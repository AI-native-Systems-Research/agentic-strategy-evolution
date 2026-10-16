"""v8 effort ladder: how hard each SDK session thinks. Pure Python, no LLM calls.

Adaptive-thinking models ignore thinking-token budgets; ``effort`` is the control they honour
(https://platform.claude.com/docs/en/build-with-claude/effort). The policy:

1. Until an official measure scores above 0, a session runs at ``medium`` (never above the model's
   default): a first correct solution rarely needs the deepest reasoning.
2. After that, sessions run at the model's default (or the campaign's explicit effort).
3. A reply that hits the CLI's output-token limit is lost, so the session resumes one level lower and
   the campaign remembers it: later sessions start one level lower too, never below ``medium``.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.util import atomic_write

LEVELS = ("low", "medium", "high", "xhigh", "max")
EFFORT_FILE = "effort_state.json"
FIRST_SOLUTION = "medium"
NEW_SESSION_FLOOR = "medium"


def model_default(model: str | None) -> str:
    """The API default effort for ``model`` (medium on Opus 5.5 and Haiku 5.5, high elsewhere)."""
    m = str(model or "")
    return "medium" if ("opus-5-5" in m or "haiku-5-5" in m) else "high"


def _idx(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else LEVELS.index("high")


def lower(level: str) -> str:
    return LEVELS[max(0, _idx(level) - 1)]


def _state(work_dir: Path) -> dict:
    try:
        data = json.loads((Path(work_dir) / EFFORT_FILE).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_output_limit(work_dir: Path) -> int:
    """Count one lost reply; returns the campaign's step-down (levels below the normal start)."""
    data = _state(work_dir)
    data["output_limit_hits"] = int(data.get("output_limit_hits") or 0) + 1
    data["step_down"] = int(data.get("step_down") or 0) + 1
    atomic_write(Path(work_dir) / EFFORT_FILE, json.dumps(data, indent=2) + "\n")
    return data["step_down"]


def session_effort(campaign: dict, work_dir: Path, model: str | None, explicit: str | None = None) -> str:
    """Effort for a new session under the ladder above."""
    from orchestrator.judge_profile import best_official
    default = explicit if explicit in LEVELS else model_default(model)
    scored = (best_official(campaign, work_dir) or 0.0) > 0
    base = default if scored else LEVELS[min(_idx(default), _idx(FIRST_SOLUTION))]
    floor = min(_idx(base), _idx(NEW_SESSION_FLOOR))
    return LEVELS[max(floor, _idx(base) - int(_state(work_dir).get("step_down") or 0))]
