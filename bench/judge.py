"""Claude-as-judge — scores each variant's final_answer on a configurable
set of metrics. See sub-issue #295.

The rubric is a set of independently-scorable metrics. Callers (CLI flags,
runner) pick which metrics to score per run by name or by preset. The
judge model receives only the rubric blocks for the selected metrics, and
returns a JSON object whose per-variant entries have one int field per
selected metric plus a rationale.

Crashed variants are skipped from the judge call; their scores in the
returned outcome are None with rationale "(crashed; not judged)". Token
cost is reported in `JudgeOutcome` (top-level) — runner.py exposes it as
`judge_usage` in `results.json`.
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

# --- rubric definitions ----------------------------------------------------

# Per-metric rubric language. Each entry is a markdown block; the renderer
# concatenates only the selected blocks into the judge prompt's
# {RUBRIC_BLOCKS} placeholder.
METRIC_RUBRICS: dict[str, str] = {
    "correctness": (
        "- **correctness** — Are the claims true, well-supported, and free of "
        "obvious errors?\n"
        "  - 10 = rigorously argued with specific numbers / mechanisms / evidence.\n"
        "  - 5 = directionally correct but vague, missing evidence, or partially wrong.\n"
        "  - 0 = clearly wrong, contradicts the question, or unsupported assertion."
    ),
    "completeness": (
        "- **completeness** — Does the answer address the research question fully, "
        "including the relevant variables, regimes, and trade-offs the question implies?\n"
        "  - 10 = exhaustive: covers main effect, magnitude, conditions, caveats.\n"
        "  - 5 = answers the question literally but skips obvious variables or regimes.\n"
        "  - 0 = doesn't engage the question."
    ),
    "novelty": (
        "- **novelty** — Did the answer surface a finding that goes beyond the "
        "literal framing of the question (e.g. a regime change, a new mechanism, "
        "or behaviour the question's framing didn't anticipate)?\n"
        "  - 10 = identifies a categorically novel finding (regime change, new "
        "mechanism, unexpected interaction).\n"
        "  - 5 = expands the answer beyond the obvious, but along the same axis "
        "the question already named.\n"
        "  - 0 = stays strictly within the question as stated."
    ),
    "coverage": (
        "- **coverage** — How many distinct conditions / arms / regimes were tested?\n"
        "  - 10 = multi-arm bundle with main + controls + dose-response + robustness, "
        "≥ 3 distinct regimes tested.\n"
        "  - 5 = one or two arms / regimes.\n"
        "  - 0 = single test, no controls."
    ),
    "diagnostic_value": (
        "- **diagnostic_value** — Does the answer identify bottlenecks, "
        "shortcomings, or concrete follow-up directions for the engineer?\n"
        "  - 10 = concrete actionable insights (named bottleneck, suggested fix, "
        "next experiment).\n"
        "  - 5 = describes what-is but offers no actionable follow-up.\n"
        "  - 0 = no actionable content."
    ),
    "reproducibility": (
        "- **reproducibility** — Could a third party verify the claims from the "
        "artifacts presented?\n"
        "  - 10 = schema-validated artifacts with predicted / observed / status per arm; "
        "claims pinned to specific files / lines / numbers.\n"
        "  - 5 = prose with concrete numbers but no structured artifact trail.\n"
        "  - 0 = unverifiable assertions, no numbers, no artifacts."
    ),
    "iter_coherence": (
        "- **iter_coherence** — Do later iterations build on earlier ones without "
        "contradicting them? (Multi-iteration runs only.)\n"
        "  - 10 = each iteration cleanly builds on prior findings; principles "
        "compound; no contradictions.\n"
        "  - 5 = some redundancy across iterations but no contradictions.\n"
        "  - 0 = contradicts own prior findings; no compounding."
    ),
    "principle_yield": (
        "- **principle_yield** — How many transferable principles were extracted, "
        "and how well-scoped are they?\n"
        "  - 10 = ≥ 5 well-scoped principles with regime / mechanism / "
        "applicability bounds stated.\n"
        "  - 5 = 2–4 principles, or vaguely-scoped.\n"
        "  - 0 = no principles extracted."
    ),
    "causal_explanation_depth": (
        "- **causal_explanation_depth** — Does the answer explain *why* (mechanism), "
        "not just *what* (result)?\n"
        "  - 10 = mechanism cited to source code or first principles; alternate "
        "explanations considered and refuted.\n"
        "  - 5 = mechanism stated but unverified.\n"
        "  - 0 = result reported without explanation."
    ),
    "transferability": (
        "- **transferability** — Could the findings apply beyond the specific system "
        "tested?\n"
        "  - 10 = states applicability bounds with a formula or rule that "
        "generalises (e.g. \"threshold scales with rate × latency × blocks\").\n"
        "  - 5 = caveat-rich but no generalisation rule.\n"
        "  - 0 = single-configuration finding with no scope statement."
    ),
    "structured_artifact_production": (
        "- **structured_artifact_production** — Did the answer produce well-formed "
        "experimental designs (hypothesis bundles, predicted/observed/status arms)?\n"
        "  - 10 = schema-valid hypothesis bundles with predicted / mechanism / "
        "diagnostic per arm.\n"
        "  - 5 = informal but structured prose.\n"
        "  - 0 = freeform answer only."
    ),
}

# All metrics in canonical order. The rubric and the JSON schema render in
# this order regardless of the input order in `metrics` arguments.
ALL_METRICS: list[str] = [
    "correctness",
    "completeness",
    "novelty",
    "coverage",
    "diagnostic_value",
    "reproducibility",
    "iter_coherence",
    "principle_yield",
    "causal_explanation_depth",
    "transferability",
    "structured_artifact_production",
]

# Multi-iter-only metrics. Single-shot variants (claude_plain,
# claude_methodology) cannot demonstrate iteration coherence, so this metric
# is auto-dropped when the run has no multi-iter variants.
MULTI_ITER_ONLY_METRICS: set[str] = {"iter_coherence"}

# Named presets. `default` = all 11 (auto-pruned for non-multi-iter runs).
PRESETS: dict[str, list[str]] = {
    "default": list(ALL_METRICS),
    "ablation-single-iter": [
        "correctness",
        "completeness",
        "novelty",
        "coverage",
        "diagnostic_value",
    ],
    "ablation-multi-iter": [
        "correctness",
        "completeness",
        "novelty",
        "coverage",
        "diagnostic_value",
        "iter_coherence",
        "principle_yield",
        "structured_artifact_production",
    ],
    "case-study": [
        "diagnostic_value",
        "causal_explanation_depth",
        "novelty",
        "transferability",
    ],
    "transferability": [
        "transferability",
        "novelty",
        "principle_yield",
    ],
    "minimal": [
        "correctness",
        "completeness",
    ],
}


class UnknownMetricError(ValueError):
    """Raised when a metric name is not in METRIC_RUBRICS."""


class UnknownPresetError(ValueError):
    """Raised when a preset name is not in PRESETS."""


def resolve_metrics(
    metrics: list[str] | None = None,
    preset: str | None = None,
    *,
    is_multi_iter: bool = False,
) -> list[str]:
    """Resolve a list of metric names from explicit names + a preset.

    Validation:
      - Both None → defaults to PRESETS["default"]
      - Unknown metric raises UnknownMetricError
      - Unknown preset raises UnknownPresetError
      - Order: canonical (ALL_METRICS order), deduped
      - Multi-iter-only metrics are dropped if is_multi_iter is False

    `metrics` and `preset` may be combined: the union is taken, then
    canonicalised.
    """
    selected: list[str] = []
    if preset is not None:
        if preset not in PRESETS:
            raise UnknownPresetError(
                f"unknown preset {preset!r}. Known: {sorted(PRESETS)}"
            )
        selected.extend(PRESETS[preset])
    if metrics is not None:
        for m in metrics:
            if m not in METRIC_RUBRICS:
                raise UnknownMetricError(
                    f"unknown metric {m!r}. Known: {sorted(METRIC_RUBRICS)}"
                )
            selected.append(m)
    if not selected:
        selected = list(PRESETS["default"])

    # Canonicalise: order by ALL_METRICS, dedupe.
    seen: set[str] = set()
    canonical: list[str] = []
    for m in ALL_METRICS:
        if m in selected and m not in seen:
            if not is_multi_iter and m in MULTI_ITER_ONLY_METRICS:
                continue
            canonical.append(m)
            seen.add(m)
    return canonical


# --- prompt rendering ------------------------------------------------------


def _render_judge_prompt(
    template: str, metrics: list[str]
) -> str:
    """Fill the judge_prompt.md frame template with the selected metrics.

    Replaces:
      {RUBRIC_BLOCKS}            → joined per-metric rubric blocks
      {METRIC_KEYS_PLACEHOLDER}  → JSON keys, one per metric, indented
    """
    blocks = "\n\n".join(METRIC_RUBRICS[m] for m in metrics)
    keys = "\n".join(f'      "{m}": <int 0-10>,' for m in metrics)
    return template.replace("{RUBRIC_BLOCKS}", blocks).replace(
        "{METRIC_KEYS_PLACEHOLDER}", keys
    )


# --- dataclasses -----------------------------------------------------------


@dataclass
class JudgeScore:
    """One variant's scores. `scores` maps metric name → int 0-10 (or None
    if the judge did not return that metric, e.g. parse failure)."""
    variant: str
    scores: dict[str, int | None] = field(default_factory=dict)
    rationale: str = ""

    # Convenience accessors for the two original metrics. Keep these to
    # avoid breaking older callers that read .correctness / .completeness
    # directly. Returns None if the metric wasn't scored.
    @property
    def correctness(self) -> int | None:
        return self.scores.get("correctness")

    @property
    def completeness(self) -> int | None:
        return self.scores.get("completeness")


@dataclass
class JudgeOutcome:
    scores: list[JudgeScore]
    metrics: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    dollars: float = 0.0
    crashed: bool = False
    error: str | None = None


# --- prompt assembly + parsing --------------------------------------------


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


def _parse_judge_response(
    result_text: str,
    expected_variants: list[str],
    metrics: list[str],
) -> list[JudgeScore]:
    """Parse the model's JSON reply into JudgeScore per variant.

    Each variant entry must have one int field per metric in `metrics` plus
    a `rationale` field. Missing or unparseable per-metric values become
    None on the corresponding JudgeScore.

    Variants present in expected_variants but missing from the response get
    a placeholder JudgeScore with all-None scores.
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
            out.append(
                JudgeScore(
                    variant=variant,
                    scores={m: None for m in metrics},
                    rationale="(judge did not score this variant)",
                )
            )
            continue
        scores: dict[str, int | None] = {}
        for m in metrics:
            try:
                scores[m] = int(e.get(m))
            except (TypeError, ValueError):
                scores[m] = None
        out.append(
            JudgeScore(
                variant=variant,
                scores=scores,
                rationale=str(e.get("rationale") or ""),
            )
        )
    return out


# --- top-level entry point -------------------------------------------------


def run_judge(
    research_question: str,
    variant_results: list[VariantResult],
    judge_prompt: str | None = None,
    model: str = DEFAULT_JUDGE_MODEL,
    timeout: int = 600,
    metrics: list[str] | None = None,
    preset: str | None = None,
    is_multi_iter: bool = False,
) -> JudgeOutcome:
    """Score variants using a Claude judge session.

    Args:
      research_question: the campaign question, included in the prompt.
      variant_results: per-variant outputs from the runner.
      judge_prompt: optional override for the judge_prompt.md template body
        (default reads from JUDGE_PROMPT_PATH).
      model: claude model id (defaults to Sonnet 4.6).
      timeout: subprocess timeout in seconds.
      metrics: explicit metric names; combined with `preset` if both given.
      preset: named preset from PRESETS.
      is_multi_iter: when True, multi-iter-only metrics like
        `iter_coherence` are kept; otherwise auto-dropped.

    Crashed variants are excluded from the judge input; their scores in the
    returned outcome are all-None with rationale "(crashed; not judged)".
    """
    resolved_metrics = resolve_metrics(
        metrics=metrics, preset=preset, is_multi_iter=is_multi_iter
    )

    if judge_prompt is None:
        judge_prompt = JUDGE_PROMPT_PATH.read_text()
    rendered_prompt = _render_judge_prompt(judge_prompt, resolved_metrics)

    judged = [r for r in variant_results if not r.crashed and r.final_answer]
    expected_names = [r.variant for r in judged]

    if not judged:
        return JudgeOutcome(
            scores=[
                JudgeScore(
                    variant=r.variant,
                    scores={m: None for m in resolved_metrics},
                    rationale="(crashed; not judged)",
                )
                for r in variant_results
            ],
            metrics=resolved_metrics,
            crashed=False,
            error="no successful variants to judge",
        )

    user_prompt = _build_user_prompt(research_question, rendered_prompt, judged)

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
            scores=_placeholder_scores(variant_results, resolved_metrics),
            metrics=resolved_metrics,
            crashed=True,
            error=f"judge timeout after {timeout}s",
        )
    except FileNotFoundError as e:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results, resolved_metrics),
            metrics=resolved_metrics,
            crashed=True,
            error=f"claude CLI not found on PATH: {e}",
        )

    if proc.returncode != 0:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results, resolved_metrics),
            metrics=resolved_metrics,
            crashed=True,
            error=f"claude exited {proc.returncode}: {proc.stderr[:500]}",
        )

    try:
        parsed = parse_claude_json(proc.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results, resolved_metrics),
            metrics=resolved_metrics,
            crashed=True,
            error=f"malformed judge output: {e}",
        )

    if parsed["is_error"] or parsed["subtype"] != "success":
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results, resolved_metrics),
            metrics=resolved_metrics,
            tokens_in=parsed["tokens_in"],
            tokens_out=parsed["tokens_out"],
            dollars=parsed["dollars"],
            crashed=True,
            error=f"judge reported error: subtype={parsed['subtype']!r}",
        )

    try:
        scored = _parse_judge_response(
            parsed["final_answer"], expected_names, resolved_metrics
        )
    except (json.JSONDecodeError, ValueError) as e:
        return JudgeOutcome(
            scores=_placeholder_scores(variant_results, resolved_metrics),
            metrics=resolved_metrics,
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
                JudgeScore(
                    variant=r.variant,
                    scores={m: None for m in resolved_metrics},
                    rationale="(crashed; not judged)",
                )
            )

    # Reorder to match the original variant_results order
    by_name = {s.variant: s for s in final_scores}
    ordered = [by_name[r.variant] for r in variant_results if r.variant in by_name]

    return JudgeOutcome(
        scores=ordered,
        metrics=resolved_metrics,
        tokens_in=parsed["tokens_in"],
        tokens_out=parsed["tokens_out"],
        dollars=parsed["dollars"],
        crashed=False,
        error=None,
    )


def _placeholder_scores(
    variant_results: Iterable[VariantResult],
    metrics: list[str],
) -> list[JudgeScore]:
    return [
        JudgeScore(
            variant=r.variant,
            scores={m: None for m in metrics},
            rationale="(judge crashed)",
        )
        for r in variant_results
    ]
