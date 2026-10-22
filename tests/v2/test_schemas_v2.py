"""JSON Schema validation tests for all v2 artifact schemas."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMAS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "orchestrator"
    / "v2"
    / "schemas"
)


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


# ── Minimal valid fixtures ───────────────────────────────────────────────


def _valid_baseline(task_type: str = "debug") -> dict:
    obs_map = {
        "debug": {"reproduced": True, "symptom": "crash", "expected": 0, "actual": 1},
        "verify": {"points": [{"condition": "x=1", "predicted": 10, "measured": 10}]},
        "optimize": {"score": 1.5},
        "policy": {"metrics": {"throughput": 100}},
        "explain": {"symptom": "slow", "control": "baseline"},
        "other": {"metrics": {"latency": 42}},
    }
    return {
        "task_type": task_type,
        "command": "make test",
        "git_sha": "abc1234",
        "observation": obs_map[task_type],
        "metrics_path": "results/metrics.json",
        "noise": {"deterministic": True},
    }


def _valid_problem() -> dict:
    return {
        "task_type": "debug",
        "claims_needed": [
            {"id": "c1", "description": "fix crash", "test_method": "unit test"},
        ],
    }


def _valid_hypothesis(**overrides) -> dict:
    h = {
        "id": "h1",
        "role": "primary",
        "family": "perf",
        "mechanism": "cache hit",
        "prediction": {"metric": "latency", "direction": "decrease"},
        "falsified_if": "latency increases",
        "claim_ids": ["c1"],
    }
    h.update(overrides)
    return h


def _valid_bundle() -> dict:
    return {"hypotheses": [_valid_hypothesis()]}


def _valid_run(**overrides) -> dict:
    r = {
        "id": "r1",
        "hypothesis_id": "h1",
        "role": "treatment",
        "command": "run.sh",
        "parameters": {"batch": 32},
        "seeds": [42],
    }
    r.update(overrides)
    return r


def _valid_plan() -> dict:
    return {"runs": [_valid_run()]}


def _valid_findings_hypothesis(**overrides) -> dict:
    h = {
        "id": "h1",
        "status": "CONFIRMED",
        "error_type": "none",
        "evidence": [],
        "question_answered": True,
        "reason": "metric improved",
    }
    h.update(overrides)
    return h


def _valid_findings() -> dict:
    return {"hypotheses": [_valid_findings_hypothesis()]}


def _valid_principle_updates() -> dict:
    return {
        "updates": [
            {"id": "p1", "text": "cache helps", "finding_ref": "h1", "action": "add"},
        ],
    }


def _valid_answer() -> dict:
    return {
        "answer": "fixed",
        "deliverable": "patch.diff",
        "repro": "make test",
        "claims": [
            {
                "id": "c1",
                "metric": "pass_rate",
                "value": 1.0,
                "condition": "all seeds",
                "evidence": {"path": "results.json", "key": "/pass", "value": True},
            },
        ],
    }


def _valid_ledger_entry() -> dict:
    return {
        "bundle_hash": "a" * 64,
        "cost_meter_usd": 0.05,
        "status": "ok",
        "input_tokens": 1000,
        "output_tokens": 500,
    }


# ── Baseline schema ─────────────────────────────────────────────────────


class TestBaselineSchema:
    schema = _load("baseline.schema.json")

    @pytest.mark.parametrize("task_type", ["debug", "verify", "optimize", "policy", "explain", "other"])
    def test_valid_all_task_types(self, task_type):
        jsonschema.validate(_valid_baseline(task_type), self.schema)

    def test_missing_required_field(self):
        doc = _valid_baseline()
        del doc["command"]
        with pytest.raises(jsonschema.ValidationError, match="'command' is a required"):
            jsonschema.validate(doc, self.schema)

    def test_invalid_task_type_enum(self):
        doc = _valid_baseline()
        doc["task_type"] = "unknown"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_invalid_git_sha_pattern(self):
        doc = _valid_baseline()
        doc["git_sha"] = "ZZZZ"
        with pytest.raises(jsonschema.ValidationError, match="pattern"):
            jsonschema.validate(doc, self.schema)

    def test_git_sha_too_short(self):
        doc = _valid_baseline()
        doc["git_sha"] = "abc"
        with pytest.raises(jsonschema.ValidationError, match="pattern"):
            jsonschema.validate(doc, self.schema)

    def test_debug_observation_missing_reproduced(self):
        doc = _valid_baseline("debug")
        del doc["observation"]["reproduced"]
        with pytest.raises(jsonschema.ValidationError, match="reproduced"):
            jsonschema.validate(doc, self.schema)

    def test_verify_observation_empty_points(self):
        doc = _valid_baseline("verify")
        doc["observation"]["points"] = []
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_optimize_observation_zero_score(self):
        doc = _valid_baseline("optimize")
        doc["observation"]["score"] = 0
        with pytest.raises(jsonschema.ValidationError, match="exclusiveMinimum"):
            jsonschema.validate(doc, self.schema)

    def test_optimize_observation_negative_score(self):
        doc = _valid_baseline("optimize")
        doc["observation"]["score"] = -1
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_policy_observation_empty_metrics(self):
        doc = _valid_baseline("policy")
        doc["observation"]["metrics"] = {}
        with pytest.raises(jsonschema.ValidationError, match="minProperties"):
            jsonschema.validate(doc, self.schema)

    def test_explain_observation_missing_control(self):
        doc = _valid_baseline("explain")
        del doc["observation"]["control"]
        with pytest.raises(jsonschema.ValidationError, match="control"):
            jsonschema.validate(doc, self.schema)

    def test_other_observation_empty_metrics(self):
        doc = _valid_baseline("other")
        doc["observation"]["metrics"] = {}
        with pytest.raises(jsonschema.ValidationError, match="minProperties"):
            jsonschema.validate(doc, self.schema)

    def test_extra_field_accepted(self):
        doc = _valid_baseline()
        doc["extra"] = {"custom": "value"}
        jsonschema.validate(doc, self.schema)

    def test_additional_property_rejected(self):
        doc = _valid_baseline()
        doc["unknown_top_level"] = 42
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(doc, self.schema)

    def test_optional_task_type_reason(self):
        doc = _valid_baseline()
        doc["task_type_reason"] = "it looks like a bug"
        jsonschema.validate(doc, self.schema)


# ── Problem schema ───────────────────────────────────────────────────────


class TestProblemSchema:
    schema = _load("problem.schema.json")

    def test_valid_minimal(self):
        jsonschema.validate(_valid_problem(), self.schema)

    def test_missing_task_type(self):
        doc = _valid_problem()
        del doc["task_type"]
        with pytest.raises(jsonschema.ValidationError, match="task_type"):
            jsonschema.validate(doc, self.schema)

    def test_empty_claims_needed(self):
        doc = _valid_problem()
        doc["claims_needed"] = []
        with pytest.raises(jsonschema.ValidationError, match="minItems"):
            jsonschema.validate(doc, self.schema)

    def test_claim_missing_id(self):
        doc = _valid_problem()
        del doc["claims_needed"][0]["id"]
        with pytest.raises(jsonschema.ValidationError, match="'id' is a required"):
            jsonschema.validate(doc, self.schema)

    def test_optional_fields_accepted(self):
        doc = _valid_problem()
        doc["claims_needed"][0]["min_seeds"] = 5
        doc["claims_needed"][0]["needs_ci"] = True
        doc["claims_needed"][0]["conditions"] = ["linux", "macos"]
        jsonschema.validate(doc, self.schema)

    def test_min_seeds_must_be_positive(self):
        doc = _valid_problem()
        doc["claims_needed"][0]["min_seeds"] = 0
        with pytest.raises(jsonschema.ValidationError, match="minimum"):
            jsonschema.validate(doc, self.schema)

    def test_additional_property_in_claim_rejected(self):
        doc = _valid_problem()
        doc["claims_needed"][0]["bogus"] = True
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(doc, self.schema)


# ── Bundle schema ────────────────────────────────────────────────────────


class TestBundleSchema:
    schema = _load("bundle.schema.json")

    def test_valid_minimal(self):
        jsonschema.validate(_valid_bundle(), self.schema)

    def test_empty_hypotheses(self):
        with pytest.raises(jsonschema.ValidationError, match="minItems"):
            jsonschema.validate({"hypotheses": []}, self.schema)

    def test_hypothesis_missing_prediction(self):
        h = _valid_hypothesis()
        del h["prediction"]
        with pytest.raises(jsonschema.ValidationError, match="prediction"):
            jsonschema.validate({"hypotheses": [h]}, self.schema)

    @pytest.mark.parametrize("direction", ["increase", "decrease", "equal", "change"])
    def test_valid_prediction_directions(self, direction):
        h = _valid_hypothesis()
        h["prediction"]["direction"] = direction
        jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_invalid_prediction_direction(self):
        h = _valid_hypothesis()
        h["prediction"]["direction"] = "sideways"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_prediction_additional_property_rejected(self):
        h = _valid_hypothesis()
        h["prediction"]["extra_field"] = 1
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_optional_control_accepted(self):
        h = _valid_hypothesis(control="baseline run")
        jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_optional_no_control_reason_accepted(self):
        h = _valid_hypothesis(no_control_reason="observational only")
        jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_single_family_reason_accepted(self):
        doc = _valid_bundle()
        doc["single_family_reason"] = "all hypotheses are about caching"
        jsonschema.validate(doc, self.schema)

    def test_magnitude_or_threshold_accepted(self):
        h = _valid_hypothesis()
        h["prediction"]["magnitude_or_threshold"] = 0.1
        jsonschema.validate({"hypotheses": [h]}, self.schema)


# ── Plan schema ──────────────────────────────────────────────────────────


class TestPlanSchema:
    schema = _load("plan.schema.json")

    def test_valid_minimal(self):
        jsonschema.validate(_valid_plan(), self.schema)

    def test_empty_runs(self):
        with pytest.raises(jsonschema.ValidationError, match="minItems"):
            jsonschema.validate({"runs": []}, self.schema)

    @pytest.mark.parametrize("role", ["treatment", "control"])
    def test_valid_roles(self, role):
        run = _valid_run(role=role)
        jsonschema.validate({"runs": [run]}, self.schema)

    def test_invalid_role(self):
        run = _valid_run(role="placebo")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"runs": [run]}, self.schema)

    def test_empty_seeds(self):
        run = _valid_run(seeds=[])
        with pytest.raises(jsonschema.ValidationError, match="minItems"):
            jsonschema.validate({"runs": [run]}, self.schema)

    def test_seeds_must_be_integers(self):
        run = _valid_run(seeds=[1.5])
        with pytest.raises(jsonschema.ValidationError, match="integer"):
            jsonschema.validate({"runs": [run]}, self.schema)

    def test_optional_wait_for(self):
        run = _valid_run(wait_for="r0")
        jsonschema.validate({"runs": [run]}, self.schema)

    def test_optional_workload_changes(self):
        run = _valid_run(workload_changes=["batch_size"])
        jsonschema.validate({"runs": [run]}, self.schema)

    def test_missing_required_field_in_run(self):
        run = _valid_run()
        del run["command"]
        with pytest.raises(jsonschema.ValidationError, match="command"):
            jsonschema.validate({"runs": [run]}, self.schema)


# ── Findings schema ──────────────────────────────────────────────────────


class TestFindingsSchema:
    schema = _load("findings.schema.json")

    def test_valid_minimal(self):
        jsonschema.validate(_valid_findings(), self.schema)

    @pytest.mark.parametrize(
        "status",
        ["CONFIRMED", "PARTIALLY_CONFIRMED", "REFUTED", "INCONCLUSIVE"],
    )
    def test_valid_statuses(self, status):
        doc = {"hypotheses": [_valid_findings_hypothesis(status=status)]}
        jsonschema.validate(doc, self.schema)

    def test_invalid_status(self):
        doc = {"hypotheses": [_valid_findings_hypothesis(status="MAYBE")]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    @pytest.mark.parametrize(
        "error_type", ["direction", "magnitude", "regime", "shape", "none"]
    )
    def test_valid_error_types(self, error_type):
        doc = {"hypotheses": [_valid_findings_hypothesis(error_type=error_type)]}
        jsonschema.validate(doc, self.schema)

    def test_invalid_error_type(self):
        doc = {"hypotheses": [_valid_findings_hypothesis(error_type="typo")]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_evidence_item_structure(self):
        h = _valid_findings_hypothesis()
        h["evidence"] = [{"path": "f.json", "key": "/x", "value": 1}]
        jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_evidence_item_extra_field(self):
        h = _valid_findings_hypothesis()
        h["evidence"] = [{"path": "f.json", "key": "/x", "value": 1, "extra": True}]
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_optional_best(self):
        doc = _valid_findings()
        doc["best"] = {"metric": "latency", "value": 42}
        jsonschema.validate(doc, self.schema)

    def test_best_missing_metric(self):
        doc = _valid_findings()
        doc["best"] = {"value": 42}
        with pytest.raises(jsonschema.ValidationError, match="metric"):
            jsonschema.validate(doc, self.schema)

    def test_optional_claims(self):
        h = _valid_findings_hypothesis()
        h["claims"] = [
            {"claim_id": "c1", "metric": "pass_rate", "condition": "all", "value": 1.0}
        ]
        jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_optional_noise_fields(self):
        h = _valid_findings_hypothesis()
        h["noise_sd"] = 0.01
        h["noise_condition"] = "3 seeds"
        jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_noise_unmeasured_must_be_true(self):
        h = _valid_findings_hypothesis()
        h["noise_unmeasured"] = False
        with pytest.raises(jsonschema.ValidationError, match="const"):
            jsonschema.validate({"hypotheses": [h]}, self.schema)

    def test_question_answered_must_be_bool(self):
        h = _valid_findings_hypothesis()
        h["question_answered"] = "yes"
        with pytest.raises(jsonschema.ValidationError, match="boolean"):
            jsonschema.validate({"hypotheses": [h]}, self.schema)


# ── Principle updates schema ─────────────────────────────────────────────


class TestPrincipleUpdatesSchema:
    schema = _load("principle_updates.schema.json")

    def test_valid_minimal(self):
        jsonschema.validate(_valid_principle_updates(), self.schema)

    def test_empty_updates_accepted(self):
        jsonschema.validate({"updates": []}, self.schema)

    @pytest.mark.parametrize("action", ["add", "revise", "remove"])
    def test_valid_actions(self, action):
        doc = {
            "updates": [
                {"id": "p1", "text": "rule", "finding_ref": "h1", "action": action}
            ]
        }
        jsonschema.validate(doc, self.schema)

    def test_invalid_action(self):
        doc = {
            "updates": [
                {"id": "p1", "text": "rule", "finding_ref": "h1", "action": "merge"}
            ]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_missing_finding_ref(self):
        doc = {"updates": [{"id": "p1", "text": "rule", "action": "add"}]}
        with pytest.raises(jsonschema.ValidationError, match="finding_ref"):
            jsonschema.validate(doc, self.schema)


# ── Answer schema ────────────────────────────────────────────────────────


class TestAnswerSchema:
    schema = _load("answer.schema.json")

    def test_valid_minimal(self):
        jsonschema.validate(_valid_answer(), self.schema)

    def test_empty_claims_accepted(self):
        doc = _valid_answer()
        doc["claims"] = []
        jsonschema.validate(doc, self.schema)

    def test_missing_answer_field(self):
        doc = _valid_answer()
        del doc["answer"]
        with pytest.raises(jsonschema.ValidationError, match="answer"):
            jsonschema.validate(doc, self.schema)

    def test_claim_evidence_extra_field(self):
        doc = _valid_answer()
        doc["claims"][0]["evidence"]["bogus"] = 1
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(doc, self.schema)

    def test_claim_missing_evidence(self):
        doc = _valid_answer()
        del doc["claims"][0]["evidence"]
        with pytest.raises(jsonschema.ValidationError, match="evidence"):
            jsonschema.validate(doc, self.schema)


# ── Ledger entry schema ─────────────────────────────────────────────────


class TestLedgerEntrySchema:
    schema = _load("ledger_entry.schema.json")

    def test_valid_full(self):
        jsonschema.validate(_valid_ledger_entry(), self.schema)

    def test_empty_object_valid(self):
        """All fields are optional; additionalProperties is true."""
        jsonschema.validate({}, self.schema)

    def test_additional_properties_allowed(self):
        doc = _valid_ledger_entry()
        doc["iteration"] = 3
        doc["whatever"] = "allowed"
        jsonschema.validate(doc, self.schema)

    def test_invalid_bundle_hash_pattern(self):
        doc = {"bundle_hash": "not-a-sha256"}
        with pytest.raises(jsonschema.ValidationError, match="pattern"):
            jsonschema.validate(doc, self.schema)

    def test_bundle_hash_valid_64_hex(self):
        doc = {"bundle_hash": "f" * 64}
        jsonschema.validate(doc, self.schema)

    @pytest.mark.parametrize("status", ["ok", "partial", "failed", "skipped"])
    def test_valid_statuses(self, status):
        jsonschema.validate({"status": status}, self.schema)

    def test_invalid_status(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"status": "error"}, self.schema)

    def test_cost_must_be_non_negative(self):
        with pytest.raises(jsonschema.ValidationError, match="minimum"):
            jsonschema.validate({"cost_meter_usd": -0.01}, self.schema)

    def test_claims_matched_fraction_range(self):
        jsonschema.validate({"claims_matched_fraction": 0.0}, self.schema)
        jsonschema.validate({"claims_matched_fraction": 1.0}, self.schema)
        with pytest.raises(jsonschema.ValidationError, match="maximum"):
            jsonschema.validate({"claims_matched_fraction": 1.5}, self.schema)

    def test_token_counts_must_be_non_negative_integers(self):
        jsonschema.validate({"input_tokens": 0}, self.schema)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"input_tokens": -1}, self.schema)
