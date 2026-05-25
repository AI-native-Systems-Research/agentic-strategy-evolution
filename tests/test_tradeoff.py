"""Behavioral tests for the H-tradeoff arm (issue #158).

Tests assert what's on disk (bundle, findings) and the deterministic
verdict classifier on synthetic numeric inputs. No live LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.findings_classifier import classify_tradeoff
from orchestrator.validate import validate_design


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _load_findings_schema() -> dict:
    return json.loads((SCHEMAS_DIR / "findings.schema.json").read_text())


# ─── Verdict classifier truth table ────────────────────────────────────────


class TestTradeoffVerdict:
    def test_all_predicates_met_confirmed(self) -> None:
        v = classify_tradeoff(
            primary_change_observed=-30.0,
            primary_change_predicted=-20.0,  # need <= -20, observed -30 is better
            secondary_change_observed=5.0,
            secondary_budget=10.0,
            secondary_direction="increase",
        )
        assert v.primary_predicate_met is True
        assert v.secondary_predicate_met is True
        assert v.verdict == "confirmed"

    def test_primary_failed(self) -> None:
        v = classify_tradeoff(
            primary_change_observed=-5.0,
            primary_change_predicted=-20.0,
            secondary_change_observed=2.0,
            secondary_budget=10.0,
            secondary_direction="increase",
        )
        assert v.primary_predicate_met is False
        assert v.secondary_predicate_met is True
        assert v.verdict == "primary_failed"

    def test_cost_too_high(self) -> None:
        v = classify_tradeoff(
            primary_change_observed=-25.0,
            primary_change_predicted=-20.0,
            secondary_change_observed=15.0,
            secondary_budget=10.0,
            secondary_direction="increase",
        )
        assert v.primary_predicate_met is True
        assert v.secondary_predicate_met is False
        assert v.verdict == "cost_too_high"

    def test_both_failed(self) -> None:
        v = classify_tradeoff(
            primary_change_observed=5.0,
            primary_change_predicted=-20.0,
            secondary_change_observed=20.0,
            secondary_budget=10.0,
            secondary_direction="increase",
        )
        assert v.primary_predicate_met is False
        assert v.secondary_predicate_met is False
        assert v.verdict == "both_failed"

    def test_decrease_direction(self) -> None:
        """secondary_direction='decrease' means worse is going down (e.g.
        accuracy). Observed -3 with budget 5 is fine."""
        v = classify_tradeoff(
            primary_change_observed=-10.0,
            primary_change_predicted=-5.0,
            secondary_change_observed=-3.0,
            secondary_budget=5.0,
            secondary_direction="decrease",
        )
        assert v.secondary_predicate_met is True
        assert v.verdict == "confirmed"

    def test_decrease_direction_violation(self) -> None:
        v = classify_tradeoff(
            primary_change_observed=-10.0,
            primary_change_predicted=-5.0,
            secondary_change_observed=-7.0,  # more decrease than budget -5
            secondary_budget=5.0,
            secondary_direction="decrease",
        )
        assert v.secondary_predicate_met is False
        assert v.verdict == "cost_too_high"

    def test_better_than_predicted_secondary_passes(self) -> None:
        """If secondary moves the BETTER direction (down when worse=up),
        it must pass regardless of budget."""
        v = classify_tradeoff(
            primary_change_observed=-10.0,
            primary_change_predicted=-5.0,
            secondary_change_observed=-50.0,  # secondary went down massively
            secondary_budget=2.0,
            secondary_direction="increase",  # worse=up
        )
        assert v.secondary_predicate_met is True

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="secondary_direction"):
            classify_tradeoff(
                primary_change_observed=0, primary_change_predicted=0,
                secondary_change_observed=0, secondary_budget=1,
                secondary_direction="sideways",
            )

    def test_negative_budget_raises(self) -> None:
        with pytest.raises(ValueError, match="secondary_budget"):
            classify_tradeoff(
                primary_change_observed=0, primary_change_predicted=0,
                secondary_change_observed=0, secondary_budget=-1,
                secondary_direction="increase",
            )


# ─── Bundle schema accepts h-tradeoff with all required fields ────────────


VALID_TRADEOFF_BUNDLE = {
    "metadata": {"iteration": 1, "family": "test", "research_question": "Is it worth it?"},
    "arms": [
        {
            "type": "h-main",
            "prediction": "Caching cuts latency",
            "mechanism": "skips redundant calls",
            "diagnostic": "check cache hit rate",
        },
        {
            "type": "h-tradeoff",
            "prediction": "Latency drops >=20% while memory stays within +500MB",
            "mechanism": "Cache trades memory for time",
            "diagnostic": "If memory exceeds budget, intervention fails",
            "metric": "latency_ms",
            "secondary_metric": "memory_mb",
            "secondary_budget": 500,
            "secondary_direction": "increase",
            "primary_change": -20.0,
        },
    ],
}


class TestBundleSchemaAcceptance:
    def test_valid_tradeoff_bundle_passes_schema(self) -> None:
        schema = _load_bundle_schema()
        jsonschema.validate(VALID_TRADEOFF_BUNDLE, schema)

    def test_validate_design_accepts_tradeoff(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        d.mkdir()
        (d / "problem.md").write_text("## RQ\nIs caching worth the memory?\n")
        (d / "bundle.yaml").write_text(yaml.safe_dump(VALID_TRADEOFF_BUNDLE))
        (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")
        result = validate_design(d)
        assert result["status"] == "pass", result.get("errors")


# ─── Cross-field validation rejects malformed tradeoff arms ───────────────


def _bundle_with_tradeoff_arm(**overrides) -> dict:
    arm = {
        "type": "h-tradeoff",
        "prediction": "latency drops, memory grows",
        "mechanism": "cache",
        "diagnostic": "check usage",
        "metric": "latency_ms",
        "secondary_metric": "memory_mb",
        "secondary_budget": 500,
        "secondary_direction": "increase",
    }
    arm.update(overrides)
    return {
        "metadata": {"iteration": 1, "family": "t", "research_question": "q?"},
        "arms": [arm],
    }


def _setup(d: Path, bundle: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "problem.md").write_text("## RQ\nq?\n")
    (d / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")


class TestTradeoffCrossFieldValidation:
    def test_rejects_same_primary_and_secondary_metric(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        bundle = _bundle_with_tradeoff_arm(secondary_metric="latency_ms")
        _setup(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("differ" in e.lower() for e in result["errors"])

    def test_rejects_missing_secondary_budget(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        arm = {
            "type": "h-tradeoff",
            "prediction": "p", "mechanism": "m", "diagnostic": "d",
            "metric": "latency_ms",
            "secondary_metric": "memory_mb",
            "secondary_direction": "increase",
            # secondary_budget omitted
        }
        bundle = {
            "metadata": {"iteration": 1, "family": "t", "research_question": "q?"},
            "arms": [arm],
        }
        _setup(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("secondary_budget" in e for e in result["errors"])

    def test_rejects_invalid_direction(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        bundle = _bundle_with_tradeoff_arm(secondary_direction="sideways")
        _setup(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"

    def test_rejects_negative_budget(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        bundle = _bundle_with_tradeoff_arm(secondary_budget=-10)
        _setup(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"


# ─── Findings schema accepts h-tradeoff arm result fields ─────────────────


class TestFindingsSchemaAcceptance:
    def test_tradeoff_findings_round_trip(self) -> None:
        findings = {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-tradeoff",
                    "predicted": "latency -20%, memory +<500MB",
                    "observed": "latency -25%, memory +600MB",
                    "status": "PARTIALLY_CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": "Memory exceeded budget",
                    "primary_change_observed": -25.0,
                    "secondary_change_observed": 600.0,
                    "primary_predicate_met": True,
                    "secondary_predicate_met": False,
                    "tradeoff_verdict": "cost_too_high",
                },
            ],
            "experiment_valid": True,
            "discrepancy_analysis": "Primary improved but secondary cost too high.",
        }
        schema = _load_findings_schema()
        jsonschema.validate(findings, schema)

    def test_tradeoff_verdict_enum_enforced(self) -> None:
        findings = {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-tradeoff",
                    "predicted": "p", "observed": "o",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                    "tradeoff_verdict": "indeterminate",  # not in enum
                },
            ],
            "experiment_valid": True,
            "discrepancy_analysis": "x",
        }
        schema = _load_findings_schema()
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(findings, schema)


# ─── End-to-end behavioral: synthetic measurements → verdict ──────────────


class TestEndToEndTradeoff:
    """Take a tradeoff arm + synthetic deltas, classify, produce verdict."""

    def test_caching_intervention_cost_too_high(self) -> None:
        # 'cache cut latency 20% but used 600MB more memory' against
        # 'budget +500MB' → cost_too_high.
        v = classify_tradeoff(
            primary_change_observed=-22.0,
            primary_change_predicted=-20.0,
            secondary_change_observed=600.0,
            secondary_budget=500.0,
            secondary_direction="increase",
        )
        assert v.verdict == "cost_too_high"

    def test_intervention_unlocks_new_failure_mode_visible(self) -> None:
        """The point of the arm: a 'CONFIRMED primary, REFUTED secondary'
        outcome is now a distinct verdict that doesn't masquerade as a
        confirmation."""
        v = classify_tradeoff(
            primary_change_observed=-50.0,  # huge primary win
            primary_change_predicted=-10.0,
            secondary_change_observed=999.0,  # catastrophic secondary cost
            secondary_budget=1.0,
            secondary_direction="increase",
        )
        # A pre-tradeoff bundle would have called this CONFIRMED.
        # The tradeoff arm makes the cost visible as a distinct verdict.
        assert v.verdict == "cost_too_high"
