"""Tests for bench/variants/base.py — Campaign and Experiment yaml parsers."""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.variants.base import Budget, Campaign, Experiment

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "bench"
BLIS_CAMPAIGN = BENCH_DIR / "campaigns" / "blis_prefix.yaml"
PHASE1_EXPERIMENT = BENCH_DIR / "experiments" / "phase1_smoke.yaml"


def test_campaign_from_yaml_loads_blis_prefix():
    campaign = Campaign.from_yaml(BLIS_CAMPAIGN)
    assert campaign.id == "blis_prefix"
    assert "TTFT" in campaign.research_question
    assert campaign.target_repo
    assert campaign.target_ref == "main"


def test_campaign_from_yaml_rejects_missing_required_field(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: x\nresearch_question: y\n")  # missing target_repo, target_ref
    with pytest.raises(KeyError):
        Campaign.from_yaml(bad)


def test_experiment_from_yaml_resolves_campaign_and_budget():
    experiment = Experiment.from_yaml(PHASE1_EXPERIMENT)
    assert experiment.id == "phase1_smoke"
    assert experiment.variants == ["nous"]
    assert isinstance(experiment.campaign, Campaign)
    assert experiment.campaign.id == "blis_prefix"
    assert isinstance(experiment.budget, Budget)
    assert experiment.budget.max_tokens == 200_000
    assert experiment.budget.max_iterations == 2
    assert experiment.budget.max_wall_seconds == 1800


def test_experiment_budget_max_wall_seconds_optional(tmp_path):
    exp_yaml = tmp_path / "exp.yaml"
    exp_yaml.write_text(
        f"id: t\n"
        f"campaign: {BLIS_CAMPAIGN}\n"
        f"variants: [nous]\n"
        f"budget:\n"
        f"  max_tokens: 100\n"
        f"  max_iterations: 1\n"
    )
    experiment = Experiment.from_yaml(exp_yaml)
    assert experiment.budget.max_wall_seconds is None
