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


# ─── #222: rehearsal_subset structured field ─────────────────────────────


class TestRehearsalSubsetSchema:
    """#222: bundle.experiment_spec.rehearsal_subset declares iter-1's
    execution scope. The post-#212 paper-burst rerun showed that
    methodology prose alone doesn't scope-shrink reliably; this is the
    structured backup."""

    def test_rehearsal_subset_validates(self):
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main", "h-control-negative"],
                "extra_validation_only": True,
            },
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_rehearsal_subset_minimal(self):
        """``seeds`` and ``arms`` are the only meaningful fields;
        extra_validation_only defaults to false (omitted)."""
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main"],
            },
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_rehearsal_subset_unknown_field_rejected(self):
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main"],
                "unknown_field": "x",
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_rehearsal_subset_empty_arms_rejected(self):
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": [],   # minItems: 1
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())


# ─── #226: timing_observations schema ─────────────────────────────────────


class TestTimingObservationsSchema:
    """#226: timing_observations records per-policy wall-time observations
    from rehearsal feasibility probes. These are informational metadata
    only — the dispatcher ignores them (#305)."""

    def test_timing_observations_validates(self):
        b = _make_bundle(experiment_spec={
            "timing_observations": {
                "expected_wall_time_seconds_per_policy": {
                    "ea-wfq": 25.0,
                    "wfq": 23.0,
                    "drf": 28.0,
                    "externality-credit": 95.0,
                    "none": 22.0,
                },
                "recommended_turn_silence_threshold_seconds": 360.0,
                "observation_method":
                    "feasibility probe at seed=42, single arm per policy",
            },
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_timing_observations_unknown_field_rejected(self):
        b = _make_bundle(experiment_spec={
            "timing_observations": {
                "expected_wall_time_seconds_per_policy": {"ea-wfq": 25},
                "recommended_turn_silence_threshold_seconds": 360,
                "another_typo_field": "x",
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_negative_threshold_rejected(self):
        b = _make_bundle(experiment_spec={
            "timing_observations": {
                "recommended_turn_silence_threshold_seconds": -1,
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())


# ─── #223 v1: structured brief_amendments.jsonl schema + REPORT renderer ─


def _load_brief_amendments_schema() -> dict:
    return json.loads(
        (SCHEMAS_DIR / "brief_amendments.schema.json").read_text()
    )


class TestBriefAmendmentsSchema:
    """#223: structured brief_amendments.jsonl entries replace the prior
    free-form markdown so they can be programmatically parsed, applied,
    and propagated across campaign runs."""

    def _valid_amendment(self, **overrides) -> dict:
        a = {
            "id": "BA-1",
            "brief_section": "paper-burst-brief.md §ITER-1",
            "problem": "Probe command produces schema-invalid output",
            "fix": "Replace probe command with workload-spec version",
            "priority": "HIGH",
        }
        a.update(overrides)
        return a

    def test_minimal_amendment_validates(self):
        jsonschema.validate(self._valid_amendment(),
                            _load_brief_amendments_schema())

    def test_full_amendment_with_optional_fields_validates(self):
        a = self._valid_amendment(
            evidence="dropped_unservable=61, adversary completed=0",
            impact="iter-2 produces ground_truth_held=false trivially",
        )
        jsonschema.validate(a, _load_brief_amendments_schema())

    def test_id_pattern_enforced(self):
        for bad in ["1", "BA-", "BA-foo", "BA1", "ba-1"]:
            a = self._valid_amendment(id=bad)
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(a, _load_brief_amendments_schema())

    def test_priority_enum_enforced(self):
        for bad in ["URGENT", "blocking", "P0", "high", ""]:
            a = self._valid_amendment(priority=bad)
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(a, _load_brief_amendments_schema())

    def test_required_fields(self):
        for missing in ["id", "brief_section", "problem", "fix", "priority"]:
            a = self._valid_amendment()
            del a[missing]
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(a, _load_brief_amendments_schema())

    def test_unknown_field_rejected(self):
        a = self._valid_amendment(severity="high")  # typo for priority
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(a, _load_brief_amendments_schema())


# ─── End-to-end coupling across #221+#222+#223+#224 ────────────────────────


