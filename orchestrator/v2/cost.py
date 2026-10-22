"""Transcript cost meter (spec 3.10).

Counts tokens per message id (dedup), computes cost from a price table,
tracks per-phase totals. Reporting only — cost never drives a decision.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_prices(defaults_path: Path) -> dict[str, dict[str, float]]:
    """Load the prices table from defaults.yaml. Returns {} on any failure."""
    try:
        import yaml
        data = yaml.safe_load(defaults_path.read_text())
    except Exception:
        logger.warning("failed to load prices from %s", defaults_path)
        return {}
    if not isinstance(data, dict):
        return {}
    return data.get("prices", {}) or {}


class CostMeter:
    """One count per message id, subagents included."""

    def __init__(self, prices: dict[str, dict[str, float]]) -> None:
        self._prices = prices
        self._seen_ids: set[str] = set()
        self._phase_totals: dict[str, dict[str, Any]] = {}
        self._current_phase: str = "BASELINE"
        self._last_snapshot: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def set_phase(self, phase: str) -> None:
        self._current_phase = phase

    def record(self, message: Any) -> None:
        msg_id = getattr(message, "message_id", None) or getattr(message, "uuid", None)
        if msg_id and msg_id in self._seen_ids:
            return
        if msg_id:
            self._seen_ids.add(msg_id)

        usage = getattr(message, "usage", None)
        if not usage:
            return
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        if input_t == 0 and output_t == 0:
            return

        model = getattr(message, "model", None) or ""
        price = self._prices.get(model, {})
        if not price and model:
            logger.debug("no price entry for model %r, costing at $0", model)
        cost = (
            input_t * price.get("input_tokens", 0)
            + output_t * price.get("output_tokens", 0)
        ) / 1_000_000

        totals = self._phase_totals.setdefault(
            self._current_phase,
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        )
        totals["input_tokens"] += input_t
        totals["output_tokens"] += output_t
        totals["cost_usd"] += cost

    def phase_summary(self, phase: str) -> dict[str, Any]:
        return dict(
            self._phase_totals.get(
                phase, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            )
        )

    def total(self) -> dict[str, Any]:
        t: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        for v in self._phase_totals.values():
            t["input_tokens"] += v["input_tokens"]
            t["output_tokens"] += v["output_tokens"]
            t["cost_usd"] += v["cost_usd"]
        return t

    def iter_delta(self) -> dict[str, Any]:
        """Return cost since the last call to iter_delta (per-iteration)."""
        current = self.total()
        delta = {
            "input_tokens": current["input_tokens"] - self._last_snapshot["input_tokens"],
            "output_tokens": current["output_tokens"] - self._last_snapshot["output_tokens"],
            "cost_usd": current["cost_usd"] - self._last_snapshot["cost_usd"],
        }
        self._last_snapshot = current
        return delta
