"""Tests for bench/variants/claude_methodology.py.

Live `claude --print` is exercised by the Phase 4 smoke run. Here we test
the variant class wiring at the seam: it should call invoke_claude with
the methodology body as system_prompt, and crash gracefully when
methodology.md is missing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.variants import claude_methodology as cm
from bench.variants._claude_common import ClaudeRunResult
from bench.variants.base import Budget, Campaign
from bench.variants.claude_methodology import ClaudeMethodologyVariant


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


def test_run_threads_methodology_into_system_prompt(monkeypatch, tmp_path):
    """The methodology.md content must be passed as system_prompt to invoke_claude."""
    captured: dict = {}

    def _fake_invoke(inv):
        captured["invocation"] = inv
        return ClaudeRunResult(
            final_answer="ok",
            tokens_in=10,
            tokens_out=5,
            dollars=0.1,
            wall_seconds=1.0,
            crashed=False,
            error=None,
            log_path=inv.log_path,
        )

    monkeypatch.setattr(cm, "invoke_claude", _fake_invoke)
    # Methodology file content for this test
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("METHODOLOGY_BODY_TEXT")
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", fake_methodology)

    variant = ClaudeMethodologyVariant()
    variant.run(_campaign(), tmp_path, _budget())

    inv = captured["invocation"]
    assert inv.system_prompt == "METHODOLOGY_BODY_TEXT"
    assert inv.question == "Does X reduce Y?"
    assert inv.workspace == tmp_path
    assert inv.log_path == tmp_path / ".bench-claude-methodology.log"


def test_run_returns_crashed_when_methodology_missing(monkeypatch, tmp_path):
    """If methodology.md doesn't exist, the variant fails fast with a clear
    error rather than calling claude with an empty system prompt."""
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", tmp_path / "nonexistent.md")

    variant = ClaudeMethodologyVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.crashed is True
    assert "methodology.md not found" in result.error
    # Doesn't call invoke_claude; no token spend
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.dollars == 0.0


def test_run_passes_through_invoke_claude_metrics(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cm, "METHODOLOGY_PATH", fake_methodology)

    def _fake_invoke(inv):
        return ClaudeRunResult(
            final_answer="found it",
            tokens_in=1234,
            tokens_out=567,
            dollars=2.5,
            wall_seconds=120.0,
            crashed=False,
            error=None,
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
            final_answer="",
            tokens_in=0,
            tokens_out=0,
            dollars=0.0,
            wall_seconds=0.5,
            crashed=True,
            error="claude exited with code 1: oops",
            log_path=inv.log_path,
        )

    monkeypatch.setattr(cm, "invoke_claude", _fake_invoke)

    variant = ClaudeMethodologyVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.crashed is True
    assert "claude exited with code 1" in result.error


def test_methodology_path_points_at_bench_methodology_dir():
    """Sanity check: the constant points at bench/methodology/methodology.md."""
    assert cm.METHODOLOGY_PATH.name == "methodology.md"
    assert cm.METHODOLOGY_PATH.parent.name == "methodology"
    # And the file actually exists in the repo (committed in Batch 1)
    assert cm.METHODOLOGY_PATH.exists(), (
        f"methodology.md not at {cm.METHODOLOGY_PATH} — Batch 1 should have created it"
    )
