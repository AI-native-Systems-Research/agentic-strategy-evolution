"""Token + cost accounting for Claude Code subprocess calls.

Centralizes the parsing of `claude --print --output-format json` output
and the rule that only `usage.input_tokens` counts as billable input
(cache fields are reflected in `total_cost_usd`; counting them in
`tokens_in` would unfairly inflate variants that benefit from caching —
this matches the Phase 1.7.1 fix to the nous variant).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def parse_claude_json(stdout: str) -> dict[str, Any]:
    """Parse a `claude --print --output-format json` payload.

    Returned keys: ``final_answer``, ``tokens_in`` (billable input only),
    ``tokens_out``, ``dollars``, ``is_error``, ``subtype``, ``num_turns``.
    Raises ``json.JSONDecodeError`` on malformed input.
    """
    data = json.loads(stdout)
    usage = data.get("usage") or {}
    return {
        "final_answer": str(data.get("result") or ""),
        "tokens_in": int(usage.get("input_tokens", 0)),
        "tokens_out": int(usage.get("output_tokens", 0)),
        "dollars": float(data.get("total_cost_usd", 0)),
        "is_error": bool(data.get("is_error", False)),
        "subtype": str(data.get("subtype") or ""),
        "num_turns": int(data.get("num_turns", 0)),
    }


@dataclass
class LLMMeter:
    """Accumulates token + cost totals across one or more Claude Code calls.

    Used by loop variants (claude_loop, claude_methodology_loop) where
    multiple subprocess calls contribute to one VariantResult. Single-call
    variants like claude_plain use ``parse_claude_json`` directly.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    dollars: float = 0.0

    def add(self, parsed: dict[str, Any]) -> None:
        self.tokens_in += int(parsed.get("tokens_in", 0))
        self.tokens_out += int(parsed.get("tokens_out", 0))
        self.dollars += float(parsed.get("dollars", 0))

    def record_claude_output(self, stdout: str) -> dict[str, Any]:
        """Parse and accumulate in one step. Returns the parsed dict."""
        parsed = parse_claude_json(stdout)
        self.add(parsed)
        return parsed
