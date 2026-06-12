"""Behavioral tests for ground-truth independence check (issue #85).

Prevents tautological experiment design at the validator boundary.
A bundle that tests a detector against a ground truth that's the same
quantity with a different threshold (the `dual-gate-generalization`
failure mode — *\"algebraically guaranteed, not empirically discovered\"*)
gets rejected before the experiment runs.

Test contract:
  - Schema accepts optional `ground_truth` block on the bundle root with
    {definition, measurement_type, detector_measurement_type,
     independence_argument, shares_computation_with_detector}.
  - validate_design REJECTS bundles with shares_computation_with_detector=true.
  - validate_design WARNS (but doesn't fail) when independence_argument is
    missing on a bundle that declares ground_truth.
  - Legacy bundles without ground_truth validate unchanged.
  - Real-world fixtures (the four tautological campaign cases from #84)
    fail the check; the steady-state-oracle remediation passes.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.validate import _validate_ground_truth_independence, validate_design


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _bundle(
    *,
    arms: list[dict] | None = None,
    ground_truth: dict | None = None,
) -> dict:
    bundle: dict = {
        "metadata": {"iteration": 1, "family": "test", "research_question": "q?"},
        "arms": arms or [{
            "type": "h-main",
            "prediction": "p", "mechanism": "m", "diagnostic": "d",
        }],
    }
    if ground_truth is not None:
        bundle["ground_truth"] = ground_truth
    return bundle


def _setup_iter_dir(tmp_path: Path, bundle: dict) -> Path:
    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "problem.md").write_text("## RQ\nq?\n")
    (iter_dir / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    return iter_dir


# ─── Schema accepts ground_truth as optional additive block ───────────────


class TestSchemaAcceptsGroundTruth:
    def test_ground_truth_block_validates(self) -> None:
        bundle = _bundle(ground_truth={
            "definition": "queue depth > 0 at end",
            "measurement_type": "stock",
            "detector_measurement_type": "flow",
            "independence_argument": (
                "Queue depth is instantaneous; detector RD is cumulative. "
                "They can disagree under in-flight requests."
            ),
            "shares_computation_with_detector": False,
        })
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_minimal_ground_truth_validates(self) -> None:
        """Only `definition` and `shares_computation_with_detector` are required."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": False,
        })
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_legacy_bundle_without_ground_truth_validates(self) -> None:
        """Backward compat: existing bundles still pass."""
        jsonschema.validate(_bundle(), _load_bundle_schema())

    def test_ground_truth_missing_definition_rejected(self) -> None:
        bundle = _bundle(ground_truth={
            "shares_computation_with_detector": False,
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())

    def test_ground_truth_unknown_measurement_type_rejected(self) -> None:
        bundle = _bundle(ground_truth={
            "definition": "x",
            "measurement_type": "vibe",  # not in enum
            "shares_computation_with_detector": False,
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())


# ─── Cross-field validator rejects tautologies ────────────────────────────


class TestIndependenceValidator:
    def test_tautological_bundle_rejected(self) -> None:
        """The composite-saturation-detection failure mode."""
        bundle = _bundle(ground_truth={
            "definition": "completion_fraction < 1 - 1/sqrt(N)",
            "shares_computation_with_detector": True,
        })
        errors = _validate_ground_truth_independence(bundle)
        assert errors
        assert any("tautolog" in e.lower() or "shares_computation" in e
                   for e in errors)

    def test_independent_bundle_passes(self) -> None:
        """The steady-state-oracle remediation."""
        bundle = _bundle(ground_truth={
            "definition": "scheduling_delay growing over time",
            "measurement_type": "trend",
            "detector_measurement_type": "flow",
            "independence_argument": (
                "Scheduling delay measures queue wait; RD counts completions. "
                "Different physical signals."
            ),
            "shares_computation_with_detector": False,
        })
        errors = _validate_ground_truth_independence(bundle)
        assert errors == []

    def test_legacy_bundle_without_ground_truth_passes(self) -> None:
        """No ground_truth block ⇒ no check applies. Legacy bundles
        validate unchanged."""
        errors = _validate_ground_truth_independence(_bundle())
        assert errors == []

    def test_missing_independence_argument_warns(self) -> None:
        """When ground_truth is declared but no independence_argument,
        the check returns a warning (string starting with 'WARN:')."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": False,
        })
        errors = _validate_ground_truth_independence(bundle)
        assert any(e.startswith("WARN:") for e in errors)
        # But no hard error
        assert not any(not e.startswith("WARN:") for e in errors)

    def test_same_measurement_type_warns(self) -> None:
        """When detector and ground truth use the same measurement_type
        (e.g., both 'flow'), warn — they may secretly be the same signal."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "measurement_type": "flow",
            "detector_measurement_type": "flow",
            "independence_argument": "they differ for reasons",
            "shares_computation_with_detector": False,
        })
        errors = _validate_ground_truth_independence(bundle)
        assert any(e.startswith("WARN:") and "measurement_type" in e
                   for e in errors)


# ─── End-to-end through validate_design ──────────────────────────────────


class TestValidateDesignIntegration:
    def test_tautological_bundle_fails_validate_design(
        self, tmp_path: Path,
    ) -> None:
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": True,
        })
        iter_dir = _setup_iter_dir(tmp_path, bundle)
        result = validate_design(iter_dir)
        assert result["status"] == "fail"
        assert any("tautolog" in e.lower() or "shares_computation" in e
                   for e in result["errors"])

    def test_independent_bundle_passes_validate_design(
        self, tmp_path: Path,
    ) -> None:
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": False,
            "independence_argument": "different signals",
        })
        iter_dir = _setup_iter_dir(tmp_path, bundle)
        result = validate_design(iter_dir)
        assert result["status"] == "pass", result.get("errors")

    def test_warnings_do_not_fail_validate_design(
        self, tmp_path: Path,
    ) -> None:
        """A bundle with WARN-level issues but no hard errors still passes
        validate_design — warnings are advisory."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": False,
            # missing independence_argument ⇒ WARN
        })
        iter_dir = _setup_iter_dir(tmp_path, bundle)
        result = validate_design(iter_dir)
        assert result["status"] == "pass", result.get("errors")

    def test_warnings_are_surfaced_not_dropped(self, tmp_path: Path) -> None:
        """PR #279 review: WARN-prefixed independence advisories must be
        returned in result['warnings'], not silently discarded."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": False,
            # missing independence_argument ⇒ WARN
        })
        iter_dir = _setup_iter_dir(tmp_path, bundle)
        result = validate_design(iter_dir)
        assert result["status"] == "pass"
        warnings = result.get("warnings", [])
        assert any(w.startswith("WARN:") for w in warnings), (
            f"expected a surfaced WARN entry, got {warnings}"
        )
