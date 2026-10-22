"""Behavioral tests for orchestrator.v2.validators."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from orchestrator.v2.validators import (
    ValidatorContext,
    bundle_hash,
    validate_artifact,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path):
    return ValidatorContext(work_dir=tmp_path, iter_dir=tmp_path)


def _make_hypothesis(
    id_: str = "h1",
    family: str = "fam-a",
    control: str | None = "baseline run",
    claim_ids: list[str] | None = None,
):
    h = {
        "id": id_,
        "role": "primary",
        "family": family,
        "mechanism": "increase batch size",
        "prediction": {"metric": "throughput", "direction": "increase"},
        "falsified_if": "throughput decreases",
        "claim_ids": claim_ids or ["c1"],
    }
    if control:
        h["control"] = control
    return h


def _valid_baseline(task_type: str = "debug") -> dict:
    base = {
        "task_type": task_type,
        "command": "pytest -q",
        "git_sha": "abc1234",
        "metrics_path": "results/metrics.json",
        "noise": {"deterministic": True},
    }
    if task_type == "debug":
        base["observation"] = {
            "reproduced": True,
            "symptom": "crash on input X",
            "expected": 0,
            "actual": 1,
        }
    elif task_type == "verify":
        base["observation"] = {
            "points": [{"condition": "c1", "predicted": 1.0, "measured": 1.0}]
        }
    elif task_type == "optimize":
        base["observation"] = {"score": 42.0}
    elif task_type == "policy":
        base["observation"] = {"metrics": {"latency": 10}}
    elif task_type == "explain":
        base["observation"] = {"symptom": "slow", "control": "fast"}
    elif task_type == "other":
        base["observation"] = {"metrics": {"foo": 1}}
    return base


def _valid_problem() -> dict:
    return {
        "task_type": "debug",
        "claims_needed": [
            {"id": "c1", "description": "fix crash", "test_method": "pytest"}
        ],
    }


def _valid_bundle(families: int = 2) -> dict:
    hyps = []
    for i in range(max(families, 1)):
        hyps.append(
            _make_hypothesis(
                id_=f"h{i+1}",
                family=f"fam-{'abcdefgh'[i]}",
                claim_ids=["c1"],
            )
        )
    return {"hypotheses": hyps}


def _valid_plan() -> dict:
    return {
        "runs": [
            {
                "id": "r1",
                "hypothesis_id": "h1",
                "role": "treatment",
                "command": "pytest -q",
                "parameters": {},
                "seeds": [42],
            }
        ]
    }


def _valid_findings(tmp_path: Path) -> dict:
    evidence_file = tmp_path / "results.json"
    evidence_file.write_text(json.dumps({"throughput": 100}))
    return {
        "hypotheses": [
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [
                    {
                        "path": "results.json",
                        "key": "/throughput",
                        "value": 100,
                    }
                ],
                "noise_sd": 0.5,
                "noise_condition": "3 seeds",
                "question_answered": True,
                "reason": "throughput increased as predicted",
            }
        ]
    }


def _valid_principle_updates() -> dict:
    return {
        "updates": [
            {
                "id": "p1",
                "text": "Batch size matters",
                "finding_ref": "h1",
                "action": "add",
            }
        ]
    }


def _valid_answer(tmp_path: Path) -> dict:
    ev_file = tmp_path / "final.json"
    ev_file.write_text(json.dumps({"metric": 42}))
    return {
        "answer": "The fix resolves the crash.",
        "deliverable": "patch applied",
        "repro": "run pytest -q",
        "claims": [
            {
                "id": "c1",
                "metric": "pass_rate",
                "value": 1.0,
                "condition": "all tests pass",
                "evidence": {
                    "path": "final.json",
                    "key": "/metric",
                    "value": 42,
                },
            }
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


# ── 1. Extra-field handling (B5) ─────────────────────────────────────────


class TestExtraFieldHandling:
    def test_unknown_keys_moved_to_extra(self, ctx):
        data = _valid_problem()
        data["mystery_key"] = "hello"
        errs = validate_artifact("problem", data, ctx)
        assert "mystery_key" not in data
        assert data["extra"]["mystery_key"] == "hello"
        assert any("mystery_key" in e and "moved to extra" in e for e in errs)

    def test_multiple_unknown_keys(self, ctx):
        data = _valid_problem()
        data["alpha"] = 1
        data["beta"] = 2
        errs = validate_artifact("problem", data, ctx)
        assert data["extra"]["alpha"] == 1
        assert data["extra"]["beta"] == 2
        warnings = [e for e in errs if "moved to extra" in e]
        assert len(warnings) == 2

    def test_no_unknown_keys_no_warnings(self, ctx):
        data = _valid_problem()
        errs = validate_artifact("problem", data, ctx)
        assert not any("moved to extra" in e for e in errs)


# ── 2. Unknown artifact type ─────────────────────────────────────────────


class TestUnknownArtifactType:
    def test_returns_error(self, ctx):
        errs = validate_artifact("nonexistent", {}, ctx)
        assert len(errs) == 1
        assert "unknown artifact type" in errs[0]


# ── 3. Schema failures ──────────────────────────────────────────────────


class TestSchemaFailures:
    def test_missing_required_field(self, ctx):
        errs = validate_artifact("problem", {"task_type": "debug"}, ctx)
        assert any(e.startswith("schema:") for e in errs)

    def test_invalid_enum_value(self, ctx):
        data = _valid_problem()
        data["task_type"] = "not_a_type"
        errs = validate_artifact("problem", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_wrong_type(self, ctx):
        errs = validate_artifact("problem", {"task_type": 123, "claims_needed": []}, ctx)
        assert any("schema:" in e for e in errs)

    def test_baseline_bad_git_sha(self, ctx):
        data = _valid_baseline()
        data["git_sha"] = "ZZZZ"
        errs = validate_artifact("baseline", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_plan_invalid_role(self, ctx):
        data = _valid_plan()
        data["runs"][0]["role"] = "observer"
        errs = validate_artifact("plan", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_plan_empty_seeds(self, ctx):
        data = _valid_plan()
        data["runs"][0]["seeds"] = []
        errs = validate_artifact("plan", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_findings_invalid_status(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["status"] = "UNKNOWN"
        errs = validate_artifact("findings", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_empty_hypotheses_bundle(self, ctx):
        errs = validate_artifact("bundle", {"hypotheses": []}, ctx)
        assert any("schema:" in e for e in errs)


# ── 4. Bundle semantics ─────────────────────────────────────────────────


class TestBundleSemantics:
    def test_valid_bundle_two_families(self, ctx):
        data = _valid_bundle(families=2)
        errs = validate_artifact("bundle", data, ctx)
        assert not errs

    def test_single_family_no_reason(self, ctx):
        data = _valid_bundle(families=1)
        errs = validate_artifact("bundle", data, ctx)
        assert any("2 distinct family" in e for e in errs)

    def test_single_family_with_reason(self, ctx):
        data = _valid_bundle(families=1)
        data["single_family_reason"] = "Only one mechanism applies"
        errs = validate_artifact("bundle", data, ctx)
        assert not any("family" in e for e in errs)

    def test_missing_control_and_no_reason(self, ctx):
        data = _valid_bundle(families=2)
        del data["hypotheses"][0]["control"]
        errs = validate_artifact("bundle", data, ctx)
        assert any("requires 'control' or 'no_control_reason'" in e for e in errs)

    def test_no_control_with_reason(self, ctx):
        data = _valid_bundle(families=2)
        del data["hypotheses"][0]["control"]
        data["hypotheses"][0]["no_control_reason"] = "Observational only"
        errs = validate_artifact("bundle", data, ctx)
        assert not any("no_control_reason" in e for e in errs)

    def test_claims_needed_uncovered(self, ctx):
        ctx.claims_needed = [
            {"id": "c1"},
            {"id": "c2"},
        ]
        data = _valid_bundle(families=2)
        # hypotheses only cover c1
        errs = validate_artifact("bundle", data, ctx)
        assert any("c2" in e for e in errs)

    def test_claims_needed_all_covered(self, ctx):
        ctx.claims_needed = [{"id": "c1"}]
        data = _valid_bundle(families=2)
        errs = validate_artifact("bundle", data, ctx)
        assert not any("claims_needed" in e for e in errs)


# ── 5. Plan semantics ───────────────────────────────────────────────────


class TestPlanSemantics:
    def test_valid_plan(self, ctx):
        data = _valid_plan()
        errs = validate_artifact("plan", data, ctx)
        assert not errs

    def test_paired_seed_mismatch(self, ctx):
        ctx.bundle_hypotheses = [
            _make_hypothesis(id_="h1", control="baseline")
        ]
        data = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "cmd",
                    "parameters": {},
                    "seeds": [1, 2, 3],
                },
                {
                    "id": "r2",
                    "hypothesis_id": "h1",
                    "role": "control",
                    "command": "cmd",
                    "parameters": {},
                    "seeds": [4, 5, 6],
                },
            ]
        }
        errs = validate_artifact("plan", data, ctx)
        assert any("same seeds" in e for e in errs)

    def test_paired_seed_match(self, ctx):
        ctx.bundle_hypotheses = [
            _make_hypothesis(id_="h1", control="baseline")
        ]
        data = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "cmd",
                    "parameters": {},
                    "seeds": [1, 2, 3],
                },
                {
                    "id": "r2",
                    "hypothesis_id": "h1",
                    "role": "control",
                    "command": "cmd",
                    "parameters": {},
                    "seeds": [1, 2, 3],
                },
            ]
        }
        errs = validate_artifact("plan", data, ctx)
        assert not any("same seeds" in e for e in errs)

    def test_locked_parameters_violation(self, ctx):
        ctx.locked_parameters = {"batch_size": 32}
        data = _valid_plan()
        data["runs"][0]["parameters"] = {"batch_size": 64}
        errs = validate_artifact("plan", data, ctx)
        assert any("locked value" in e and "batch_size" in e for e in errs)

    def test_locked_parameters_with_workload_changes(self, ctx):
        ctx.locked_parameters = {"batch_size": 32}
        data = _valid_plan()
        data["runs"][0]["parameters"] = {"batch_size": 64}
        data["runs"][0]["workload_changes"] = ["batch_size"]
        errs = validate_artifact("plan", data, ctx)
        assert not any("locked value" in e for e in errs)

    def test_locked_workload_violation(self, ctx):
        ctx.locked_workload = {"dataset": "imagenet"}
        data = _valid_plan()
        data["runs"][0]["parameters"] = {"dataset": "cifar10"}
        errs = validate_artifact("plan", data, ctx)
        assert any("workload parameter" in e and "dataset" in e for e in errs)

    def test_locked_workload_with_workload_changes(self, ctx):
        ctx.locked_workload = {"dataset": "imagenet"}
        data = _valid_plan()
        data["runs"][0]["parameters"] = {"dataset": "cifar10"}
        data["runs"][0]["workload_changes"] = ["dataset"]
        errs = validate_artifact("plan", data, ctx)
        assert not any("workload parameter" in e for e in errs)

    def test_locked_params_matching_value_ok(self, ctx):
        ctx.locked_parameters = {"batch_size": 32}
        data = _valid_plan()
        data["runs"][0]["parameters"] = {"batch_size": 32}
        errs = validate_artifact("plan", data, ctx)
        assert not any("locked value" in e for e in errs)

    def test_no_bundle_hypotheses_skips_seed_check(self, ctx):
        data = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "cmd",
                    "parameters": {},
                    "seeds": [1],
                },
                {
                    "id": "r2",
                    "hypothesis_id": "h1",
                    "role": "control",
                    "command": "cmd",
                    "parameters": {},
                    "seeds": [99],
                },
            ]
        }
        errs = validate_artifact("plan", data, ctx)
        assert not any("same seeds" in e for e in errs)


# ── 6. Findings semantics ───────────────────────────────────────────────


class TestFindingsSemantics:
    def test_valid_findings(self, ctx):
        data = _valid_findings(ctx.work_dir)
        errs = validate_artifact("findings", data, ctx)
        assert not errs

    def test_partially_confirmed_without_note(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["status"] = "PARTIALLY_CONFIRMED"
        errs = validate_artifact("findings", data, ctx)
        assert any("partial_note" in e for e in errs)

    def test_partially_confirmed_with_note(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["status"] = "PARTIALLY_CONFIRMED"
        data["hypotheses"][0]["partial_note"] = "direction matched but magnitude too small"
        errs = validate_artifact("findings", data, ctx)
        assert not any("partial_note" in e for e in errs)

    def test_confirmed_without_noise(self, ctx):
        data = _valid_findings(ctx.work_dir)
        del data["hypotheses"][0]["noise_sd"]
        del data["hypotheses"][0]["noise_condition"]
        errs = validate_artifact("findings", data, ctx)
        assert any("noise_sd" in e and "noise_unmeasured" in e for e in errs)

    def test_confirmed_with_noise_unmeasured(self, ctx):
        data = _valid_findings(ctx.work_dir)
        del data["hypotheses"][0]["noise_sd"]
        del data["hypotheses"][0]["noise_condition"]
        data["hypotheses"][0]["noise_unmeasured"] = True
        data["hypotheses"][0]["noise_reason"] = "no repeated runs"
        errs = validate_artifact("findings", data, ctx)
        assert not any("noise" in e.lower() for e in errs)

    def test_refuted_without_noise(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["status"] = "REFUTED"
        data["hypotheses"][0]["error_type"] = "direction"
        del data["hypotheses"][0]["noise_sd"]
        del data["hypotheses"][0]["noise_condition"]
        errs = validate_artifact("findings", data, ctx)
        assert any("REFUTED requires" in e for e in errs)

    def test_inconclusive_no_noise_ok(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["status"] = "INCONCLUSIVE"
        del data["hypotheses"][0]["noise_sd"]
        del data["hypotheses"][0]["noise_condition"]
        errs = validate_artifact("findings", data, ctx)
        assert not any("noise" in e.lower() for e in errs)

    def test_evidence_path_not_found(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["evidence"][0]["path"] = "does_not_exist.json"
        errs = validate_artifact("findings", data, ctx)
        assert any("does not exist" in e for e in errs)

    def test_evidence_value_mismatch(self, ctx):
        data = _valid_findings(ctx.work_dir)
        data["hypotheses"][0]["evidence"][0]["value"] = 999
        errs = validate_artifact("findings", data, ctx)
        assert any("mismatch" in e for e in errs)


# ── 7. Principle updates ────────────────────────────────────────────────


class TestPrincipleUpdates:
    def test_valid(self, ctx):
        ctx.bundle_hypotheses = [_make_hypothesis(id_="h1")]
        data = _valid_principle_updates()
        errs = validate_artifact("principle_updates", data, ctx)
        assert not errs

    def test_finding_ref_unknown(self, ctx):
        ctx.bundle_hypotheses = [_make_hypothesis(id_="h1")]
        data = _valid_principle_updates()
        data["updates"][0]["finding_ref"] = "h999"
        errs = validate_artifact("principle_updates", data, ctx)
        assert any("h999" in e and "not a known hypothesis" in e for e in errs)

    def test_no_bundle_hypotheses_skips_check(self, ctx):
        data = _valid_principle_updates()
        data["updates"][0]["finding_ref"] = "anything"
        errs = validate_artifact("principle_updates", data, ctx)
        assert not any("not a known hypothesis" in e for e in errs)


# ── 8. Answer semantics ─────────────────────────────────────────────────


class TestAnswerSemantics:
    def test_valid_answer(self, ctx):
        data = _valid_answer(ctx.work_dir)
        errs = validate_artifact("answer", data, ctx)
        assert not errs

    def test_secret_in_answer(self, ctx):
        ctx.secrets = {"API_KEY": "sk-abc123"}
        data = _valid_answer(ctx.work_dir)
        data["answer"] = "Used key sk-abc123 to access API"
        errs = validate_artifact("answer", data, ctx)
        assert any("answer.answer" in e and "API_KEY" in e for e in errs)

    def test_secret_in_deliverable(self, ctx):
        ctx.secrets = {"TOKEN": "ghp_secret"}
        data = _valid_answer(ctx.work_dir)
        data["deliverable"] = "deployed with token ghp_secret"
        errs = validate_artifact("answer", data, ctx)
        assert any("answer.deliverable" in e and "TOKEN" in e for e in errs)

    def test_secret_in_repro(self, ctx):
        ctx.secrets = {"DB_PASS": "hunter2"}
        data = _valid_answer(ctx.work_dir)
        data["repro"] = "connect with password hunter2"
        errs = validate_artifact("answer", data, ctx)
        assert any("answer.repro" in e and "DB_PASS" in e for e in errs)

    def test_no_secrets_no_error(self, ctx):
        data = _valid_answer(ctx.work_dir)
        errs = validate_artifact("answer", data, ctx)
        assert not any("secret" in e.lower() for e in errs)

    def test_claim_evidence_checked(self, ctx):
        data = _valid_answer(ctx.work_dir)
        data["claims"][0]["evidence"]["path"] = "nonexistent.json"
        errs = validate_artifact("answer", data, ctx)
        assert any("does not exist" in e for e in errs)


# ── 9. Task limits (B11) ────────────────────────────────────────────────


class TestTaskLimits:
    def test_exceeds_max_runs(self, ctx):
        runs_file = ctx.work_dir / "runs.jsonl"
        lines = [json.dumps({"wall_seconds": 1}) for _ in range(10)]
        runs_file.write_text("\n".join(lines))
        ctx.runs_jsonl = runs_file
        ctx.task_limits = {"max_runs": 5}
        data = _valid_findings(ctx.work_dir)
        errs = validate_artifact("findings", data, ctx)
        assert any("exceeds max_runs" in e for e in errs)

    def test_within_max_runs(self, ctx):
        runs_file = ctx.work_dir / "runs.jsonl"
        lines = [json.dumps({"wall_seconds": 1}) for _ in range(3)]
        runs_file.write_text("\n".join(lines))
        ctx.runs_jsonl = runs_file
        ctx.task_limits = {"max_runs": 5}
        data = _valid_findings(ctx.work_dir)
        errs = validate_artifact("findings", data, ctx)
        assert not any("max_runs" in e for e in errs)

    def test_exceeds_wall_time(self, ctx):
        runs_file = ctx.work_dir / "runs.jsonl"
        lines = [json.dumps({"wall_seconds": 100}) for _ in range(5)]
        runs_file.write_text("\n".join(lines))
        ctx.runs_jsonl = runs_file
        ctx.task_limits = {"max_wall_seconds": 300}
        data = _valid_findings(ctx.work_dir)
        errs = validate_artifact("findings", data, ctx)
        assert any("max_wall_seconds" in e for e in errs)

    def test_no_task_limits_no_error(self, ctx):
        data = _valid_findings(ctx.work_dir)
        errs = validate_artifact("findings", data, ctx)
        assert not any("task_limits" in e for e in errs)

    def test_missing_runs_jsonl_no_error(self, ctx):
        ctx.task_limits = {"max_runs": 1}
        ctx.runs_jsonl = ctx.work_dir / "nonexistent.jsonl"
        data = _valid_findings(ctx.work_dir)
        errs = validate_artifact("findings", data, ctx)
        assert not any("task_limits" in e for e in errs)


# ── 10. Baseline noise variants ─────────────────────────────────────────


class TestBaselineNoise:
    def test_deterministic_noise(self, ctx):
        data = _valid_baseline()
        data["noise"] = {"deterministic": True}
        errs = validate_artifact("baseline", data, ctx)
        assert not any("noise" in e for e in errs)

    def test_unmeasured_noise(self, ctx):
        data = _valid_baseline()
        data["noise"] = {"unmeasured": True, "reason": "single run only"}
        errs = validate_artifact("baseline", data, ctx)
        assert not any("noise" in e for e in errs)

    def test_measured_noise(self, ctx):
        data = _valid_baseline()
        data["noise"] = {"seeds": [1, 2, 3], "values": [10.1, 10.2, 9.9], "sd": 0.15}
        errs = validate_artifact("baseline", data, ctx)
        assert not any("noise" in e for e in errs)

    def test_empty_noise_error(self, ctx):
        data = _valid_baseline()
        data["noise"] = {}
        errs = validate_artifact("baseline", data, ctx)
        assert any("noise must be one of" in e for e in errs)

    def test_measured_noise_missing_sd(self, ctx):
        data = _valid_baseline()
        data["noise"] = {"seeds": [1], "values": [10.0]}
        errs = validate_artifact("baseline", data, ctx)
        assert any("measured noise requires 'sd'" in e for e in errs)

    def test_unmeasured_without_reason(self, ctx):
        data = _valid_baseline()
        data["noise"] = {"unmeasured": True}
        errs = validate_artifact("baseline", data, ctx)
        assert any("requires 'reason'" in e for e in errs)


# ── 11. Bundle hash ─────────────────────────────────────────────────────


class TestBundleHash:
    def test_returns_hex_string(self):
        h = bundle_hash({"hypotheses": [{"id": "h1"}]})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        data = {"hypotheses": [{"id": "h1", "z": 1, "a": 2}]}
        assert bundle_hash(data) == bundle_hash(data)

    def test_key_order_irrelevant(self):
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert bundle_hash(d1) == bundle_hash(d2)

    def test_different_data_different_hash(self):
        assert bundle_hash({"x": 1}) != bundle_hash({"x": 2})


# ── 12. Ledger entry ────────────────────────────────────────────────────


class TestLedgerEntry:
    def test_valid_entry(self, ctx):
        data = _valid_ledger_entry()
        errs = validate_artifact("ledger_entry", data, ctx)
        assert not errs

    def test_empty_entry(self, ctx):
        errs = validate_artifact("ledger_entry", {}, ctx)
        assert not errs  # all fields optional, additionalProperties: true

    def test_invalid_status_enum(self, ctx):
        data = _valid_ledger_entry()
        data["status"] = "broken"
        errs = validate_artifact("ledger_entry", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_negative_cost_rejected(self, ctx):
        data = _valid_ledger_entry()
        data["cost_meter_usd"] = -1
        errs = validate_artifact("ledger_entry", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_claims_matched_fraction_out_of_range(self, ctx):
        data = _valid_ledger_entry()
        data["claims_matched_fraction"] = 1.5
        errs = validate_artifact("ledger_entry", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_additional_properties_allowed(self, ctx):
        data = _valid_ledger_entry()
        data["custom_field"] = "anything"
        errs = validate_artifact("ledger_entry", data, ctx)
        # additionalProperties: true, so custom_field stays in data (not moved)
        # but _move_extras will still move it since it's not in schema properties
        # Wait -- ledger_entry has additionalProperties: true, but _move_extras
        # uses schema["properties"] keys. "custom_field" is not in properties,
        # so it WILL be moved to extra with a warning.
        # That's fine -- warnings are returned but it's not a hard error.
        assert not any("schema:" in e for e in errs)


# ── Baseline conditional observation shapes ──────────────────────────────


class TestBaselineTaskTypes:
    @pytest.mark.parametrize("task_type", ["debug", "verify", "optimize", "policy", "explain", "other"])
    def test_valid_per_type(self, ctx, task_type):
        data = _valid_baseline(task_type)
        errs = validate_artifact("baseline", data, ctx)
        # Only noise-related or file-related errors should remain
        schema_errors = [e for e in errs if "schema:" in e]
        assert not schema_errors

    def test_debug_missing_reproduced(self, ctx):
        data = _valid_baseline("debug")
        del data["observation"]["reproduced"]
        errs = validate_artifact("baseline", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_verify_empty_points(self, ctx):
        data = _valid_baseline("verify")
        data["observation"]["points"] = []
        errs = validate_artifact("baseline", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_optimize_zero_score(self, ctx):
        data = _valid_baseline("optimize")
        data["observation"]["score"] = 0
        errs = validate_artifact("baseline", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_policy_empty_metrics(self, ctx):
        data = _valid_baseline("policy")
        data["observation"]["metrics"] = {}
        errs = validate_artifact("baseline", data, ctx)
        assert any("schema:" in e for e in errs)


# ── Problem schema ───────────────────────────────────────────────────────


class TestProblemSchema:
    def test_valid_problem(self, ctx):
        data = _valid_problem()
        errs = validate_artifact("problem", data, ctx)
        assert not errs

    def test_empty_claims_needed(self, ctx):
        data = {"task_type": "debug", "claims_needed": []}
        errs = validate_artifact("problem", data, ctx)
        assert any("schema:" in e for e in errs)

    def test_claim_with_optional_fields(self, ctx):
        data = {
            "task_type": "optimize",
            "claims_needed": [
                {
                    "id": "c1",
                    "description": "improve throughput",
                    "test_method": "benchmark",
                    "min_seeds": 5,
                    "needs_ci": True,
                    "conditions": ["batch=32", "batch=64"],
                }
            ],
        }
        errs = validate_artifact("problem", data, ctx)
        assert not errs
