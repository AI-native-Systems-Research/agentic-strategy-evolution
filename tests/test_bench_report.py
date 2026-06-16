"""Tests for bench/report.py — markdown report rendering."""
from __future__ import annotations

import json
from pathlib import Path

from bench.report import render


def _write_results(run_dir: Path, variants_data: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "experiment_id": "exp1",
        "campaign_id": "c1",
        "run_id": "2026-06-13_exp1",
        "research_question": "Does X reduce Y?",
        "started_at": "2026-06-13T00:00:00+00:00",
        "ended_at": "2026-06-13T00:30:00+00:00",
        "variants": variants_data,
    }
    (run_dir / "results.json").write_text(json.dumps(results))


def _ok_variant(name: str = "nous", **overrides) -> dict:
    base = {
        "variant": name,
        "campaign_id": "c1",
        "tokens_in": 1234,
        "tokens_out": 567,
        "dollars": 1.23,
        "wall_seconds": 120.5,
        "final_answer": "yes — TTFT decreases by ~30%",
        "artifacts_dir": "/path/art",
        "raw_log_path": "/path/log",
        "crashed": False,
        "hit_cap": False,
        "error": None,
    }
    base.update(overrides)
    return base


from pathlib import Path  # noqa: E402  (used by the judge helpers below)


def test_render_writes_report_with_summary_and_details(tmp_path):
    _write_results(tmp_path / "run", [_ok_variant()])
    out = render(tmp_path / "run")

    assert out.name == "report.md"
    text = out.read_text()
    assert "# exp1 — comparison report" in text
    assert "| nous |" in text
    assert "$1.23" in text
    assert "120.5" in text
    assert "Does X reduce Y?" in text
    assert "yes — TTFT decreases" in text


def test_render_marks_crashed_variant_in_status_column(tmp_path):
    _write_results(
        tmp_path / "run",
        [_ok_variant(crashed=True, error="nous CLI not found")],
    )
    text = render(tmp_path / "run").read_text()
    assert "crashed: nous CLI not found" in text


def test_render_marks_hit_cap_in_status_column(tmp_path):
    _write_results(tmp_path / "run", [_ok_variant(hit_cap=True)])
    text = render(tmp_path / "run").read_text()
    assert "hit_cap" in text


def test_render_handles_multiple_variants(tmp_path):
    _write_results(
        tmp_path / "run",
        [_ok_variant("nous"), _ok_variant("claude_plain")],
    )
    text = render(tmp_path / "run").read_text()
    assert "| nous |" in text
    assert "| claude_plain |" in text
    assert "### nous" in text
    assert "### claude_plain" in text


def test_render_handles_empty_final_answer(tmp_path):
    _write_results(tmp_path / "run", [_ok_variant(final_answer="")])
    text = render(tmp_path / "run").read_text()
    assert "(empty)" in text


def _write_results_with_judge(run_dir: Path, variants_data: list[dict], judge_usage: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "experiment_id": "exp1",
        "campaign_id": "c1",
        "run_id": "2026-06-14_exp1",
        "research_question": "Does X reduce Y?",
        "started_at": "2026-06-14T00:00:00+00:00",
        "ended_at": "2026-06-14T00:30:00+00:00",
        "variants": variants_data,
        "judge_usage": judge_usage,
    }
    (run_dir / "results.json").write_text(json.dumps(results))


def test_render_with_judge_scores_adds_columns_and_rationale(tmp_path):
    variants = [
        _ok_variant("nous", judge_correctness=9, judge_completeness=8,
                    judge_rationale="thorough; numbers cited"),
        _ok_variant("claude_plain", judge_correctness=4, judge_completeness=5,
                    judge_rationale="vague; no specific numbers"),
    ]
    _write_results_with_judge(
        tmp_path / "run", variants,
        {"tokens_in": 1000, "tokens_out": 200, "dollars": 0.05,
         "crashed": False, "error": None},
    )
    text = render(tmp_path / "run").read_text()

    # Header shows judge usage
    assert "Judge:" in text
    assert "$0.05" in text
    # Summary table has correctness + completeness columns
    assert "Correctness" in text
    assert "Completeness" in text
    assert "| 9 |" in text
    assert "| 4 |" in text
    # Rationale appears in per-variant section
    assert "thorough; numbers cited" in text
    assert "vague; no specific numbers" in text


def test_render_skips_judge_columns_when_no_scores(tmp_path):
    """skip_judge=True path: judge_usage absent → narrow table."""
    _write_results(tmp_path / "run", [_ok_variant()])
    text = render(tmp_path / "run").read_text()
    assert "Correctness" not in text
    assert "Completeness" not in text


def test_render_handles_judge_crash(tmp_path):
    variants = [_ok_variant()]
    _write_results_with_judge(
        tmp_path / "run", variants,
        {"tokens_in": 0, "tokens_out": 0, "dollars": 0.0,
         "crashed": True, "error": "judge timeout after 600s"},
    )
    text = render(tmp_path / "run").read_text()
    assert "Judge:" in text
    assert "crashed" in text
    assert "timeout" in text
    # Still no per-variant judge columns since no scores produced
    assert "Correctness" not in text


def test_render_handles_partial_judge_scores(tmp_path):
    """One variant scored, one crashed (None scores)."""
    variants = [
        _ok_variant("nous", judge_correctness=8, judge_completeness=7,
                    judge_rationale="solid"),
        _ok_variant("claude_plain", crashed=True, error="claude failed",
                    judge_correctness=None, judge_completeness=None,
                    judge_rationale="(crashed; not judged)"),
    ]
    _write_results_with_judge(
        tmp_path / "run", variants,
        {"tokens_in": 500, "tokens_out": 100, "dollars": 0.02,
         "crashed": False, "error": None},
    )
    text = render(tmp_path / "run").read_text()
    # Crashed variant gets — for both score columns
    assert "—" in text
    # Successful variant still shows numeric scores
    assert "| 8 |" in text
