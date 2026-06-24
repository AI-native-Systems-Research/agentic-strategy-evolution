"""Tests for bench/judge.py — Claude-as-judge.

Live `claude` invocation is exercised by paid validation runs (tests 1-3
in sub-issue #295). Here we test the pure helpers: metric resolution,
prompt rendering, response parsing, fence stripping, and the high-level
run_judge() with crashed/empty inputs. No live LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.judge import (
    ALL_METRICS,
    DEFAULT_JUDGE_MODEL,
    JUDGE_PROMPT_PATH,
    METRIC_RUBRICS,
    MULTI_ITER_ONLY_METRICS,
    PRESETS,
    JudgeOutcome,
    JudgeScore,
    UnknownMetricError,
    UnknownPresetError,
    _build_user_prompt,
    _parse_judge_response,
    _render_judge_prompt,
    _strip_json_fences,
    resolve_metrics,
    run_judge,
)
from bench.variants.base import VariantResult


def _result(variant: str, answer: str, crashed: bool = False) -> VariantResult:
    return VariantResult(
        variant=variant,
        campaign_id="c1",
        tokens_in=10,
        tokens_out=5,
        dollars=0.01,
        wall_seconds=1.0,
        final_answer=answer,
        artifacts_dir=Path("/x"),
        raw_log_path=Path("/y"),
        crashed=crashed,
        hit_cap=False,
        error=None,
    )


# --- metric registry ------------------------------------------------------


def test_all_metrics_have_rubric_blocks():
    """Every metric in ALL_METRICS has a corresponding rubric block."""
    for m in ALL_METRICS:
        assert m in METRIC_RUBRICS
        assert len(METRIC_RUBRICS[m]) > 50  # nontrivial rubric language


def test_all_metric_rubrics_have_anchors():
    """Each rubric block must show 0/5/10 anchors so the judge can ground its scores."""
    for m, block in METRIC_RUBRICS.items():
        assert "10 =" in block, f"{m} rubric missing 10 anchor"
        assert "5 =" in block, f"{m} rubric missing 5 anchor"
        assert "0 =" in block, f"{m} rubric missing 0 anchor"


def test_presets_only_reference_known_metrics():
    """Every preset's metrics must exist in METRIC_RUBRICS."""
    for preset_name, metrics in PRESETS.items():
        for m in metrics:
            assert m in METRIC_RUBRICS, (
                f"preset {preset_name!r} references unknown metric {m!r}"
            )


def test_default_preset_is_all_metrics():
    """`default` preset must include every metric we ship."""
    assert PRESETS["default"] == list(ALL_METRICS)


# --- resolve_metrics ------------------------------------------------------


def test_resolve_metrics_defaults_to_default_preset():
    out = resolve_metrics()
    # Drops iter_coherence since is_multi_iter defaults to False
    assert out == [m for m in ALL_METRICS if m not in MULTI_ITER_ONLY_METRICS]


def test_resolve_metrics_keeps_iter_coherence_when_multi_iter():
    out = resolve_metrics(is_multi_iter=True)
    assert "iter_coherence" in out


def test_resolve_metrics_drops_iter_coherence_when_single_iter():
    """Even if explicitly asked, drop iter_coherence on single-iter runs."""
    out = resolve_metrics(metrics=["correctness", "iter_coherence"], is_multi_iter=False)
    assert "iter_coherence" not in out
    assert "correctness" in out


def test_resolve_metrics_explicit_list():
    out = resolve_metrics(metrics=["correctness", "novelty"])
    assert out == ["correctness", "novelty"]


def test_resolve_metrics_returns_canonical_order():
    """Order is ALL_METRICS order, not input order."""
    # Input in reverse of canonical
    out = resolve_metrics(metrics=["novelty", "correctness"])
    # Canonical order: correctness comes before novelty
    assert out == ["correctness", "novelty"]


def test_resolve_metrics_dedupes():
    out = resolve_metrics(metrics=["correctness", "correctness", "novelty"])
    assert out == ["correctness", "novelty"]


def test_resolve_metrics_preset_only():
    out = resolve_metrics(preset="ablation-single-iter")
    assert out == [
        "correctness", "completeness", "novelty",
        "coverage", "diagnostic_value",
    ]


def test_resolve_metrics_combines_preset_and_explicit():
    """Explicit metrics are unioned with preset."""
    out = resolve_metrics(
        preset="minimal",
        metrics=["novelty"],
    )
    # minimal = correctness, completeness; + novelty
    assert out == ["correctness", "completeness", "novelty"]


def test_resolve_metrics_unknown_metric_raises():
    with pytest.raises(UnknownMetricError):
        resolve_metrics(metrics=["nonexistent"])


def test_resolve_metrics_unknown_preset_raises():
    with pytest.raises(UnknownPresetError):
        resolve_metrics(preset="not-a-preset")


# --- _render_judge_prompt -------------------------------------------------


def _read_template() -> str:
    return JUDGE_PROMPT_PATH.read_text()


def test_render_includes_only_selected_metric_blocks():
    template = _read_template()
    out = _render_judge_prompt(template, ["correctness", "novelty"])
    # Selected metrics appear in the rendered text
    assert "correctness" in out
    assert "novelty" in out
    # Non-selected metrics' rubric blocks do NOT appear
    assert "diagnostic_value" not in out
    assert "transferability" not in out


def test_render_substitutes_metric_keys_into_schema_block():
    template = _read_template()
    out = _render_judge_prompt(template, ["correctness", "novelty"])
    # Output schema includes JSON keys for every selected metric
    assert '"correctness": <int 0-10>' in out
    assert '"novelty": <int 0-10>' in out
    # Schema does NOT include keys for unselected metrics
    assert '"diagnostic_value": <int 0-10>' not in out


def test_render_leaves_no_unfilled_placeholders():
    template = _read_template()
    out = _render_judge_prompt(template, ["correctness"])
    assert "{RUBRIC_BLOCKS}" not in out
    assert "{METRIC_KEYS_PLACEHOLDER}" not in out


# --- prompt assembly ------------------------------------------------------


def test_build_user_prompt_includes_question_and_each_variant():
    prompt = _build_user_prompt(
        "Does X reduce Y?",
        "JUDGE PROMPT BODY",
        [_result("a", "answer a"), _result("b", "answer b")],
    )
    assert "JUDGE PROMPT BODY" in prompt
    assert "Does X reduce Y?" in prompt
    assert "[variant=a]" in prompt
    assert "answer a" in prompt
    assert "[variant=b]" in prompt
    assert "answer b" in prompt


def test_build_user_prompt_substitutes_empty_for_blank_answer():
    prompt = _build_user_prompt(
        "Q?", "JP", [_result("x", "")],
    )
    assert "(empty)" in prompt


# --- fence stripping ------------------------------------------------------


def test_strip_json_fences_removes_markdown_wrapper():
    raw = '```json\n{"scores": []}\n```'
    assert _strip_json_fences(raw) == '{"scores": []}'


def test_strip_json_fences_handles_unfenced_json():
    raw = '{"scores": []}'
    assert _strip_json_fences(raw) == '{"scores": []}'


def test_strip_json_fences_handles_bare_triple_backticks():
    raw = '```\n{"a": 1}\n```'
    assert _strip_json_fences(raw) == '{"a": 1}'


# --- _parse_judge_response ------------------------------------------------


def test_parse_judge_response_extracts_dict_scores():
    resp = json.dumps({
        "scores": [
            {"variant": "nous", "correctness": 9, "completeness": 8,
             "rationale": "thorough"},
            {"variant": "claude_plain", "correctness": 4, "completeness": 5,
             "rationale": "vague"},
        ]
    })
    scores = _parse_judge_response(
        resp,
        ["nous", "claude_plain"],
        ["correctness", "completeness"],
    )
    assert len(scores) == 2
    assert scores[0].variant == "nous"
    assert scores[0].scores == {"correctness": 9, "completeness": 8}
    assert scores[0].rationale == "thorough"
    assert scores[1].variant == "claude_plain"
    assert scores[1].scores == {"correctness": 4, "completeness": 5}


def test_parse_judge_response_extracts_extended_metrics():
    resp = json.dumps({
        "scores": [
            {"variant": "nous", "correctness": 9, "novelty": 9,
             "transferability": 8, "rationale": "deep"},
        ]
    })
    scores = _parse_judge_response(
        resp,
        ["nous"],
        ["correctness", "novelty", "transferability"],
    )
    assert scores[0].scores == {
        "correctness": 9, "novelty": 9, "transferability": 8,
    }


def test_parse_judge_response_handles_missing_variant():
    resp = json.dumps({"scores": [
        {"variant": "nous", "correctness": 9, "completeness": 8, "rationale": "ok"},
    ]})
    scores = _parse_judge_response(
        resp,
        ["nous", "claude_plain"],
        ["correctness", "completeness"],
    )
    assert len(scores) == 2
    assert scores[1].variant == "claude_plain"
    assert scores[1].scores == {"correctness": None, "completeness": None}
    assert "did not score" in scores[1].rationale


def test_parse_judge_response_coerces_invalid_score_to_none():
    resp = json.dumps({"scores": [
        {"variant": "x", "correctness": "high", "completeness": None,
         "rationale": "weird"},
    ]})
    scores = _parse_judge_response(resp, ["x"], ["correctness", "completeness"])
    assert scores[0].scores == {"correctness": None, "completeness": None}
    assert scores[0].rationale == "weird"


def test_parse_judge_response_handles_missing_metric_in_response():
    """Judge returned correctness but not novelty for this variant. Missing
    metric becomes None, others parse normally."""
    resp = json.dumps({"scores": [
        {"variant": "x", "correctness": 7, "rationale": "partial"},
    ]})
    scores = _parse_judge_response(resp, ["x"], ["correctness", "novelty"])
    assert scores[0].scores["correctness"] == 7
    assert scores[0].scores["novelty"] is None


def test_parse_judge_response_strips_fences_before_parsing():
    resp = '```json\n' + json.dumps({"scores": [
        {"variant": "x", "correctness": 7, "completeness": 6, "rationale": "ok"},
    ]}) + '\n```'
    scores = _parse_judge_response(resp, ["x"], ["correctness", "completeness"])
    assert scores[0].scores == {"correctness": 7, "completeness": 6}


# --- JudgeScore convenience accessors -------------------------------------


def test_judge_score_correctness_completeness_accessors():
    s = JudgeScore(
        variant="x",
        scores={"correctness": 9, "completeness": 7},
        rationale="ok",
    )
    assert s.correctness == 9
    assert s.completeness == 7


def test_judge_score_accessors_return_none_when_metric_absent():
    s = JudgeScore(variant="x", scores={"novelty": 9}, rationale="ok")
    assert s.correctness is None
    assert s.completeness is None


# --- run_judge end-to-end (no live claude) --------------------------------


def test_run_judge_returns_placeholder_scores_when_no_successful_variants():
    """All variants crashed → judge skipped, all scores are None."""
    crashed = [
        _result("a", "", crashed=True),
        _result("b", "", crashed=True),
    ]
    outcome = run_judge("Q?", crashed)
    assert outcome.error is not None
    assert "no successful variants" in outcome.error
    assert all(
        all(v is None for v in s.scores.values()) for s in outcome.scores
    )
    assert outcome.dollars == 0.0


def test_run_judge_metrics_field_propagates_to_outcome():
    """Even when crashed-only path is taken, JudgeOutcome.metrics reflects
    the resolved metric list so the renderer/runner know which columns
    would have been scored."""
    crashed = [_result("a", "", crashed=True)]
    outcome = run_judge("Q?", crashed, metrics=["correctness", "novelty"])
    assert outcome.metrics == ["correctness", "novelty"]


# --- artifacts ------------------------------------------------------------


def test_judge_prompt_file_exists_and_is_template():
    """The committed judge_prompt.md must ship and contain the template
    placeholders."""
    assert JUDGE_PROMPT_PATH.exists()
    text = JUDGE_PROMPT_PATH.read_text()
    assert "{RUBRIC_BLOCKS}" in text
    assert "{METRIC_KEYS_PLACEHOLDER}" in text
    assert len(text) > 200


def test_default_judge_model_is_opus_4_7():
    """Default judge is Opus 4.7 — Sonnet 4.6 was dropping variants from
    its scores array on multi-variant ablation runs (happened on graph-
    coloring L1). Opus is reliable for structured output across 4+
    variants. Override with --judge-model on cheap smoke runs."""
    assert DEFAULT_JUDGE_MODEL == "claude-opus-4-7"
