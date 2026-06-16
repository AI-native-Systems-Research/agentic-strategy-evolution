"""nous variant — wraps the existing `nous run` CLI. See plan §6 Phase 1."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from bench.variants.base import Budget, Campaign, VariantResult

DEFAULT_MODEL = "claude-sonnet-4-6"


def _translate_to_nous_yaml(
    campaign: Campaign,
    workspace: Path,
    max_iterations: int,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Convert a bench Campaign into a nous-compatible campaign yaml dict.

    Bench schema is flat; nous schema (orchestrator/schemas/campaign.schema.yaml)
    is nested. This is the only place that knows the mapping.
    """
    return {
        "research_question": campaign.research_question,
        "run_id": campaign.id,
        "max_iterations": max_iterations,
        "target_system": {
            "name": campaign.id,
            "description": f"Target system for bench campaign {campaign.id}",
            "repo_path": str(workspace),
        },
        "prompts": {
            "methodology_layer": "prompts/methodology",
            "domain_adapter_layer": None,
        },
        "models": {
            "design": model,
            "execute_analyze": model,
            "report": model,
        },
    }


def _harvest_metrics(metrics_path: Path) -> tuple[int, int, float]:
    """Sum billable tokens + cost across all rows of nous's llm_metrics.jsonl.

    Counts only `input_tokens` (full-rate fresh input) and `output_tokens`.
    Cache creation/read tokens are billed at different rates and are already
    reflected in `cost_usd`; counting them here would unfairly inflate
    variants that benefit from caching (nous's long sessions cache heavily).
    """
    tokens_in = 0
    tokens_out = 0
    dollars = 0.0
    if not metrics_path.exists():
        return tokens_in, tokens_out, dollars
    with open(metrics_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            tokens_in += int(row.get("input_tokens", 0))
            tokens_out += int(row.get("output_tokens", 0))
            dollars += float(row.get("cost_usd", 0))
    return tokens_in, tokens_out, dollars


def _render_findings(data: dict) -> str:
    """Render canonical nous findings.json as a single comparison-friendly string.

    Includes the cross-arm summary (`discrepancy_analysis`) AND per-arm
    `predicted` / `observed` / `status` / `diagnostic_note`. Stripping
    these to just `discrepancy_analysis` (as an earlier version did) gave
    the judge a content-free summary while baseline variants got their
    full prose, biasing the comparison.
    """
    parts: list[str] = []
    summary = data.get("discrepancy_analysis")
    if isinstance(summary, str) and summary:
        parts.append(summary)

    arms = data.get("arms") or []
    if arms:
        parts.append("")
        parts.append("Per-arm results:")
        for arm in arms:
            arm_type = arm.get("arm_type", "?")
            status = arm.get("status", "?")
            parts.append("")
            parts.append(f"- {arm_type} (status: {status})")
            for label, key in (
                ("Predicted", "predicted"),
                ("Observed", "observed"),
                ("Diagnostic", "diagnostic_note"),
            ):
                val = arm.get(key)
                if isinstance(val, str) and val:
                    parts.append(f"  {label}: {val}")
            err = arm.get("error_type")
            if err:
                parts.append(f"  Error type: {err}")

    if data.get("experiment_valid") is False:
        parts.append("")
        parts.append("Experiment marked NOT valid.")

    return "\n".join(parts).strip()


def _render_findings_or_fallback(data: dict) -> str:
    """Render one findings.json. Prefers rich arms[] rendering; falls back
    to simple-key extraction; falls back to truncated JSON dump."""
    arms = data.get("arms")
    if isinstance(arms, list) and arms:
        rendered = _render_findings(data)
        if rendered:
            return rendered
    for key in (
        "conclusion",
        "answer",
        "summary",
        "verdict",
        "result",
        "discrepancy_analysis",
    ):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return json.dumps(data)[:1000]


def _iter_dirs_ascending(runs_dir: Path) -> list[tuple[int, Path]]:
    """Return (N, iter_dir) pairs for runs/iter-N/, sorted by N ascending."""
    if not runs_dir.exists():
        return []
    out: list[tuple[int, Path]] = []
    for p in runs_dir.glob("iter-*"):
        try:
            n = int(p.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        out.append((n, p))
    out.sort()
    return out


def _render_all_findings(runs_dir: Path) -> str:
    """Render every iter-N/findings.json (not just latest), in ascending
    iteration order. Each iter gets a '## Iteration N findings' header.
    Empty / missing returns ''."""
    sections: list[str] = []
    for n, iter_dir in _iter_dirs_ascending(runs_dir):
        findings = iter_dir / "findings.json"
        if not findings.exists():
            continue
        with open(findings) as f:
            data = json.load(f)
        rendered = _render_findings_or_fallback(data)
        if rendered:
            sections.append(f"## Iteration {n} findings\n\n{rendered}")
    return "\n\n".join(sections)


def _render_principles(artifacts_dir: Path) -> str:
    """Render principles.json's active principles. Returns '' if missing
    or empty. Lenient on `status`: missing/null treated as active."""
    path = artifacts_dir / "principles.json"
    if not path.exists():
        return ""
    with open(path) as f:
        data = json.load(f)
    principles = data.get("principles") or []
    blocks: list[str] = []
    for p in principles:
        status = p.get("status")
        if isinstance(status, str) and status and status != "active":
            continue
        pid = p.get("id", "?")
        statement = p.get("statement", "")
        if not statement:
            continue
        block_lines = [f"- [{pid}] {statement}"]
        for label, key in (
            ("Regime", "regime"),
            ("Mechanism", "mechanism"),
            ("Applicability bounds", "applicability_bounds"),
            ("Confidence", "confidence"),
        ):
            value = p.get(key)
            if isinstance(value, str) and value:
                block_lines.append(f"  {label}: {value}")
        blocks.append("\n".join(block_lines))
    if not blocks:
        return ""
    return "## Principles extracted\n\n" + "\n\n".join(blocks)


def _render_ledger(artifacts_dir: Path) -> str:
    """Render ledger.json as a markdown table. Skips iteration=0 (seed row,
    always null fields). Returns '' if file missing or no real iters."""
    path = artifacts_dir / "ledger.json"
    if not path.exists():
        return ""
    with open(path) as f:
        data = json.load(f)
    rows = []
    for entry in data.get("iterations") or []:
        if entry.get("iteration") == 0:
            continue
        iter_n = entry.get("iteration", "?")
        family = entry.get("family") or "—"
        h_main = entry.get("h_main_result") or "—"
        control = entry.get("control_result") or "—"
        robust = entry.get("robustness_result") or "—"
        acc = entry.get("prediction_accuracy") or {}
        if isinstance(acc, dict) and acc.get("arms_total"):
            acc_str = f"{acc.get('arms_correct', 0)}/{acc['arms_total']} ({acc.get('accuracy_pct', 0)}%)"
        else:
            acc_str = "—"
        rows.append(
            f"| {iter_n} | {family} | {h_main} | {control} | {robust} | {acc_str} |"
        )
    if not rows:
        return ""
    header = (
        "## Iteration ledger\n\n"
        "| Iter | Family | h-main | control | robustness | Accuracy |\n"
        "|---|---|---|---|---|---|"
    )
    return header + "\n" + "\n".join(rows)


def _render_report(artifacts_dir: Path) -> str:
    """Return contents of report.md prefixed with a header. '' if absent."""
    path = artifacts_dir / "report.md"
    if not path.exists():
        return ""
    text = path.read_text().strip()
    if not text:
        return ""
    return f"## Campaign report\n\n{text}"


def _read_final_answer(artifacts_dir: Path) -> str:
    """Render the full set of nous artifacts as a single comparison-friendly
    string. See #292: includes all iters' findings, principles, ledger, and
    report (each gracefully skipped when absent)."""
    sections = [
        _render_all_findings(artifacts_dir / "runs"),
        _render_principles(artifacts_dir),
        _render_ledger(artifacts_dir),
        _render_report(artifacts_dir),
    ]
    return "\n\n---\n\n".join(s for s in sections if s.strip())


class NousVariant:
    name = "nous"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        start = time.monotonic()

        nous_yaml_data = _translate_to_nous_yaml(
            campaign, workspace, budget.max_iterations
        )
        nous_yaml_path = workspace / ".bench-nous-campaign.yaml"
        with open(nous_yaml_path, "w") as f:
            yaml.safe_dump(nous_yaml_data, f, sort_keys=False)

        cmd = [
            "nous",
            "run",
            str(nous_yaml_path),
            "--auto-approve",
            "--run-id",
            campaign.id,
            "--max-iterations",
            str(budget.max_iterations),
        ]
        if budget.max_wall_seconds:
            cmd.extend(["--timeout", str(budget.max_wall_seconds)])

        log_path = workspace / ".bench-nous.log"
        crashed = False
        error: str | None = None
        try:
            with open(log_path, "w") as logf:
                proc = subprocess.run(
                    cmd,
                    cwd=workspace,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if proc.returncode != 0:
                crashed = True
                error = f"nous run exited with code {proc.returncode}"
        except FileNotFoundError as e:
            crashed = True
            error = f"nous CLI not found on PATH: {e}"
        except Exception as e:
            crashed = True
            error = f"{type(e).__name__}: {e}"

        wall = time.monotonic() - start

        artifacts_dir = workspace / ".nous" / campaign.id
        tokens_in, tokens_out, dollars = _harvest_metrics(
            artifacts_dir / "llm_metrics.jsonl"
        )
        final_answer = _read_final_answer(artifacts_dir)
        hit_cap = (tokens_in + tokens_out) > budget.max_tokens

        return VariantResult(
            variant=self.name,
            campaign_id=campaign.id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            dollars=dollars,
            wall_seconds=wall,
            final_answer=final_answer,
            artifacts_dir=artifacts_dir,
            raw_log_path=log_path,
            crashed=crashed,
            hit_cap=hit_cap,
            error=error,
        )
