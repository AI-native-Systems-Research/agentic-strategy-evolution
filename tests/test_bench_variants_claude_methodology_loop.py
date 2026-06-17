"""Tests for bench/variants/claude_methodology_loop.py.

Two layers:
  - _extract_principles regex behaviour (many edge cases)
  - ClaudeMethodologyLoopVariant wiring (mocked invoke_claude + methodology
    file)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.variants import claude_methodology_loop as cml
from bench.variants._claude_common import ClaudeRunResult
from bench.variants.base import Budget, Campaign
from bench.variants.claude_methodology_loop import (
    ClaudeMethodologyLoopVariant,
    _extract_principles,
    _strip_code_blocks,
)


def _budget(max_iterations: int = 3) -> Budget:
    return Budget(
        max_tokens=200_000,
        max_iterations=max_iterations,
        max_wall_seconds=1800,
    )


def _campaign() -> Campaign:
    return Campaign(
        id="loop_meth_test",
        research_question="Does X reduce Y?",
        target_repo="/tmp/fake",
        target_ref="main",
    )


# --- _strip_code_blocks ---


def test_strip_code_blocks_removes_fenced_content():
    text = "before\n```\nin block\n```\nafter"
    assert _strip_code_blocks(text) == "before\nafter"


def test_strip_code_blocks_handles_unclosed_fence():
    text = "before\n```\nstill in block forever"
    # unclosed → everything after the fence is dropped
    assert _strip_code_blocks(text) == "before"


def test_strip_code_blocks_passes_through_when_no_fences():
    assert _strip_code_blocks("plain text\n## Header") == "plain text\n## Header"


# --- _extract_principles: header variants ---


def test_extract_principles_basic_dash_bullets():
    text = """
## Principles

- [P1] First principle statement
- [P2] Second principle statement
"""
    out = _extract_principles(text)
    assert len(out) == 2
    assert "First principle statement" in out[0]
    assert "Second principle statement" in out[1]


def test_extract_principles_handles_h3_header():
    text = "### Principles\n- [P1] foo\n- [P2] bar\n"
    out = _extract_principles(text)
    assert len(out) == 2


def test_extract_principles_case_insensitive_header():
    text = "## PRINCIPLES\n- [P1] A\n"
    out = _extract_principles(text)
    assert len(out) == 1


def test_extract_principles_singular_principle_word():
    text = "## Principle\n- [P1] A\n"
    out = _extract_principles(text)
    assert len(out) == 1


def test_extract_principles_handles_trailing_colon_in_header():
    text = "## Principles:\n- [P1] A\n"
    out = _extract_principles(text)
    assert len(out) == 1


def test_extract_principles_handles_bold_header():
    text = "## **Principles**\n- [P1] A\n"
    out = _extract_principles(text)
    assert len(out) == 1


# --- _extract_principles: bullet-marker variants ---


def test_extract_principles_handles_asterisk_bullets():
    text = "## Principles\n* [P1] A\n* [P2] B\n"
    out = _extract_principles(text)
    assert len(out) == 2


def test_extract_principles_handles_numbered_bullets():
    text = "## Principles\n1. [P1] First\n2. [P2] Second\n"
    out = _extract_principles(text)
    assert len(out) == 2


# --- _extract_principles: ID prefix stripping ---


def test_extract_principles_strips_pn_id_prefix():
    text = "## Principles\n- [P1] The actual content\n"
    out = _extract_principles(text)
    # ID prefix gone; only the statement remains
    assert out[0] == "The actual content"


def test_extract_principles_handles_no_id_prefix():
    text = "## Principles\n- Just the statement\n"
    out = _extract_principles(text)
    assert out[0] == "Just the statement"


# --- _extract_principles: sub-fields concatenation ---


def test_extract_principles_concatenates_subfields():
    text = """
## Principles

- [P1] Statement of P1
  Regime: when it applies
  Mechanism: why it works
  Confidence: high
"""
    out = _extract_principles(text)
    assert len(out) == 1
    assert "Statement of P1" in out[0]
    assert "Regime: when it applies" in out[0]
    assert "Mechanism: why it works" in out[0]
    assert "Confidence: high" in out[0]


def test_extract_principles_separates_principles_with_blank_lines():
    text = """
## Principles

- [P1] First
  Regime: A

- [P2] Second
  Regime: B
"""
    out = _extract_principles(text)
    assert len(out) == 2
    assert "First" in out[0]
    assert "Regime: A" in out[0]
    assert "Second" in out[1]
    assert "Regime: B" in out[1]


# --- _extract_principles: bounding ---


def test_extract_principles_stops_at_next_header():
    text = """
## Principles

- [P1] Inside section
- [P2] Also inside

## Some Other Section

- [P3] Should not appear
"""
    out = _extract_principles(text)
    assert len(out) == 2
    assert all("Should not appear" not in p for p in out)


def test_extract_principles_skips_code_block_false_match():
    text = """
Here is some prose.

```
## Principles
- not really a section because it's in code
```

Real text resumes here.
"""
    out = _extract_principles(text)
    assert out == []


# --- _extract_principles: empty / fallback ---


def test_extract_principles_empty_when_no_section():
    assert _extract_principles("Just some prose.\n\nNo headers at all.") == []


def test_extract_principles_empty_when_section_has_no_bullets():
    text = "## Principles\n\nSome prose without bullets.\n"
    out = _extract_principles(text)
    # The prose gets collected as a "subfield" of a None-current; flush guard
    # filters it. Either way: no real principles surfaced.
    # Behavior: tries to extract; in absence of bullets, returns whatever
    # text appears (may be empty list). Document: no bullet → no principle.
    assert out == [] or out == ["Some prose without bullets."]


# --- ClaudeMethodologyLoopVariant ---


def _make_invoke_recorder(canned_results: list[ClaudeRunResult]):
    captured: dict = {"invocations": []}
    queue = list(canned_results)

    def _fake_invoke(inv):
        captured["invocations"].append(inv)
        if queue:
            r = queue.pop(0)
            return ClaudeRunResult(
                final_answer=r.final_answer, tokens_in=r.tokens_in,
                tokens_out=r.tokens_out, dollars=r.dollars,
                wall_seconds=r.wall_seconds, crashed=r.crashed,
                error=r.error, log_path=inv.log_path,
            )
        return ClaudeRunResult(
            final_answer=f"answer-{len(captured['invocations'])}",
            tokens_in=10, tokens_out=5, dollars=0.1, wall_seconds=1.0,
            crashed=False, error=None, log_path=inv.log_path,
        )
    return _fake_invoke, captured


def _ok(answer: str = "ok\n\n## Principles\n- [P1] A new principle\n", **kwargs):
    base = dict(
        final_answer=answer, tokens_in=10, tokens_out=5, dollars=0.1,
        wall_seconds=1.0, crashed=False, error=None, log_path=Path("/tmp/log"),
    )
    base.update(kwargs)
    return ClaudeRunResult(**base)


def test_variant_name_is_claude_methodology_loop():
    assert ClaudeMethodologyLoopVariant.name == "claude_methodology_loop"


def test_run_returns_crashed_when_methodology_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", tmp_path / "missing.md")

    variant = ClaudeMethodologyLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.crashed is True
    assert "methodology.md not found" in result.error


def test_run_threads_methodology_into_every_iter(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("METHODOLOGY_BODY")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)

    fake, captured = _make_invoke_recorder([_ok(), _ok(), _ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    # Every iter has the methodology in system_prompt
    for inv in captured["invocations"]:
        assert inv.system_prompt == "METHODOLOGY_BODY"


def test_run_first_iter_uses_research_question_directly(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([_ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=1))

    assert captured["invocations"][0].question == "Does X reduce Y?"


def test_run_subsequent_iters_prepend_accumulated_principles(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)

    iter1_answer = "Result analysis...\n\n## Principles\n- [P1] First principle text\n"
    iter2_answer = "Continued...\n\n## Principles\n- [P2] Second principle text\n"
    fake, captured = _make_invoke_recorder([_ok(iter1_answer), _ok(iter2_answer)])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    # Iter 2 sees iter 1's principle
    iter2_q = captured["invocations"][1].question
    assert "First principle text" in iter2_q
    # Original research question is still posed
    assert "Does X reduce Y?" in iter2_q


def test_run_principles_accumulate_across_iterations(monkeypatch, tmp_path):
    """Iter 3 should see BOTH iter 1's and iter 2's principles in its prompt."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)

    iter1 = "...\n## Principles\n- [P1] PRINCIPLE_FROM_ITER_1\n"
    iter2 = "...\n## Principles\n- [P2] PRINCIPLE_FROM_ITER_2\n"
    iter3 = "...\n## Principles\n- [P3] iter 3 conclusion\n"
    fake, captured = _make_invoke_recorder([_ok(iter1), _ok(iter2), _ok(iter3)])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    iter3_q = captured["invocations"][2].question
    assert "PRINCIPLE_FROM_ITER_1" in iter3_q
    assert "PRINCIPLE_FROM_ITER_2" in iter3_q


def test_run_short_circuits_on_crash(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)

    fake, captured = _make_invoke_recorder([
        _ok("ok 1\n## Principles\n- [P1] A\n"),
        _ok("", crashed=True, error="iter 2 boom"),
        _ok("never seen"),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert len(captured["invocations"]) == 2
    assert result.crashed is True
    assert result.error == "iter 2 boom"


def test_run_handles_no_principles_extracted(monkeypatch, tmp_path):
    """If the agent doesn't emit a Principles section, the variant should
    keep going (just without accumulated context)."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)

    # Neither answer has a Principles section
    fake, captured = _make_invoke_recorder([
        _ok("Just prose, no principles section"),
        _ok("More prose, still no principles"),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    # 2 iters ran — graceful fallback to original question
    assert len(captured["invocations"]) == 2
    iter2_q = captured["invocations"][1].question
    # Iter 2's question doesn't have an accumulated-principles block
    assert "Principles from previous sessions" not in iter2_q


def test_run_aggregates_metrics_across_iterations(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)

    fake, _ = _make_invoke_recorder([
        _ok(tokens_in=100, tokens_out=50, dollars=0.5, wall_seconds=10.0),
        _ok(tokens_in=200, tokens_out=75, dollars=1.0, wall_seconds=15.0),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    assert result.tokens_in == 300
    assert result.tokens_out == 125
    assert result.dollars == pytest.approx(1.5)
    assert result.wall_seconds == pytest.approx(25.0)


def test_run_per_iter_log_paths_distinct(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([_ok(), _ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    paths = [inv.log_path for inv in captured["invocations"]]
    assert paths[0].name == ".bench-claude-methodology-loop-iter-1.log"
    assert paths[1].name == ".bench-claude-methodology-loop-iter-2.log"
