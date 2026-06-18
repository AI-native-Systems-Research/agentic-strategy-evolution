"""Tests for bench/variants/claude_plain.py — variant class + L0 prompt.

JSON parsing is tested in test_bench_metrics.py (LLMMeter and parse_claude_json).
Live `claude --print` subprocess invocation is exercised by paid runs,
not here.
"""
from __future__ import annotations

from bench.variants.claude_plain import (
    DEFAULT_MODEL,
    ClaudePlainVariant,
    _build_l0_prompt,
)


def test_variant_name_is_claude_plain():
    assert ClaudePlainVariant.name == "claude_plain"


def test_default_model_is_sonnet_4_6():
    assert DEFAULT_MODEL == "claude-sonnet-4-6"


def test_l0_prompt_contains_research_question():
    prompt = _build_l0_prompt("Does X reduce Y under load?")
    assert "Does X reduce Y under load?" in prompt


def test_l0_prompt_appends_investigation_instruction():
    """L0 closing line tells Claude to investigate and report."""
    prompt = _build_l0_prompt("Some research question.")
    assert "Investigate this and report your findings." in prompt


def test_l0_prompt_does_not_contain_methodology():
    """L0 must not include scientific guidance — that's L1's job."""
    prompt = _build_l0_prompt("RQ?")
    assert "Form hypotheses" not in prompt
    assert "Approach this systematically" not in prompt


def test_l0_prompt_does_not_contain_iteration_framing():
    """L0 is a single session — no 'iteration N of M' framing."""
    prompt = _build_l0_prompt("RQ?")
    assert "iteration" not in prompt.lower()
