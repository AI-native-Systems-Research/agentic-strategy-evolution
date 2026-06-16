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


def _format_score(v: dict[str, Any], key: str) -> str:
    score = v.get(key)
    return "—" if score is None else str(score)


def render(run_dir: Path) -> Path:
    """Read results.json from run_dir, write report.md, return its path."""
    run_dir = Path(run_dir)
    with open(run_dir / "results.json") as f:
        results = json.load(f)

    judge_used = "judge_usage" in results
    has_judge_scores = judge_used and any(
        v.get("judge_correctness") is not None for v in results["variants"]
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
            lines.append(
                f"**Judge:** {ju['tokens_in']:,} in / {ju['tokens_out']:,} out · "
                f"${ju['dollars']:.2f}  "
            )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    if has_judge_scores:
        lines.append(
            "| Variant | $ | Wall (s) | Correctness | Completeness | Status |"
        )
        lines.append("|---|---|---|---|---|---|")
    else:
        lines.append("| Variant | $ | Wall (s) | Status |")
        lines.append("|---|---|---|---|")

    for v in results["variants"]:
        dollars = f"${v['dollars']:.2f}"
        wall = f"{v['wall_seconds']:.1f}"
        status = _format_status(v)
        if has_judge_scores:
            corr = _format_score(v, "judge_correctness")
            comp = _format_score(v, "judge_completeness")
            lines.append(
                f"| {v['variant']} | {dollars} | {wall} | "
                f"{corr} | {comp} | {status} |"
            )
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
            corr = _format_score(v, "judge_correctness")
            comp = _format_score(v, "judge_completeness")
            lines.append(
                f"**Judge:** correctness {corr}/10, completeness {comp}/10 — "
                f"{v['judge_rationale']}"
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
