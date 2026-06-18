"""Tests for bench/variants/claude_methodology.py.

L1 inlines methodology in the user prompt — no system_prompt usage.
Live `claude --print` is exercised by paid runs; here we test the prompt
shape and the crash-on-missing-methodology fallback.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.variants import claude_methodology as cm
from bench.variants._claude_common import ClaudeRunResult
from bench.variants.base import Budget, Campaign
from bench.variants.claude_methodology import (
    ClaudeMethodologyVariant,
    _build_l1_prompt,
)


def _budget() -> Budget:
    return Budget(max_tokens=200_000, max_iterations=1, max_wall_seconds=1800)


def _campaign() -> Campaign:
    return Campaign(
        id="test_campaign",
        research_question="Does X reduce Y?",
        target_repo="/tmp/fake",
        target_ref="main",
    )


def test_variant_name_is_claude_methodology():
    assert ClaudeMethodologyVariant.name == "claude_methodology"


# --- _build_l1_prompt ---


def test_l1_prompt_includes_research_question_and_methodology():
    prompt = _build_l1_prompt(
        "Does X reduce Y?",
        "Approach this systematically:\n- Form hypotheses\n- Run experiments",
    )
    assert "Does X reduce Y?" in prompt
    assert "Form hypotheses" in prompt
    assert "Run experiments" in prompt


def test_l1_prompt_ends_with_report_findings_instruction():
    prompt = _build_l1_prompt("RQ?", "methodology body")
    assert prompt.endswith("Report your findings with the evidence that supports them.")


def test_l1_prompt_strips_trailing_whitespace_from_methodology():
    """methodology.md tends to have a trailing newline; the closing line
    should still be cleanly attached without doubled blank lines."""
    prompt = _build_l1_prompt("RQ?", "methodology body\n\n\n")
    # Methodology body shows up; no triple-blank-line gap before the closing
    assert "methodology body\n\nReport your findings" in prompt


def test_l1_prompt_does_not_contain_iteration_framing():
    """L1 is a single session — no 'iteration N of M' framing."""
    prompt = _build_l1_prompt("RQ?", "methodology body")
    assert "iteration" not in prompt.lower()


# --- run() wiring ---


def test_run_does_not_use_system_prompt(monkeypatch, tmp_path):
    """Methodology lives in the user prompt now; system_prompt is unused."""
    captured: dict = {}

    def _fake_invoke(inv):
        captured["invocation"] = inv
        return ClaudeRunResult(
            final_answer="ok", tokens_in=10, tokens_out=5, dollars=0.1,
            wall_seconds=1.0, crashed=False, error=None, log_path=inv.log_path,
        )

    monkeypatch.setattr(cm, "invoke_claude", _fake_invoke)
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("METHODOLOGY_BODY")
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", fake_methodology)

    variant = ClaudeMethodologyVariant()
    variant.run(_campaign(), tmp_path, _budget())

    inv = captured["invocation"]
    assert inv.system_prompt is None
    # And the methodology body is in the user prompt
    assert "METHODOLOGY_BODY" in inv.question
    assert "Does X reduce Y?" in inv.question


def test_run_returns_crashed_when_methodology_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", tmp_path / "nonexistent.md")

    variant = ClaudeMethodologyVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.crashed is True
    assert "methodology.md not found" in result.error
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.dollars == 0.0


def test_run_passes_through_invoke_claude_metrics(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", fake_methodology)

    def _fake_invoke(inv):
        return ClaudeRunResult(
            final_answer="found it", tokens_in=1234, tokens_out=567,
            dollars=2.5, wall_seconds=120.0, crashed=False, error=None,
            log_path=inv.log_path,
        )

    monkeypatch.setattr(cm, "invoke_claude", _fake_invoke)

    variant = ClaudeMethodologyVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.variant == "claude_methodology"
    assert result.campaign_id == "test_campaign"
    assert result.tokens_in == 1234
    assert result.tokens_out == 567
    assert result.dollars == 2.5
    assert result.final_answer == "found it"
    assert result.crashed is False


def test_run_propagates_invoke_claude_crash(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", fake_methodology)

    def _fake_invoke(inv):
        return ClaudeRunResult(
            final_answer="", tokens_in=0, tokens_out=0, dollars=0.0,
            wall_seconds=0.5, crashed=True,
            error="claude exited with code 1: oops",
            log_path=inv.log_path,
        )

    monkeypatch.setattr(cm, "invoke_claude", _fake_invoke)

    variant = ClaudeMethodologyVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.crashed is True
    assert "claude exited with code 1" in result.error


def test_methodology_path_points_at_bench_methodology_dir():
    """Sanity check: the constant points at bench/methodology/methodology.md
    and the file actually ships."""
    assert cm.METHODOLOGY_PATH.name == "methodology.md"
    assert cm.METHODOLOGY_PATH.parent.name == "methodology"
    assert cm.METHODOLOGY_PATH.exists()


def test_committed_methodology_md_is_just_scientific_bullets():
    """The shipped methodology.md (L1 form) must contain the four
    scientific bullets we expect."""
    body = cm.METHODOLOGY_PATH.read_text()
    assert "Form hypotheses" in body
    assert "Run controlled experiments" in body
    assert "When your prediction is wrong" in body
    assert "Track what you learn" in body
    # No leftover placeholders or iteration-specific instructions
    assert "[Problem description]" not in body
    assert "Key takeaways" not in body


def test_l1_methodology_does_not_include_build_on_prior_findings_clause():
    """The 'Build on prior findings rather than starting from scratch each
    time' clause is L2-only — it lives in methodology_loop.md, not here.
    L1 is a single session; that clause would be off-message."""
    body = cm.METHODOLOGY_PATH.read_text()
    assert "Build on prior findings" not in body
