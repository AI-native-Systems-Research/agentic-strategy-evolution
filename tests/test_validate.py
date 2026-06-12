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

    def test_sdk_executor_log_under_inputs_passes(self, tmp_path: Path) -> None:
        """#190: SDK dispatcher writes executor_log.jsonl under inputs/.

        The validator must accept the design iter dir even when the SDK has
        teed a streaming log there — that's where the dispatcher belongs.
        """
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "inputs").mkdir(exist_ok=True)
        (d / "inputs" / "executor_log.jsonl").write_text(
            '{"type": "AssistantMessage", "ts": 1.0}\n'
        )
        result = validate_design(d)
        assert result["status"] == "pass"

    def test_campaign_iter_root_extensions_allow_extra_files(self, tmp_path: Path) -> None:
        """#199: campaign.validation.iter_root_extensions adds to the
        global whitelist. Paper-* campaigns need this for analysis_summary.json,
        manifest.json, probe_report.md.
        """
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "analysis_summary.json").write_text("{}")
        (d / "manifest.json").write_text("{}")
        (d / "probe_report.md").write_text("# Probe report")

        # Without the extension: reject all three.
        result = validate_design(d)
        assert result["status"] == "fail"
        assert sum(
            1 for e in result["errors"]
            if any(name in e for name in (
                "analysis_summary.json",
                "manifest.json",
                "probe_report.md",
            ))
        ) == 3

        # With the extension: pass.
        campaign = {
            "validation": {
                "iter_root_extensions": [
                    "analysis_summary.json",
                    "manifest.json",
                    "probe_report.md",
                ],
            },
        }
        result = validate_design(d, campaign=campaign)
        assert result["status"] == "pass", result

    def test_extension_does_not_disable_whitelist(self, tmp_path: Path) -> None:
        """#199: even with extensions, files outside both lists still fail."""
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "analysis_summary.json").write_text("{}")  # extension
        (d / "rogue_file.txt").write_text("nope")        # not extension
        campaign = {
            "validation": {"iter_root_extensions": ["analysis_summary.json"]},
        }
        result = validate_design(d, campaign=campaign)
        assert result["status"] == "fail"
        assert any("rogue_file.txt" in e for e in result["errors"])
        assert not any(
            "analysis_summary.json" in e and "unexpected file" in e
            for e in result["errors"]
        )

    def test_no_validation_block_keeps_strict_default(self, tmp_path: Path) -> None:
        """#199: campaigns that don't declare extensions get the strict default."""
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "analysis_summary.json").write_text("{}")  # not on default whitelist
        result = validate_design(d, campaign={})  # no validation block
        assert result["status"] == "fail"
        assert any("analysis_summary.json" in e for e in result["errors"])

    def test_executor_log_at_iter_root_still_rejected(self, tmp_path: Path) -> None:
        """#190 contract: the iter root remains artifact-only.

        Putting executor_log.jsonl at the iter root is the legacy bug shape
        and should continue to fail the validator. This pins the invariant.
        """
        d = tmp_path / "iter-1"
        _setup_design(d)
        (d / "executor_log.jsonl").write_text(
            '{"type": "AssistantMessage", "ts": 1.0}\n'
        )
        result = validate_design(d)
        assert result["status"] == "fail"
        assert any(
            "executor_log.jsonl" in e and "unexpected file" in e
            for e in result["errors"]
        )


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


# ─── #199 v2 — required_iter_root ────────────────────────────────────────
#
# Sister field to iter_root_extensions: campaigns can declare files that
# MUST exist at the iter root after EXECUTE_ANALYZE completes. Missing
# entries fail validate_execution. Mirrors the #187 / #200 pattern of
# turning silent omissions into structured errors.


class TestRequiredIterRoot:
    """#199 v2: campaign.validation.required_iter_root makes campaign-
    specific iter-root files mandatory at validate_execution time. The
    validator fails with a clear ``required iter-root file missing: X``
    error so operators see what the campaign promised to produce."""

    def test_missing_required_file_fails_execution(
        self, tmp_path: Path,
    ) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        # No analysis_summary.json on disk.
        campaign = {
            "validation": {
                "required_iter_root": ["analysis_summary.json"],
                # Required files are also implicitly allowed (so a
                # campaign doesn't have to list them in both blocks).
            },
        }
        result = validate_execution(d, campaign=campaign)
        assert result["status"] == "fail"
        assert any(
            "required iter-root file missing" in e
            and "analysis_summary.json" in e
            for e in result["errors"]
        ), result["errors"]

    def test_present_required_file_passes(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "analysis_summary.json").write_text("{}")
        campaign = {
            "validation": {
                "required_iter_root": ["analysis_summary.json"],
            },
        }
        result = validate_execution(d, campaign=campaign)
        assert result["status"] == "pass", result

    def test_required_file_implicitly_allowed_at_iter_root(
        self, tmp_path: Path,
    ) -> None:
        """A required file should NOT need to be listed in
        iter_root_extensions to avoid the unexpected-file rejection.
        Required ⊆ allowed — the validator merges them automatically."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "probe_report.md").write_text("# Probe report\n")
        campaign = {
            "validation": {
                "required_iter_root": ["probe_report.md"],
                # Note: iter_root_extensions intentionally omitted.
            },
        }
        result = validate_execution(d, campaign=campaign)
        assert result["status"] == "pass", result
        # Negative: the unexpected-file error must not have fired.
        if result.get("errors"):
            assert not any(
                "unexpected file" in e and "probe_report.md" in e
                for e in result["errors"]
            ), result["errors"]

    def test_missing_required_listed_alongside_other_errors(
        self, tmp_path: Path,
    ) -> None:
        """Required-file check runs even when other errors exist —
        validation collects all errors so the operator sees the full
        picture in one pass."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "findings.json").unlink()  # primary error
        campaign = {
            "validation": {
                "required_iter_root": ["analysis_summary.json"],
            },
        }
        result = validate_execution(d, campaign=campaign)
        assert result["status"] == "fail"
        joined = " | ".join(result["errors"])
        assert "findings.json" in joined
        assert "analysis_summary.json" in joined

    def test_no_required_block_keeps_default_behavior(
        self, tmp_path: Path,
    ) -> None:
        """Campaigns without required_iter_root behave exactly as
        before this PR (backward-compat)."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        # No analysis_summary.json on disk; no required_iter_root either.
        result = validate_execution(d, campaign={})
        assert result["status"] == "pass", result

    def test_required_combined_with_extensions(
        self, tmp_path: Path,
    ) -> None:
        """A campaign declares both required and optional iter-root
        files; only the required one is enforced for presence."""
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "analysis_summary.json").write_text("{}")  # required, present
        # manifest.json is "extensions" (optional) and absent — no error.
        campaign = {
            "validation": {
                "required_iter_root": ["analysis_summary.json"],
                "iter_root_extensions": ["manifest.json"],
            },
        }
        result = validate_execution(d, campaign=campaign)
        assert result["status"] == "pass", result

    def test_required_file_at_design_time_is_allowed_not_required(
        self, tmp_path: Path,
    ) -> None:
        """validate_design merges required ⊆ allowed (so a campaign that
        writes a required file during DESIGN doesn't get rejected by the
        unexpected-file check), but does NOT enforce required-presence
        at design time — most required artifacts are EXECUTE-phase
        outputs (e.g. probe_report.md is written during EXECUTE for
        paper-* campaigns).

        Pins both invariants:
          (a) present-during-design → no "unexpected file" rejection
          (b) absent-during-design → still passes design (no required-presence enforcement)
        """
        campaign = {
            "validation": {"required_iter_root": ["probe_report.md"]},
        }

        # (a) Present during DESIGN — required ⊆ allowed must let it through.
        d1 = tmp_path / "iter-1"
        _setup_design(d1)
        (d1 / "probe_report.md").write_text("# Probe report\n")
        result = validate_design(d1, campaign=campaign)
        assert result["status"] == "pass", result

        # (b) Absent during DESIGN — must still pass (only validate_execution
        # enforces required-presence).
        d2 = tmp_path / "iter-2"
        _setup_design(d2)
        result = validate_design(d2, campaign=campaign)
        assert result["status"] == "pass", result

    def test_required_overlapping_known_root_file_still_enforced(
        self, tmp_path: Path,
    ) -> None:
        """A campaign may declare a file already in _KNOWN_ROOT_FILES
        (e.g. findings.json) as required. The required-presence check
        must still fire when the file is missing, even though the
        unexpected-file check would never have flagged it.
        """
        d = tmp_path / "iter-1"
        _setup_execution(d)
        (d / "findings.json").unlink()  # in _KNOWN_ROOT_FILES, now absent.
        campaign = {
            "validation": {"required_iter_root": ["findings.json"]},
        }
        result = validate_execution(d, campaign=campaign)
        assert result["status"] == "fail"
        assert any(
            "required iter-root file missing" in e and "findings.json" in e
            for e in result["errors"]
        ), result["errors"]

    def test_schema_accepts_required_iter_root(self) -> None:
        """The campaign.schema.yaml must accept the new field — without
        a schema entry, jsonschema validation in nous run would reject
        the campaign before the validator ever sees it."""
        from orchestrator.validate import _load_yaml_schema
        import jsonschema

        schema = _load_yaml_schema("campaign.schema.yaml")
        campaign = {
            "research_question": "Does X work?",
            "run_id": "demo",
            "target_system": {"name": "T", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "validation": {
                "required_iter_root": ["probe_report.md"],
                "iter_root_extensions": ["analysis_summary.json"],
            },
        }
        # Should not raise.
        jsonschema.validate(campaign, schema)
