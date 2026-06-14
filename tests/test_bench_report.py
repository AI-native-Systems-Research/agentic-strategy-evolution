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
