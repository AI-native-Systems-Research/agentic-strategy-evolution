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


def _read_final_answer(runs_dir: Path) -> str:
    """Read findings.json from the most recent iter-N dir."""
    if not runs_dir.exists():
        return ""
    iter_dirs = []
    for p in runs_dir.glob("iter-*"):
        try:
            n = int(p.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        iter_dirs.append((n, p))
    iter_dirs.sort(reverse=True)
    for _, iter_dir in iter_dirs:
        findings = iter_dir / "findings.json"
        if not findings.exists():
            continue
        with open(findings) as f:
            data = json.load(f)
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
    return ""


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
        final_answer = _read_final_answer(artifacts_dir / "runs")
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
