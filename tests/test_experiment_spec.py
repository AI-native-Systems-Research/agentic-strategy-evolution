"""Tests for the operational ``experiment_spec`` block on bundles
(#209/#210) and the ``bundle_amendments.jsonl`` drift record (#211).

The block lets DESIGN pin operational decisions (build commands, fan-out
template, classification logic, verified parameters) so EXECUTE_ANALYZE
doesn't re-derive them in a fresh worktree. Amendments record overrides
EXECUTE_ANALYZE makes during smoke / validation, so REPORT can surface
the drift instead of describing the prescribed bundle.

No live LLM calls — pure schema validation + helpers + LLMDispatcher
seam injection.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.llm_dispatch import (
    LLMDispatcher,
    _format_bundle_amendments_summary,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _make_bundle(*, experiment_spec: dict | None = None) -> dict:
    bundle: dict = {
        "metadata": {
            "iteration": 1, "family": "test",
            "research_question": "Does X work?",
        },
        "arms": [
            {"type": "h-main", "prediction": "p", "mechanism": "m",
             "diagnostic": "d"},
        ],
    }
    if experiment_spec is not None:
        bundle["experiment_spec"] = experiment_spec
    return bundle


def _make_completion(responses: list[str]):
    call_log: list[dict] = []
    idx = {"n": 0}

    def _fn(**kwargs):
        call_log.append(kwargs)
        resp = MagicMock()
        resp.choices = [
            MagicMock(message=MagicMock(content=responses[idx["n"]])),
        ]
        idx["n"] += 1
        return resp

    _fn.call_log = call_log  # type: ignore[attr-defined]
    return _fn


def _make_campaign() -> dict:
    return {
        "research_question": "?",
        "target_system": {
            "name": "TestSys", "description": "test",
            "observable_metrics": ["m"], "controllable_knobs": ["k"],
        },
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
    }


# ─── Schema acceptance for experiment_spec ───────────────────────────────


class TestSchemaAcceptsExperimentSpec:
    def test_no_experiment_spec_validates(self):
        """Backward compat: bundles without experiment_spec still pass."""
        jsonschema.validate(_make_bundle(), _load_bundle_schema())

    def test_preflight_commands_validates(self):
        b = _make_bundle(experiment_spec={
            "preflight_commands": ["go build -o blis main.go"],
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_full_experiment_spec_validates(self):
        b = _make_bundle(experiment_spec={
            "preflight_commands": ["go build -o blis main.go"],
            "fanout_template":
                "cat /tmp/args.txt | parallel -j $N './blis run {} > {}.log 2>&1'",
            "classification_function":
                "lambda r: 'adv' if r['num_prefill_tokens'] > 4096 else 'coop'",
            "verified_parameters": {"total_kv_blocks": 1200, "horizon_us": 3e8},
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_preflight_must_be_list_of_strings(self):
        b = _make_bundle(experiment_spec={"preflight_commands": "go build"})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_empty_string_in_preflight_rejected(self):
        b = _make_bundle(experiment_spec={"preflight_commands": [""]})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_typo_field_rejected(self):
        """#2 critical-fix regression: experiment_spec is additionalProperties:
        false, so a typo'd field name (preflight_command singular,
        verifid_parameters, etc.) fails validation loudly instead of
        silently skipping the operational handoff."""
        b = _make_bundle(experiment_spec={
            "preflight_command": ["build"],  # typo: should be plural
        })
        with pytest.raises(jsonschema.ValidationError, match="preflight_command"):
            jsonschema.validate(b, _load_bundle_schema())

    def test_unknown_top_level_field_rejected(self):
        b = _make_bundle(experiment_spec={
            "preflight_commands": ["build"],
            "verifid_parameters": {"x": 1},  # typo
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_verified_parameters_keeps_open_value_namespace(self):
        """#2 fix scope: verified_parameters is the one place where
        additionalProperties: true is correct — it's a target-knob
        namespace and the keys can't be enumerated. Verify the locked
        outer block doesn't accidentally lock down inner knobs."""
        b = _make_bundle(experiment_spec={
            "verified_parameters": {
                "any_target_knob": 1100,
                "another_one": "string-value",
                "nested": {"k": 2},
            },
        })
        jsonschema.validate(b, _load_bundle_schema())


# ─── #211: bundle_amendments.jsonl rendering ─────────────────────────────


class TestBundleAmendmentsSummary:
    def test_no_runs_dir_returns_friendly_marker(self, tmp_path: Path) -> None:
        out = _format_bundle_amendments_summary(tmp_path / "campaign")
        assert "no iteration directories" in out.lower()

    def test_no_amendments_files_returns_clean_marker(
            self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        (wd / "runs" / "iter-1").mkdir(parents=True)
        out = _format_bundle_amendments_summary(wd)
        assert "no bundle_amendments" in out.lower()

    def test_renders_single_amendment(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "bundle_amendments.jsonl").write_text(json.dumps({
            "parameter": "total_kv_blocks",
            "prescribed_value": 1100,
            "actual_value": 1200,
            "reason": "smoke produced dropped_unservable=120",
        }) + "\n")

        out = _format_bundle_amendments_summary(wd)
        assert "iter-1" in out
        assert "total_kv_blocks" in out
        assert "1100" in out
        assert "1200" in out
        assert "dropped_unservable" in out

    def test_renders_multiple_amendments(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        rows = [
            json.dumps({"parameter": "kv_blocks", "prescribed_value": 1100,
                        "actual_value": 1200, "reason": "drop fix"}),
            json.dumps({"parameter": "horizon", "prescribed_value": 60,
                        "actual_value": 300, "reason": "burst tail"}),
        ]
        (inputs / "bundle_amendments.jsonl").write_text("\n".join(rows) + "\n")

        out = _format_bundle_amendments_summary(wd)
        assert "2 amendment(s)" in out
        assert "kv_blocks" in out
        assert "horizon" in out

    def test_malformed_lines_surfaced_not_silently_skipped(
            self, tmp_path: Path) -> None:
        """A corrupted amendment line is *exactly* the divergence #211
        was added to surface. Skipping it silently re-introduces the
        silence — the helper must announce the skip count so operators
        know the amendment record may be incomplete."""
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "bundle_amendments.jsonl").write_text(
            json.dumps({"parameter": "kv_blocks", "prescribed_value": 1100,
                        "actual_value": 1200, "reason": "valid row"}) + "\n"
            + "not valid json {\n"
            + "{\"another_invalid\":\n"
            + json.dumps({"parameter": "p2", "prescribed_value": 1,
                          "actual_value": 2, "reason": "another valid row"}) + "\n"
        )

        out = _format_bundle_amendments_summary(wd)
        # The valid rows render
        assert "kv_blocks" in out
        assert "p2" in out
        # The malformed lines are SURFACED, not silently dropped
        assert "malformed" in out.lower()
        assert "2" in out  # 2 malformed lines

    def test_unreadable_amendments_log_surfaced(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When read_text raises OSError (e.g., permission denied), the
        helper produces a visible row instead of silently dropping the
        iter from the report's view."""
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        log = inputs / "bundle_amendments.jsonl"
        log.write_text("{}")  # exists; we'll patch read_text

        from pathlib import Path as _Path
        original_read_text = _Path.read_text

        def _failing_read_text(self, *args, **kwargs):
            if self == log:
                raise PermissionError("simulated unreadable")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(_Path, "read_text", _failing_read_text)

        out = _format_bundle_amendments_summary(wd)
        assert "unreadable" in out.lower()
        assert "PermissionError" in out

    def test_caps_long_amendment_lists(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        rows = [
            json.dumps({"parameter": f"p{i}", "prescribed_value": i,
                        "actual_value": i + 1, "reason": "x"})
            for i in range(50)
        ]
        (inputs / "bundle_amendments.jsonl").write_text("\n".join(rows) + "\n")

        out = _format_bundle_amendments_summary(wd)
        assert "50 amendment(s)" in out
        assert "and 30 more" in out  # 50 - 20 cap


class TestReportContextIncludesAmendments:
    """#211: REPORT extractor's prompt must include the amendment summary
    so the report can surface 'we ran with kv_blocks=1200, not the bundle's
    1100'."""

    def test_amendments_appear_in_extractor_prompt(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Set up an iter with both results and an amendment.
        results = tmp_path / "runs" / "iter-1" / "results"
        results.mkdir(parents=True)
        (results / "h-main_seed42.json").write_text("{}")

        inputs = tmp_path / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "bundle_amendments.jsonl").write_text(json.dumps({
            "parameter": "total_kv_blocks",
            "prescribed_value": 1100,
            "actual_value": 1200,
            "reason": "smoke showed dropped_unservable",
        }) + "\n")

        (tmp_path / "ledger.json").write_text(json.dumps({"iterations": []}))
        (tmp_path / "principles.json").write_text(json.dumps({"principles": []}))

        d = LLMDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(),
            completion_fn=_make_completion(["# stub report"]),
        )
        d.dispatch(
            "extractor", "report",
            output_path=tmp_path / "report.md",
            iteration=0,
        )

        all_prompt = ""
        for call in d._completion.call_log:  # type: ignore[attr-defined]
            for msg in call.get("messages", []):
                all_prompt += msg.get("content", "") + "\n"

        assert "total_kv_blocks" in all_prompt, (
            "#211: REPORT extractor must see bundle_amendments so the "
            "report can describe the actually-executed parameters."
        )
        assert "1200" in all_prompt
        assert "1100" in all_prompt
