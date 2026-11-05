"""Tests for orchestrator.lightweight.validators: answer.json validation."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.lightweight.validators import (
    ValidatorContext,
    _move_extras,
    validate_answer,
    validate_answer_file,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _ctx(tmp_path: Path, **kw) -> ValidatorContext:
    return ValidatorContext(work_dir=tmp_path, **kw)


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


# ── Extra-field handling ────────────────────────────────────────────


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


# ── validate_answer: schema ──────────────────────────────────────────────


class TestValidateAnswerSchema:
    def test_missing_required_field_returns_error(self, tmp_path):
        errs = validate_answer({"answer": "a"}, _ctx(tmp_path))
        assert any(e.startswith("schema: (top level):") for e in errs)

    def test_extra_fields_moved_not_rejected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["surprise_field"] = "hello"
        assert validate_answer(data, _ctx(tmp_path)) == []
        assert data["extra"]["surprise_field"] == "hello"

    def test_every_schema_error_reported_with_its_path(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["claims"][0].pop("metric")
        data["claims"][0]["bogus"] = 1
        errs = validate_answer(data, _ctx(tmp_path))
        assert errs and all(e.startswith("schema: claims/0") for e in errs)


class TestValidateAnswerFile:
    def test_missing_file(self, tmp_path):
        assert validate_answer_file(tmp_path) == ["answer: file not found at answer.json"]

    def test_bad_json(self, tmp_path):
        (tmp_path / "answer.json").write_text("{nope")
        errs = validate_answer_file(tmp_path)
        assert len(errs) == 1 and errs[0].startswith("answer: invalid JSON")

    def test_errors_are_prefixed(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["claims"][0]["value"] = 41
        (tmp_path / "answer.json").write_text(json.dumps(data))
        errs = validate_answer_file(tmp_path)
        assert errs and all(e.startswith("answer: ") for e in errs)

    def test_repo_dir_is_a_second_evidence_root(self, tmp_path):
        work, repo = tmp_path / "w", tmp_path / "repo"
        work.mkdir()
        repo.mkdir()
        (repo / "out.json").write_text('{"v": 7}')
        (work / "answer.json").write_text(json.dumps({
            "answer": "a", "deliverable": "d", "repro": "make", "claims": [
                {"id": "c1", "metric": "m", "value": 7, "condition": "c",
                 "evidence": {"path": "out.json", "key": "/v", "value": 7}}]}))
        assert validate_answer_file(work) != []
        assert validate_answer_file(work, repo_dir=repo) == []


# ── Answer semantics ────────────────────────────────────────────────────


class TestAnswerSemantics:
    def test_valid_answer_passes(self, tmp_path):
        errs = validate_answer(_valid_answer(tmp_path), _ctx(tmp_path))
        assert errs == []

    def test_secret_leak_detected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["answer"] = "The API key is sk-12345secret"
        ctx = _ctx(tmp_path, secrets={"api_key": "sk-12345secret"})
        errs = validate_answer(data, ctx)
        assert any("secret" in e and "api_key" in e for e in errs)

    def test_no_secrets_no_error(self, tmp_path):
        data = _valid_answer(tmp_path)
        ctx = _ctx(tmp_path, secrets={"api_key": "sk-12345secret"})
        errs = validate_answer(data, ctx)
        assert not any("secret" in e for e in errs)


class TestSecrets:
    def test_secret_anywhere_in_answer_detected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["claims"][0]["condition"] = "token sk-12345secret"
        ctx = _ctx(tmp_path, secrets={"api_key": "sk-12345secret"})
        errs = validate_answer(data, ctx)
        assert any("api_key" in e for e in errs)

    def test_secret_in_report_md_detected(self, tmp_path):
        (tmp_path / "report.md").write_text("key: sk-12345secret\n")
        ctx = _ctx(tmp_path, secrets={"api_key": "sk-12345secret"})
        errs = validate_answer(_valid_answer(tmp_path), ctx)
        assert any("report.md" in e and "api_key" in e for e in errs)



# ── Round 2: claim value must match its evidence; repro hygiene ──────────


class TestClaimValueMatchesEvidence:
    def test_object_evidence_value_mismatch_rejected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["claims"][0]["value"] = 41
        errs = validate_answer(data, _ctx(tmp_path))
        assert any("copy the exact value" in e for e in errs)

    def test_evidence_detail_value_mismatch_rejected(self, tmp_path):
        data = _valid_answer(tmp_path)
        claim = data["claims"][0]
        claim["evidence_detail"] = claim["evidence"]
        claim["evidence"] = "final.json"
        claim["value"] = "about 42"
        errs = validate_answer(data, _ctx(tmp_path))
        assert any("copy the exact value" in e for e in errs)

    def test_object_evidence_float_close_accepted(self, tmp_path):
        (tmp_path / "f.json").write_text(json.dumps({"x": 0.1 + 0.2}))
        data = _valid_answer(tmp_path)
        data["claims"][0].update(value=0.3, evidence={"path": "f.json", "key": "/x", "value": 0.3})
        assert validate_answer(data, _ctx(tmp_path)) == []

    def test_string_evidence_value_in_file_accepted(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["claims"][0]["evidence"] = "final.json"
        assert validate_answer(data, _ctx(tmp_path)) == []

    def test_string_evidence_value_not_in_file_rejected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["claims"][0].update(evidence="final.json", value=17.5)
        errs = validate_answer(data, _ctx(tmp_path))
        assert any("17.5" in e and "copy the exact value" in e for e in errs)


class TestReproHygiene:
    def test_repro_starting_with_cd_rejected(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["repro"] = "cd sub && make test"
        errs = validate_answer(data, _ctx(tmp_path))
        assert any("repository root" in e for e in errs)

    def test_repro_without_cd_accepted(self, tmp_path):
        data = _valid_answer(tmp_path)
        data["repro"] = "make -C sub test"
        assert validate_answer(data, _ctx(tmp_path)) == []
