"""Tests for bench/variants/claude_methodology_loop.py.

L2 is N sequential methodology sessions with full-prior-output carry-forward.
No takeaway extraction, no fallback logic — just paste prior iters' output
verbatim into the next iter's prompt.

Two layers:
  - prompt-builder behaviour (_build_iter_1_prompt, _build_iter_n_prompt)
  - ClaudeMethodologyLoopVariant.run() wiring (mocked invoke_claude)

No live LLM calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.variants import claude_methodology_loop as cml
from bench.variants._claude_common import ClaudeRunResult
from bench.variants.base import Budget, Campaign
from bench.variants.claude_methodology_loop import (
    ClaudeMethodologyLoopVariant,
    _build_iter_1_prompt,
    _build_iter_n_prompt,
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


# --- _build_iter_1_prompt -------------------------------------------------


def test_iter_1_prompt_includes_research_question_and_methodology():
    p = _build_iter_1_prompt("Does X reduce Y?", "methodology body", total_iters=5)
    assert "Does X reduce Y?" in p
    assert "methodology body" in p


def test_iter_1_prompt_includes_iteration_framing():
    p = _build_iter_1_prompt("RQ?", "method", total_iters=5)
    assert "iteration 1 of 5" in p


def test_iter_1_prompt_asks_what_to_investigate_next():
    p = _build_iter_1_prompt("RQ?", "method", total_iters=3)
    assert "Report your findings and what you would investigate next." in p


def test_iter_1_prompt_does_not_include_prior_findings_block():
    """Iter 1 has no prior findings; the 'Prior findings' marker is
    a K>1 thing only."""
    p = _build_iter_1_prompt("RQ?", "method", total_iters=3)
    assert "Prior findings" not in p


# --- _build_iter_n_prompt -------------------------------------------------


def test_iter_n_prompt_includes_research_question_and_methodology():
    p = _build_iter_n_prompt(
        "Does X reduce Y?", "methodology body",
        current_iter=2, total_iters=5,
        prior_outputs=["iter 1 output"],
    )
    assert "Does X reduce Y?" in p
    assert "methodology body" in p


def test_iter_n_prompt_includes_current_and_total_iter_count():
    p = _build_iter_n_prompt(
        "RQ?", "method", current_iter=3, total_iters=5,
        prior_outputs=["a", "b"],
    )
    assert "iteration 3 of 5" in p


def test_iter_n_prompt_pastes_all_prior_outputs_in_order():
    """Per spec: '[Paste: full output from all prior iterations, as-is,
    unstructured]'. We verify all are present, in order."""
    p = _build_iter_n_prompt(
        "RQ?", "method", current_iter=4, total_iters=5,
        prior_outputs=[
            "ITER_1_FINDINGS_TEXT",
            "ITER_2_FINDINGS_TEXT",
            "ITER_3_FINDINGS_TEXT",
        ],
    )
    pos_1 = p.find("ITER_1_FINDINGS_TEXT")
    pos_2 = p.find("ITER_2_FINDINGS_TEXT")
    pos_3 = p.find("ITER_3_FINDINGS_TEXT")
    assert pos_1 != -1 and pos_2 != -1 and pos_3 != -1
    assert pos_1 < pos_2 < pos_3


def test_iter_n_prompt_brackets_prior_findings_with_marker():
    """Per spec: '--- Prior findings ---' header + '---' footer around
    the prior-output block, so the agent sees a clear demarcation."""
    p = _build_iter_n_prompt(
        "RQ?", "method", current_iter=2, total_iters=5,
        prior_outputs=["something"],
    )
    assert "--- Prior findings ---" in p
    # Footer marker present
    assert "---" in p.split("--- Prior findings ---", 1)[1]


def test_iter_n_prompt_labels_each_prior_iteration():
    """Each prior output gets an '### Iteration K' header so the agent
    knows which iter said what."""
    p = _build_iter_n_prompt(
        "RQ?", "method", current_iter=3, total_iters=5,
        prior_outputs=["one", "two"],
    )
    assert "### Iteration 1" in p
    assert "### Iteration 2" in p


def test_iter_n_prompt_closing_asks_to_continue_and_report():
    """Per spec: 'Continue your investigation. Build on what you found
    before. Report your findings and what you would investigate next.'"""
    p = _build_iter_n_prompt(
        "RQ?", "method", current_iter=2, total_iters=3,
        prior_outputs=["x"],
    )
    assert "Continue your investigation" in p
    assert "Report your findings and what you would investigate next." in p


# --- run() wiring ---------------------------------------------------------


def _make_invoke_recorder(canned_results: list[ClaudeRunResult]):
    captured: dict = {"invocations": []}
    queue = list(canned_results)

    def _fake_invoke(inv):
        captured["invocations"].append(inv)
        if queue:
            r = queue.pop(0)
            return ClaudeRunResult(
                final_answer=r.final_answer,
                tokens_in=r.tokens_in, tokens_out=r.tokens_out,
                dollars=r.dollars, wall_seconds=r.wall_seconds,
                crashed=r.crashed, error=r.error, log_path=inv.log_path,
            )
        return ClaudeRunResult(
            final_answer=f"answer-{len(captured['invocations'])}",
            tokens_in=10, tokens_out=5, dollars=0.1, wall_seconds=1.0,
            crashed=False, error=None, log_path=inv.log_path,
        )
    return _fake_invoke, captured


def _ok(answer: str = "ok", **kwargs):
    base = dict(
        final_answer=answer, tokens_in=10, tokens_out=5, dollars=0.1,
        wall_seconds=1.0, crashed=False, error=None, log_path=Path("/tmp/log"),
    )
    base.update(kwargs)
    return ClaudeRunResult(**base)


def test_variant_name_is_claude_methodology_loop():
    assert ClaudeMethodologyLoopVariant.name == "claude_methodology_loop"


def test_l2_methodology_path_points_at_methodology_loop_md():
    """L2 reads from methodology_loop.md — a separate file from L1's
    methodology.md. The L2 file has the 'Build on prior findings' clause
    on bullet 4; the L1 file does not."""
    assert cml.METHODOLOGY_LOOP_PATH.name == "methodology_loop.md"
    assert cml.METHODOLOGY_LOOP_PATH.parent.name == "methodology"
    assert cml.METHODOLOGY_LOOP_PATH.exists()


def test_committed_methodology_loop_md_contains_build_on_prior_findings():
    """The shipped methodology_loop.md must include the cross-iteration
    clause that distinguishes it from methodology.md (L1)."""
    body = cml.METHODOLOGY_LOOP_PATH.read_text()
    assert "Form hypotheses" in body
    assert "Track what you learn" in body
    # The L2-only clause:
    assert "Build on prior findings" in body
    # No leftover placeholders or iteration instructions:
    assert "[Problem description]" not in body
    assert "Key takeaways" not in body


def test_run_returns_crashed_when_methodology_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", tmp_path / "missing.md")

    variant = ClaudeMethodologyLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget())

    assert result.crashed is True
    assert "methodology_loop.md not found" in result.error


def test_run_does_not_use_system_prompt(monkeypatch, tmp_path):
    """L2 inlines methodology in the user prompt; no system_prompt usage."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("METHODOLOGY_BODY")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([_ok(), _ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    for inv in captured["invocations"]:
        assert inv.system_prompt is None
        assert "METHODOLOGY_BODY" in inv.question


def test_run_iter_1_uses_iter_1_prompt_shape(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([_ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    iter1_q = captured["invocations"][0].question
    assert "iteration 1 of 3" in iter1_q
    # Iter 1 must NOT contain the 'Prior findings' block
    assert "Prior findings" not in iter1_q


def test_run_iter_2_pastes_iter_1_full_output(monkeypatch, tmp_path):
    """The full text of iter-1's answer must show up verbatim in iter-2's
    prompt, no extraction or summarization."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)

    iter1_answer = (
        "Long iter-1 prose with details about hypotheses tested, "
        "experiments run, and results observed. UNIQUE_ITER_1_MARKER."
    )
    fake, captured = _make_invoke_recorder([
        _ok(iter1_answer),
        _ok("iter 2 result"),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    iter2_q = captured["invocations"][1].question
    # Full prior output verbatim — no extraction
    assert "UNIQUE_ITER_1_MARKER" in iter2_q
    assert "Long iter-1 prose with details" in iter2_q
    # Iter 2 framing
    assert "iteration 2 of 2" in iter2_q
    assert "--- Prior findings ---" in iter2_q


def test_run_iter_3_pastes_both_iter_1_and_iter_2_full_outputs(monkeypatch, tmp_path):
    """All prior iters' outputs accumulate, in order."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)

    fake, captured = _make_invoke_recorder([
        _ok("UNIQUE_ITER_1"),
        _ok("UNIQUE_ITER_2"),
        _ok("iter 3 result"),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    iter3_q = captured["invocations"][2].question
    pos_1 = iter3_q.find("UNIQUE_ITER_1")
    pos_2 = iter3_q.find("UNIQUE_ITER_2")
    assert pos_1 != -1
    assert pos_2 != -1
    assert pos_1 < pos_2  # iter 1 before iter 2
    assert "iteration 3 of 3" in iter3_q


def test_run_short_circuits_on_crash(monkeypatch, tmp_path):
    """If iter 2 crashes, iter 3 should NOT run."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)

    fake, captured = _make_invoke_recorder([
        _ok("ok 1"),
        _ok("", crashed=True, error="iter 2 boom"),
        _ok("never seen"),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=3))

    assert len(captured["invocations"]) == 2
    assert result.crashed is True
    assert result.error == "iter 2 boom"


def test_run_crashed_iter_does_not_get_added_to_prior_outputs(monkeypatch, tmp_path):
    """If iter 2 crashes, its (empty) output must NOT be in iter 3's prompt
    — but iter 3 doesn't run anyway because of short-circuit. This test
    verifies the contract: only successful iters' answers are accumulated."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)

    fake, captured = _make_invoke_recorder([
        _ok("ok 1"),
        _ok("", crashed=True, error="iter 2 crashed"),
    ])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    # Only 2 invocations happened; the second crashed. Confirm short-circuit.
    assert len(captured["invocations"]) == 2


def test_run_aggregates_metrics_across_iterations(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)

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


def test_max_iterations_zero_makes_no_calls(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    result = variant.run(_campaign(), tmp_path, _budget(max_iterations=0))

    assert len(captured["invocations"]) == 0
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.crashed is False
    assert result.final_answer == ""


def test_run_per_iter_log_paths_distinct(monkeypatch, tmp_path):
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([_ok(), _ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=2))

    paths = [inv.log_path for inv in captured["invocations"]]
    assert paths[0].name == ".bench-claude-methodology-loop-iter-1.log"
    assert paths[1].name == ".bench-claude-methodology-loop-iter-2.log"


def test_run_first_iter_total_iters_matches_budget(monkeypatch, tmp_path):
    """When budget says max_iterations=7, iter-1 prompt should say
    'iteration 1 of 7'."""
    fake_methodology = tmp_path / "methodology.md"
    fake_methodology.write_text("body")
    monkeypatch.setattr(cml, "METHODOLOGY_LOOP_PATH", fake_methodology)
    fake, captured = _make_invoke_recorder([_ok()])
    monkeypatch.setattr(cml, "invoke_claude", fake)

    variant = ClaudeMethodologyLoopVariant()
    variant.run(_campaign(), tmp_path, _budget(max_iterations=7))

    assert "iteration 1 of 7" in captured["invocations"][0].question
