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
    """Campaign cost. The authority is the CLI's own session cost (``ResultMessage.total_cost_usd``,
    cumulative per session id, subagents included). Between results, and when the CLI reports
    none, assistant usage is priced per message id (largest usage wins: a streamed reply repeats
    its id). Streamed usage undercounts output, so the CLI figure replaces the estimate."""

    def __init__(self, prices: dict[str, dict[str, float]]) -> None:
        self._prices = prices
        self._by_id: dict[str, tuple[float, int, int]] = {}  # id -> (cost, input, output)
        self._tokens: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self._settled = 0.0  # CLI-reported cost, summed over sessions
        self._session_cost: dict[str, float] = {}  # session id -> last cumulative CLI cost
        self._estimate = 0.0  # priced usage since the last CLI-reported result
        self._last_snapshot: dict[str, Any] = self.total()

    def record(self, message: Any) -> None:
        if hasattr(message, "total_cost_usd"):  # ResultMessage: its usage repeats the messages
            self._settle(message)
            return
        model = getattr(message, "model", None)
        usage = getattr(message, "usage", None)
        if not model or not usage:
            return
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
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
        msg_id = getattr(message, "message_id", None) or getattr(message, "uuid", None) or id(message)
        prev = self._by_id.get(msg_id, (0.0, 0, 0))
        if cost <= prev[0] and (input_t, output_t) <= prev[1:]:
            return
        self._by_id[msg_id] = (cost, input_t, output_t)
        self._tokens["input_tokens"] += input_t - prev[1]
        self._tokens["output_tokens"] += output_t - prev[2]
        self._estimate += cost - prev[0]

    def _settle(self, result: Any) -> None:
        cli = getattr(result, "total_cost_usd", None)
        sid = getattr(result, "session_id", None) or ""
        if not isinstance(cli, (int, float)):
            return  # no CLI figure: keep the priced estimate
        prev = self._session_cost.get(sid, 0.0)
        # Cumulative per session id, also across a resume (measured: CLI 2.1.308, SDK 0.2.172)
        if cli < prev:  # the CLI restarted its count for this session id
            prev = 0.0
        self._settled += cli - prev
        self._session_cost[sid] = cli
        self._estimate = 0.0

    def total(self) -> dict[str, Any]:
        return {**self._tokens, "cost_usd": self._settled + self._estimate}

    def iter_delta(self) -> dict[str, Any]:
        """Return cost since the last call to iter_delta (per-iteration)."""
        current = self.total()
        delta = {k: current[k] - self._last_snapshot[k] for k in current}
        self._last_snapshot = current
        return delta
