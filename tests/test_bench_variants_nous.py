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
    _render_all_findings,
    _render_ledger,
    _render_principles,
    _render_report,
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
    tokens_in, tokens_out, dollars, wall = _harvest_metrics(tmp_path / "missing.jsonl")
    assert (tokens_in, tokens_out, dollars, wall) == (0, 0, 0.0, 0.0)


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
    tokens_in, tokens_out, dollars, _ = _harvest_metrics(path)

    assert tokens_in == 100 + 200
    assert tokens_out == 50 + 75
    assert dollars == pytest.approx(1.5)


def test_harvest_metrics_skips_blank_lines(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text(
        json.dumps({"input_tokens": 5, "output_tokens": 3, "cost_usd": 0.1})
        + "\n\n   \n"
    )
    tokens_in, tokens_out, dollars, _ = _harvest_metrics(path)
    assert (tokens_in, tokens_out) == (5, 3)
    assert dollars == pytest.approx(0.1)


def test_harvest_metrics_sums_duration_ms_as_wall_seconds(tmp_path):
    """wall_seconds = sum(duration_ms)/1000 — gives nous's active LLM
    compute time, comparable to bench baselines' subprocess wall_seconds."""
    path = tmp_path / "m.jsonl"
    rows = [
        {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.1, "duration_ms": 30000},
        {"input_tokens": 20, "output_tokens": 10, "cost_usd": 0.2, "duration_ms": 60000},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    _, _, _, wall = _harvest_metrics(path)
    assert wall == pytest.approx(90.0)  # 30s + 60s


def test_harvest_metrics_handles_missing_or_null_duration(tmp_path):
    """Some older campaigns may lack duration_ms; treat as 0 contribution."""
    path = tmp_path / "m.jsonl"
    rows = [
        {"input_tokens": 5, "duration_ms": 5000},
        {"input_tokens": 5},  # missing duration
        {"input_tokens": 5, "duration_ms": None},  # null
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    _, _, _, wall = _harvest_metrics(path)
    assert wall == pytest.approx(5.0)


def test_read_final_answer_renders_all_iters_in_ascending_order(tmp_path):
    """#292: render every iter's findings, not just the latest. Multi-iter
    runs need to show the full trajectory."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-2").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"conclusion": "early conclusion"})
    )
    (runs / "iter-2" / "findings.json").write_text(
        json.dumps({"conclusion": "late conclusion"})
    )

    answer = _read_final_answer(tmp_path)
    assert "## Iteration 1 findings" in answer
    assert "## Iteration 2 findings" in answer
    assert "early conclusion" in answer
    assert "late conclusion" in answer
    # Ascending order — iter-1 appears before iter-2
    assert answer.index("Iteration 1 findings") < answer.index("Iteration 2 findings")


def test_read_final_answer_skips_iter_dirs_without_findings(tmp_path):
    """An iter-N dir without findings.json is silently skipped — present
    iters still render."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-2").mkdir(parents=True)  # no findings.json here
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"conclusion": "iter-1 conclusion"})
    )

    answer = _read_final_answer(tmp_path)
    assert "iter-1 conclusion" in answer
    assert "## Iteration 1 findings" in answer
    assert "## Iteration 2 findings" not in answer


def test_read_final_answer_tries_alternate_keys(tmp_path):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"summary": "the summary text"})
    )

    assert "the summary text" in _read_final_answer(tmp_path)


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
    assert "All arms confirmed. Effect is real." in _read_final_answer(tmp_path)


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
    answer = _read_final_answer(tmp_path)

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
    answer = _read_final_answer(tmp_path)
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
    answer = _read_final_answer(tmp_path)
    assert "NOT valid" in answer


def test_read_final_answer_dumps_json_when_no_known_key(tmp_path):
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"weird_key": "value"})
    )

    out = _read_final_answer(tmp_path)
    assert "weird_key" in out


def test_read_final_answer_empty_when_no_runs_dir(tmp_path):
    assert _read_final_answer(tmp_path) == ""


def test_read_final_answer_ignores_non_iter_subdirs(tmp_path):
    runs = tmp_path / "runs"
    (runs / "not-an-iter").mkdir(parents=True)
    (runs / "not-an-iter" / "findings.json").write_text(json.dumps({"answer": "x"}))

    assert _read_final_answer(tmp_path) == ""


def test_variant_name_is_nous():
    assert NousVariant.name == "nous"


# --- _render_all_findings ---


def test_render_all_findings_returns_empty_when_runs_dir_missing(tmp_path):
    assert _render_all_findings(tmp_path / "nope") == ""


def test_render_all_findings_handles_double_digit_iter_numbers(tmp_path):
    """iter-2 must come before iter-10 in ascending order."""
    runs = tmp_path / "runs"
    for n in (1, 2, 10):
        (runs / f"iter-{n}").mkdir(parents=True)
        (runs / f"iter-{n}" / "findings.json").write_text(
            json.dumps({"conclusion": f"iter-{n} done"})
        )
    out = _render_all_findings(runs)
    # All three appear in ascending numeric order
    pos_1 = out.index("Iteration 1 findings")
    pos_2 = out.index("Iteration 2 findings")
    pos_10 = out.index("Iteration 10 findings")
    assert pos_1 < pos_2 < pos_10


# --- _render_principles ---


def _principle(pid: str, **overrides) -> dict:
    base = {
        "id": pid,
        "statement": f"{pid} statement text",
        "regime": f"{pid} regime",
        "mechanism": f"{pid} mechanism",
        "applicability_bounds": f"{pid} bounds",
        "confidence": "high",
        "status": "active",
    }
    base.update(overrides)
    return base


def test_render_principles_returns_empty_when_file_missing(tmp_path):
    assert _render_principles(tmp_path) == ""


def test_render_principles_returns_empty_when_no_principles(tmp_path):
    (tmp_path / "principles.json").write_text(json.dumps({"principles": []}))
    assert _render_principles(tmp_path) == ""


def test_render_principles_renders_each_active(tmp_path):
    (tmp_path / "principles.json").write_text(
        json.dumps({"principles": [_principle("RP-1"), _principle("RP-2")]})
    )
    out = _render_principles(tmp_path)
    assert "## Principles extracted" in out
    assert "[RP-1] RP-1 statement text" in out
    assert "[RP-2] RP-2 statement text" in out
    assert "Regime: RP-1 regime" in out
    assert "Mechanism: RP-1 mechanism" in out
    assert "Applicability bounds: RP-1 bounds" in out
    assert "Confidence: high" in out


def test_render_principles_skips_inactive(tmp_path):
    (tmp_path / "principles.json").write_text(
        json.dumps(
            {
                "principles": [
                    _principle("RP-1", status="active"),
                    _principle("RP-2", status="superseded"),
                ]
            }
        )
    )
    out = _render_principles(tmp_path)
    assert "RP-1" in out
    assert "RP-2" not in out


def test_render_principles_lenient_on_missing_status(tmp_path):
    """Resolved during plan review: missing/null status treated as active."""
    (tmp_path / "principles.json").write_text(
        json.dumps(
            {
                "principles": [
                    {"id": "RP-1", "statement": "no status field"},
                    {"id": "RP-2", "statement": "null status", "status": None},
                ]
            }
        )
    )
    out = _render_principles(tmp_path)
    assert "RP-1" in out
    assert "RP-2" in out


def test_render_principles_skips_principles_without_statement(tmp_path):
    (tmp_path / "principles.json").write_text(
        json.dumps({"principles": [{"id": "RP-X", "statement": ""}]})
    )
    assert _render_principles(tmp_path) == ""


# --- _render_ledger ---


def _ledger_iter(n: int, **overrides) -> dict:
    base = {
        "iteration": n,
        "family": "test-family",
        "h_main_result": "CONFIRMED",
        "control_result": "CONFIRMED",
        "robustness_result": "CONFIRMED",
        "prediction_accuracy": {
            "arms_correct": 3,
            "arms_total": 3,
            "accuracy_pct": 100.0,
        },
    }
    base.update(overrides)
    return base


def test_render_ledger_returns_empty_when_file_missing(tmp_path):
    assert _render_ledger(tmp_path) == ""


def test_render_ledger_renders_table(tmp_path):
    (tmp_path / "ledger.json").write_text(
        json.dumps({"iterations": [_ledger_iter(1)]})
    )
    out = _render_ledger(tmp_path)
    assert "## Iteration ledger" in out
    assert "| Iter | Family |" in out
    assert "| 1 | test-family | CONFIRMED | CONFIRMED | CONFIRMED | 3/3 (100.0%) |" in out


def test_render_ledger_skips_seed_iteration(tmp_path):
    """Seed row (iteration=0) is always null fields; not useful for the judge."""
    (tmp_path / "ledger.json").write_text(
        json.dumps({"iterations": [_ledger_iter(0), _ledger_iter(1)]})
    )
    out = _render_ledger(tmp_path)
    # Iteration 1 row appears
    assert "| 1 |" in out
    # Iteration 0 row does NOT
    assert "| 0 |" not in out


def test_render_ledger_returns_empty_when_only_seed_row(tmp_path):
    """A run with only the iteration=0 seed entry has nothing real to render."""
    (tmp_path / "ledger.json").write_text(
        json.dumps({"iterations": [_ledger_iter(0)]})
    )
    assert _render_ledger(tmp_path) == ""


def test_render_ledger_handles_missing_prediction_accuracy(tmp_path):
    (tmp_path / "ledger.json").write_text(
        json.dumps(
            {"iterations": [_ledger_iter(1, prediction_accuracy=None)]}
        )
    )
    out = _render_ledger(tmp_path)
    # Accuracy column shows '—' instead of crashing
    assert "—" in out


# --- _render_report ---


def test_render_report_returns_empty_when_file_missing(tmp_path):
    assert _render_report(tmp_path) == ""


def test_render_report_returns_empty_when_file_blank(tmp_path):
    (tmp_path / "report.md").write_text("   \n  \n")
    assert _render_report(tmp_path) == ""


def test_render_report_includes_contents_verbatim(tmp_path):
    (tmp_path / "report.md").write_text(
        "# Campaign Findings\n\nThe effect is real and reproducible."
    )
    out = _render_report(tmp_path)
    assert out.startswith("## Campaign report")
    assert "The effect is real and reproducible." in out


# --- _read_final_answer (multi-source composition) ---


def test_read_final_answer_composes_all_sources(tmp_path):
    """Full artifact set: findings + principles + ledger + report all rendered,
    separated by '---'."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"discrepancy_analysis": "FINDINGS_MARKER"})
    )
    (tmp_path / "principles.json").write_text(
        json.dumps({"principles": [_principle("RP-1", statement="PRINCIPLES_MARKER")]})
    )
    (tmp_path / "ledger.json").write_text(
        json.dumps({"iterations": [_ledger_iter(1, family="LEDGER_MARKER")]})
    )
    (tmp_path / "report.md").write_text("REPORT_MARKER body text")

    out = _read_final_answer(tmp_path)
    # All four markers present
    assert "FINDINGS_MARKER" in out
    assert "PRINCIPLES_MARKER" in out
    assert "LEDGER_MARKER" in out
    assert "REPORT_MARKER" in out
    # Section separators between non-empty sources
    assert "\n\n---\n\n" in out


def test_read_final_answer_smoke_run_shape_findings_only(tmp_path):
    """The shape our actual smoke run produced: findings + principles +
    ledger present, report.md absent. All three other sources should appear,
    no Campaign report section."""
    runs = tmp_path / "runs"
    (runs / "iter-1").mkdir(parents=True)
    (runs / "iter-1" / "findings.json").write_text(
        json.dumps({"conclusion": "smoke conclusion"})
    )
    (tmp_path / "principles.json").write_text(
        json.dumps({"principles": [_principle("RP-1")]})
    )
    (tmp_path / "ledger.json").write_text(
        json.dumps({"iterations": [_ledger_iter(1)]})
    )

    out = _read_final_answer(tmp_path)
    assert "smoke conclusion" in out
    assert "## Principles extracted" in out
    assert "## Iteration ledger" in out
    assert "## Campaign report" not in out
