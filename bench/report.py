"""Markdown report renderer for nous-bench. Phase 1 minimal."""
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


def render(run_dir: Path) -> Path:
    """Read results.json from run_dir, write report.md, return its path."""
    run_dir = Path(run_dir)
    with open(run_dir / "results.json") as f:
        results = json.load(f)

    lines: list[str] = []
    lines.append(f"# {results['experiment_id']} — comparison report")
    lines.append("")
    lines.append(f"**Campaign:** `{results['campaign_id']}`  ")
    lines.append(f"**Run:** `{results['run_id']}`  ")
    if results.get("research_question"):
        lines.append(f"**Question:** {results['research_question']}  ")
    lines.append(f"**Started:** {results['started_at']}  ")
    lines.append(f"**Ended:** {results['ended_at']}  ")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Variant | Tokens (in / out) | $ | Wall (s) | Status |")
    lines.append("|---|---|---|---|---|")
    for v in results["variants"]:
        tokens = f"{v['tokens_in']:,} / {v['tokens_out']:,}"
        dollars = f"${v['dollars']:.2f}"
        wall = f"{v['wall_seconds']:.1f}"
        status = _format_status(v)
        lines.append(
            f"| {v['variant']} | {tokens} | {dollars} | {wall} | {status} |"
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
        lines.append(f"- crashed: `{v['crashed']}`")
        lines.append(f"- hit_cap: `{v['hit_cap']}`")
        if v.get("error"):
            lines.append(f"- error: `{v['error']}`")
        lines.append(f"- artifacts: `{v['artifacts_dir']}`")
        lines.append(f"- transcript: `{v['raw_log_path']}`")

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path
