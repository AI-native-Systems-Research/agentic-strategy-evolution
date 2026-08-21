"""Behavioral tests for the ``kind: optimization`` campaign schema and the
cross-field validator (Task 10).

Optimization campaigns are authored by AI, so a bare rejection is a
defect: every cross-field-rule test below asserts the message contains
the actionable hint, not just that validation failed.

Two families of coverage:

* JSON-Schema-level structural checks (``jsonschema.validate`` against
  ``campaign.schema.yaml``) — things the schema itself must reject.
* ``validate_optimization_campaign`` cross-field checks — the ten rules
  JSON Schema cannot express, each returning a human/AI-actionable
  repair message.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.validate import campaign_kind, validate_optimization_campaign

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml"
EXAMPLES_DIR = REPO_ROOT / "examples"
SPEC_PATH = (
    REPO_ROOT / "docs" / "superpowers" / "specs"
    / "2026-08-13-optimization-campaign-kind-design.md"
)


def _schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text())


def _numeric_factor(**over) -> dict:
    raw = {
        "id": "L1",
        "name": "queue_count",
        "type": "numeric",
        "levels": [2, 4, 8, 16],
        "grid": 1,
        "apply": "--queues={level}",
        "manipulation": {
            "observable": "telemetry.queue_count", "op": "==", "value": "{level}",
        },
        "relations": [
            {
                "id": "R1", "kind": "correctness",
                "statement": "queue_count at baseline reproduces baseline within noise",
                "native_test": "tests/prop_queue.py::test_baseline_noop",
            },
        ],
    }
    raw.update(over)
    return raw


def _numeric_factor_2(**over) -> dict:
    raw = {
        "id": "L2",
        "name": "batch_size",
        "type": "numeric",
        "levels": [1, 4, 8, 16],
        "grid": 1,
        "apply": "--batch={level}",
        "manipulation": {
            "observable": "telemetry.batch_size", "op": "==", "value": "{level}",
        },
        "relations": [
            {
                "id": "R2", "kind": "correctness",
                "statement": "batch_size at baseline reproduces baseline within noise",
                "native_test": "tests/prop_batch.py::test_baseline_noop",
            },
        ],
    }
    raw.update(over)
    return raw


def _choice_factor(**over) -> dict:
    raw = {
        "id": "L5",
        "name": "batching",
        "type": "choice",
        "levels": ["off", "on"],
        "apply": {"kind": "env_var", "name": "CERTUS_BATCHING", "value": "{level}"},
        "manipulation": {
            "observable": "telemetry.mean_batch_size", "op": ">", "value": 1,
            "when": "on",
        },
        "relations": [
            {
                "id": "R3", "kind": "correctness",
                "statement": "batching=off is byte-identical to baseline",
                "native_test": "tests/prop_batch.py::test_off_is_noop",
            },
        ],
    }
    raw.update(over)
    return raw


def _choice_factor_2(**over) -> dict:
    raw = {
        "id": "L6",
        "name": "compression",
        "type": "choice",
        "levels": ["off", "on"],
        "apply": {"kind": "env_var", "name": "CERTUS_COMPRESSION", "value": "{level}"},
        "manipulation": {
            "observable": "telemetry.compression_ratio", "op": ">", "value": 1,
            "when": "on",
        },
        "relations": [
            {
                "id": "R4", "kind": "correctness",
                "statement": "compression=off is byte-identical to baseline",
                "native_test": "tests/prop_compress.py::test_off_is_noop",
            },
        ],
    }
    raw.update(over)
    return raw


def _minimal_optimization_campaign(**over) -> dict:
    """A minimal, schema-valid + cross-field-valid optimization campaign."""
    campaign = {
        "kind": "optimization",
        "research_question": "Does queue_count improve throughput?",
        "target_system": {
            "name": "certus",
            "description": "Cold-read path benchmark target.",
        },
        "prompts": {"methodology_layer": "prompts/methodology"},
        "optimization": {
            "response": {
                "primary": {"metric": "throughput_gbps", "direction": "maximize"},
            },
            "factors": [
                _numeric_factor(), _numeric_factor_2(),
                _choice_factor(), _choice_factor_2(),
            ],
            "design": {
                "screen": {"resolution": 4, "center_points": 2},
                "refine": {"kind": "central_composite", "center_points": 2},
                "confirm": {"replicates": 3},
                "max_runs": 60,
            },
        },
    }
    campaign.update(over)
    return campaign


def _reflective_campaign(**over) -> dict:
    campaign = {
        "research_question": "Does X help?",
        "target_system": {"name": "sys", "description": "desc"},
        "prompts": {"methodology_layer": "prompts/methodology"},
    }
    campaign.update(over)
    return campaign


# ---------------------------------------------------------------------------
# Test item 1: minimal valid optimization campaign passes jsonschema.validate
# ---------------------------------------------------------------------------


def test_minimal_optimization_campaign_passes_json_schema():
    jsonschema.validate(_minimal_optimization_campaign(), _schema())


def test_minimal_optimization_campaign_passes_cross_field_validator():
    errors = validate_optimization_campaign(_minimal_optimization_campaign())
    hard_errors = [e for e in errors if not e.startswith("WARN:")]
    assert hard_errors == []


# ---------------------------------------------------------------------------
# Test item 2: every existing example campaign still validates (backward
# compatibility — no `kind` means reflective).
# ---------------------------------------------------------------------------


def test_existing_example_campaigns_still_validate_as_reflective():
    schema = _schema()
    example_paths = sorted(EXAMPLES_DIR.glob("*.yaml")) + sorted(
        (REPO_ROOT / "orchestrator" / "templates").glob("campaign.yaml")
    )
    assert example_paths, "expected at least one example/template campaign yaml"
    for path in example_paths:
        campaign = yaml.safe_load(path.read_text())
        jsonschema.validate(campaign, schema)
        assert campaign_kind(campaign) == "reflective", path


# ---------------------------------------------------------------------------
# Test item 3: type: ordinal is rejected by the schema enum.
# ---------------------------------------------------------------------------


def test_factor_type_ordinal_rejected_by_schema():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"][0]["type"] = "ordinal"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(campaign, _schema())


# ---------------------------------------------------------------------------
# Test item 4: a factor with one level is rejected.
# ---------------------------------------------------------------------------


def test_factor_with_one_level_rejected_by_schema():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"][0]["levels"] = [2]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(campaign, _schema())


# ---------------------------------------------------------------------------
# Test item 5: a relation without native_test is rejected.
# ---------------------------------------------------------------------------


def test_relation_without_native_test_rejected_by_schema():
    campaign = _minimal_optimization_campaign()
    del campaign["optimization"]["factors"][0]["relations"][0]["native_test"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(campaign, _schema())


# ---------------------------------------------------------------------------
# Test item 6: guidance with a third slot is rejected.
# ---------------------------------------------------------------------------


def test_guidance_with_third_slot_rejected_by_schema():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["guidance"] = {
        "factor_nomination": "explore widely",
        "interpretation": "be careful",
        "extra_slot": "not allowed",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(campaign, _schema())


def test_guidance_with_two_slots_is_accepted():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["guidance"] = {
        "factor_nomination": "explore widely",
        "interpretation": "be careful",
    }
    jsonschema.validate(campaign, _schema())


# ---------------------------------------------------------------------------
# Test item 7: the ten cross-field rules, one test per rule.
# ---------------------------------------------------------------------------


# Rule 1: kind: optimization requires an optimization block; kind: reflective
# (or absent) forbids one.


def test_rule1_kind_optimization_requires_optimization_block():
    campaign = _minimal_optimization_campaign()
    del campaign["optimization"]
    errors = validate_optimization_campaign(campaign)
    assert any("optimization" in e and "kind: optimization" in e for e in errors)


def test_rule1_kind_reflective_forbids_optimization_block():
    campaign = _reflective_campaign()
    campaign["optimization"] = _minimal_optimization_campaign()["optimization"]
    errors = validate_optimization_campaign(campaign)
    assert any(
        "reflective" in e and "optimization" in e for e in errors
    )


def test_rule1_absent_kind_forbids_optimization_block():
    campaign = _reflective_campaign()
    campaign["optimization"] = _minimal_optimization_campaign()["optimization"]
    # No "kind" key at all -- defaults to reflective.
    assert "kind" not in campaign
    errors = validate_optimization_campaign(campaign)
    assert any("optimization" in e for e in errors)


# Rule 2: held_out leakage guard.


def test_rule2_held_out_equal_to_primary_metric_is_leakage():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["response"]["held_out"] = ["throughput_gbps"]
    errors = validate_optimization_campaign(campaign)
    assert any(
        "held_out" in e and "throughput_gbps" in e and "leak" in e.lower()
        for e in errors
    )


def test_rule2_held_out_in_constraints_is_leakage():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["response"]["constraints"] = [
        {"metric": "held_out_score", "op": ">", "value": 0},
    ]
    campaign["optimization"]["response"]["held_out"] = ["held_out_score"]
    errors = validate_optimization_campaign(campaign)
    assert any("held_out_score" in e and "constraints" in e for e in errors)


def test_rule2_held_out_in_regimes_is_leakage():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["response"]["regimes"] = [
        {"id": "r1", "metric": "held_out_score", "op": ">", "value": 0},
    ]
    campaign["optimization"]["response"]["held_out"] = ["held_out_score"]
    errors = validate_optimization_campaign(campaign)
    assert any("held_out_score" in e and "regimes" in e for e in errors)


def test_rule2_held_out_disjoint_from_fitting_inputs_passes():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["response"]["held_out"] = ["held_out_score"]
    errors = validate_optimization_campaign(campaign)
    hard_errors = [e for e in errors if not e.startswith("WARN:")]
    assert not any("leak" in e.lower() for e in hard_errors)


def test_rule2_held_out_whitespace_variant_of_primary_metric_is_leakage():
    # Trailing whitespace differs by exact string but is the same metric
    # to a human author; the runtime resolves by exact match, so this
    # can never leak data through the pipeline -- the point is that the
    # author's intent (same metric, protected) is silently defeated
    # without a warning unless comparison normalizes.
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["response"]["held_out"] = ["throughput_gbps "]
    errors = validate_optimization_campaign(campaign)
    assert any(
        "throughput_gbps " in e and "throughput_gbps" in e and "leak" in e.lower()
        for e in errors
    )


def test_rule2_held_out_case_variant_of_constraint_metric_is_leakage():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["response"]["constraints"] = [
        {"metric": "OOS", "op": ">", "value": 0},
    ]
    campaign["optimization"]["response"]["held_out"] = ["oos"]
    errors = validate_optimization_campaign(campaign)
    assert any("OOS" in e and "oos" in e and "leak" in e.lower() for e in errors)


# Rule 3: every screen_levels entry must be a member of that factor's levels.


def test_rule3_screen_levels_not_members_of_levels():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"][0]["screen_levels"] = [2, 999]
    errors = validate_optimization_campaign(campaign)
    assert any(
        "screen_levels" in e and "999" in e and "L1" in e for e in errors
    )


def test_rule3_screen_levels_members_of_levels_passes():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"][0]["screen_levels"] = [2, 16]
    errors = validate_optimization_campaign(campaign)
    assert not any("screen_levels" in e for e in errors)


# Rule 4: refine.kind requires >=2 refinable factors.


def test_rule4_refine_kind_with_fewer_than_two_refinable_factors_errors():
    campaign = _minimal_optimization_campaign()
    # Only one refinable (numeric, >2 levels) factor; drop the second.
    campaign["optimization"]["factors"] = [_numeric_factor(), _choice_factor()]
    errors = validate_optimization_campaign(campaign)
    assert any(
        "refine" in e and ("drop" in e.lower() or "add levels" in e.lower())
        for e in errors
    )


def test_rule4_refine_kind_with_two_refinable_factors_passes():
    campaign = _minimal_optimization_campaign()
    errors = validate_optimization_campaign(campaign)
    assert not any("refine.kind" in e for e in errors)


def test_rule4_no_refine_block_is_fine_even_with_one_refinable_factor():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"] = [_numeric_factor(), _choice_factor()]
    del campaign["optimization"]["design"]["refine"]
    errors = validate_optimization_campaign(campaign)
    assert not any("refine" in e for e in errors)


# Rule 5: each factor needs >=1 correctness relation.
# (parse_factors already enforces per-factor structure at parse time, but
# validate_optimization_campaign works directly on raw dicts before any
# parse_factors call, and must catch this independently for factors whose
# 'relations' list is present but contains no correctness kind.)


def test_rule5_factor_missing_correctness_relation_errors():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"][0]["relations"] = [
        {
            "id": "R1", "kind": "behavioral",
            "statement": "monotone",
            "native_test": "tests/prop.py::test_mono",
        },
    ]
    errors = validate_optimization_campaign(campaign)
    assert any(
        "L1" in e and "correctness" in e for e in errors
    )


def test_rule5_factor_with_correctness_relation_passes():
    campaign = _minimal_optimization_campaign()
    errors = validate_optimization_campaign(campaign)
    assert not any("correctness relation" in e for e in errors)


# Rule 6: no manipulation or invariant predicate may be trivially true.


def test_rule6_trivial_manipulation_predicate_errors():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"][0]["manipulation"] = {
        "observable": "telemetry.queue_count", "op": "!=", "value": None,
    }
    errors = validate_optimization_campaign(campaign)
    assert any("L1" in e and "trivial" in e.lower() for e in errors)


def test_rule6_trivial_invariant_predicate_errors():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["design_space"] = {
        "invariants": [
            {
                "id": "I1", "statement": "always true",
                "observable": "telemetry.x", "op": ">", "value": 0,
            },
        ],
    }
    errors = validate_optimization_campaign(campaign)
    assert any("I1" in e and "trivial" in e.lower() for e in errors)


def test_rule6_non_trivial_predicates_pass():
    campaign = _minimal_optimization_campaign()
    errors = validate_optimization_campaign(campaign)
    assert not any("trivial" in e.lower() for e in errors)


# Rule 7: design.screen.resolution < 5 with > 1 factor is a WARNING naming
# the aliased pairs.


def test_rule7_low_resolution_screen_with_multiple_factors_is_a_warning():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["design"]["screen"]["resolution"] = 4
    errors = validate_optimization_campaign(campaign)
    warnings = [e for e in errors if e.startswith("WARN:")]
    assert any(
        "resolution" in w and ("alias" in w.lower()) for w in warnings
    )
    # A warning must not turn into a hard error.
    hard_errors = [e for e in errors if not e.startswith("WARN:")]
    assert not any("resolution" in e for e in hard_errors)


def test_rule7_resolution_five_screen_produces_no_warning():
    campaign = _minimal_optimization_campaign()
    # 5 factors at resolution 5 is tabulated (16 runs) -- add a 5th factor
    # so rule 8 doesn't also fire "not tabulated" for (4, 5).
    campaign["optimization"]["factors"].append(_numeric_factor(id="L7", name="l7"))
    campaign["optimization"]["design"]["screen"]["resolution"] = 5
    campaign["optimization"]["design"]["max_runs"] = 60
    errors = validate_optimization_campaign(campaign)
    assert not any(w.startswith("WARN:") and "resolution" in w for w in errors)


def test_rule7_low_resolution_with_single_factor_is_not_warned():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["factors"] = [_numeric_factor()]
    campaign["optimization"]["design"]["screen"]["resolution"] = 4
    del campaign["optimization"]["design"]["refine"]
    del campaign["optimization"]["design"]["max_runs"]
    errors = validate_optimization_campaign(campaign)
    assert not any(w.startswith("WARN:") and "resolution" in w for w in errors)


# Rule 8 (corrected per task brief): tabulated vs untabulated (k, resolution).


def test_rule8_tabulated_combination_exceeding_max_runs_is_an_error_with_two_options():
    campaign = _minimal_optimization_campaign()
    # k=2 factors, resolution 4 is untabulated for k=2, so use a tabulated
    # pair instead: (4, 4) -> 8 runs needed. Use max_runs below that.
    campaign["optimization"]["factors"] = [
        _numeric_factor(id="L1"), _numeric_factor_2(id="L2"),
        _numeric_factor(id="L3", name="l3"), _numeric_factor_2(id="L4", name="l4"),
    ]
    campaign["optimization"]["design"]["screen"]["resolution"] = 4
    campaign["optimization"]["design"]["max_runs"] = 4
    errors = validate_optimization_campaign(campaign)
    matches = [e for e in errors if "max_runs" in e and "8" in e and "4" in e]
    assert matches, errors
    msg = matches[0]
    assert "raise" in msg.lower() and (
        "lower resolution" in msg.lower() or "accept" in msg.lower()
    )


def test_rule8_tabulated_combination_within_max_runs_passes():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["design"]["screen"]["resolution"] = 4
    campaign["optimization"]["design"]["max_runs"] = 60
    errors = validate_optimization_campaign(campaign)
    assert not any("max_runs" in e for e in errors)


def test_rule8_untabulated_combination_never_fabricates_a_number():
    campaign = _minimal_optimization_campaign()
    # k=6 factors at resolution 3 is NOT in _GENERATORS (only (7,3) is
    # tabulated at resolution III). The fallback 2**6=64 must NOT be
    # compared against max_runs as if it were a real minimum.
    factors = [
        _numeric_factor(id=f"L{i}", name=f"f{i}")
        for i in range(1, 7)
    ]
    campaign["optimization"]["factors"] = factors
    campaign["optimization"]["design"]["screen"]["resolution"] = 3
    campaign["optimization"]["design"]["max_runs"] = 8
    errors = validate_optimization_campaign(campaign)
    not_tabulated = [
        e for e in errors
        if not e.startswith("WARN:") and "not a tabulated design" in e.lower()
    ]
    assert not_tabulated, errors
    msg = not_tabulated[0]
    assert "cannot certify" in msg.lower()
    assert "64" in msg or "full factorial" in msg.lower()
    # Must NOT claim 64 runs are "required" against the declared max_runs=8
    # budget -- that would be comparing a fabricated number to the budget.
    assert not any(
        "required" in e and "64" in e and "8" in e for e in errors
    )


def test_min_runs_for_confirms_the_untabulated_fallback_is_conservative():
    """Empirical check backing the rule-8 correction: (6, 3) is untabulated
    and min_runs_for falls back to 2**6=64, even though a genuine
    resolution-III design for 6 factors exists at 8 runs (via the
    tabulated (7, 3) generator's 8-run base, dropping one column)."""
    from orchestrator.optimize.design import _GENERATORS, min_runs_for

    assert (6, 3) not in _GENERATORS
    assert min_runs_for(6, 3) == 64


# Rule 9: complexity_tier / tier_justification under kind: optimization is
# an error.


def test_rule9_complexity_tier_under_optimization_is_an_error():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["complexity_tier"] = 2
    errors = validate_optimization_campaign(campaign)
    assert any(
        "complexity_tier" in e and "reflective" in e.lower() for e in errors
    )


def test_rule9_tier_justification_under_optimization_is_an_error():
    campaign = _minimal_optimization_campaign()
    campaign["optimization"]["tier_justification"] = "tier 2 because..."
    errors = validate_optimization_campaign(campaign)
    assert any(
        "tier_justification" in e and "reflective" in e.lower() for e in errors
    )


def test_rule9_absent_tier_fields_pass():
    campaign = _minimal_optimization_campaign()
    errors = validate_optimization_campaign(campaign)
    assert not any("complexity_tier" in e or "tier_justification" in e for e in errors)


def test_rule9_complexity_tier_under_metadata_is_an_error():
    # #206 made `metadata` the canonical location complexity_tier.py reads
    # from -- an author following that convention must not get silence.
    campaign = _minimal_optimization_campaign()
    campaign["metadata"] = {"complexity_tier": 2}
    errors = validate_optimization_campaign(campaign)
    assert any(
        "complexity_tier" in e and "metadata" in e and "reflective" in e.lower()
        for e in errors
    )


def test_rule9_tier_justification_under_metadata_is_an_error():
    campaign = _minimal_optimization_campaign()
    campaign["metadata"] = {"tier_justification": "tier 2 because multi-knob"}
    errors = validate_optimization_campaign(campaign)
    assert any(
        "tier_justification" in e and "metadata" in e and "reflective" in e.lower()
        for e in errors
    )


def test_rule9_complexity_tier_at_legacy_top_level_is_an_error():
    campaign = _minimal_optimization_campaign()
    campaign["complexity_tier"] = 1
    errors = validate_optimization_campaign(campaign)
    assert any(
        "complexity_tier" in e and "top level" in e and "reflective" in e.lower()
        for e in errors
    )


def test_rule9_tier_fields_under_both_metadata_and_top_level_are_both_errors():
    campaign = _minimal_optimization_campaign()
    campaign["metadata"] = {"complexity_tier": 2}
    campaign["complexity_tier"] = 1
    errors = validate_optimization_campaign(campaign)
    hard = [e for e in errors if not e.startswith("WARN:")]
    assert any("metadata" in e and "complexity_tier" in e for e in hard)
    assert any("top level" in e and "complexity_tier" in e for e in hard)


# Rule 10: a controllable_knob in neither factors nor locked_parameters is a
# WARNING.


def test_rule10_uncontrolled_knob_is_a_warning():
    campaign = _minimal_optimization_campaign()
    campaign["target_system"]["controllable_knobs"] = ["queue_count", "cache_size"]
    errors = validate_optimization_campaign(campaign)
    warnings = [e for e in errors if e.startswith("WARN:")]
    assert any("cache_size" in w for w in warnings)
    hard_errors = [e for e in errors if not e.startswith("WARN:")]
    assert not any("cache_size" in e for e in hard_errors)


def test_rule10_knob_covered_by_factor_id_or_name_is_not_warned():
    campaign = _minimal_optimization_campaign()
    campaign["target_system"]["controllable_knobs"] = ["queue_count", "batch_size"]
    errors = validate_optimization_campaign(campaign)
    assert not any(
        "queue_count" in e or "batch_size" in e for e in errors
    )


def test_rule10_knob_covered_by_locked_parameters_is_not_warned():
    campaign = _minimal_optimization_campaign()
    campaign["target_system"]["controllable_knobs"] = ["queue_count", "warmup_seconds"]
    campaign["locked_parameters"] = {"warmup_seconds": 30}
    errors = validate_optimization_campaign(campaign)
    assert not any("warmup_seconds" in e for e in errors)


# ---------------------------------------------------------------------------
# Test item 8: campaign_kind returns "reflective" for a campaign with no
# kind field.
# ---------------------------------------------------------------------------


def test_campaign_kind_defaults_to_reflective():
    assert campaign_kind(_reflective_campaign()) == "reflective"


def test_campaign_kind_returns_optimization_when_declared():
    assert campaign_kind(_minimal_optimization_campaign()) == "optimization"


# ---------------------------------------------------------------------------
# Test item 9: the spec's worked example, extracted programmatically, must
# validate end-to-end against both the schema and the cross-field validator.
# This keeps docs/superpowers/specs/... and the schema from drifting apart.
# ---------------------------------------------------------------------------


def _spec_worked_examples() -> list[dict]:
    spec = SPEC_PATH.read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", spec, re.S)
    candidates = [yaml.safe_load(b) for b in blocks]
    return [
        c for c in candidates
        if isinstance(c, dict) and "research_question" in c
    ]


def test_spec_contains_a_complete_worked_example():
    full = _spec_worked_examples()
    assert full, "spec must contain a complete worked example"


def test_spec_worked_example_validates_against_schema_and_cross_field_rules():
    full = _spec_worked_examples()
    assert full, "spec must contain a complete worked example"
    schema = _schema()
    for example in full:
        jsonschema.validate(example, schema)
        errors = validate_optimization_campaign(example)
        hard_errors = [e for e in errors if not e.startswith("WARN:")]
        assert hard_errors == [], (example.get("run_id"), hard_errors)


# ─── rule 8: an untabulated combination the full factorial can satisfy ────

def _small_campaign(n_factors: int, max_runs: int, resolution: int = 5) -> dict:
    ids = [chr(65 + i) for i in range(n_factors)]
    return {
        "kind": "optimization",
        "research_question": "q",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "t", "description": "d"},
        "optimization": {
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "factors": [
                {"id": i, "name": i, "type": "numeric", "levels": [1, 2, 4, 8],
                 "apply": f"--{i}={{level}}",
                 "manipulation": {"observable": f"cfg.{i}", "op": "==",
                                  "value": "{level}"},
                 "relations": [{"id": f"R{i}", "kind": "correctness",
                                "statement": "s", "native_test": "t.py::t"}]}
                for i in ids
            ],
            "design": {"screen": {"resolution": resolution, "center_points": 4},
                       "confirm": {"replicates": 3}, "max_runs": max_runs},
        },
    }


def _hard_errors(campaign: dict) -> list[str]:
    from orchestrator.validate import validate_optimization_campaign

    return [e for e in validate_optimization_campaign(campaign)
            if not e.startswith("WARN:")]


def test_rule8_untabulated_but_full_factorial_fits_the_budget_is_feasible():
    """The validator must not reject what the runner executes correctly.

    A full factorial aliases nothing, so it achieves ANY requested
    resolution — verified: alias_pairs() is empty for k=2,3,4. And
    stage_runner._build_design already falls back to the full factorial for
    an untabulated (k, resolution). Erroring here forced the guide's small
    examples to omit design.max_runs entirely, which is where a budget is
    easiest to state correctly.
    """
    from orchestrator.optimize.design import is_tabulated

    for n in (2, 3):
        assert not is_tabulated(n, 5), f"{n} factors at res V should be untabulated"
        assert _hard_errors(_small_campaign(n, max_runs=60)) == []


def test_rule8_untabulated_and_full_factorial_exceeds_the_budget_still_errors():
    """2**k is an upper bound on the minimum, so when it does not fit, the
    honest answer is that Nous cannot certify a design within the budget —
    not that none exists.
    """
    errors = _hard_errors(_small_campaign(3, max_runs=4))  # needs 8
    assert errors and "not a tabulated" in errors[0]


def test_rule8_tabulated_over_budget_still_names_the_exact_requirement():
    errors = _hard_errors(_small_campaign(5, max_runs=10))  # res V needs 16
    assert errors
    assert "16 runs" in errors[0] and "max_runs=10" in errors[0]


# ─── `nous validate campaign` — the CLI surface for the cross-field rules ──

def test_validate_campaign_accepts_a_clean_optimization_campaign(tmp_path, capsys):
    """Before this existed, validate_optimization_campaign had NO production
    caller — the ten cross-field rules ran only in tests. An author got raw
    jsonschema messages with no repair path, and a wrong native_test
    identifier was discovered only when a real campaign aborted at verify.
    """
    import yaml

    from orchestrator.cli import _validate_campaign_file

    campaign = _small_campaign(5, max_runs=60)
    campaign["run_id"] = "cli-validate-ok"
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(campaign))

    _validate_campaign_file(path)          # must not raise or exit
    out = capsys.readouterr().out
    assert "kind:     optimization" in out
    assert "OK — no errors" in out
    # the native_test caveat must be surfaced, since it is the failure mode
    # that costs a whole campaign run to discover otherwise
    assert "native_test" in out


def test_validate_campaign_reports_schema_errors_with_the_field_path(
    tmp_path, capsys,
):
    """`60 is not of type 'object'` without a path is not actionable."""
    import pytest
    import yaml

    from orchestrator.cli import _validate_campaign_file

    campaign = _small_campaign(3, max_runs=60)
    campaign["max_turns"] = 60          # must be a per-phase object
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(campaign))

    with pytest.raises(SystemExit) as exc:
        _validate_campaign_file(path)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[schema] max_turns" in err
    assert "campaign-guide" in err        # points at the authoring guide


def test_validate_campaign_reports_cross_field_rule_violations(tmp_path, capsys):
    """A rule JSON Schema cannot express — here, held-out leakage."""
    import pytest
    import yaml

    from orchestrator.cli import _validate_campaign_file

    campaign = _small_campaign(3, max_runs=60)
    # the primary metric declared held_out: optimising against the
    # generalization check
    campaign["optimization"]["response"]["held_out"] = ["m"]
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(campaign))

    with pytest.raises(SystemExit) as exc:
        _validate_campaign_file(path)
    assert exc.value.code == 1
    assert "[rules]" in capsys.readouterr().err


def test_validate_campaign_rejects_a_missing_file(tmp_path, capsys):
    import pytest

    from orchestrator.cli import _validate_campaign_file

    with pytest.raises(SystemExit) as exc:
        _validate_campaign_file(tmp_path / "nope.yaml")
    assert exc.value.code == 2
    assert "does not exist" in capsys.readouterr().err


def test_validate_campaign_works_for_the_reflective_kind_too(tmp_path, capsys):
    """The cross-field validator is a no-op on reflective campaigns, but the
    schema layer still applies — an author of either kind should be able to
    check their file before spending anything.
    """
    import yaml

    from orchestrator.cli import _validate_campaign_file

    campaign = {
        "run_id": "cli-validate-reflective",
        "research_question": "does the mechanism explain the effect?",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "t", "description": "d"},
    }
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(campaign))

    _validate_campaign_file(path)
    out = capsys.readouterr().out
    assert "kind:     reflective" in out
    assert "OK — no errors" in out


# ─── rules 13-14 (Task 9): the baseline and the registered policy numbers ──
#
# Both blocks are reached at the WORST possible moment — the baseline when
# nothing else survived, the policy numbers on every certification decision —
# so a defect in either is invisible until it matters most.


def test_known_valid_baseline_and_policy_block_pass_when_well_formed():
    c = _minimal_optimization_campaign()
    c["optimization"]["known_valid_baseline"] = {"L1": 2, "L5": "off"}
    c["optimization"]["policy"] = {
        "epsilon": {"pct": 2.0}, "delta_screen": 0.05, "delta_terminal": 0.05,
        "confirm_max_rounds": 3,
    }
    jsonschema.validate(c, _schema())
    assert _hard_errors(c) == []


def test_rule13_known_valid_baseline_outside_declared_levels_is_rejected():
    c = _minimal_optimization_campaign()
    c["optimization"]["known_valid_baseline"] = {"L1": 999}
    errors = _hard_errors(c)
    assert errors and "known_valid_baseline" in errors[0]
    assert "999" in errors[0] and "declared levels" in errors[0]


def test_rule13_known_valid_baseline_naming_an_unknown_factor_is_rejected():
    """An unrecognised id renders NO flag at all (``matrix.render_apply`` skips
    ids it does not know), so the baseline would silently run with that knob at
    whatever the target defaults to — the least visible of the two failures."""
    c = _minimal_optimization_campaign()
    c["optimization"]["known_valid_baseline"] = {"NOPE": 2}
    errors = _hard_errors(c)
    assert errors and "NOPE" in errors[0] and "not a declared factor" in errors[0]


def test_rule13_an_empty_baseline_is_rejected():
    c = _minimal_optimization_campaign()
    c["optimization"]["known_valid_baseline"] = {}
    assert any("non-empty" in e for e in _hard_errors(c))
    # ...and the schema refuses it too, so the CLI reports it either way.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(c, _schema())


def test_rule13_an_int_valued_baseline_against_a_float_level_is_accepted():
    """Numeric levels are compared with a tolerance, matching
    ``matrix.check_fidelity``: ``2.0`` and ``2`` are the same configuration and
    rejecting one would fail a campaign over a YAML representation choice."""
    c = _minimal_optimization_campaign()
    c["optimization"]["known_valid_baseline"] = {"L1": 2.0}
    assert _hard_errors(c) == []


def test_rule14_policy_delta_outside_the_open_unit_half_is_rejected():
    for value in (0.9, 0.0, -0.1, 1.0):
        c = _minimal_optimization_campaign()
        c["optimization"]["policy"] = {"delta_terminal": value}
        errors = _hard_errors(c)
        assert any("delta_terminal" in e for e in errors), (value, errors)
    c = _minimal_optimization_campaign()
    c["optimization"]["policy"] = {"delta_screen": 0.6}
    assert any("delta_screen" in e for e in _hard_errors(c))


def test_rule14_epsilon_with_both_abs_and_pct_is_rejected():
    """``resolve_epsilon`` prefers ``abs`` and silently discards ``pct``, so a
    campaign declaring both has one of its two stated thresholds quietly
    ignored — the shape of defect that only shows up as a wrong number."""
    c = _minimal_optimization_campaign()
    c["optimization"]["policy"] = {"epsilon": {"abs": 0.5, "pct": 2.0}}
    errors = _hard_errors(c)
    assert any("epsilon" in e and "abs" in e for e in errors), errors


def test_rule14_epsilon_with_neither_abs_nor_pct_is_rejected():
    c = _minimal_optimization_campaign()
    c["optimization"]["policy"] = {"epsilon": {}}
    assert any("epsilon" in e for e in _hard_errors(c))


def test_rule14_confirm_max_rounds_below_one_is_rejected():
    """The compiled guard is ``round >= max_rounds`` against a 1-BASED counter,
    so 0 sends the campaign to report before the first round produced anything."""
    c = _minimal_optimization_campaign()
    c["optimization"]["policy"] = {"confirm_max_rounds": 0}
    assert any("confirm_max_rounds" in e for e in _hard_errors(c))


def test_shortlist_size_is_accepted_by_the_schema_and_defaults_to_three():
    """The default is 3 (terminal discrimination); the field stays OPTIONAL so
    every campaign authored before Task 9 keeps validating."""
    from orchestrator.optimize.policy import compile_policy

    c = _minimal_optimization_campaign()
    assert "shortlist_size" not in c["optimization"]["design"]["confirm"]
    jsonschema.validate(c, _schema())
    pol = compile_policy(c)
    assert pol["states"]["confirm"]["design"]["shortlist_size"] == 3

    c["optimization"]["design"]["confirm"]["shortlist_size"] = 1
    jsonschema.validate(c, _schema())
    assert compile_policy(c)["states"]["confirm"]["design"]["shortlist_size"] == 1
    assert _hard_errors(c) == []


def test_a_zero_shortlist_size_is_rejected_by_the_schema():
    c = _minimal_optimization_campaign()
    c["optimization"]["design"]["confirm"]["shortlist_size"] = 0
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(c, _schema())


# ---------------------------------------------------------------------------
# Rule 17: a config_patch factor whose file the run_command never names
# ---------------------------------------------------------------------------
#
# The apply/measure seam rewrites the run command's reference to the config
# file with a per-run patched copy. A command that never mentions the file has
# nothing to rewrite, so the patch cannot possibly take effect -- and before
# this rule existed, that campaign validated with zero errors, smoke-tested
# green, and then measured the BASELINE on every row while its design matrix
# and fitted surface looked real.


def _config_patch_factor(**over) -> dict:
    raw = {
        "id": "L7", "name": "cpu_bytes", "type": "numeric",
        "levels": [42949672960, 85899345920], "grid": 1,
        "apply": {"kind": "config_patch", "path": "engine.json",
                  "pointer": "/cache/cpu_bytes_to_use", "value": "{level}"},
        "manipulation": {"observable": "applied.L7", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": "R7", "kind": "correctness",
                       "statement": "the patched config round-trips",
                       "native_test": "tests/prop_cfg.py::test_patch"}],
    }
    raw.update(over)
    return raw


def test_rule17_config_patch_path_absent_from_run_command_is_an_error():
    c = _minimal_optimization_campaign()
    c["optimization"]["factors"].append(_config_patch_factor())
    c["optimization"]["run_command"] = "bench --json"
    errors = _hard_errors(c)
    assert any("engine.json" in e and "run_command" in e for e in errors), errors


def test_rule17_config_patch_path_present_in_run_command_passes():
    c = _minimal_optimization_campaign()
    c["optimization"]["factors"].append(_config_patch_factor())
    c["optimization"]["run_command"] = "bench --config engine.json --json"
    assert not [
        e for e in _hard_errors(c) if "engine.json" in e and "run_command" in e
    ]


def test_rule17_config_patch_path_missing_on_disk_warns(tmp_path: Path):
    """Path-based, so a WARNING: the file may legitimately be authored by the
    ``build`` stage, or live behind a symlink the validator cannot resolve."""
    c = _minimal_optimization_campaign()
    c["optimization"]["factors"].append(_config_patch_factor())
    c["optimization"]["run_command"] = "bench --config engine.json --json"
    c["target_system"]["repo_path"] = str(tmp_path)
    warnings = [e for e in validate_optimization_campaign(c) if e.startswith("WARN:")]
    assert any("engine.json" in w for w in warnings), warnings

    (tmp_path / "engine.json").write_text("{}")
    warnings = [e for e in validate_optimization_campaign(c) if e.startswith("WARN:")]
    assert not [w for w in warnings if "engine.json" in w]


def test_rule17_no_run_command_declared_is_not_reported():
    """A campaign with no ``run_command`` at all has other problems; reporting
    the patch path here would bury them under a secondary message."""
    c = _minimal_optimization_campaign()
    c["optimization"]["factors"].append(_config_patch_factor())
    c["optimization"].pop("run_command", None)
    assert not [e for e in _hard_errors(c) if "engine.json" in e]


def test_rule17_agrees_with_the_runtime_on_what_naming_the_file_means():
    """A path that appears only as the TAIL of a longer path is not "named":
    the runtime rewrites at argument boundaries, so a validator using a bare
    ``in`` substring test would pass a campaign the runtime then rejects --
    reintroducing the "validated clean, aborted later" gap inside the check."""
    c = _minimal_optimization_campaign()
    c["optimization"]["factors"].append(_config_patch_factor())
    c["optimization"]["run_command"] = "bench --config other/engine.json --json"
    assert any("engine.json" in e and "run_command" in e for e in _hard_errors(c))

    c["optimization"]["run_command"] = "bench --config=engine.json --json"
    assert not [
        e for e in _hard_errors(c) if "engine.json" in e and "run_command" in e
    ], "the --flag=value form is an ordinary way to name a config file"
