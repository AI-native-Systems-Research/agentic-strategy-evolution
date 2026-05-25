"""Behavioral tests for the H-dose-response arm (issue #157).

Tests assert what's on disk (bundles, findings) and the deterministic
classifier's verdicts on synthetic numeric series. No live LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from orchestrator.findings_classifier import (
    classify_dose_shape,
    shape_matches,
    VALID_SHAPES,
)
from orchestrator.validate import validate_design


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _load_findings_schema() -> dict:
    return json.loads((SCHEMAS_DIR / "findings.schema.json").read_text())


# ─── Shape classifier on synthetic numeric data ───────────────────────────


class TestShapeClassifier:
    """Each shape must be detected from a clean synthetic series."""

    def test_monotone_increasing(self) -> None:
        assert classify_dose_shape([1.0, 2.0, 3.0, 4.0]) == "monotone_increasing"

    def test_monotone_decreasing(self) -> None:
        assert classify_dose_shape([10.0, 8.0, 6.0, 4.0]) == "monotone_decreasing"

    def test_u_shaped(self) -> None:
        assert classify_dose_shape([5.0, 3.0, 2.0, 4.0, 7.0]) == "u_shaped"

    def test_inverted_u(self) -> None:
        assert classify_dose_shape([1.0, 4.0, 7.0, 5.0, 2.0]) == "inverted_u"

    def test_saturating(self) -> None:
        # Big jump, then near-flat — classic saturation curve.
        assert classify_dose_shape([0.0, 10.0, 11.0, 11.2, 11.3]) == "saturating"

    def test_flat(self) -> None:
        # Variation < 5% of mean.
        assert classify_dose_shape([100.0, 101.0, 99.5, 100.2]) == "flat"

    def test_noisy_when_too_short(self) -> None:
        assert classify_dose_shape([1.0, 2.0]) == "noisy"
        assert classify_dose_shape([]) == "noisy"

    def test_noisy_zigzag(self) -> None:
        # Multiple sign flips → noisy, not a clean U or inverted-U.
        assert classify_dose_shape([1.0, 5.0, 2.0, 6.0, 3.0]) == "noisy"

    def test_classifier_returns_valid_enum(self) -> None:
        # Every output is one of the schema's enum values OR "noisy".
        all_valid = set(VALID_SHAPES) | {"noisy"}
        for series in (
            [1, 2, 3], [3, 2, 1], [1, 5, 1], [5, 1, 5], [1, 1, 1],
            [0, 10, 11, 11], [1, 5, 2, 6, 3],
        ):
            assert classify_dose_shape(series) in all_valid


class TestShapeMatching:
    """shape_matches encodes loose equivalences (saturating ~ monotone)."""

    def test_exact_match(self) -> None:
        assert shape_matches("monotone_increasing", "monotone_increasing")
        assert shape_matches("u_shaped", "u_shaped")

    def test_saturating_satisfies_monotone(self) -> None:
        assert shape_matches("monotone_increasing", "saturating")
        assert shape_matches("monotone_decreasing", "saturating")

    def test_monotone_does_not_satisfy_other_monotone(self) -> None:
        assert not shape_matches("monotone_increasing", "monotone_decreasing")

    def test_noisy_never_matches(self) -> None:
        assert not shape_matches("monotone_increasing", "noisy")
        assert not shape_matches("flat", "noisy")

    def test_none_inputs_never_match(self) -> None:
        assert not shape_matches(None, "monotone_increasing")
        assert not shape_matches("monotone_increasing", None)


# ─── Bundle schema accepts h-dose-response ────────────────────────────────


VALID_DOSE_BUNDLE = {
    "metadata": {"iteration": 1, "family": "test", "research_question": "How should X be set?"},
    "arms": [
        {
            "type": "h-main",
            "prediction": "Increasing batch_size decreases latency",
            "mechanism": "Amortizes fixed overhead",
            "diagnostic": "Check overhead per batch",
        },
        {
            "type": "h-dose-response",
            "prediction": "Latency decreases monotonically as batch_size increases",
            "mechanism": "Per-call overhead amortizes across the batch",
            "diagnostic": "If flat, overhead is not the bottleneck",
            "knob": "batch_size",
            "values": [1, 4, 16, 64],
            "metric": "latency_ms",
            "expected_shape": "monotone_decreasing",
        },
    ],
}


class TestBundleSchemaAcceptance:
    def test_valid_dose_response_bundle_passes_schema(self) -> None:
        schema = _load_bundle_schema()
        jsonschema.validate(VALID_DOSE_BUNDLE, schema)  # no raise

    def test_validate_design_accepts_dose_response(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        d.mkdir()
        (d / "problem.md").write_text("## Research Question\n\nHow should batch_size be set?\n")
        (d / "bundle.yaml").write_text(yaml.safe_dump(VALID_DOSE_BUNDLE))
        (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nTest\n")
        result = validate_design(d)
        assert result["status"] == "pass", result.get("errors")


# ─── Cross-field validation rejects malformed dose-response arms ──────────


def _bundle_with_dose_arm(**overrides: object) -> dict:
    arm = {
        "type": "h-dose-response",
        "prediction": "monotone decrease in latency",
        "mechanism": "amortization",
        "diagnostic": "check overhead",
        "knob": "batch_size",
        "values": [1, 4, 16, 64],
        "metric": "latency_ms",
        "expected_shape": "monotone_decreasing",
    }
    arm.update(overrides)
    return {
        "metadata": {"iteration": 1, "family": "t", "research_question": "q?"},
        "arms": [arm],
    }


def _setup_design_with_bundle(d: Path, bundle: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "problem.md").write_text("## RQ\nq?\n")
    (d / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")


class TestDoseResponseCrossFieldValidation:
    def test_rejects_too_few_values(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        # Schema has minItems 3, so 2 values is rejected at the JSON
        # Schema level (jsonschema renders this as "is too short").
        bundle = _bundle_with_dose_arm(values=[1, 2])
        _setup_design_with_bundle(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"
        joined = " | ".join(result["errors"]).lower()
        assert "too short" in joined or "values" in joined or "minitems" in joined, result["errors"]

    def test_rejects_duplicate_values(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        # uniqueItems will trip in schema first.
        bundle = _bundle_with_dose_arm(values=[1, 2, 2, 3])
        _setup_design_with_bundle(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"

    def test_rejects_invalid_expected_shape(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        bundle = _bundle_with_dose_arm(expected_shape="banana_curve")
        _setup_design_with_bundle(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"
        joined = " | ".join(result["errors"])
        assert "banana_curve" in joined or "is not one of" in joined

    def test_rejects_missing_knob(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        # Build arm without the knob field — schema accepts (it's optional);
        # the cross-field validator must catch it.
        arm = {
            "type": "h-dose-response",
            "prediction": "monotone decrease",
            "mechanism": "amortization",
            "diagnostic": "check overhead",
            "values": [1, 4, 16],
            "metric": "latency_ms",
            "expected_shape": "monotone_decreasing",
        }
        bundle = {
            "metadata": {"iteration": 1, "family": "t", "research_question": "q?"},
            "arms": [arm],
        }
        _setup_design_with_bundle(d, bundle)
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("knob" in e for e in result["errors"])


# ─── Findings schema accepts dose-response arm result fields ──────────────


class TestFindingsSchemaAcceptance:
    def test_dose_arm_result_with_shape_match_validates(self) -> None:
        findings = {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-dose-response",
                    "predicted": "monotone decrease in latency",
                    "observed": "latency dropped from 100ms to 12ms",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                    "observed_shape": "monotone_decreasing",
                    "shape_match": True,
                    "dose_points": [
                        {"value": 1, "metric": 100.0},
                        {"value": 4, "metric": 35.0},
                        {"value": 16, "metric": 12.0},
                    ],
                },
            ],
            "experiment_valid": True,
            "discrepancy_analysis": "Shape matched.",
        }
        schema = _load_findings_schema()
        jsonschema.validate(findings, schema)

    def test_shape_mismatch_error_type_validates(self) -> None:
        findings = {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-dose-response",
                    "predicted": "monotone increase",
                    "observed": "flat",
                    "status": "REFUTED",
                    "error_type": "shape_mismatch",
                    "diagnostic_note": "no response detected",
                    "observed_shape": "flat",
                    "shape_match": False,
                    "dose_points": [
                        {"value": 1, "metric": 50.0},
                        {"value": 4, "metric": 50.5},
                        {"value": 16, "metric": 49.8},
                    ],
                },
            ],
            "experiment_valid": True,
            "discrepancy_analysis": "Knob has no effect on metric.",
        }
        schema = _load_findings_schema()
        jsonschema.validate(findings, schema)


# ─── End-to-end behavioral: classify synthetic data, judge against expected ──


class TestEndToEndShapeJudgement:
    """Simulate the executor: take the arm's expected_shape and synthetic
    measurements, classify, and produce shape_match — no LLM."""

    def test_predicted_increase_data_increases_confirmed(self) -> None:
        expected = "monotone_increasing"
        observed_metrics = [10.0, 20.0, 35.0, 50.0]
        observed = classify_dose_shape(observed_metrics)
        assert observed == "monotone_increasing"
        assert shape_matches(expected, observed) is True

    def test_predicted_decrease_data_flat_refuted(self) -> None:
        expected = "monotone_decreasing"
        observed_metrics = [50.0, 50.2, 50.1, 49.9]
        observed = classify_dose_shape(observed_metrics)
        assert observed == "flat"
        assert shape_matches(expected, observed) is False

    def test_predicted_u_data_inverted_u_refuted(self) -> None:
        expected = "u_shaped"
        observed_metrics = [1.0, 4.0, 7.0, 5.0, 2.0]
        observed = classify_dose_shape(observed_metrics)
        assert observed == "inverted_u"
        assert shape_matches(expected, observed) is False
