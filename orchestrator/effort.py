"""v8 effort rule: how hard each SDK session thinks. Pure Python, no LLM calls.

Adaptive-thinking models ignore thinking-token budgets; ``effort`` is the control they honour
(https://platform.claude.com/docs/en/build-with-claude/effort). On ``stop_reason: max_tokens`` the docs
advise raising the output limit or lowering effort; Claude Code caps output at 64k, so we lower effort.

1. The evaluator session (setup: a grader and a first baseline) runs at ``medium``.
2. Every other session runs at the model's default, or the campaign's explicit effort.
3. Each reply cut at the output limit lowers later sessions one level (never below ``medium``); inside the
   cut session each resume drops one level, down to ``low`` as a last resort.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.util import atomic_write

LEVELS = ("low", "medium", "high", "xhigh", "max")
EFFORT_FILE = "effort_state.json"
SETUP_EFFORT = "medium"
NEW_SESSION_FLOOR = "medium"
SETUP_LABELS = frozenset({"evaluator"})


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
    """Count one lost reply; returns how many levels later sessions start below their normal level."""
    data = _state(work_dir)
    data["output_limit_hits"] = int(data.get("output_limit_hits") or 0) + 1
    data["step_down"] = int(data.get("step_down") or 0) + 1
    atomic_write(Path(work_dir) / EFFORT_FILE, json.dumps(data, indent=2) + "\n")
    return data["step_down"]


def session_effort(work_dir: Path, model: str | None, label: str | None = None,
                   explicit: str | None = None) -> str:
    """Effort for a new session under the rule above."""
    normal = explicit if explicit in LEVELS else model_default(model)
    if label in SETUP_LABELS:
        normal = LEVELS[min(_idx(normal), _idx(SETUP_EFFORT))]
    floor = min(_idx(normal), _idx(NEW_SESSION_FLOOR))
    return LEVELS[max(floor, _idx(normal) - int(_state(work_dir).get("step_down") or 0))]
