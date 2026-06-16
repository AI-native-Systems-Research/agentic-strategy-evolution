"""Shared helpers for variants that wrap headless Claude Code.

Used by claude_plain, claude_methodology, claude_loop, claude_methodology_loop.
Extracted from claude_plain.py during sub-issue #293 to avoid duplicating
~80 lines of subprocess + parsing per variant.

The seam tests patch is `bench.variants._claude_common.subprocess.run`.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from bench.metrics import parse_claude_json
from bench.variants.base import Budget, VariantResult

DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class ClaudeInvocation:
    """One headless Claude Code call's input.

    Caller constructs `question` (which may include prepended context for
    loop variants) and `log_path` (per-iter for loop variants, single for
    one-shot variants). `system_prompt` is None for plain variants and
    the methodology body for methodology variants.
    """

    question: str
    workspace: Path
    budget: Budget
    log_path: Path
    system_prompt: str | None = None
    model: str = DEFAULT_MODEL


@dataclass
class ClaudeRunResult:
    """Output of one `claude --print` invocation."""

    final_answer: str
    tokens_in: int
    tokens_out: int
    dollars: float
    wall_seconds: float
    crashed: bool
    error: str | None
    log_path: Path


def invoke_claude(inv: ClaudeInvocation) -> ClaudeRunResult:
    """Run `claude --print --output-format json` once. Returns parsed result.

    Crash paths (each → crashed=True with a specific error string):
      - subprocess.TimeoutExpired
      - FileNotFoundError (claude CLI missing)
      - non-zero exit code
      - malformed stdout JSON
      - is_error=True or subtype != "success" in the parsed response
      - any other exception
    """
    start = time.monotonic()
    cmd = [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "--model",
        inv.model,
    ]
    if inv.system_prompt:
        cmd.extend(["--append-system-prompt", inv.system_prompt])
    cmd.append(inv.question)

    crashed = False
    error: str | None = None
    final_answer = ""
    tokens_in = 0
    tokens_out = 0
    dollars = 0.0

    try:
        proc = subprocess.run(
            cmd,
            cwd=inv.workspace,
            capture_output=True,
            text=True,
            timeout=inv.budget.max_wall_seconds,
            check=False,
        )
        inv.log_path.write_text(
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
                parsed = parse_claude_json(proc.stdout)
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
        error = f"claude timeout after {inv.budget.max_wall_seconds}s"
        inv.log_path.write_text(f"timeout after {inv.budget.max_wall_seconds}s")
    except FileNotFoundError as e:
        crashed = True
        error = f"claude CLI not found on PATH: {e}"
    except Exception as e:
        crashed = True
        error = f"{type(e).__name__}: {e}"

    wall = time.monotonic() - start

    return ClaudeRunResult(
        final_answer=final_answer,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        dollars=dollars,
        wall_seconds=wall,
        crashed=crashed,
        error=error,
        log_path=inv.log_path,
    )


def variant_result_from(
    runs: list[ClaudeRunResult],
    variant_name: str,
    campaign_id: str,
    workspace: Path,
    budget: Budget,
) -> VariantResult:
    """Aggregate one or more ClaudeRunResults into a VariantResult.

    Single-run variants (claude_plain, claude_methodology) pass `[run]`.
    Loop variants pass `[run1, ..., runN]`.

    Aggregation rules (resolved during plan review):
      - tokens_in / tokens_out / dollars / wall_seconds: SUM across runs
      - final_answer: last NON-crashed run's answer; fall back to last run's
        answer (which may be empty) if all crashed
      - crashed: ANY run crashed
      - error: first crashed run's error; None otherwise
      - hit_cap: (sum_in + sum_out) > budget.max_tokens
      - artifacts_dir: workspace
      - raw_log_path: for single-run, the run's own log_path; for multi-run,
        a concatenated log at workspace/.bench-<variant>.log with
        '=== iter-N ===' section headers
    """
    tokens_in = sum(r.tokens_in for r in runs)
    tokens_out = sum(r.tokens_out for r in runs)
    dollars = sum(r.dollars for r in runs)
    wall_seconds = sum(r.wall_seconds for r in runs)

    crashed = any(r.crashed for r in runs)
    error = next((r.error for r in runs if r.crashed), None)

    non_crashed = [r for r in runs if not r.crashed]
    if non_crashed:
        final_answer = non_crashed[-1].final_answer
    elif runs:
        final_answer = runs[-1].final_answer
    else:
        final_answer = ""

    if len(runs) <= 1:
        raw_log_path = runs[0].log_path if runs else workspace / f".bench-{variant_name}.log"
    else:
        raw_log_path = workspace / f".bench-{variant_name}.log"
        sections: list[str] = []
        for i, r in enumerate(runs, start=1):
            try:
                content = r.log_path.read_text()
            except FileNotFoundError:
                content = "(log missing)"
            sections.append(f"=== iter-{i} ===\n{content}")
        raw_log_path.write_text("\n\n".join(sections))

    hit_cap = (tokens_in + tokens_out) > budget.max_tokens

    return VariantResult(
        variant=variant_name,
        campaign_id=campaign_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        dollars=dollars,
        wall_seconds=wall_seconds,
        final_answer=final_answer,
        artifacts_dir=workspace,
        raw_log_path=raw_log_path,
        crashed=crashed,
        hit_cap=hit_cap,
        error=error,
    )
