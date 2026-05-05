"""Minimal LLM metrics logging for Nous campaigns.

Appends per-call entries to a JSONL file and provides aggregation.
"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone


def log_metrics(metrics_path: Path, entry: dict) -> None:
    """Append a single metrics entry to the JSONL file."""
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with open(metrics_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def summarize_metrics(metrics_path: Path) -> dict:
    """Read JSONL and return aggregate summary."""
    if not metrics_path.exists():
        return {"total_calls": 0, "total_cost_usd": 0, "total_input_tokens": 0, "total_output_tokens": 0}

    entries = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]

    summary = {
        "total_calls": len(entries),
        "total_cost_usd": sum(e.get("cost_usd", 0) or 0 for e in entries),
        "total_input_tokens": sum(e.get("input_tokens", 0) or 0 for e in entries),
        "total_output_tokens": sum(e.get("output_tokens", 0) or 0 for e in entries),
        "total_duration_ms": sum(e.get("duration_ms", 0) or 0 for e in entries),
        "by_phase": {},
        "by_dispatcher": {},
    }

    for e in entries:
        # Group by phase
        phase = e.get("phase", "unknown")
        bucket = summary["by_phase"].setdefault(phase, {
            "calls": 0, "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
        })
        bucket["calls"] += 1
        bucket["cost_usd"] += e.get("cost_usd", 0) or 0
        bucket["input_tokens"] += e.get("input_tokens", 0) or 0
        bucket["output_tokens"] += e.get("output_tokens", 0) or 0

        # Group by dispatcher type
        dispatcher = e.get("dispatcher", "unknown")
        dbucket = summary["by_dispatcher"].setdefault(dispatcher, {
            "calls": 0, "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
        })
        dbucket["calls"] += 1
        dbucket["cost_usd"] += e.get("cost_usd", 0) or 0
        dbucket["input_tokens"] += e.get("input_tokens", 0) or 0
        dbucket["output_tokens"] += e.get("output_tokens", 0) or 0

    return summary
