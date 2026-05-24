"""Cache hit-rate aggregation over llm_metrics.jsonl (issue #122).

Reads the per-call metrics file and computes:

  * total cache_read_input_tokens (paid for once per cache window)
  * total cache_creation_input_tokens (paid the first time only)
  * total uncached input tokens
  * cache hit rate = read / (read + creation + uncached)
  * by-phase breakdown (so DESIGN-vs-EXECUTE_ANALYZE differences surface)

The result powers ``nous cost --cache-stats``. Output is JSON-serializable
so the same numbers can drive Routines (#134) reporting later.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _iter_rows(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def cache_stats(metrics_path: Path) -> dict[str, Any]:
    """Compute cache hit-rate statistics from a metrics JSONL file.

    Returns:
      ::

        {
          "total_calls": int,
          "input_tokens_uncached": int,
          "cache_creation_input_tokens": int,
          "cache_read_input_tokens": int,
          "hit_rate": float,        # 0.0–1.0
          "by_phase": {
            <phase>: { same fields, scoped to that phase }
          }
        }
    """
    rows = list(_iter_rows(Path(metrics_path)))
    return _aggregate(rows)


def _aggregate(rows: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total_calls": 0,
        "input_tokens_uncached": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "hit_rate": 0.0,
        "by_phase": {},
    }
    phase_aggregates: dict[str, dict[str, int]] = {}

    for row in rows:
        out["total_calls"] += 1
        # Standard schema: input_tokens captures the uncached portion;
        # cache_creation/read are emitted as separate fields by both the
        # CLIDispatcher (since #41) and the SDKDispatcher (#121).
        uncached = int(row.get("input_tokens", 0) or 0)
        creation = int(row.get("cache_creation_input_tokens", 0) or 0)
        read = int(row.get("cache_read_input_tokens", 0) or 0)
        out["input_tokens_uncached"] += uncached
        out["cache_creation_input_tokens"] += creation
        out["cache_read_input_tokens"] += read

        phase = row.get("phase", "unknown")
        bucket = phase_aggregates.setdefault(phase, {
            "calls": 0,
            "input_tokens_uncached": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        })
        bucket["calls"] += 1
        bucket["input_tokens_uncached"] += uncached
        bucket["cache_creation_input_tokens"] += creation
        bucket["cache_read_input_tokens"] += read

    total_input = (
        out["input_tokens_uncached"]
        + out["cache_creation_input_tokens"]
        + out["cache_read_input_tokens"]
    )
    out["hit_rate"] = (
        out["cache_read_input_tokens"] / total_input if total_input else 0.0
    )

    for phase, b in sorted(phase_aggregates.items()):
        phase_total = (
            b["input_tokens_uncached"]
            + b["cache_creation_input_tokens"]
            + b["cache_read_input_tokens"]
        )
        b["hit_rate"] = (
            b["cache_read_input_tokens"] / phase_total if phase_total else 0.0
        )
    out["by_phase"] = phase_aggregates
    return out


def format_cache_stats(stats: dict[str, Any]) -> str:
    """Render stats as a multiline human-readable summary."""
    lines: list[str] = []
    lines.append(f"  Calls:                  {stats['total_calls']}")
    lines.append(f"  Uncached input tokens:  {stats['input_tokens_uncached']:,}")
    lines.append(f"  Cache-creation tokens:  {stats['cache_creation_input_tokens']:,}")
    lines.append(f"  Cache-read tokens:      {stats['cache_read_input_tokens']:,}")
    lines.append(f"  Hit rate:               {stats['hit_rate']:.1%}")
    if stats.get("by_phase"):
        lines.append("")
        lines.append("  By phase:")
        for phase, b in stats["by_phase"].items():
            lines.append(
                f"    {phase}: {b['calls']} call(s), "
                f"hit rate {b['hit_rate']:.1%} "
                f"(read {b['cache_read_input_tokens']:,} / "
                f"create {b['cache_creation_input_tokens']:,} / "
                f"uncached {b['input_tokens_uncached']:,})"
            )
    return "\n".join(lines)
