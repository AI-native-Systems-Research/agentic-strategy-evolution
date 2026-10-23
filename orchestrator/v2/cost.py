"""Transcript cost meter (spec 3.10).

Counts tokens per message id (dedup), computes cost from a price table,
tracks campaign totals. Reporting only — cost never drives a decision.
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
        self._total: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        self._last_snapshot: dict[str, Any] = dict(self._total)

    def record(self, message: Any) -> None:
        msg_id = getattr(message, "message_id", None) or getattr(message, "uuid", None)
        if msg_id and msg_id in self._seen_ids:
            return
        if msg_id:
            self._seen_ids.add(msg_id)

        # ResultMessage carries no model and repeats the per-message usage: skip it
        model = getattr(message, "model", None)
        usage = getattr(message, "usage", None)
        if not model or not usage:
            return
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        cache_r = usage.get("cache_read_input_tokens", 0) or 0
        cache_w = usage.get("cache_creation_input_tokens", 0) or 0
        price = self._prices.get(model, {})
        if not price:
            logger.debug("no price entry for model %r, costing at $0", model)
        pin = price.get("input_tokens", 0)
        # Anthropic ratios: cache read 0.1x input, cache write 1.25x input
        cost = (
            input_t * pin + output_t * price.get("output_tokens", 0)
            + cache_r * pin * 0.1 + cache_w * pin * 1.25
        ) / 1_000_000
        self._total["input_tokens"] += input_t
        self._total["output_tokens"] += output_t
        self._total["cost_usd"] += cost

    def total(self) -> dict[str, Any]:
        return dict(self._total)

    def iter_delta(self) -> dict[str, Any]:
        """Return cost since the last call to iter_delta (per-iteration)."""
        current = self.total()
        delta = {k: current[k] - self._last_snapshot[k] for k in current}
        self._last_snapshot = current
        return delta
