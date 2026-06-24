"""Tests for bench/__main__.py — argparse + list + rejudge commands.

No live LLM calls: rejudge tests stub run_judge.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.__main__ import _parse_metrics_csv, build_parser, main


def test_run_subcommand_parses_experiment_arg():
    parser = build_parser()
    args = parser.parse_args(["run", "exp.yaml"])
    assert args.cmd == "run"
    assert args.experiment == "exp.yaml"
    assert args.variants is None
    assert args.max_tokens is None


def test_run_subcommand_parses_all_overrides():
    parser = build_parser()
    args = parser.parse_args([
        "run", "exp.yaml",
        "--variants", "nous,claude_plain",
        "--max-tokens", "1000",
        "--max-iterations", "5",
        "--max-wall-seconds", "600",
        "--run-id", "custom_id",
    ])
    assert args.variants == "nous,claude_plain"
    assert args.max_tokens == 1000
    assert args.max_iterations == 5
    assert args.max_wall_seconds == 600
    assert args.run_id == "custom_id"


def test_list_subcommand_parses():
    parser = build_parser()
    args = parser.parse_args(["list"])
    assert args.cmd == "list"


def test_run_subcommand_requires_experiment_arg():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])


def test_main_list_prints_variants_and_campaigns(capsys):
    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Variants:" in out
    assert "nous" in out
    assert "Campaigns:" in out
    assert "blis_prefix" in out


def test_main_no_subcommand_exits_with_error():
    with pytest.raises(SystemExit):
        main([])


def test_main_list_includes_judge_metrics_and_presets(capsys):
    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Judge metrics:" in out
    assert "novelty" in out
    assert "Judge presets:" in out
    assert "ablation-single-iter" in out


# --- _parse_metrics_csv ---------------------------------------------------


def test_parse_metrics_csv_returns_none_for_none():
    assert _parse_metrics_csv(None) is None


def test_parse_metrics_csv_splits_and_strips():
    assert _parse_metrics_csv("correctness, novelty , coverage") == [
        "correctness", "novelty", "coverage",
    ]


def test_parse_metrics_csv_drops_empty_entries():
    """Trailing comma or double-comma shouldn't produce empty strings."""
    assert _parse_metrics_csv("correctness,,novelty,") == [
        "correctness", "novelty",
    ]


# --- run subcommand: judge flags --------------------------------------------


def test_run_subcommand_parses_judge_flags():
    parser = build_parser()
    args = parser.parse_args([
        "run", "exp.yaml",
        "--judge-metrics", "correctness,novelty",
        "--judge-preset", "ablation-single-iter",
        "--judge-model", "claude-opus-4-7",
    ])
    assert args.judge_metrics == "correctness,novelty"
    assert args.judge_preset == "ablation-single-iter"
    assert args.judge_model == "claude-opus-4-7"


def test_run_subcommand_parses_variant_model_flag():
    parser = build_parser()
    args = parser.parse_args([
        "run", "exp.yaml", "--variant-model", "claude-opus-4-7",
    ])
    assert args.variant_model == "claude-opus-4-7"


def test_run_subcommand_variant_model_defaults_none():
    parser = build_parser()
    args = parser.parse_args(["run", "exp.yaml"])
    assert args.variant_model is None


def test_run_subcommand_judge_preset_rejects_unknown():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "run", "exp.yaml", "--judge-preset", "not-a-preset",
        ])


# --- rejudge subcommand ---------------------------------------------------


def test_rejudge_subcommand_parses_required_args():
    parser = build_parser()
    args = parser.parse_args(["rejudge", "results.json"])
    assert args.cmd == "rejudge"
    assert args.results_path == "results.json"
    assert args.out is None
    assert args.judge_metrics is None
    assert args.judge_preset is None
    assert args.multi_iter is False


def test_rejudge_subcommand_parses_all_optional_args():
    parser = build_parser()
    args = parser.parse_args([
        "rejudge", "runs/x/results.json",
        "--out", "/tmp/out.json",
        "--judge-metrics", "correctness,novelty",
        "--judge-preset", "case-study",
        "--judge-model", "claude-opus-4-7",
        "--multi-iter",
    ])
    assert args.out == "/tmp/out.json"
    assert args.judge_metrics == "correctness,novelty"
    assert args.judge_preset == "case-study"
    assert args.judge_model == "claude-opus-4-7"
    assert args.multi_iter is True


def test_rejudge_subcommand_missing_results_arg_errors():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["rejudge"])


def test_rejudge_returns_2_when_results_path_missing(tmp_path):
    """No live LLM call — fails fast on missing file."""
    rc = main(["rejudge", str(tmp_path / "does-not-exist.json")])
    assert rc == 2


def _make_fake_results(path: Path) -> None:
    """Write a results.json with one variant + a snapshot for multi-iter detection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    results = {
        "experiment_id": "exp1",
        "campaign_id": "c1",
        "research_question": "Does X reduce Y?",
        "run_id": "test_run",
        "started_at": "2026-06-18T00:00:00+00:00",
        "ended_at": "2026-06-18T00:01:00+00:00",
        "variants": [
            {
                "variant": "stub",
                "campaign_id": "c1",
                "tokens_in": 10,
                "tokens_out": 5,
                "dollars": 0.01,
                "wall_seconds": 1.0,
                "final_answer": "stub answer text",
                "artifacts_dir": "/tmp/stub",
                "raw_log_path": "/tmp/stub.log",
                "crashed": False,
                "hit_cap": False,
                "error": None,
                "judge_scores": {"correctness": 5, "completeness": 5},
                "judge_rationale": "old rubric",
            },
        ],
        "judge_usage": {
            "tokens_in": 100,
            "tokens_out": 50,
            "dollars": 0.01,
            "crashed": False,
            "error": None,
            "metrics": ["correctness", "completeness"],
        },
    }
    path.write_text(json.dumps(results))


def test_rejudge_writes_new_results_with_updated_metrics(tmp_path, monkeypatch):
    """Stub run_judge so no live LLM call. Verify the rejudged file has
    new metric scores and judge_usage.metrics."""
    from bench import judge as judge_mod
    from bench.judge import JudgeOutcome, JudgeScore

    def _fake_run_judge(question, variants, *args, **kwargs):
        return JudgeOutcome(
            scores=[
                JudgeScore(
                    variant=r.variant,
                    scores={"correctness": 9, "novelty": 8},
                    rationale="rejudged with new metrics",
                )
                for r in variants
            ],
            metrics=["correctness", "novelty"],
            tokens_in=200, tokens_out=80, dollars=0.05,
            crashed=False, error=None,
        )

    monkeypatch.setattr(judge_mod, "run_judge", _fake_run_judge)
    # Patch the binding inside bench.__main__ too (it imports judge as judge_mod)
    from bench import __main__ as main_mod
    monkeypatch.setattr(main_mod.judge_mod, "run_judge", _fake_run_judge)

    results_path = tmp_path / "runs" / "x" / "results.json"
    _make_fake_results(results_path)

    rc = main([
        "rejudge", str(results_path),
        "--judge-metrics", "correctness,novelty",
    ])
    assert rc == 0

    out_path = tmp_path / "runs" / "x" / "results.rejudged.json"
    assert out_path.exists()
    new_results = json.loads(out_path.read_text())

    # Variant scores updated to the new metric set
    assert new_results["variants"][0]["judge_scores"] == {
        "correctness": 9, "novelty": 8,
    }
    assert new_results["variants"][0]["judge_rationale"] == (
        "rejudged with new metrics"
    )
    # judge_usage reflects the new metrics list + cost
    assert new_results["judge_usage"]["metrics"] == ["correctness", "novelty"]
    assert new_results["judge_usage"]["dollars"] == 0.05


def test_rejudge_honors_explicit_out_path(tmp_path, monkeypatch):
    """--out flag writes to the requested path instead of beside the input."""
    from bench import judge as judge_mod
    from bench import __main__ as main_mod
    from bench.judge import JudgeOutcome, JudgeScore

    def _fake_run_judge(question, variants, *args, **kwargs):
        return JudgeOutcome(
            scores=[
                JudgeScore(variant=r.variant, scores={"correctness": 7}, rationale="ok")
                for r in variants
            ],
            metrics=["correctness"],
            tokens_in=50, tokens_out=20, dollars=0.01,
            crashed=False, error=None,
        )

    monkeypatch.setattr(judge_mod, "run_judge", _fake_run_judge)
    monkeypatch.setattr(main_mod.judge_mod, "run_judge", _fake_run_judge)

    results_path = tmp_path / "results.json"
    _make_fake_results(results_path)
    out_path = tmp_path / "custom-out.json"

    rc = main([
        "rejudge", str(results_path),
        "--out", str(out_path),
        "--judge-metrics", "correctness",
    ])
    assert rc == 0
    assert out_path.exists()
    # And the default location is NOT written
    assert not (tmp_path / "results.rejudged.json").exists()


def test_import_nous_subcommand_parses_required_args():
    parser = build_parser()
    args = parser.parse_args(["import-nous", "/tmp/nous-campaign"])
    assert args.cmd == "import-nous"
    assert args.input_dir == "/tmp/nous-campaign"
    assert args.out is None
    assert args.campaign_id is None
    assert args.research_question is None
    assert args.run_id is None
    assert args.merge_baselines is None


def test_import_nous_subcommand_parses_all_optional_args():
    parser = build_parser()
    args = parser.parse_args([
        "import-nous", "/path/to/campaign",
        "--out", "/tmp/out.json",
        "--campaign-id", "my_id",
        "--research-question", "Custom RQ",
        "--run-id", "custom_run",
        "--merge-baselines", "/tmp/baselines.json",
    ])
    assert args.out == "/tmp/out.json"
    assert args.campaign_id == "my_id"
    assert args.research_question == "Custom RQ"
    assert args.run_id == "custom_run"
    assert args.merge_baselines == "/tmp/baselines.json"


def test_import_nous_returns_2_when_input_dir_missing(tmp_path):
    rc = main(["import-nous", str(tmp_path / "does-not-exist")])
    assert rc == 2


def test_import_nous_returns_2_when_input_dir_is_not_a_campaign(tmp_path):
    """Dir exists but has no principles.json/ledger.json/runs/."""
    (tmp_path / "random.txt").write_text("not a campaign")
    rc = main(["import-nous", str(tmp_path)])
    assert rc == 2


def _scaffold_minimal_campaign(root: Path) -> Path:
    """Tiny scaffold for end-to-end import-nous tests. Returns artifacts dir."""
    import yaml
    (root / "campaign.yaml").write_text(
        yaml.safe_dump({"run_id": "minicamp", "research_question": "Does X reduce Y?"})
    )
    (root / "principles.json").write_text(json.dumps({"principles": []}))
    (root / "ledger.json").write_text(json.dumps({
        "iterations": [
            {"iteration": 0, "family": "baseline"},
            {"iteration": 1, "family": "test", "h_main_result": "CONFIRMED"},
        ]
    }))
    runs = root / "runs" / "iter-1"
    runs.mkdir(parents=True)
    (runs / "findings.json").write_text(json.dumps({
        "iteration": 1,
        "arms": [{"arm_type": "h-main", "predicted": "p", "observed": "o", "status": "CONFIRMED"}],
    }))
    (root / "llm_metrics.jsonl").write_text(
        json.dumps({"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.05}) + "\n"
    )
    return root


def test_import_nous_writes_results_json(tmp_path):
    """End-to-end: import a minimal campaign and verify the output JSON
    has the right shape."""
    campaign_dir = tmp_path / "input"
    campaign_dir.mkdir()
    _scaffold_minimal_campaign(campaign_dir)

    out_path = tmp_path / "out" / "results.json"
    rc = main([
        "import-nous", str(campaign_dir),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.exists()

    data = json.loads(out_path.read_text())
    assert data["campaign_id"] == "minicamp"
    assert data["research_question"] == "Does X reduce Y?"
    assert len(data["variants"]) == 1
    assert data["variants"][0]["variant"] == "nous"


def test_import_nous_merges_baselines_when_flag_passed(tmp_path):
    """--merge-baselines combines the imported nous variant with an
    existing baselines results.json into a single 5-variant result."""
    campaign_dir = tmp_path / "input"
    campaign_dir.mkdir()
    _scaffold_minimal_campaign(campaign_dir)

    # Prep a fake baselines results.json
    baselines_path = tmp_path / "baselines.json"
    baselines_path.write_text(json.dumps({
        "experiment_id": "ablation",
        "campaign_id": "minicamp",
        "run_id": "ablation_baselines",
        "research_question": "Does X reduce Y?",
        "started_at": "x",
        "ended_at": "y",
        "variants": [
            {"variant": "claude_plain", "final_answer": "p"},
            {"variant": "claude_loop", "final_answer": "l"},
        ],
    }))

    out_path = tmp_path / "out" / "merged.json"
    rc = main([
        "import-nous", str(campaign_dir),
        "--out", str(out_path),
        "--merge-baselines", str(baselines_path),
    ])
    assert rc == 0

    data = json.loads(out_path.read_text())
    variant_names = [v["variant"] for v in data["variants"]]
    assert "nous" in variant_names
    assert "claude_plain" in variant_names
    assert "claude_loop" in variant_names
    assert variant_names[0] == "nous"  # nous comes first


def test_rejudge_returns_1_when_judge_crashes(tmp_path, monkeypatch):
    """Non-zero exit when the judge itself reports a crash."""
    from bench import judge as judge_mod
    from bench import __main__ as main_mod
    from bench.judge import JudgeOutcome, JudgeScore

    def _fake_crashed_judge(question, variants, *args, **kwargs):
        return JudgeOutcome(
            scores=[
                JudgeScore(variant=r.variant, scores={"correctness": None}, rationale="(crashed)")
                for r in variants
            ],
            metrics=["correctness"],
            crashed=True, error="judge timeout",
        )

    monkeypatch.setattr(judge_mod, "run_judge", _fake_crashed_judge)
    monkeypatch.setattr(main_mod.judge_mod, "run_judge", _fake_crashed_judge)

    results_path = tmp_path / "results.json"
    _make_fake_results(results_path)

    rc = main(["rejudge", str(results_path), "--judge-metrics", "correctness"])
    assert rc == 1
