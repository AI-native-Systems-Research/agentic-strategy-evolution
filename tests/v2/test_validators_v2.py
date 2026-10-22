"""Tests for orchestrator.v2.validators — artifact validation public API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestrator.v2.validators import (
    ValidatorContext,
    _check_noise_schema,
    _move_extras,
    bundle_hash,
    validate_artifact,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _ctx(tmp_path: Path, **kw) -> ValidatorContext:
    return ValidatorContext(work_dir=tmp_path, **kw)


def _valid_baseline() -> dict:
    return {
        "task_type": "debug",
        "command": "make test",
        "git_sha": "abc1234",
        "observation": {"reproduced": True, "symptom": "crash", "expected": 0, "actual": 1},
        "metrics_path": "results/metrics.json",
        "noise": {"deterministic": True},
    }


def _valid_bundle(*, families: int = 2) -> dict:
    hyps = []
    for i in range(max(families, 1)):
        hyps.append({
            "id": f"h{i+1}",
            "role": "treatment",
            "family": f"fam{i+1}" if families > 1 else "fam1",
            "mechanism": f"mech{i+1}",
            "prediction": {"metric": "latency", "direction": "decrease"},
            "control": "no-op",
            "falsified_if": "latency >= baseline",
            "claim_ids": [],
        })
    return {"hypotheses": hyps}


def _valid_plan() -> dict:
    return {
        "runs": [
            {
                "id": "r1",
                "hypothesis_id": "h1",
                "role": "treatment",
                "command": "run.sh",
                "parameters": {"threads": 4},
                "seeds": [42],
            }
        ]
    }


def _valid_findings(tmp_path: Path) -> dict:
    ev_path = tmp_path / "results.json"
    ev_path.write_text(json.dumps({"latency": 1.5}))
    return {
        "hypotheses": [
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [{"path": "results.json", "key": "/latency", "value": 1.5}],
                "effect": {"value": 5.0},
                "noise_sd": 0.1,
                "question_answered": True,
                "reason": "latency dropped",
            }
        ]
    }


def _valid_answer(tmp_path: Path) -> dict:
    ev_path = tmp_path / "final.json"
    ev_path.write_text(json.dumps({"metric": 42}))
    return {
        "answer": "Fixed the bug.",
        "deliverable": "patch.diff",
        "repro": "make test",
        "claims": [
            {
                "id": "c1",
                "metric": "latency",
                "value": 42,
                "condition": "default",
                "evidence": {"path": "final.json", "key": "/metric", "value": 42},
            }
        ],
    }


def _valid_principle_updates() -> dict:
    return {
        "updates": [
            {
                "id": "p1",
                "text": "Use 4 threads.",
                "finding_ref": "h1",
                "action": "add",
            }
        ]
    }


def _valid_problem() -> dict:
    return {
        "task_type": "debug",
        "claims_needed": [
            {"id": "c1", "description": "fix crash", "test_method": "unit test"},
        ],
    }


# ── Extra-field handling (B5) ────────────────────────────────────────────


class TestMoveExtras:
    def test_unknown_keys_moved_to_extra(self):
        data = {"task_type": "debug", "unknown_key": "value", "another": 99}
        schema = {"properties": {"task_type": {}}}
        warnings = _move_extras(data, schema)
        assert "unknown_key" not in data
        assert "another" not in data
        assert data["extra"]["unknown_key"] == "value"
        assert data["extra"]["another"] == 99
        assert len(warnings) == 2

    def test_known_keys_preserved(self):
        data = {"task_type": "debug", "command": "test"}
        schema = {"properties": {"task_type": {}, "command": {}}}
        warnings = _move_extras(data, schema)
        assert warnings == []
        assert "extra" not in data
        assert data["task_type"] == "debug"

    def test_existing_extra_merged(self):
        data = {"task_type": "debug", "extra": {"old": 1}, "new_key": 2}
        schema = {"properties": {"task_type": {}, "extra": {}}}
        _move_extras(data, schema)
        assert data["extra"]["old"] == 1
        assert data["extra"]["new_key"] == 2


# ── Bundle hash ──────────────────────────────────────────────────────────


class TestBundleHash:
    def test_deterministic(self):
        data = {"hypotheses": [{"id": "h1"}]}
        h1 = bundle_hash(data)
        h2 = bundle_hash(data)
        assert h1 == h2

    def test_matches_sha256(self):
        data = {"a": 1, "b": [2, 3]}
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert bundle_hash(data) == expected

    def test_key_order_irrelevant(self):
        assert bundle_hash({"a": 1, "b": 2}) == bundle_hash({"b": 2, "a": 1})


# ── Noise schema ─────────────────────────────────────────────────────────


class TestNoiseSchema:
    def test_deterministic_valid(self):
        assert _check_noise_schema({"deterministic": True}) == []

    def test_deterministic_false_rejected(self):
        errs = _check_noise_schema({"deterministic": False})
        assert any("deterministic must be true" in e for e in errs)

    def test_unmeasured_valid(self):
        assert _check_noise_schema({"unmeasured": True, "reason": "no seeds"}) == []

    def test_unmeasured_missing_reason(self):
        errs = _check_noise_schema({"unmeasured": True})
        assert any("reason" in e for e in errs)

    def test_measured_valid(self):
        assert _check_noise_schema({"seeds": [1, 2], "values": [1.0, 2.0], "sd": 0.5}) == []

    @pytest.mark.parametrize("missing", ["seeds", "values", "sd"])
    def test_measured_missing_field(self, missing):
        noise = {"seeds": [1], "values": [1.0], "sd": 0.5}
        del noise[missing]
        errs = _check_noise_schema(noise)
        assert any(missing in e for e in errs)

    def test_no_recognized_form(self):
        errs = _check_noise_schema({"foo": "bar"})
        assert any("must be one of" in e for e in errs)


# ── validate_artifact: main entry point ──────────────────────────────────


class TestValidateArtifact:
    def test_unknown_artifact_type(self, tmp_path):
        errs = validate_artifact("bogus", {}, _ctx(tmp_path))
        assert any("unknown artifact type" in e for e in errs)

    def test_valid_baseline_passes(self, tmp_path):
        errs = validate_artifact("baseline", _valid_baseline(), _ctx(tmp_path))
        assert errs == [] or all("moved to extra" in e for e in errs)

    def test_missing_required_field_returns_error(self, tmp_path):
        data = {"task_type": "debug"}  # missing command, git_sha, etc.
        errs = validate_artifact("baseline", data, _ctx(tmp_path))
        assert any("schema:" in e for e in errs)

    def test_extra_fields_moved_not_rejected(self, tmp_path):
        data = _valid_baseline()
        data["surprise_field"] = "hello"
        errs = validate_artifact("baseline", data, _ctx(tmp_path))
        assert data.get("extra", {}).get("surprise_field") == "hello"
        assert "surprise_field" not in data
        fatal = [e for e in errs if "schema:" in e]
        assert fatal == []

    def test_valid_content_not_discarded(self, tmp_path):
        data = _valid_baseline()
        original_cmd = data["command"]
        validate_artifact("baseline", data, _ctx(tmp_path))
        assert data["command"] == original_cmd


# ── Bundle semantics ─────────────────────────────────────────────────────


class TestBundleSemantics:
    def test_two_families_passes(self, tmp_path):
        data = _valid_bundle(families=2)
        errs = validate_artifact("bundle", data, _ctx(tmp_path))
        assert not any("family" in e for e in errs)

    def test_single_family_without_reason_fails(self, tmp_path):
        data = _valid_bundle(families=1)
        errs = validate_artifact("bundle", data, _ctx(tmp_path))
        assert any("single_family_reason" in e for e in errs)

    def test_single_family_with_reason_passes(self, tmp_path):
        data = _valid_bundle(families=1)
        data["single_family_reason"] = "only one mechanism relevant"
        errs = validate_artifact("bundle", data, _ctx(tmp_path))
        assert not any("single_family_reason" in e for e in errs)

    def test_missing_control_and_no_control_reason(self, tmp_path):
        data = _valid_bundle(families=2)
        del data["hypotheses"][0]["control"]
        errs = validate_artifact("bundle", data, _ctx(tmp_path))
        assert any("no_control_reason" in e for e in errs)

    def test_no_control_reason_accepted(self, tmp_path):
        data = _valid_bundle(families=2)
        del data["hypotheses"][0]["control"]
        data["hypotheses"][0]["no_control_reason"] = "inherently monotonic"
        errs = validate_artifact("bundle", data, _ctx(tmp_path))
        assert not any("no_control_reason" in e for e in errs)

    def test_claims_needed_coverage_check(self, tmp_path):
        data = _valid_bundle(families=2)
        data["hypotheses"][0]["claim_ids"] = ["c1"]
        ctx = _ctx(
            tmp_path,
            claims_needed=[
                {"id": "c1", "description": "x", "test_method": "y"},
                {"id": "c2", "description": "z", "test_method": "w"},
            ],
        )
        errs = validate_artifact("bundle", data, ctx)
        assert any("c2" in e for e in errs)


# ── Plan semantics ───────────────────────────────────────────────────────


class TestPlanSemantics:
    def test_valid_plan_passes(self, tmp_path):
        errs = validate_artifact("plan", _valid_plan(), _ctx(tmp_path))
        assert errs == []

    def test_paired_seed_mismatch(self, tmp_path):
        data = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "run.sh",
                    "parameters": {},
                    "seeds": [42, 99],
                },
                {
                    "id": "r2",
                    "hypothesis_id": "h1",
                    "role": "control",
                    "command": "run.sh",
                    "parameters": {},
                    "seeds": [42, 100],
                },
            ]
        }
        ctx = _ctx(
            tmp_path,
            bundle_hypotheses=[{"id": "h1", "control": "no-op"}],
        )
        errs = validate_artifact("plan", data, ctx)
        assert any("same seeds" in e for e in errs)

    def test_paired_seed_match_passes(self, tmp_path):
        data = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "run.sh",
                    "parameters": {},
                    "seeds": [42, 99],
                },
                {
                    "id": "r2",
                    "hypothesis_id": "h1",
                    "role": "control",
                    "command": "run.sh",
                    "parameters": {},
                    "seeds": [42, 99],
                },
            ]
        }
        ctx = _ctx(
            tmp_path,
            bundle_hypotheses=[{"id": "h1", "control": "no-op"}],
        )
        errs = validate_artifact("plan", data, ctx)
        assert not any("same seeds" in e for e in errs)

    def test_locked_parameters_violation(self, tmp_path):
        data = _valid_plan()
        data["runs"][0]["parameters"]["threads"] = 8
        ctx = _ctx(tmp_path, locked_parameters={"threads": 4})
        errs = validate_artifact("plan", data, ctx)
        assert any("locked value" in e for e in errs)

    def test_locked_parameters_ok_with_workload_changes(self, tmp_path):
        data = _valid_plan()
        data["runs"][0]["parameters"]["threads"] = 8
        data["runs"][0]["workload_changes"] = ["threads"]
        ctx = _ctx(tmp_path, locked_parameters={"threads": 4})
        errs = validate_artifact("plan", data, ctx)
        assert not any("locked value" in e for e in errs)

    def test_locked_workload_violation(self, tmp_path):
        data = _valid_plan()
        data["runs"][0]["parameters"]["input_size"] = 200
        ctx = _ctx(tmp_path, locked_workload={"input_size": 100})
        errs = validate_artifact("plan", data, ctx)
        assert any("workload parameter" in e for e in errs)


# ── Findings semantics ───────────────────────────────────────────────────


class TestFindingsSemantics:
    def test_valid_findings_passes(self, tmp_path):
        errs = validate_artifact(
            "findings", _valid_findings(tmp_path), _ctx(tmp_path)
        )
        assert errs == []

    def test_partially_confirmed_requires_partial_note(self, tmp_path):
        data = _valid_findings(tmp_path)
        data["hypotheses"][0]["status"] = "PARTIALLY_CONFIRMED"
        data["hypotheses"][0]["noise_sd"] = 0.1
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("partial_note" in e for e in errs)

    def test_partially_confirmed_with_note_passes(self, tmp_path):
        data = _valid_findings(tmp_path)
        data["hypotheses"][0]["status"] = "PARTIALLY_CONFIRMED"
        data["hypotheses"][0]["partial_note"] = "only for large inputs"
        data["hypotheses"][0]["noise_sd"] = 0.1
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert not any("partial_note" in e for e in errs)

    def test_confirmed_requires_noise_info(self, tmp_path):
        data = _valid_findings(tmp_path)
        del data["hypotheses"][0]["noise_sd"]
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("noise_sd" in e or "noise_unmeasured" in e for e in errs)

    def test_confirmed_with_unmeasured_noise_passes(self, tmp_path):
        data = _valid_findings(tmp_path)
        del data["hypotheses"][0]["noise_sd"]
        data["hypotheses"][0]["noise_unmeasured"] = True
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert not any("noise_sd" in e for e in errs)

    def test_evidence_mismatch_reported(self, tmp_path):
        ev_path = tmp_path / "results.json"
        ev_path.write_text(json.dumps({"latency": 99.9}))
        data = {
            "hypotheses": [
                {
                    "id": "h1",
                    "status": "CONFIRMED",
                    "error_type": "none",
                    "evidence": [
                        {"path": "results.json", "key": "/latency", "value": 1.5}
                    ],
                    "effect": {"value": 5.0},
                    "noise_sd": 0.1,
                    "question_answered": True,
                    "reason": "latency dropped",
                }
            ]
        }
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any(
            "evidence value mismatch" in e
            and "expected" in e
            and "got" in e
            for e in errs
        )

    def test_effect_inside_noise_rejected(self, tmp_path):
        data = _valid_findings(tmp_path)
        data["hypotheses"][0]["noise_sd"] = 10.0
        data["hypotheses"][0]["effect"] = {"value": 0.5}
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("effect" in e and "noise_sd" in e for e in errs)

    def test_effect_outside_noise_passes(self, tmp_path):
        data = _valid_findings(tmp_path)
        data["hypotheses"][0]["noise_sd"] = 0.1
        data["hypotheses"][0]["effect"] = {"value": 5.0}
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert not any("effect" in e and "noise_sd" in e for e in errs)

    def test_deterministic_noise_zero_sd(self, tmp_path):
        data = _valid_findings(tmp_path)
        data["hypotheses"][0]["noise_sd"] = 0.0
        data["hypotheses"][0]["effect"] = {"value": 0.001}
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert not any("effect" in e and "noise_sd" in e for e in errs)

    def test_unmeasured_noise_exempt_from_magnitude(self, tmp_path):
        data = _valid_findings(tmp_path)
        del data["hypotheses"][0]["noise_sd"]
        data["hypotheses"][0]["noise_unmeasured"] = True
        data["hypotheses"][0]["noise_reason"] = "no seeds available"
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert not any("effect" in e and "noise_sd" in e for e in errs)

    def test_missing_effect_with_noise_sd_is_error(self, tmp_path):
        data = _valid_findings(tmp_path)
        data["hypotheses"][0]["noise_sd"] = 10.0
        if "effect" in data["hypotheses"][0]:
            del data["hypotheses"][0]["effect"]
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("effect.value" in e for e in errs)

    def test_baseline_noise_fallback(self, tmp_path):
        baseline = {
            "task_type": "optimize",
            "command": "make bench",
            "git_sha": "abc123",
            "noise": {"seeds": [1, 2, 3], "values": [1.0, 1.1, 0.9], "sd": 0.05},
            "observations": {"latency_ms": 100},
        }
        (tmp_path / "baseline.json").write_text(json.dumps(baseline))
        data = _valid_findings(tmp_path)
        h = data["hypotheses"][0]
        del h["noise_sd"]
        h["effect"] = {"value": 0.01}
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("2" in e and "noise" in e for e in errs)

    def test_baseline_deterministic_noise_fallback(self, tmp_path):
        baseline = {
            "task_type": "optimize",
            "command": "make bench",
            "git_sha": "abc123",
            "noise": {"deterministic": True},
            "observations": {"latency_ms": 100},
        }
        (tmp_path / "baseline.json").write_text(json.dumps(baseline))
        data = _valid_findings(tmp_path)
        h = data["hypotheses"][0]
        del h["noise_sd"]
        h["effect"] = {"value": 0.0}
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("2" in e and "noise" in e for e in errs)

    def test_no_baseline_no_noise_sd_no_unmeasured_is_error(self, tmp_path):
        data = _valid_findings(tmp_path)
        h = data["hypotheses"][0]
        del h["noise_sd"]
        h["effect"] = {"value": 5.0}
        errs = validate_artifact("findings", data, _ctx(tmp_path))
        assert any("noise_sd" in e or "noise_unmeasured" in e for e in errs)


# ── Answer semantics ────────────────────────────────────────────────────


class TestAnswerSemantics:
    def test_valid_answer_passes(self, tmp_path):
        errs = validate_artifact("answer", _valid_answer(tmp_path), _ctx(tmp_path))
        assert errs == []

    def test_secret_leak_detected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["answer"] = "The API key is sk-12345secret"
        ctx = _ctx(tmp_path, secrets={"api_key": "sk-12345secret"})
        errs = validate_artifact("answer", data, ctx)
        assert any("secret" in e and "api_key" in e for e in errs)

    def test_no_secrets_no_error(self, tmp_path):
        data = _valid_answer(tmp_path)
        ctx = _ctx(tmp_path, secrets={"api_key": "sk-12345secret"})
        errs = validate_artifact("answer", data, ctx)
        assert not any("secret" in e for e in errs)


# ── Principle updates semantics ──────────────────────────────────────────


class TestPrincipleUpdatesSemantics:
    def test_valid_passes(self, tmp_path):
        data = _valid_principle_updates()
        ctx = _ctx(
            tmp_path,
            bundle_hypotheses=[{"id": "h1"}],
        )
        errs = validate_artifact("principle_updates", data, ctx)
        assert errs == []

    def test_invalid_finding_ref(self, tmp_path):
        data = _valid_principle_updates()
        data["updates"][0]["finding_ref"] = "nonexistent"
        ctx = _ctx(
            tmp_path,
            bundle_hypotheses=[{"id": "h1"}],
        )
        errs = validate_artifact("principle_updates", data, ctx)
        assert any("finding_ref" in e and "nonexistent" in e for e in errs)


# ── Task limits (B11) ────────────────────────────────────────────────────


class TestTaskLimits:
    def test_max_runs_exceeded(self, tmp_path):
        runs_path = tmp_path / "runs.jsonl"
        lines = [json.dumps({"wall_seconds": 1.0}) for _ in range(5)]
        runs_path.write_text("\n".join(lines))

        data = _valid_findings(tmp_path)
        ctx = _ctx(
            tmp_path,
            task_limits={"max_runs": 3},
            runs_jsonl=runs_path,
        )
        errs = validate_artifact("findings", data, ctx)
        assert any("max_runs" in e for e in errs)

    def test_max_runs_within_limit(self, tmp_path):
        runs_path = tmp_path / "runs.jsonl"
        lines = [json.dumps({"wall_seconds": 1.0}) for _ in range(2)]
        runs_path.write_text("\n".join(lines))

        data = _valid_findings(tmp_path)
        ctx = _ctx(
            tmp_path,
            task_limits={"max_runs": 5},
            runs_jsonl=runs_path,
        )
        errs = validate_artifact("findings", data, ctx)
        assert not any("max_runs" in e for e in errs)

    def test_max_wall_seconds_exceeded(self, tmp_path):
        runs_path = tmp_path / "runs.jsonl"
        lines = [json.dumps({"wall_seconds": 100.0}) for _ in range(3)]
        runs_path.write_text("\n".join(lines))

        data = _valid_findings(tmp_path)
        ctx = _ctx(
            tmp_path,
            task_limits={"max_wall_seconds": 200},
            runs_jsonl=runs_path,
        )
        errs = validate_artifact("findings", data, ctx)
        assert any("max_wall_seconds" in e for e in errs)

    def test_no_limits_no_error(self, tmp_path):
        data = _valid_findings(tmp_path)
        ctx = _ctx(tmp_path)
        errs = validate_artifact("findings", data, ctx)
        assert not any("task_limits" in e for e in errs)


# ── ValidatorContext ─────────────────────────────────────────────────────


class TestValidatorContext:
    def test_defaults(self, tmp_path):
        ctx = ValidatorContext(work_dir=tmp_path)
        assert ctx.iter_dir is None
        assert ctx.locked_parameters is None
        assert ctx.secrets is None

    def test_all_fields(self, tmp_path):
        ctx = ValidatorContext(
            work_dir=tmp_path,
            iter_dir=tmp_path / "iter-1",
            locked_parameters={"k": "v"},
            locked_workload={"w": 1},
            task_limits={"max_runs": 10},
            secrets={"key": "val"},
            bundle_hypotheses=[{"id": "h1"}],
            claims_needed=[{"id": "c1"}],
            runs_jsonl=tmp_path / "runs.jsonl",
        )
        assert ctx.locked_parameters == {"k": "v"}
        assert ctx.secrets == {"key": "val"}
