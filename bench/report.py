"""Markdown report renderer for nous-bench."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _format_status(v: dict[str, Any]) -> str:
    if v.get("crashed"):
        return f"crashed: {v.get('error') or '?'}"
    flags: list[str] = []
    if v.get("hit_cap"):
        flags.append("hit_cap")
    return ", ".join(flags) if flags else "ok"


def _format_metric(v: dict[str, Any], metric: str) -> str:
    """Look up a metric in the variant's judge_scores dict."""
    scores = v.get("judge_scores") or {}
    val = scores.get(metric)
    return "—" if val is None else str(val)


def _column_header(metric: str) -> str:
    """Pretty-print a metric name for a markdown column header."""
    # snake_case → Title Case With Spaces
    return " ".join(part.capitalize() for part in metric.split("_"))


def _resolve_metrics_to_render(results: dict[str, Any]) -> list[str]:
    """Read the list of metrics from judge_usage; fall back to whatever
    keys appear in the first scored variant if metrics field is missing."""
    judge_usage = results.get("judge_usage") or {}
    metrics = judge_usage.get("metrics")
    if metrics:
        return list(metrics)
    # Fallback: introspect from variants
    for v in results.get("variants", []):
        scores = v.get("judge_scores")
        if scores:
            return list(scores.keys())
    return []


def render(run_dir: Path) -> Path:
    """Read results.json from run_dir, write report.md, return its path."""
    run_dir = Path(run_dir)
    with open(run_dir / "results.json") as f:
        results = json.load(f)

    judge_used = "judge_usage" in results
    metrics = _resolve_metrics_to_render(results) if judge_used else []
    has_judge_scores = bool(metrics) and any(
        (v.get("judge_scores") or {}) for v in results["variants"]
    )

    lines: list[str] = []
    lines.append(f"# {results['experiment_id']} — comparison report")
    lines.append("")
    lines.append(f"**Campaign:** `{results['campaign_id']}`  ")
    lines.append(f"**Run:** `{results['run_id']}`  ")
    if results.get("research_question"):
        lines.append(f"**Question:** {results['research_question']}  ")
    lines.append(f"**Started:** {results['started_at']}  ")
    lines.append(f"**Ended:** {results['ended_at']}  ")
    if judge_used:
        ju = results["judge_usage"]
        if ju.get("crashed"):
            lines.append(
                f"**Judge:** crashed ({ju.get('error', '?')}) "
                f"· spent ${ju.get('dollars', 0):.2f}  "
            )
        else:
            metrics_str = (
                f" · metrics: {', '.join(metrics)}" if metrics else ""
            )
            lines.append(
                f"**Judge:** {ju['tokens_in']:,} in / {ju['tokens_out']:,} out · "
                f"${ju['dollars']:.2f}{metrics_str}  "
            )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    if has_judge_scores:
        headers = ["Variant", "$", "Wall (s)"] + [
            _column_header(m) for m in metrics
        ] + ["Status"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "---|" * len(headers))
    else:
        lines.append("| Variant | $ | Wall (s) | Status |")
        lines.append("|---|---|---|---|")

    for v in results["variants"]:
        dollars = f"${v['dollars']:.2f}"
        wall = f"{v['wall_seconds']:.1f}"
        status = _format_status(v)
        if has_judge_scores:
            row = [v["variant"], dollars, wall]
            row += [_format_metric(v, m) for m in metrics]
            row.append(status)
            lines.append("| " + " | ".join(row) + " |")
        else:
            lines.append(
                f"| {v['variant']} | {dollars} | {wall} | {status} |"
            )

    lines.append("")
    lines.append("## Per-variant details")
    for v in results["variants"]:
        lines.append("")
        lines.append(f"### {v['variant']}")
        lines.append("")
        answer = v.get("final_answer") or "(empty)"
        lines.append(f"**Final answer:** {answer}")
        lines.append("")
        if has_judge_scores and v.get("judge_rationale"):
            score_parts = [
                f"{m} {_format_metric(v, m)}/10" for m in metrics
            ]
            lines.append(
                f"**Judge:** {', '.join(score_parts)} — {v['judge_rationale']}"
            )
            lines.append("")
        lines.append(f"- crashed: `{v['crashed']}`")
        lines.append(f"- hit_cap: `{v['hit_cap']}`")
        if v.get("error"):
            lines.append(f"- error: `{v['error']}`")
        lines.append(f"- artifacts: `{v['artifacts_dir']}`")
        lines.append(f"- transcript: `{v['raw_log_path']}`")

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path
