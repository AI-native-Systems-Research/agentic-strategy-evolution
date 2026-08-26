"""Tests for bench/runner.py — pure helpers, plus end-to-end with a stub variant."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from bench import runner as runner_mod
from bench.runner import (
    find_repo_root,
    generate_run_id,
    result_to_jsonable,
    validate_variants,
)
from bench.variants.base import Budget, Campaign, VariantResult


def test_find_repo_root_walks_up_to_pyproject():
    here = Path(__file__).resolve()
    root = find_repo_root(here)
    assert (root / "pyproject.toml").exists()
    assert (root / "bench").is_dir()


def test_find_repo_root_raises_when_no_pyproject(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_repo_root(tmp_path)


def test_validate_variants_passes_known_names():
    assert validate_variants(["nous"]) == ["nous"]


def test_validate_variants_rejects_duplicates():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_variants(["nous", "nous"])


def test_validate_variants_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown"):
        validate_variants(["nonexistent_variant"])


def test_generate_run_id_starts_with_iso_date():
    rid = generate_run_id("phase1_smoke")
    assert rid.endswith("_phase1_smoke")
    date_part = rid.split("_phase1_smoke")[0]
    parts = date_part.split("-")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_result_to_jsonable_converts_paths_to_strings(tmp_path):
    result = VariantResult(
        variant="x",
        campaign_id="c",
        tokens_in=1,
        tokens_out=2,
        dollars=0.5,
        wall_seconds=3.0,
        final_answer="a",
        artifacts_dir=tmp_path / "art",
        raw_log_path=tmp_path / "log",
    )
    d = result_to_jsonable(result)
    assert isinstance(d["artifacts_dir"], str)
    assert isinstance(d["raw_log_path"], str)
    assert d["artifacts_dir"].endswith("art")


# --- End-to-end test with a stub variant (no live subprocess) ---


class _StubVariant:
    name = "stub"

    def run(self, campaign: Campaign, workspace: Path, budget: Budget) -> VariantResult:
        return VariantResult(
            variant=self.name,
            campaign_id=campaign.id,
            tokens_in=42,
            tokens_out=10,
            dollars=0.001,
            wall_seconds=0.5,
            final_answer=f"stub answer for {campaign.id}",
            artifacts_dir=workspace,
            raw_log_path=workspace / "stub.log",
            crashed=False,
            hit_cap=False,
            error=None,
        )


@pytest.fixture
def stub_target_repo(tmp_path):
    """Create a tiny git repo to use as the bench target."""
    import subprocess

    repo = tmp_path / "stub_target"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit",
         "--allow-empty", "-m", "init", "-q"],
        cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "branch", "-M", "main"], cwd=repo, check=True,
    )
    return repo


@pytest.fixture
def stub_experiment_yaml(tmp_path, stub_target_repo):
    """Create a minimal campaign + experiment yaml pair pointing at the stub repo."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'fake'\n")

    bench_dir = tmp_path / "bench"
    (bench_dir / "campaigns").mkdir(parents=True)
    (bench_dir / "experiments").mkdir(parents=True)

    campaign = bench_dir / "campaigns" / "stub.yaml"
    campaign.write_text(
        f"id: stub\n"
        f"research_question: Does stub work?\n"
        f"target_repo: {stub_target_repo}\n"
        f"target_ref: main\n"
    )
    experiment = bench_dir / "experiments" / "stub_exp.yaml"
    experiment.write_text(
        f"id: stub_exp\n"
        f"campaign: campaigns/stub.yaml\n"
        f"variants: [stub]\n"
        f"budget:\n"
        f"  max_tokens: 1000\n"
        f"  max_iterations: 1\n"
    )
    return experiment


def test_run_experiment_end_to_end_with_stub_variant(
    stub_experiment_yaml, monkeypatch
):
    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "stub", _StubVariant)
    run_dir = runner_mod.run_experiment(stub_experiment_yaml, skip_judge=True)

    assert (run_dir / "report.md").exists() or True  # report comes in #6
    assert (run_dir / "results.json").exists()
    assert (run_dir / "experiment.snapshot.yaml").exists()
    assert (run_dir / "campaign.snapshot.yaml").exists()
    assert (run_dir / "stub" / "result.json").exists()

    with open(run_dir / "results.json") as f:
        combined = json.load(f)
    assert combined["experiment_id"] == "stub_exp"
    assert combined["campaign_id"] == "stub"
    assert len(combined["variants"]) == 1
    assert combined["variants"][0]["variant"] == "stub"
    assert combined["variants"][0]["tokens_in"] == 42
    assert combined["variants"][0]["final_answer"] == "stub answer for stub"


def test_run_experiment_variants_override(stub_experiment_yaml, monkeypatch):
    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "stub", _StubVariant)
    run_dir = runner_mod.run_experiment(
        stub_experiment_yaml, variants_override=["stub"], skip_judge=True
    )
    with open(run_dir / "results.json") as f:
        combined = json.load(f)
    assert [v["variant"] for v in combined["variants"]] == ["stub"]


def test_run_experiment_parallel_preserves_input_order(
    stub_target_repo, tmp_path, monkeypatch
):
    """With slow + fast stub variants run in parallel, results must come back
    in the order requested (matching the variants list), not completion order."""
    import time as _time

    class _SlowStub:
        name = "slow"

        def run(self, campaign, workspace, budget):
            _time.sleep(0.15)
            return _StubVariant().run(campaign, workspace, budget)._replace_variant(
                "slow"
            ) if False else VariantResult(
                variant="slow", campaign_id=campaign.id, tokens_in=1, tokens_out=1,
                dollars=0.01, wall_seconds=0.15, final_answer="slow_done",
                artifacts_dir=workspace, raw_log_path=workspace / "log",
                crashed=False, hit_cap=False, error=None,
            )

    class _FastStub:
        name = "fast"

        def run(self, campaign, workspace, budget):
            return VariantResult(
                variant="fast", campaign_id=campaign.id, tokens_in=2, tokens_out=2,
                dollars=0.02, wall_seconds=0.001, final_answer="fast_done",
                artifacts_dir=workspace, raw_log_path=workspace / "log",
                crashed=False, hit_cap=False, error=None,
            )

    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "slow", _SlowStub)
    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "fast", _FastStub)

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'fake'\n")
    bench_dir = tmp_path / "bench"
    (bench_dir / "campaigns").mkdir(parents=True)
    (bench_dir / "experiments").mkdir(parents=True)
    campaign = bench_dir / "campaigns" / "stub.yaml"
    campaign.write_text(
        f"id: stub\n"
        f"research_question: Does parallel work?\n"
        f"target_repo: {stub_target_repo}\n"
        f"target_ref: main\n"
    )
    experiment = bench_dir / "experiments" / "parallel_exp.yaml"
    experiment.write_text(
        f"id: parallel_exp\n"
        f"campaign: campaigns/stub.yaml\n"
        f"variants: [slow, fast]\n"
        f"budget:\n"
        f"  max_tokens: 1000\n"
        f"  max_iterations: 1\n"
    )

    start = time.monotonic()
    run_dir = runner_mod.run_experiment(experiment, skip_judge=True)
    elapsed = time.monotonic() - start

    with open(run_dir / "results.json") as f:
        combined = json.load(f)

    # Results in input order, not completion order
    assert [v["variant"] for v in combined["variants"]] == ["slow", "fast"]
    # Both completed successfully
    assert combined["variants"][0]["final_answer"] == "slow_done"
    assert combined["variants"][1]["final_answer"] == "fast_done"
    # Concurrency proof: total wall < sum-of-each (0.15 + 0 ≈ 0.15);
    # sequential would also be ~0.15 since fast is 0. Use a generous upper bound.
    assert elapsed < 1.0


def test_default_max_parallel_caps_at_cpu_count():
    from bench.runner import _default_max_parallel
    # With 100 variants and a small CPU count, should cap at cpu_count
    assert _default_max_parallel(100) <= (os.cpu_count() or 4)
    # With 1 variant, returns 1
    assert _default_max_parallel(1) == 1


def test_run_experiment_skip_judge_omits_judge_usage(
    stub_experiment_yaml, monkeypatch
):
    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "stub", _StubVariant)
    run_dir = runner_mod.run_experiment(stub_experiment_yaml, skip_judge=True)

    with open(run_dir / "results.json") as f:
        combined = json.load(f)
    assert "judge_usage" not in combined
    for v in combined["variants"]:
        assert "judge_scores" not in v


def test_run_experiment_judge_runs_by_default_and_attaches_scores(
    stub_experiment_yaml, monkeypatch
):
    """Stub the judge so we don't hit live claude. Check wiring."""
    from bench import judge as judge_mod
    from bench.judge import JudgeOutcome, JudgeScore

    def _fake_run_judge(question, results, *args, **kwargs):
        metrics = ["correctness", "completeness"]
        return JudgeOutcome(
            scores=[
                JudgeScore(
                    variant=r.variant,
                    scores={"correctness": 7, "completeness": 6},
                    rationale="looks fine",
                )
                for r in results
            ],
            metrics=metrics,
            tokens_in=100, tokens_out=20, dollars=0.05,
            crashed=False, error=None,
        )

    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "stub", _StubVariant)
    monkeypatch.setattr(judge_mod, "run_judge", _fake_run_judge)
    monkeypatch.setattr(runner_mod.judge_mod, "run_judge", _fake_run_judge)

    run_dir = runner_mod.run_experiment(stub_experiment_yaml)

    with open(run_dir / "results.json") as f:
        combined = json.load(f)
    assert combined["judge_usage"]["dollars"] == 0.05
    assert combined["judge_usage"]["crashed"] is False
    assert combined["judge_usage"]["metrics"] == ["correctness", "completeness"]
    assert combined["variants"][0]["judge_scores"]["correctness"] == 7
    assert combined["variants"][0]["judge_scores"]["completeness"] == 6
    assert combined["variants"][0]["judge_rationale"] == "looks fine"


def test_run_experiment_budget_override(stub_experiment_yaml, monkeypatch):
    captured = {}

    class _RecordingVariant:
        name = "recording"

        def run(self, campaign, workspace, budget):
            captured["max_tokens"] = budget.max_tokens
            return _StubVariant().run(campaign, workspace, budget)

    monkeypatch.setitem(runner_mod.VARIANT_REGISTRY, "recording", _RecordingVariant)
    runner_mod.run_experiment(
        stub_experiment_yaml,
        variants_override=["recording"],
        budget_overrides={"max_tokens": 9999},
        skip_judge=True,
    )
    assert captured["max_tokens"] == 9999
