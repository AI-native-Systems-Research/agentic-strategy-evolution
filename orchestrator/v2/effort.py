"""Effort ladder and output cut-off handling (spec 3.10, B12).

Detects stop_reason == "max_tokens", steps effort down, resets per phase.
"""

from __future__ import annotations

from pathlib import Path

from .resume import update_state

EFFORT_LADDER = ["max", "xhigh", "high", "medium", "low"]

_CUT_RESUME_MSG = (
    "Your last reply was cut at the output limit. "
    "Write and run the simplest correct step first."
)


class EffortManager:
    def __init__(self, configured_effort: str | None = None) -> None:
        self._configured = configured_effort
        self._consecutive_cuts: int = 0
        self._total_cuts: int = 0
        self._current_idx: int = 0
        self.reset()

    def reset(self) -> None:
        start = self._configured or "high"
        try:
            self._current_idx = EFFORT_LADDER.index(start)
        except ValueError:
            self._current_idx = 2  # default to "high"
        self._consecutive_cuts = 0

    @property
    def current(self) -> str:
        return EFFORT_LADDER[self._current_idx]

    def on_cut(self) -> str:
        self._consecutive_cuts += 1
        self._total_cuts += 1

        next_idx = self._current_idx + 1
        # "low" only after 2 consecutive cuts
        if self._consecutive_cuts < 2:
            ceiling = len(EFFORT_LADDER) - 2  # medium
        else:
            ceiling = len(EFFORT_LADDER) - 1  # low
        self._current_idx = min(next_idx, ceiling)
        return self.current

    def on_success(self) -> None:
        self._consecutive_cuts = 0

    @property
    def total_cuts(self) -> int:
        return self._total_cuts

    def persist_cut_offs(self, state_path: Path) -> None:
        update_state(state_path.parent, cut_offs=self._total_cuts)
