"""Tests for bench/variants/nous.py — yaml translation and metric harvesting.

These tests cover the pure helpers in isolation; the live `nous run`
subprocess is exercised by the Phase 1.7 smoke test, not here.
"""
from __future__ import annotations

import json

import pytest

from bench.variants.base import Campaign
from bench.variants.nous import (
    DEFAULT_MODEL,
    NousVariant,
    _harvest_metrics,
    _read_final_answer,
    _translate_to_nous_yaml,
)


def _campaign() -> Campaign:
    return Campaign(
        id="test_campaign",
        research_question="Does X reduce Y under load?",
        target_repo="/tmp/fake_target",
        target_ref="main",
    )


def test_translate_produces_nested_target_system(tmp_path):
    workspace = tmp_path / "ws"
    out = _translate_to_nous_yaml(_campaign(), workspace, max_iterations=3)

    assert out["research_question"] == "Does X reduce Y under load?"
    assert out["run_id"] == "test_campaign"
    assert out["max_iterations"] == 3
    assert out["target_system"]["repo_path"] == str(workspace)
    assert out["target_system"]["name"]
    assert out["target_system"]["description"]
    assert out["prompts"]["methodology_layer"] == "prompts/methodology"
    assert out["prompts"]["domain_adapter_layer"] is None


def test_translate_uses_default_sonnet_model_for_all_phases(tmp_path):
    out = _translate_to_nous_yaml(_campaign(), tmp_path, max_iterations=1)
    for phase in ("design", "execute_analyze", "report"):
        assert out["models"][phase] == DEFAULT_MODEL


def test_translate_respects_custom_model(tmp_path):
    out = _translate_to_nous_yaml(
        _campaign(), tmp_path, max_iterations=1, model="claude-opus-4-7"
    )
    assert all(v == "claude-opus-4-7" for v in out["models"].values())


def test_harvest_metrics_returns_zeros_when_file_missing(tmp_path):
    tokens_in, tokens_out, dollars = _harvest_metrics(tmp_path / "missing.jsonl")
    assert (tokens_in, tokens_out, dollars) == (0, 0, 0.0)


def test_harvest_metrics_counts_billable_input_only(tmp_path):
    """tokens_in counts input_tokens only; cache fields are reflected in
    cost_usd and counting them would inflate cache-heavy variants unfairly."""
    path = tmp_path / "metrics.jsonl"
    rows = [
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.5,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        {
            "input_tokens": 200,
            "output_tokens": 75,
            "cost_usd": 1.0,
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 5000,
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    tokens_in, tokens_out, dollars = _harvest_metrics(path)

    assert tokens_in == 100 + 200
    assert tokens_out == 50 + 75
    assert dollars == pytest.approx(1.5)


def test_harvest_metrics_skips_blank_lines(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text(
        json.dumps({"input_tokens": 5, "output_tokens": 3, "cost_usd": 0.1})
        + "\n\n   \n"
    )
    tokens_in, tokens_out, dollars = _harvest_metrics(path)
    assert (tokens_in, tokens_out) == (5, 3)
    assert dollars == pytest.approx(0.1)


def test_read_final_answer_picks_latest_iter(tmp_path):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-2").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"conclusion": "early conclusion"})
    )
    (runs / "iter-2" / "findings.json").write_text(
        json.dumps({"conclusion": "late conclusion"})
    )

    assert _read_final_answer(runs) == "late conclusion"


def test_read_final_answer_falls_back_to_earlier_iter_when_latest_missing_findings(
    tmp_path,
):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-2").mkdir(parents=True)  # no findings.json here
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"conclusion": "iter-1 conclusion"})
    )

    assert _read_final_answer(runs) == "iter-1 conclusion"


def test_read_final_answer_tries_alternate_keys(tmp_path):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"summary": "the summary text"})
    )

    assert _read_final_answer(runs) == "the summary text"


def test_read_final_answer_recognizes_discrepancy_analysis(tmp_path):
    """When arms[] is empty, fall through to simple-key extraction so the
    discrepancy_analysis text is still surfaced."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps(
            {
                "iteration": 1,
                "arms": [],
                "discrepancy_analysis": "All arms confirmed. Effect is real.",
            }
        )
    )
    assert _read_final_answer(runs) == "All arms confirmed. Effect is real."


def test_read_final_answer_renders_full_arms_when_present(tmp_path):
    """Phase 2.7 fix: when arms[] has data, the rendered final_answer
    must include per-arm predicted/observed/status, not just the summary.
    Otherwise the judge sees a content-free meta-summary while baseline
    variants get their full prose, biasing the comparison."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps(
            {
                "iteration": 1,
                "arms": [
                    {
                        "arm_type": "h-main",
                        "predicted": "TTFT decreases by >30% as prefix increases.",
                        "observed": "Reduction = 53.8% (prefix=0: 338.67ms → prefix=384: 156.47ms).",
                        "status": "CONFIRMED",
                        "diagnostic_note": None,
                    },
                    {
                        "arm_type": "h-control",
                        "predicted": "At low load, prefix has minimal effect.",
                        "observed": "Max diff = 1.9ms across all prefix levels.",
                        "status": "CONFIRMED",
                        "diagnostic_note": "Effect is queue-mediated.",
                    },
                ],
                "experiment_valid": True,
                "discrepancy_analysis": "Effect confirmed across arms.",
            }
        )
    )
    answer = _read_final_answer(runs)

    # Cross-arm summary appears
    assert "Effect confirmed across arms." in answer
    # Per-arm structure present
    assert "h-main" in answer and "CONFIRMED" in answer
    assert "h-control" in answer
    # Specific numerical evidence preserved
    assert "53.8%" in answer
    assert "338.67ms" in answer
    assert "1.9ms" in answer
    # Diagnostic note preserved when present
    assert "queue-mediated" in answer


def test_read_final_answer_handles_arms_without_summary(tmp_path):
    """findings.json with arms but no discrepancy_analysis still renders."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps(
            {
                "arms": [
                    {
                        "arm_type": "h-main",
                        "predicted": "X",
                        "observed": "Y",
                        "status": "CONFIRMED",
                    }
                ],
            }
        )
    )
    answer = _read_final_answer(runs)
    assert "h-main" in answer
    assert "Predicted: X" in answer
    assert "Observed: Y" in answer


def test_read_final_answer_marks_invalid_experiment(tmp_path):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps(
            {
                "arms": [
                    {"arm_type": "h-x", "predicted": "p", "observed": "o", "status": "FAIL"},
                ],
                "experiment_valid": False,
            }
        )
    )
    answer = _read_final_answer(runs)
    assert "NOT valid" in answer


def test_read_final_answer_dumps_json_when_no_known_key(tmp_path):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"weird_key": "value"})
    )

    out = _read_final_answer(runs)
    assert "weird_key" in out


def test_read_final_answer_empty_when_no_runs_dir(tmp_path):
    assert _read_final_answer(tmp_path / "runs") == ""


def test_read_final_answer_ignores_non_iter_subdirs(tmp_path):
    runs = tmp_path / "runs"
    (runs / "not-an-iter").mkdir(parents=True)
    (runs / "not-an-iter" / "findings.json").write_text(json.dumps({"answer": "x"}))

    assert _read_final_answer(runs) == ""


def test_variant_name_is_nous():
    assert NousVariant.name == "nous"
