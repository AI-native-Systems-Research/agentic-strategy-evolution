"""Tests for bench/variants/claude_loop.py.

Live `claude --print` is exercised by the Phase 4 smoke run. Here we test
the loop logic at the seam: invoke_claude is mocked; we verify call count,
question-prepending, short-circuit on crash, and metric aggregation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.variants import claude_loop as cl
from bench.variants._claude_common import ClaudeRunResult
from bench.variants.base import Budget, Campaign
from bench.variants.claude_loop import ClaudeLoopVariant


def _budget(max_iterations: int = 3) -> Budget:
    return Budget(
        max_tokens=200_000,
        max_iterations=max_iterations,
        max_wall_seconds=1800,
    )


def _campaign() -> Campaign:
    return Campaign(
        id="loop_test",
        research_question="Does X reduce Y?",
        target_repo="/tmp/fake",
        target_ref="main",
    )


def _make_invoke_recorder(canned_results: list[ClaudeRunResult]):
    """Returns (fake_invoke, captured) where captured['invocations'] grows
    on each call and fake_invoke pops a canned result."""
    captured: dict = {"invocations": []}
    queue = list(canned_results)

    def _fake_invoke(inv):
        captured["invocations"].append(inv)
        if queue:
            r = queue.pop(0)
            # Override log_path with what the variant passed in
            return ClaudeRunResult(
                final_answer=r.final_answer,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                dollars=r.dollars,
                wall_seconds=r.wall_seconds,
                crashed=r.crashed,
                error=r.error,
                log_path=inv.log_path,
            )
        # Default: succeed
        return ClaudeRunResult(
            final_answer=f"answer-{len(captured['invocations'])}",
            tokens_in=10,
            tokens_out=5,
            dollars=0.1,
            wall_seconds=1.0,
            crashed=False,
            error=None,
            log_path=inv.log_path,
        )
    return _fake_invoke, captured


def _ok(answer: str = "ok", **kwargs) -> ClaudeRunResult:
    base = dict(
        final_answer=answer, tokens_in=10, tokens_out=5, dollars=0.1,
        wall_seconds=1.0, crashed=False, error=None, log_path=Path("/tmp/log"),
    )
    base.update(kwargs)
    return ClaudeRunResult(**base)


def test_variant_name_is_claude_loop():
    assert ClaudeLoopVariant.name == "claude_loop"


def test_runs_max_iterations_when_no_crash(monkeypatch, tmp_path):
    fake, captured = _make_invoke_recorder([
        _ok("answer 1"), _ok("answer 2"), _ok("answer 3"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert len(captured["invocations"]) == 3


def test_short_circuits_on_crash(monkeypatch, tmp_path):
    """If iter 2 crashes, iter 3 should NOT run."""
    fake, captured = _make_invoke_recorder([
        _ok("ok 1"),
        _ok("", crashed=True, error="iter 2 boom"),
        _ok("never seen"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert len(captured["invocations"]) == 2
    assert result.crashed is True
    assert result.error == "iter 2 boom"


def test_first_iter_uses_research_question_directly(monkeypatch, tmp_path):
    fake, captured = _make_invoke_recorder([_ok("ok 1")])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=1))

    first = captured["invocations"][0]
    assert first.question == "Does X reduce Y?"


def test_subsequent_iters_prepend_previous_answer(monkeypatch, tmp_path):
    fake, captured = _make_invoke_recorder([
        _ok("first answer text"),
        _ok("second answer text"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    second = captured["invocations"][1]
    # Previous answer is in the prepended context
    assert "first answer text" in second.question
    # Original question is still present
    assert "Does X reduce Y?" in second.question
    # Continuation cue
    assert "Continue refining" in second.question


def test_third_iter_prepends_only_previous_answer_not_all_history(monkeypatch, tmp_path):
    """The carry-forward is only the IMMEDIATELY PREVIOUS answer, not the
    accumulated history. claude_loop has no methodology / no principles —
    it's a 'last answer' chain."""
    fake, captured = _make_invoke_recorder([
        _ok("answer 1 unique"),
        _ok("answer 2 unique"),
        _ok("answer 3"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    third = captured["invocations"][2]
    # Iter 3 sees iter 2's answer
    assert "answer 2 unique" in third.question
    # Iter 3 does NOT see iter 1's answer in the prepended block
    assert "answer 1 unique" not in third.question


def test_aggregates_metrics_across_iterations(monkeypatch, tmp_path):
    fake, _ = _make_invoke_recorder([
        _ok(tokens_in=100, tokens_out=50, dollars=0.5, wall_seconds=10.0),
        _ok(tokens_in=200, tokens_out=75, dollars=1.0, wall_seconds=15.0),
        _ok(tokens_in=150, tokens_out=60, dollars=0.75, wall_seconds=12.0),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert result.tokens_in == 450
    assert result.tokens_out == 185
    assert result.dollars == pytest.approx(2.25)
    assert result.wall_seconds == pytest.approx(37.0)


def test_max_iterations_one_behaves_like_single_call(monkeypatch, tmp_path):
    fake, captured = _make_invoke_recorder([_ok("only answer")])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=1))

    assert len(captured["invocations"]) == 1
    assert result.final_answer == "only answer"


def test_per_iter_log_paths_are_distinct(monkeypatch, tmp_path):
    fake, captured = _make_invoke_recorder([_ok(), _ok(), _ok()])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    paths = [inv.log_path for inv in captured["invocations"]]
    assert paths[0].name == ".bench-claude-loop-iter-1.log"
    assert paths[1].name == ".bench-claude-loop-iter-2.log"
    assert paths[2].name == ".bench-claude-loop-iter-3.log"


def test_final_answer_is_last_non_crashed(monkeypatch, tmp_path):
    fake, _ = _make_invoke_recorder([
        _ok("first"),
        _ok("second"),
        _ok("third"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert result.final_answer == "third"


def test_final_answer_after_partial_crash(monkeypatch, tmp_path):
    """If iter 2 crashes after iter 1 succeeded, final_answer = iter 1's."""
    fake, _ = _make_invoke_recorder([
        _ok("first answer"),
        _ok("", crashed=True, error="boom"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert result.final_answer == "first answer"
    assert result.crashed is True


def test_short_circuits_when_first_iter_crashes(monkeypatch, tmp_path):
    """If iter 1 itself crashes, the loop runs exactly one iter — no
    iter-2 attempt despite max_iterations=3."""
    fake, captured = _make_invoke_recorder([
        _ok("", crashed=True, error="iter 1 boom"),
    ])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert len(captured["invocations"]) == 1
    assert result.crashed is True
    assert result.error == "iter 1 boom"
    assert result.final_answer == ""  # all (one) runs crashed → empty


def test_max_iterations_zero_makes_no_calls(monkeypatch, tmp_path):
    """Degenerate input: max_iterations=0 should produce a clean
    no-op result — no invoke_claude calls, no crash."""
    fake, captured = _make_invoke_recorder([])
    monkeypatch.setattr(cl, "invoke_claude", fake)

    variant = ClaudeLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=0))

    assert len(captured["invocations"]) == 0
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.crashed is False
    assert result.final_answer == ""
