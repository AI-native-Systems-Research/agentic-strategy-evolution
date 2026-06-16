"""Tests for bench/judge.py — Claude-as-judge.

Live `claude` invocation is exercised by the Phase 2.6 smoke test. Here we
test the pure helpers: prompt assembly, response parsing, fence stripping,
and the high-level run_judge() with crashed/empty inputs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.judge import (
    DEFAULT_JUDGE_MODEL,
    JUDGE_PROMPT_PATH,
    JudgeOutcome,
    JudgeScore,
    _build_user_prompt,
    _parse_judge_response,
    _strip_json_fences,
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


# --- prompt assembly ---


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


# --- fence stripping ---


def test_strip_json_fences_removes_markdown_wrapper():
    raw = '```json\n{"scores": []}\n```'
    assert _strip_json_fences(raw) == '{"scores": []}'


def test_strip_json_fences_handles_unfenced_json():
    raw = '{"scores": []}'
    assert _strip_json_fences(raw) == '{"scores": []}'


def test_strip_json_fences_handles_bare_triple_backticks():
    raw = '```\n{"a": 1}\n```'
    assert _strip_json_fences(raw) == '{"a": 1}'


# --- response parsing ---


def test_parse_judge_response_extracts_scores():
    resp = json.dumps({
        "scores": [
            {"variant": "nous", "correctness": 9, "completeness": 8,
             "rationale": "thorough"},
            {"variant": "claude_plain", "correctness": 4, "completeness": 5,
             "rationale": "vague"},
        ]
    })
    scores = _parse_judge_response(resp, ["nous", "claude_plain"])
    assert len(scores) == 2
    assert scores[0].variant == "nous"
    assert scores[0].correctness == 9
    assert scores[0].completeness == 8
    assert scores[0].rationale == "thorough"
    assert scores[1].variant == "claude_plain"
    assert scores[1].correctness == 4


def test_parse_judge_response_handles_missing_variant():
    resp = json.dumps({"scores": [
        {"variant": "nous", "correctness": 9, "completeness": 8, "rationale": "ok"},
    ]})
    scores = _parse_judge_response(resp, ["nous", "claude_plain"])
    assert len(scores) == 2
    assert scores[1].variant == "claude_plain"
    assert scores[1].correctness is None
    assert scores[1].completeness is None
    assert "did not score" in scores[1].rationale


def test_parse_judge_response_coerces_invalid_score_to_none():
    resp = json.dumps({"scores": [
        {"variant": "x", "correctness": "high", "completeness": None,
         "rationale": "weird"},
    ]})
    scores = _parse_judge_response(resp, ["x"])
    assert scores[0].correctness is None
    assert scores[0].completeness is None
    assert scores[0].rationale == "weird"


def test_parse_judge_response_strips_fences_before_parsing():
    resp = '```json\n' + json.dumps({"scores": [
        {"variant": "x", "correctness": 7, "completeness": 6, "rationale": "ok"},
    ]}) + '\n```'
    scores = _parse_judge_response(resp, ["x"])
    assert scores[0].correctness == 7


# --- run_judge end-to-end (no live claude) ---


def test_run_judge_returns_placeholder_scores_when_no_successful_variants():
    """All variants crashed → judge skipped, all scores are None."""
    crashed = [
        _result("a", "", crashed=True),
        _result("b", "", crashed=True),
    ]
    outcome = run_judge("Q?", crashed)
    assert outcome.error is not None
    assert "no successful variants" in outcome.error
    assert all(s.correctness is None for s in outcome.scores)
    assert all(s.completeness is None for s in outcome.scores)
    assert outcome.dollars == 0.0


# --- artifacts ---


def test_judge_prompt_file_exists_and_is_nontrivial():
    """The committed judge_prompt.md must ship with the package."""
    assert JUDGE_PROMPT_PATH.exists()
    text = JUDGE_PROMPT_PATH.read_text()
    assert "correctness" in text
    assert "completeness" in text
    assert len(text) > 200


def test_default_judge_model_is_sonnet_4_6():
    assert DEFAULT_JUDGE_MODEL == "claude-sonnet-4-6"
