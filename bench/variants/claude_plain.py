"""claude_plain variant — single headless Claude Code session, no methodology.

See plan §6 Phase 2 for invocation details. The JSON parser here will be
promoted to bench/metrics.py:LLMMeter in Phase 2.2.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from bench.variants.base import Budget, Campaign, VariantResult

DEFAULT_MODEL = "claude-sonnet-4-6"


def _parse_claude_output(stdout: str) -> dict[str, Any]:
    """Extract metrics + final answer from `claude --output-format json` stdout.

    Counts only `usage.input_tokens` for `tokens_in` (mirrors the Phase 1.7.1
    fix to the nous variant — cache reads/writes are billed differently and
    would unfairly inflate cache-heavy variants).
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


class ClaudePlainVariant:
    name = "claude_plain"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        start = time.monotonic()
        log_path = workspace / ".bench-claude-plain.log"

        cmd = [
            "claude",
            "--print",
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--model", DEFAULT_MODEL,
            campaign.research_question,
        ]

        crashed = False
        error: str | None = None
        tokens_in = 0
        tokens_out = 0
        dollars = 0.0
        final_answer = ""

        try:
            proc = subprocess.run(
                cmd,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=budget.max_wall_seconds,
                check=False,
            )
            log_path.write_text(
                f"=== stdout ===\n{proc.stdout}\n=== stderr ===\n{proc.stderr}"
            )
            if proc.returncode != 0:
                crashed = True
                error = (
                    f"claude exited with code {proc.returncode}: "
                    f"{proc.stderr[:500]}"
                )
            else:
                try:
                    parsed = _parse_claude_output(proc.stdout)
                except (json.JSONDecodeError, ValueError) as e:
                    crashed = True
                    error = f"malformed claude json output: {e}"
                else:
                    if parsed["is_error"] or parsed["subtype"] != "success":
                        crashed = True
                        error = (
                            f"claude reported error: subtype={parsed['subtype']!r}"
                        )
                    final_answer = parsed["final_answer"]
                    tokens_in = parsed["tokens_in"]
                    tokens_out = parsed["tokens_out"]
                    dollars = parsed["dollars"]
        except subprocess.TimeoutExpired:
            crashed = True
            error = f"claude timeout after {budget.max_wall_seconds}s"
            log_path.write_text(f"timeout after {budget.max_wall_seconds}s")
        except FileNotFoundError as e:
            crashed = True
            error = f"claude CLI not found on PATH: {e}"
        except Exception as e:
            crashed = True
            error = f"{type(e).__name__}: {e}"

        wall = time.monotonic() - start
        hit_cap = (tokens_in + tokens_out) > budget.max_tokens

        return VariantResult(
            variant=self.name,
            campaign_id=campaign.id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            dollars=dollars,
            wall_seconds=wall,
            final_answer=final_answer,
            artifacts_dir=workspace,
            raw_log_path=log_path,
            crashed=crashed,
            hit_cap=hit_cap,
            error=error,
        )
