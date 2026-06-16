"""Claude-as-judge — scores each variant's final_answer on correctness +
completeness. See plan §6 Phase 2.

Skips crashed variants (their scores are None). Token cost is reported
separately in a top-level `judge_usage` field, not mixed into per-variant
rows.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from bench.metrics import parse_claude_json
from bench.variants.base import VariantResult

DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"
JUDGE_PROMPT_PATH = Path(__file__).parent / "judge_prompt.md"


@dataclass
class JudgeScore:
    variant: str
    correctness: int | None
    completeness: int | None
    rationale: str


@dataclass
class JudgeOutcome:
    scores: list[JudgeScore]
    tokens_in: int = 0
    tokens_out: int = 0
    dollars: float = 0.0
    crashed: bool = False
    error: str | None = None


def _build_user_prompt(
    research_question: str,
    judge_prompt: str,
    judged_results: list[VariantResult],
) -> str:
    parts = [
        judge_prompt,
        "",
        "---",
        "",
        f"Research question: {research_question}",
        "",
        "Candidate answers:",
        "",
    ]
    for r in judged_results:
        parts.append(f"[variant={r.variant}]")
        parts.append(r.final_answer or "(empty)")
        parts.append("")
    parts.append(
        "Score every variant above. Output JSON only, no markdown fences."
    )
    return "\n".join(parts)


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers if present, return inner text."""
    text = text.strip()
    fence = re.match(
        r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE
    )
    if fence:
        return fence.group(1).strip()
    return text


def _parse_judge_response(result_text: str, expected_variants: list[str]) -> list[JudgeScore]:
    """Parse the model's JSON reply into JudgeScore per variant.

    Variants present in expected_variants but missing from the response get
    a placeholder JudgeScore with None scores.
    """
    cleaned = _strip_json_fences(result_text)
    data = json.loads(cleaned)
    by_name: dict[str, dict] = {}
    for entry in data.get("scores", []):
        name = str(entry.get("variant", ""))
        if name:
            by_name[name] = entry

    out: list[JudgeScore] = []
    for variant in expected_variants:
        e = by_name.get(variant)
        if e is None:
            out.append(JudgeScore(variant, None, None, "(judge did not score this variant)"))
            continue
        try:
            correctness = int(e.get("correctness"))
            completeness = int(e.get("completeness"))
        except (TypeError, ValueError):
            correctness = None
            completeness = None
        out.append(
            JudgeScore(
                variant=variant,
                correctness=correctness,
                completeness=completeness,
                rationale=str(e.get("rationale") or ""),
            )
        )
    return out


def run_judge(
    research_question: str,
    variant_results: list[VariantResult],
    judge_prompt: str | None = None,
    model: str = DEFAULT_JUDGE_MODEL,
    timeout: int = 600,
) -> JudgeOutcome:
    """Score variants using a Claude judge session.

    Crashed variants are excluded from the judge input; their scores in the
    returned outcome are None with rationale "(crashed; not judged)".
    """
    if judge_prompt is None:
        judge_prompt = JUDGE_PROMPT_PATH.read_text()

    judged = [r for r in variant_results if not r.crashed and r.final_answer]
    expected_names = [r.variant for r in judged]

    if not judged:
        return JudgeOutcome(
            scores=[
                JudgeScore(r.variant, None, None, "(crashed; not judged)")
                for r in variant_results
            ],
            crashed=False,
            error="no successful variants to judge",
        )

    user_prompt = _build_user_prompt(research_question, judge_prompt, judged)

    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "--model", model,
        user_prompt,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results),
            crashed=True,
            error=f"judge timeout after {timeout}s",
        )
    except FileNotFoundError as e:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results),
            crashed=True,
            error=f"claude CLI not found on PATH: {e}",
        )

    if proc.returncode != 0:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results),
            crashed=True,
            error=f"claude exited {proc.returncode}: {proc.stderr[:500]}",
        )

    try:
        parsed = parse_claude_json(proc.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results),
            crashed=True,
            error=f"malformed judge output: {e}",
        )

    if parsed["is_error"] or parsed["subtype"] != "success":
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results),
            tokens_in=parsed["tokens_in"],
            tokens_out=parsed["tokens_out"],
            dollars=parsed["dollars"],
            crashed=True,
            error=f"judge reported error: subtype={parsed['subtype']!r}",
        )

    try:
        scored = _parse_judge_response(parsed["final_answer"], expected_names)
    except (json.JSONDecodeError, ValueError) as e:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results),
            tokens_in=parsed["tokens_in"],
            tokens_out=parsed["tokens_out"],
            dollars=parsed["dollars"],
            crashed=True,
            error=f"judge response was not valid JSON: {e}",
        )

    # Add placeholder scores for crashed variants (skipped from the judge call)
    crashed_names = {r.variant for r in variant_results if r.crashed or not r.final_answer}
    final_scores = list(scored)
    for r in variant_results:
        if r.variant in crashed_names:
            final_scores.append(
                JudgeScore(r.variant, None, None, "(crashed; not judged)")
            )

    # Reorder to match the original variant_results order
    by_name = {s.variant: s for s in final_scores}
    ordered = [by_name[r.variant] for r in variant_results if r.variant in by_name]

    return JudgeOutcome(
        scores=ordered,
        tokens_in=parsed["tokens_in"],
        tokens_out=parsed["tokens_out"],
        dollars=parsed["dollars"],
        crashed=False,
        error=None,
    )


def _placeholder_scores(variant_results: Iterable[VariantResult]) -> list[JudgeScore]:
    return [
        JudgeScore(r.variant, None, None, "(judge crashed)")
        for r in variant_results
    ]
