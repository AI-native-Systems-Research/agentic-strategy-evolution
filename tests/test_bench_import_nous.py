"""Tests for bench/import_nous.py — converting an existing nous campaign
into a bench-compatible results.json. No live LLM calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from bench.import_nous import (
    ArtifactsDirNotFound,
    NousCampaignSnapshot,
    find_artifacts_dir,
    import_nous_campaign,
    merge_baselines,
    snapshot_to_bench_results,
)


def _scaffold_nous_campaign(
    root: Path,
    *,
    nested_under: str | None = None,
    campaign_yaml_data: dict | None = None,
    iterations: int = 2,
    include_report: bool = True,
) -> Path:
    """Create a minimal but realistic nous campaign tree on disk.

    If nested_under is set, places artifacts inside root/<nested_under>/
    and the campaign yaml at root/. Returns the artifacts dir path.
    """
    artifacts = root / nested_under if nested_under else root
    artifacts.mkdir(parents=True, exist_ok=True)

    # campaign.yaml at the root
    yml = campaign_yaml_data or {
        "run_id": "test_campaign",
        "research_question": "Does X reduce Y?",
        "max_iterations": iterations,
    }
    with open(root / "campaign.yaml", "w") as f:
        yaml.safe_dump(yml, f)

    # principles.json
    principles = {
        "principles": [
            {
                "id": "RP-1",
                "statement": "Test principle",
                "regime": "always",
                "mechanism": "test",
                "applicability_bounds": "test",
                "confidence": "high",
                "status": "active",
            }
        ]
    }
    with open(artifacts / "principles.json", "w") as f:
        json.dump(principles, f)

    # ledger.json with `iterations` rows
    ledger_iters = [
        {
            "iteration": 0,
            "family": "baseline",
            "h_main_result": None,
            "control_result": None,
            "robustness_result": None,
            "prediction_accuracy": None,
        }
    ]
    for i in range(1, iterations + 1):
        ledger_iters.append({
            "iteration": i,
            "family": f"family-{i}",
            "h_main_result": "CONFIRMED",
            "control_result": "CONFIRMED",
            "robustness_result": None,
            "prediction_accuracy": {"arms_correct": 2, "arms_total": 2,
                                    "accuracy_pct": 100.0},
        })
    with open(artifacts / "ledger.json", "w") as f:
        json.dump({"iterations": ledger_iters}, f)

    # runs/iter-N/findings.json
    runs_dir = artifacts / "runs"
    runs_dir.mkdir(exist_ok=True)
    for i in range(1, iterations + 1):
        iter_dir = runs_dir / f"iter-{i}"
        iter_dir.mkdir(exist_ok=True)
        findings = {
            "iteration": i,
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": f"prediction iter {i}",
                    "observed": f"observed iter {i}",
                    "status": "CONFIRMED",
                }
            ],
        }
        with open(iter_dir / "findings.json", "w") as f:
            json.dump(findings, f)

    # report.md (optional — pd-disagg + Graph-Coloring don't have it)
    if include_report:
        (artifacts / "report.md").write_text(
            "# Campaign Report\n\nNous found a thing.\n"
        )

    # llm_metrics.jsonl (one row per iter; uses nous's actual schema:
    # input_tokens / output_tokens / cost_usd, not tokens_in/dollars)
    metrics_lines = []
    for i in range(1, iterations + 1):
        metrics_lines.append(json.dumps({
            "iteration": i,
            "model": "claude-sonnet-4-6",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_usd": 0.50,
        }))
    (artifacts / "llm_metrics.jsonl").write_text("\n".join(metrics_lines) + "\n")

    return artifacts


# --- find_artifacts_dir ---------------------------------------------------


def test_find_artifacts_dir_flat_layout(tmp_path):
    """Layout like flow-control-reflective-v2: artifacts at root."""
    artifacts = _scaffold_nous_campaign(tmp_path)
    found = find_artifacts_dir(tmp_path)
    assert found == artifacts.resolve()


def test_find_artifacts_dir_nested_layout(tmp_path):
    """Layout like Graph-Coloring/graph-coloring-v1/: artifacts one level deep."""
    artifacts = _scaffold_nous_campaign(tmp_path, nested_under="run-v1")
    found = find_artifacts_dir(tmp_path)
    assert found == artifacts.resolve()


def test_find_artifacts_dir_picks_first_match(tmp_path):
    """If multiple subdirs are present, returns the first valid one."""
    # Create a non-artifacts subdir
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("not an artifacts dir")
    artifacts = _scaffold_nous_campaign(tmp_path, nested_under="run-v1")
    found = find_artifacts_dir(tmp_path)
    assert found == artifacts.resolve()


def test_find_artifacts_dir_raises_when_no_artifacts(tmp_path):
    """If neither root nor any subdir has principles.json + ledger.json + runs/."""
    (tmp_path / "random.txt").write_text("nothing here")
    (tmp_path / "subdir").mkdir()
    with pytest.raises(ArtifactsDirNotFound):
        find_artifacts_dir(tmp_path)


def test_find_artifacts_dir_partial_match_still_raises(tmp_path):
    """Has principles.json but missing ledger.json → not detected."""
    (tmp_path / "principles.json").write_text("{}")
    with pytest.raises(ArtifactsDirNotFound):
        find_artifacts_dir(tmp_path)


# --- import_nous_campaign -------------------------------------------------


def test_import_reads_campaign_yaml(tmp_path):
    _scaffold_nous_campaign(tmp_path, campaign_yaml_data={
        "run_id": "my_campaign",
        "research_question": "What is the meaning of X?",
        "max_iterations": 3,
    }, iterations=3)

    snap = import_nous_campaign(tmp_path)
    assert snap.campaign_id == "my_campaign"
    assert snap.research_question == "What is the meaning of X?"
    assert snap.iterations_completed == 3


def test_import_works_with_nested_layout(tmp_path):
    """e.g. Graph-Coloring/graph-coloring-v1/."""
    _scaffold_nous_campaign(tmp_path, nested_under="run-v1", iterations=2)
    snap = import_nous_campaign(tmp_path)
    assert snap.iterations_completed == 2
    assert snap.artifacts_dir.name == "run-v1"


def test_import_falls_back_to_dirname_for_id(tmp_path):
    """If campaign yaml has no run_id, use the input dir name."""
    yml = {"research_question": "Q?"}
    _scaffold_nous_campaign(tmp_path, campaign_yaml_data=yml)
    snap = import_nous_campaign(tmp_path)
    assert snap.campaign_id == tmp_path.name


def test_import_explicit_overrides_take_precedence(tmp_path):
    _scaffold_nous_campaign(tmp_path, campaign_yaml_data={
        "run_id": "yaml_id", "research_question": "yaml RQ"
    })
    snap = import_nous_campaign(
        tmp_path, campaign_id="explicit_id", research_question="explicit RQ",
    )
    assert snap.campaign_id == "explicit_id"
    assert snap.research_question == "explicit RQ"


def test_import_raises_when_no_research_question(tmp_path):
    """No yaml RQ + no override → can't proceed."""
    _scaffold_nous_campaign(tmp_path, campaign_yaml_data={"run_id": "x"})
    with pytest.raises(ValueError, match="research_question"):
        import_nous_campaign(tmp_path)


def test_import_renders_final_answer_with_principles_section(tmp_path):
    """The rendered final_answer must include the rendered principles."""
    _scaffold_nous_campaign(tmp_path, iterations=2)
    snap = import_nous_campaign(tmp_path)
    assert "Test principle" in snap.final_answer
    assert "Iteration 1 findings" in snap.final_answer or "iter 1" in snap.final_answer.lower()


def test_import_handles_missing_report(tmp_path):
    """pd-disagg + Graph-Coloring don't have report.md — must still work."""
    _scaffold_nous_campaign(tmp_path, include_report=False)
    snap = import_nous_campaign(tmp_path)
    # final_answer renders without crashing; just no report section
    assert "Campaign report" not in snap.final_answer


def test_import_harvests_metrics(tmp_path):
    _scaffold_nous_campaign(tmp_path, iterations=3)
    snap = import_nous_campaign(tmp_path)
    # 3 iters × $0.50 = $1.50
    assert snap.dollars == pytest.approx(1.50)
    # 3 iters × 1000 tokens_in (only billable input tokens count per Phase 1.7.1)
    assert snap.tokens_in == 3000
    assert snap.tokens_out == 1500


def test_import_handles_null_metric_fields(tmp_path):
    """Some real campaigns emit `cost_usd: null` for non-billable rows; we
    must not crash."""
    _scaffold_nous_campaign(tmp_path, iterations=1)
    # Append a null-cost row, simulating what flow-control-reflective-v2 has
    metrics_path = tmp_path / "llm_metrics.jsonl"
    with open(metrics_path, "a") as f:
        f.write(json.dumps({
            "iteration": 1,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        }) + "\n")

    # Should NOT raise
    snap = import_nous_campaign(tmp_path)
    # Original 1 row still counted; null row contributes nothing
    assert snap.dollars == pytest.approx(0.50)
    assert snap.tokens_in == 1000


# --- snapshot_to_bench_results --------------------------------------------


def _basic_snapshot(tmp_path) -> NousCampaignSnapshot:
    return NousCampaignSnapshot(
        campaign_id="test",
        research_question="Q?",
        artifacts_dir=tmp_path,
        iterations_completed=3,
        final_answer="rendered nous output",
        tokens_in=10000,
        tokens_out=2000,
        dollars=5.0,
        wall_seconds=0.0,
    )


def test_snapshot_to_bench_results_produces_one_nous_variant(tmp_path):
    snap = _basic_snapshot(tmp_path)
    out = snapshot_to_bench_results(snap, run_id="test_run")

    assert out["run_id"] == "test_run"
    assert out["campaign_id"] == "test"
    assert out["research_question"] == "Q?"
    assert len(out["variants"]) == 1
    assert out["variants"][0]["variant"] == "nous"
    assert out["variants"][0]["final_answer"] == "rendered nous output"
    assert out["variants"][0]["dollars"] == 5.0
    assert out["variants"][0]["crashed"] is False
    # Provenance block
    assert out["imported"]["iterations_completed"] == 3


def test_snapshot_to_bench_results_includes_required_variant_fields(tmp_path):
    """The variant entry must have every field bench/runner.py and report.py
    expect, so downstream tools don't crash."""
    snap = _basic_snapshot(tmp_path)
    out = snapshot_to_bench_results(snap, run_id="r1")
    v = out["variants"][0]
    required = {
        "variant", "campaign_id", "tokens_in", "tokens_out", "dollars",
        "wall_seconds", "final_answer", "artifacts_dir", "raw_log_path",
        "crashed", "hit_cap", "error",
    }
    assert required.issubset(set(v.keys()))


# --- merge_baselines ------------------------------------------------------


def test_merge_baselines_combines_nous_with_baseline_variants(tmp_path):
    """Output has nous + 4 baselines, with nous first."""
    snap = _basic_snapshot(tmp_path)
    nous_only = snapshot_to_bench_results(snap, run_id="r1")

    baselines = {
        "experiment_id": "ablation",
        "campaign_id": "test",
        "run_id": "r1_baselines",
        "research_question": "Q?",
        "started_at": "x",
        "ended_at": "y",
        "variants": [
            {"variant": "claude_plain", "final_answer": "p", "dollars": 1.0,
             "wall_seconds": 10, "tokens_in": 100, "tokens_out": 50,
             "campaign_id": "test", "artifacts_dir": "/x", "raw_log_path": "/y",
             "crashed": False, "hit_cap": False, "error": None},
            {"variant": "claude_loop", "final_answer": "l", "dollars": 2.0,
             "wall_seconds": 20, "tokens_in": 200, "tokens_out": 100,
             "campaign_id": "test", "artifacts_dir": "/x", "raw_log_path": "/y",
             "crashed": False, "hit_cap": False, "error": None},
        ],
    }

    merged = merge_baselines(nous_only, baselines)
    variant_names = [v["variant"] for v in merged["variants"]]
    assert variant_names == ["nous", "claude_plain", "claude_loop"]


def test_merge_baselines_drops_baseline_nous_if_present(tmp_path):
    """If the baselines results.json accidentally contains a nous variant,
    we should keep ours (the imported one) and drop theirs."""
    snap = _basic_snapshot(tmp_path)
    nous_only = snapshot_to_bench_results(snap, run_id="r1")
    nous_only["variants"][0]["final_answer"] = "REAL_NOUS_OUTPUT"

    baselines = {
        "variants": [
            {"variant": "nous", "final_answer": "FAKE_NOUS"},
            {"variant": "claude_plain", "final_answer": "p"},
        ],
    }
    merged = merge_baselines(nous_only, baselines)
    nous_entry = next(v for v in merged["variants"] if v["variant"] == "nous")
    assert nous_entry["final_answer"] == "REAL_NOUS_OUTPUT"


def test_merge_baselines_carries_judge_usage_from_baselines(tmp_path):
    snap = _basic_snapshot(tmp_path)
    nous_only = snapshot_to_bench_results(snap, run_id="r1")
    baselines = {
        "variants": [
            {"variant": "claude_plain", "final_answer": "p"},
        ],
        "judge_usage": {"tokens_in": 1000, "tokens_out": 500, "dollars": 0.10,
                        "crashed": False, "error": None,
                        "metrics": ["correctness", "novelty"]},
    }
    merged = merge_baselines(nous_only, baselines)
    assert merged["judge_usage"]["dollars"] == 0.10
    assert merged["judge_usage"]["metrics"] == ["correctness", "novelty"]
