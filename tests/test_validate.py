"""Tests for orchestrator.validate — design and execution validation gates."""
import json
from pathlib import Path

import pytest
import yaml

from orchestrator.validate import validate_design, validate_execution, _check_unexpected_files


VALID_BUNDLE = {
    "metadata": {"iteration": 1, "family": "test", "research_question": "Does X work?"},
    "arms": [
        {"type": "h-main", "prediction": "+20%", "mechanism": "cause", "diagnostic": "check"},
        {"type": "h-control-negative", "prediction": "no effect", "mechanism": "none", "diagnostic": "check"},
    ],
}

VALID_BUNDLE_WITH_CODE = {
    "metadata": {"iteration": 1, "family": "test", "research_question": "Does X work?"},
    "arms": [
        {
            "type": "h-main", "prediction": "+20%", "mechanism": "cause", "diagnostic": "check",
            "code_changes": [{"file": "src/engine.go", "intent": "enable batch mode", "rationale": "test"}],
        },
        {"type": "h-control-negative", "prediction": "no effect", "mechanism": "none", "diagnostic": "check"},
    ],
}

VALID_FINDINGS = {
    "iteration": 1,
    "bundle_ref": "runs/iter-1/bundle.yaml",
    "arms": [
        {"arm_type": "h-main", "predicted": "+20%", "observed": "+22%",
         "status": "CONFIRMED", "error_type": None, "diagnostic_note": None},
    ],
    "experiment_valid": True,
    "discrepancy_analysis": "All confirmed.",
    "dominant_component_pct": None,
}

VALID_PLAN = {
    "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
    "arms": [
        {"arm_id": "h-main", "conditions": [
            {"name": "baseline", "cmd": "echo baseline"},
        ]},
    ],
}

VALID_PRINCIPLES = [
    {
        "id": "RP-1", "statement": "X works", "confidence": "high",
        "regime": "all", "evidence": ["iter-1"], "contradicts": [],
        "extraction_iteration": 1, "mechanism": "cause",
        "applicability_bounds": "test", "superseded_by": None,
        "category": "domain", "status": "active",
    },
]


def _setup_design(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "problem.md").write_text("## Research Question\nDoes X work?\n")
    (d / "bundle.yaml").write_text(yaml.safe_dump(VALID_BUNDLE))
    (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nTest X.\n")


def _setup_execution(d: Path, bundle: dict | None = None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "bundle.yaml").write_text(yaml.safe_dump(bundle or VALID_BUNDLE))
    (d / "experiment_plan.yaml").write_text(yaml.safe_dump(VALID_PLAN))
    (d / "findings.json").write_text(json.dumps(VALID_FINDINGS, indent=2))
    (d / "principle_updates.json").write_text(json.dumps(VALID_PRINCIPLES, indent=2))


class TestValidateDesign:
    def test_pass(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        result = validate_design(d)
        assert result["status"] == "pass"

    def test_missing_problem(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "problem.md").unlink()
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("problem.md" in e for e in result["errors"])

    def test_empty_problem(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "problem.md").write_text("")
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("empty" in e for e in result["errors"])

    def test_missing_bundle(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "bundle.yaml").unlink()
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("bundle.yaml" in e for e in result["errors"])

    def test_invalid_bundle_schema(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "bundle.yaml").write_text(yaml.safe_dump({"bad": "data"}))
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("schema" in e for e in result["errors"])

    def test_missing_handoff(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "handoff_snapshot.md").unlink()
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("handoff" in e for e in result["errors"])

    def test_unexpected_file_at_root(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "stray_probe.json").write_text("{}")
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any("unexpected file" in e for e in result["errors"])


class TestValidateExecution:
    def test_pass_observe_mode(self, tmp_path: Path) -> None:
        """Observe mode: no code_changes, no patches needed."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        result = validate_execution(d)
        assert result["status"] == "pass"

    def test_pass_evolve_mode(self, tmp_path: Path) -> None:
        """Evolve mode: code_changes present, patches required."""
        d = tmp_path / "iter-1"
        _setup_execution(d, bundle=VALID_BUNDLE_WITH_CODE)
        patches = d / "patches"
        patches.mkdir()
        (patches / "h-main.patch").write_text("diff --git a/src/engine.go\n+batch=true\n")
        result = validate_execution(d)
        assert result["status"] == "pass"

    def test_missing_findings(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "findings.json").unlink()
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("findings.json" in e for e in result["errors"])

    def test_invalid_findings_schema(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "findings.json").write_text(json.dumps({"bad": "data"}))
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("schema" in e for e in result["errors"])

    def test_missing_principles(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "principle_updates.json").unlink()
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("principle_updates" in e for e in result["errors"])

    def test_missing_patches_when_code_changes(self, tmp_path: Path) -> None:
        """Evolve mode: bundle has code_changes but no patches directory."""
        d = tmp_path / "iter-1"
        _setup_execution(d, bundle=VALID_BUNDLE_WITH_CODE)
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("patches" in e for e in result["errors"])

    def test_empty_patch_file(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d, bundle=VALID_BUNDLE_WITH_CODE)
        patches = d / "patches"
        patches.mkdir()
        (patches / "h-main.patch").write_text("")
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("empty" in e for e in result["errors"])

    def test_missing_experiment_plan(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "experiment_plan.yaml").unlink()
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("experiment_plan" in e for e in result["errors"])

    def test_principles_not_a_list(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "principle_updates.json").write_text(json.dumps({"not": "a list"}))
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("list" in e for e in result["errors"])

    def test_principle_missing_id(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "principle_updates.json").write_text(json.dumps([{"statement": "no id"}]))
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("id" in e for e in result["errors"])

    def test_missing_output_file_referenced_in_plan(self, tmp_path: Path) -> None:
        """Plan references output files that don't exist."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        plan_with_output = {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo test",
                 "output": str(d / "results" / "baseline.json")},
            ]}],
        }
        (d / "experiment_plan.yaml").write_text(yaml.safe_dump(plan_with_output))
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("output file" in e for e in result["errors"])

    def test_output_file_exists_passes(self, tmp_path: Path) -> None:
        """Plan references output files that exist — should pass."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        results_dir = d / "results"
        results_dir.mkdir()
        (results_dir / "baseline.json").write_text('{"metric": 42}')
        plan_with_output = {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo test",
                 "output": str(results_dir / "baseline.json")},
            ]}],
        }
        (d / "experiment_plan.yaml").write_text(yaml.safe_dump(plan_with_output))
        result = validate_execution(d)
        assert result["status"] == "pass"

    def test_no_output_field_skips_check(self, tmp_path: Path) -> None:
        """Conditions without output field — no check needed."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        result = validate_execution(d)
        assert result["status"] == "pass"

    def test_missing_input_file_referenced_in_plan(self, tmp_path: Path) -> None:
        """Plan references input files that don't exist."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        plan_with_inputs = {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo test",
                 "inputs": [str(d / "inputs" / "workload.yaml")]},
            ]}],
        }
        (d / "experiment_plan.yaml").write_text(yaml.safe_dump(plan_with_inputs))
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("input file" in e for e in result["errors"])

    def test_input_file_exists_passes(self, tmp_path: Path) -> None:
        """Plan references input files that exist — should pass."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        inputs_dir = d / "inputs"
        inputs_dir.mkdir()
        (inputs_dir / "workload.yaml").write_text("rate: 80")
        plan_with_inputs = {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo test",
                 "inputs": [str(inputs_dir / "workload.yaml")]},
            ]}],
        }
        (d / "experiment_plan.yaml").write_text(yaml.safe_dump(plan_with_inputs))
        result = validate_execution(d)
        assert result["status"] == "pass"

    def test_relative_input_path_resolved(self, tmp_path: Path) -> None:
        """Relative input paths are resolved against iter_dir."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        inputs_dir = d / "inputs"
        inputs_dir.mkdir()
        (inputs_dir / "config.json").write_text("{}")
        plan_with_inputs = {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo test",
                 "inputs": ["inputs/config.json"]},
            ]}],
        }
        (d / "experiment_plan.yaml").write_text(yaml.safe_dump(plan_with_inputs))
        result = validate_execution(d)
        assert result["status"] == "pass"

    def test_input_check_runs_despite_other_errors(self, tmp_path: Path) -> None:
        """Input file check runs even when other validation errors exist."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "findings.json").unlink()  # cause a prior error
        plan_with_inputs = {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main", "conditions": [
                {"name": "baseline", "cmd": "echo test",
                 "inputs": [str(d / "inputs" / "missing.yaml")]},
            ]}],
        }
        (d / "experiment_plan.yaml").write_text(yaml.safe_dump(plan_with_inputs))
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("input file" in e for e in result["errors"])
        assert any("findings" in e for e in result["errors"])

    def test_unexpected_file_at_root(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "workload.yaml").write_text("rate: 80")
        result = validate_execution(d)
        assert result["status"] == "fail"
        assert any("unexpected file" in e for e in result["errors"])


class TestCheckUnexpectedFiles:
    def test_known_files_no_errors(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        d.mkdir()
        (d / "problem.md").write_text("content")
        (d / "bundle.yaml").write_text("content")
        assert _check_unexpected_files(d) == []

    def test_unknown_file_produces_error(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        d.mkdir()
        (d / "problem.md").write_text("content")
        (d / "stray_probe.json").write_text("{}")
        errors = _check_unexpected_files(d)
        assert len(errors) == 1
        assert "unexpected file" in errors[0]
        assert "stray_probe.json" in errors[0]

    def test_subdirectories_ignored(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        d.mkdir()
        (d / "results").mkdir()
        (d / "inputs").mkdir()
        assert _check_unexpected_files(d) == []
