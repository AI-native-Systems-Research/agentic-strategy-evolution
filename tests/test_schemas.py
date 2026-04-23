"""Tests for all 7 schemas — validates both positive and negative cases."""
import json

import jsonschema
import pytest


class TestStateSchema:
    def test_valid_init_state(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "campaign-001",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        jsonschema.validate(instance, schema)

    def test_valid_running_state(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "RUNNING",
            "iteration": 3,
            "run_id": "campaign-001",
            "family": "routing-signals",
            "timestamp": "2026-04-01T12:00:00Z",
        }
        jsonschema.validate(instance, schema)

    def test_all_phases_accepted(self, load_schema):
        schema = load_schema("state.schema.json")
        phases = [
            "INIT", "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
            "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
            "TUNING", "EXTRACTION", "DONE",
        ]
        for phase in phases:
            instance = {
                "phase": phase,
                "iteration": 0,
                "run_id": "test",
                "family": None,
                "timestamp": "2026-04-01T00:00:00Z",
            }
            jsonschema.validate(instance, schema)

    def test_invalid_phase_rejected(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INVALID_PHASE",
            "iteration": 0,
            "run_id": "campaign-001",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_negative_iteration_rejected(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INIT",
            "iteration": -1,
            "run_id": "campaign-001",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestLedgerSchema:
    def test_valid_baseline_row(self, load_schema):
        schema = load_schema("ledger.schema.json")
        instance = {
            "iterations": [
                {
                    "iteration": 0,
                    "family": "baseline",
                    "timestamp": "2026-04-01T00:00:00Z",
                    "candidate_id": "baseline",
                    "h_main_result": None,
                    "ablation_results": {},
                    "control_result": None,
                    "robustness_result": None,
                    "prediction_accuracy": None,
                    "principles_extracted": [],
                    "frontier_update": None,
                }
            ]
        }
        jsonschema.validate(instance, schema)

    def test_valid_iteration_row(self, load_schema):
        schema = load_schema("ledger.schema.json")
        instance = {
            "iterations": [
                {
                    "iteration": 5,
                    "family": "routing-signals",
                    "timestamp": "2026-04-01T12:00:00Z",
                    "candidate_id": "compound-routing-pa-qd",
                    "h_main_result": "CONFIRMED",
                    "ablation_results": {
                        "h-ablation-pa": "CONFIRMED",
                        "h-ablation-qd": "REFUTED",
                    },
                    "control_result": "REFUTED",
                    "robustness_result": "PARTIALLY_CONFIRMED",
                    "prediction_accuracy": {
                        "arms_correct": 4,
                        "arms_total": 6,
                        "accuracy_pct": 66.7,
                    },
                    "principles_extracted": [
                        {"id": "principle-005", "action": "INSERT"},
                        {"id": "principle-003", "action": "UPDATE"},
                    ],
                    "frontier_update": "Investigate QD signal degradation under bursty load",
                }
            ]
        }
        jsonschema.validate(instance, schema)

    def test_empty_ledger_valid(self, load_schema):
        schema = load_schema("ledger.schema.json")
        jsonschema.validate({"iterations": []}, schema)

    def test_invalid_result_value_rejected(self, load_schema):
        schema = load_schema("ledger.schema.json")
        instance = {
            "iterations": [
                {
                    "iteration": 1,
                    "family": "test",
                    "timestamp": "2026-04-01T00:00:00Z",
                    "candidate_id": "test",
                    "h_main_result": "INVALID_STATUS",
                    "ablation_results": {},
                    "control_result": None,
                    "robustness_result": None,
                    "prediction_accuracy": None,
                    "principles_extracted": [],
                    "frontier_update": None,
                }
            ]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_invalid_principle_action_rejected(self, load_schema):
        schema = load_schema("ledger.schema.json")
        instance = {
            "iterations": [
                {
                    "iteration": 1,
                    "family": "test",
                    "timestamp": "2026-04-01T00:00:00Z",
                    "candidate_id": "test",
                    "h_main_result": None,
                    "ablation_results": {},
                    "control_result": None,
                    "robustness_result": None,
                    "prediction_accuracy": None,
                    "principles_extracted": [{"id": "p-1", "action": "DELETE"}],
                    "frontier_update": None,
                }
            ]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestPrinciplesSchema:
    def test_valid_principle_store(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [
                {
                    "id": "RP-1",
                    "statement": "SLO-gated admission control is non-zero-sum at saturation",
                    "confidence": "high",
                    "regime": "arrival_rate > 50% capacity",
                    "evidence": ["iteration-5-h-main", "iteration-12-robustness"],
                    "contradicts": [],
                    "extraction_iteration": 5,
                    "mechanism": "Admission control prevents low-value work from saturating service",
                    "applicability_bounds": "holds across bursty, constant, stochastic workloads",
                    "superseded_by": None,
                    "status": "active",
                }
            ]
        }
        jsonschema.validate(instance, schema)

    def test_empty_store_valid(self, load_schema):
        schema = load_schema("principles.schema.json")
        jsonschema.validate({"principles": []}, schema)

    def test_pruned_principle(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [
                {
                    "id": "RP-3",
                    "statement": "KV-utilization is counterproductive under memory pressure",
                    "confidence": "high",
                    "regime": "memory_pressure > 80%",
                    "evidence": ["iteration-6-h-main"],
                    "contradicts": ["RP-1"],
                    "extraction_iteration": 6,
                    "mechanism": "KV-utilization scorer adds overhead without benefit",
                    "applicability_bounds": "high-memory-pressure regimes only",
                    "superseded_by": "RP-7",
                    "status": "pruned",
                }
            ]
        }
        jsonschema.validate(instance, schema)

    def test_invalid_confidence_rejected(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [
                {
                    "id": "RP-1",
                    "statement": "test",
                    "confidence": "very_high",
                    "regime": "all",
                    "evidence": [],
                    "contradicts": [],
                    "extraction_iteration": 1,
                    "mechanism": "test",
                    "applicability_bounds": "test",
                    "superseded_by": None,
                    "status": "active",
                }
            ]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestBundleSchema:
    def test_valid_full_bundle(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 5,
                "family": "routing-signals",
                "research_question": "Does compound routing reduce critical TTFT P99?",
            },
            "arms": [
                {
                    "type": "h-main",
                    "prediction": "Compound routing reduces critical TTFT P99 by >40%",
                    "mechanism": "PA reduces jitter, QD ensures fairness under saturation",
                    "diagnostic": "If failed, check interaction between scheduling priority and depth signal",
                },
                {
                    "type": "h-ablation",
                    "component": "prefix-affinity",
                    "prediction": "PA alone reduces P99 TTFT by >25%",
                    "mechanism": "Reduces jitter by grouping similar-length sequences",
                    "diagnostic": "If failed, check if variance reduction was correct metric",
                },
                {
                    "type": "h-control-negative",
                    "prediction": "At <50% utilization, compound ≈ round-robin",
                    "mechanism": "No contention → scheduling irrelevant",
                    "diagnostic": "If failed, overhead or secondary effect present",
                },
            ],
        }
        jsonschema.validate(instance, schema)

    def test_invalid_arm_type_rejected(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 1,
                "family": "test",
                "research_question": "test?",
            },
            "arms": [
                {
                    "type": "h-invalid",
                    "prediction": "x",
                    "mechanism": "y",
                    "diagnostic": "z",
                }
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_empty_arms_rejected(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 1,
                "family": "test",
                "research_question": "test?",
            },
            "arms": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestFindingsSchema:
    def test_valid_findings(self, load_schema):
        schema = load_schema("findings.schema.json")
        instance = {
            "iteration": 5,
            "bundle_ref": "runs/iter-5/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": ">40% reduction in critical TTFT P99",
                    "observed": "42.1% reduction",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                },
                {
                    "arm_type": "h-control-negative",
                    "predicted": "≈round-robin at <50% util",
                    "observed": "2.1% improvement still observed",
                    "status": "REFUTED",
                    "error_type": "regime",
                    "diagnostic_note": "Threshold is ~60%, not 50%",
                },
            ],
            "discrepancy_analysis": "Control-negative failure indicates mechanism threshold is higher than predicted.",
        }
        jsonschema.validate(instance, schema)

    def test_invalid_error_type_rejected(self, load_schema):
        schema = load_schema("findings.schema.json")
        instance = {
            "iteration": 1,
            "bundle_ref": "test",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": "x",
                    "observed": "y",
                    "status": "REFUTED",
                    "error_type": "unknown_error",
                    "diagnostic_note": None,
                }
            ],
            "discrepancy_analysis": "test",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestTraceSchema:
    def test_valid_state_transition(self, load_schema):
        schema = load_schema("trace.schema.json")
        instance = {
            "timestamp": "2026-04-01T12:00:00Z",
            "run_id": "campaign-001",
            "event_type": "state_transition",
            "payload": {
                "from_state": "DESIGN",
                "to_state": "DESIGN_REVIEW",
                "trigger": "hypothesis.md written",
            },
        }
        jsonschema.validate(instance, schema)

    def test_valid_llm_call(self, load_schema):
        schema = load_schema("trace.schema.json")
        instance = {
            "timestamp": "2026-04-01T12:01:00Z",
            "run_id": "campaign-001",
            "event_type": "llm_call",
            "payload": {
                "role": "planner",
                "prompt_tokens": 5000,
                "completion_tokens": 2000,
                "cost_usd": 0.035,
            },
        }
        jsonschema.validate(instance, schema)

    def test_valid_gate_decision(self, load_schema):
        schema = load_schema("trace.schema.json")
        instance = {
            "timestamp": "2026-04-01T12:03:00Z",
            "run_id": "campaign-001",
            "event_type": "gate_decision",
            "payload": {
                "gate": "HUMAN_DESIGN_GATE",
                "decision": "approve",
                "artifact": "runs/iter-1/hypothesis.md",
            },
        }
        jsonschema.validate(instance, schema)

    def test_invalid_event_type_rejected(self, load_schema):
        schema = load_schema("trace.schema.json")
        instance = {
            "timestamp": "2026-04-01T12:00:00Z",
            "run_id": "test",
            "event_type": "invalid_type",
            "payload": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestAdditionalPropertiesRejected:
    """Verify additionalProperties: false is enforced across schemas."""

    def test_state_rejects_extra_field(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z",
            "extra_field": "should be rejected",
        }
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(instance, schema)

    def test_findings_rejects_extra_field(self, load_schema):
        schema = load_schema("findings.schema.json")
        instance = {
            "iteration": 1,
            "bundle_ref": "test",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": "x",
                    "observed": "y",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                }
            ],
            "discrepancy_analysis": "test",
            "bogus_key": True,
        }
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(instance, schema)

    def test_trace_rejects_extra_field(self, load_schema):
        schema = load_schema("trace.schema.json")
        instance = {
            "timestamp": "2026-04-01T12:00:00Z",
            "run_id": "test",
            "event_type": "state_transition",
            "payload": {},
            "extra": "nope",
        }
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(instance, schema)


class TestSummarySchema:
    def test_valid_summary(self, load_schema):
        schema = load_schema("summary.schema.json")
        instance = {
            "run_id": "campaign-001",
            "total_cost_usd": 42.15,
            "total_tokens": {"input": 1250000, "output": 380000},
            "total_iterations": 12,
            "cost_by_phase": {
                "FRAMING": 2.5,
                "DESIGN": 8.3,
                "RUNNING": 18.0,
            },
            "per_iteration_stats": [
                {
                    "iteration": 1,
                    "family": "routing",
                    "cost_usd": 3.2,
                    "tokens": 95000,
                    "h_main_result": "CONFIRMED",
                }
            ],
            "mechanism_families_investigated": ["routing-signals", "scheduling"],
            "principles_inserted": 14,
            "principles_updated": 3,
            "principles_pruned": 2,
            "final_principle_count": 15,
        }
        jsonschema.validate(instance, schema)

    def test_negative_cost_rejected(self, load_schema):
        schema = load_schema("summary.schema.json")
        instance = {
            "run_id": "test",
            "total_cost_usd": -1.0,
            "total_tokens": {"input": 0, "output": 0},
            "total_iterations": 0,
            "cost_by_phase": {},
            "per_iteration_stats": [],
            "mechanism_families_investigated": [],
            "principles_inserted": 0,
            "principles_updated": 0,
            "principles_pruned": 0,
            "final_principle_count": 0,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestCampaignSchema:
    def test_valid_campaign(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "research_question": "Can routing algorithms reduce tail latency?",
            "target_system": {
                "name": "BLIS",
                "description": "LLM inference serving simulator",
                "observable_metrics": ["latency_p99", "throughput"],
                "controllable_knobs": ["routing_algorithm", "batch_size"],
            },
            "review": {
                "design_perspectives": ["stats", "causal", "confound"],
                "findings_perspectives": ["stats", "causal", "confound", "robustness"],
                "max_review_rounds": 10,
            },
            "prompts": {
                "methodology_layer": "prompts/methodology/",
                "domain_adapter_layer": "prompts/blis/",
            },
        }
        jsonschema.validate(instance, schema)

    def test_minimal_campaign(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "research_question": "What affects latency?",
            "target_system": {
                "name": "my-system",
                "description": "A system.",
                "observable_metrics": ["latency"],
                "controllable_knobs": ["config_a"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 1,
            },
            "prompts": {
                "methodology_layer": "prompts/",
                "domain_adapter_layer": None,
            },
        }
        jsonschema.validate(instance, schema)

    def test_missing_target_system_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 5,
            },
            "prompts": {"methodology_layer": "prompts/"},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_empty_metrics_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "target_system": {
                "name": "x",
                "description": "x",
                "observable_metrics": [],
                "controllable_knobs": ["a"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 5,
            },
            "prompts": {"methodology_layer": "prompts/"},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_zero_review_rounds_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "target_system": {
                "name": "x",
                "description": "x",
                "observable_metrics": ["m"],
                "controllable_knobs": ["k"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 0,
            },
            "prompts": {"methodology_layer": "prompts/"},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_extra_top_level_field_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "research_question": "What affects latency?",
            "target_system": {
                "name": "x",
                "description": "x",
                "observable_metrics": ["m"],
                "controllable_knobs": ["k"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 5,
            },
            "prompts": {"methodology_layer": "prompts/"},
            "extra_field": "should fail",
        }
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(instance, schema)

    def test_max_iterations_accepted(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "research_question": "What affects latency?",
            "max_iterations": 5,
            "target_system": {
                "name": "x",
                "description": "x",
                "observable_metrics": ["m"],
                "controllable_knobs": ["k"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 1,
            },
            "prompts": {"methodology_layer": "prompts/"},
        }
        jsonschema.validate(instance, schema)

    def test_max_iterations_zero_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = {
            "research_question": "What affects latency?",
            "max_iterations": 0,
            "target_system": {
                "name": "x",
                "description": "x",
                "observable_metrics": ["m"],
                "controllable_knobs": ["k"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 1,
            },
            "prompts": {"methodology_layer": "prompts/"},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_campaign_minimal_valid(self, load_schema):
        """Campaign with only name, description, repo_path is valid."""
        schema = load_schema("campaign.schema.yaml")
        minimal = {
            "research_question": "Why is it slow?",
            "target_system": {
                "name": "TestSys",
                "description": "A test system.",
                "repo_path": "/tmp/repo",
            },
            "review": {
                "design_perspectives": ["rigor"],
                "findings_perspectives": ["rigor"],
                "max_review_rounds": 1,
            },
            "prompts": {
                "methodology_layer": "prompts/methodology",
                "domain_adapter_layer": None,
            },
        }
        jsonschema.validate(minimal, schema)  # Should not raise


class TestPrinciplesCategoryField:
    def test_domain_category_accepted(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [{
                "id": "P-1", "statement": "test", "confidence": "high",
                "regime": "all", "evidence": [], "contradicts": [],
                "extraction_iteration": 1, "mechanism": "test",
                "applicability_bounds": "test", "superseded_by": None,
                "category": "domain", "status": "active",
            }]
        }
        jsonschema.validate(instance, schema)

    def test_meta_category_accepted(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [{
                "id": "M-1", "statement": "reviewer X is ineffective",
                "confidence": "medium", "regime": "all", "evidence": [],
                "contradicts": [], "extraction_iteration": 5,
                "mechanism": "meta-review", "applicability_bounds": "all",
                "superseded_by": None, "category": "meta", "status": "active",
            }]
        }
        jsonschema.validate(instance, schema)

    def test_omitted_category_accepted(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [{
                "id": "P-1", "statement": "test", "confidence": "high",
                "regime": "all", "evidence": [], "contradicts": [],
                "extraction_iteration": 1, "mechanism": "test",
                "applicability_bounds": "test", "superseded_by": None,
                "status": "active",
            }]
        }
        jsonschema.validate(instance, schema)

    def test_invalid_category_rejected(self, load_schema):
        schema = load_schema("principles.schema.json")
        instance = {
            "principles": [{
                "id": "P-1", "statement": "test", "confidence": "high",
                "regime": "all", "evidence": [], "contradicts": [],
                "extraction_iteration": 1, "mechanism": "test",
                "applicability_bounds": "test", "superseded_by": None,
                "category": "system", "status": "active",
            }]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestStateConfigRef:
    def test_config_ref_string_accepted(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INIT", "iteration": 0, "run_id": "test",
            "family": None, "timestamp": "2026-04-01T00:00:00Z",
            "config_ref": "campaign.yaml",
        }
        jsonschema.validate(instance, schema)

    def test_config_ref_null_accepted(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INIT", "iteration": 0, "run_id": "test",
            "family": None, "timestamp": "2026-04-01T00:00:00Z",
            "config_ref": None,
        }
        jsonschema.validate(instance, schema)

    def test_config_ref_omitted_accepted(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INIT", "iteration": 0, "run_id": "test",
            "family": None, "timestamp": "2026-04-01T00:00:00Z",
        }
        jsonschema.validate(instance, schema)


class TestArmMetadata:
    def test_bundle_arm_with_metadata(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 1, "family": "test",
                "research_question": "test?",
            },
            "arms": [{
                "type": "h-main",
                "prediction": "x", "mechanism": "y", "diagnostic": "z",
                "metadata": {"gpu_type": "A100", "custom_param": 42},
            }],
        }
        jsonschema.validate(instance, schema)

    def test_bundle_arm_without_metadata(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 1, "family": "test",
                "research_question": "test?",
            },
            "arms": [{
                "type": "h-main",
                "prediction": "x", "mechanism": "y", "diagnostic": "z",
            }],
        }
        jsonschema.validate(instance, schema)

    def test_findings_arm_with_metadata(self, load_schema):
        schema = load_schema("findings.schema.json")
        instance = {
            "iteration": 1, "bundle_ref": "test",
            "arms": [{
                "arm_type": "h-main",
                "predicted": "x", "observed": "y",
                "status": "CONFIRMED", "error_type": None,
                "diagnostic_note": None,
                "metadata": {"latency_p99_ms": 42.1},
            }],
            "discrepancy_analysis": "test",
        }
        jsonschema.validate(instance, schema)


class TestLedgerDomainMetrics:
    def test_ledger_row_with_domain_metrics(self, load_schema):
        schema = load_schema("ledger.schema.json")
        instance = {
            "iterations": [{
                "iteration": 1, "family": "test",
                "timestamp": "2026-04-01T00:00:00Z",
                "candidate_id": "test",
                "h_main_result": "CONFIRMED",
                "ablation_results": {},
                "control_result": None,
                "robustness_result": None,
                "prediction_accuracy": None,
                "principles_extracted": [],
                "frontier_update": None,
                "domain_metrics": {
                    "memory_peak_gb": 12.4,
                    "compilation_time_s": 3.2,
                },
            }]
        }
        jsonschema.validate(instance, schema)

    def test_ledger_row_without_domain_metrics(self, load_schema):
        schema = load_schema("ledger.schema.json")
        instance = {
            "iterations": [{
                "iteration": 1, "family": "test",
                "timestamp": "2026-04-01T00:00:00Z",
                "candidate_id": "test",
                "h_main_result": None,
                "ablation_results": {},
                "control_result": None,
                "robustness_result": None,
                "prediction_accuracy": None,
                "principles_extracted": [],
                "frontier_update": None,
            }]
        }
        jsonschema.validate(instance, schema)


class TestCampaignExecutionConfig:
    """Tests for the optional execution config in campaign schema."""

    def _base_campaign(self, **execution_fields):
        campaign = {
            "research_question": "Test question?",
            "target_system": {
                "name": "test",
                "description": "test system",
                "observable_metrics": ["latency"],
                "controllable_knobs": ["config"],
            },
            "review": {
                "design_perspectives": ["general"],
                "findings_perspectives": ["general"],
                "max_review_rounds": 1,
            },
            "prompts": {"methodology_layer": "prompts/"},
        }
        if execution_fields:
            campaign["target_system"]["execution"] = execution_fields
        return campaign

    def test_campaign_without_execution_valid(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        jsonschema.validate(self._base_campaign(), schema)

    def test_campaign_with_execution_valid(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = self._base_campaign(
            run_command="./sim run --metrics-path {metrics_path}",
            repo_path="/tmp/my-repo",
            setup_commands=["pip install -e ."],
            metrics_output_format="json",
            cleanup_commands=["rm -rf tmp/"],
            timeout=600,
        )
        jsonschema.validate(instance, schema)

    def test_execution_minimal_valid(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = self._base_campaign(
            run_command="./sim run --metrics-path {metrics_path}",
        )
        jsonschema.validate(instance, schema)

    def test_execution_without_run_command_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = self._base_campaign(repo_path="/tmp/repo")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_execution_null_repo_path_valid(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = self._base_campaign(
            run_command="./sim run --metrics-path {metrics_path}",
            repo_path=None,
        )
        jsonschema.validate(instance, schema)

    def test_execution_invalid_timeout_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = self._base_campaign(
            run_command="./sim run --metrics-path {metrics_path}",
            timeout=0,
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_execution_invalid_metrics_format_rejected(self, load_schema):
        schema = load_schema("campaign.schema.yaml")
        instance = self._base_campaign(
            run_command="./sim run --metrics-path {metrics_path}",
            metrics_output_format="csv",
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


class TestInvestigationSummarySchema:
    """Tests for investigation_summary.schema.json."""

    def test_valid_summary(self, load_schema):
        schema = load_schema("investigation_summary.schema.json")
        instance = {
            "iteration": 1,
            "what_was_tested": "Prefix token sharing mechanism for KV-cache reuse.",
            "key_findings": "H-main refuted: BLIS does not implement prefix reuse.",
            "principles_changed": "Inserted RP-1 (no prefix reuse), MP-1 (verify features).",
            "open_questions": "Does the scheduler affect TTFT under load?",
            "suggested_next_direction": "Investigate scheduling policy effects.",
        }
        jsonschema.validate(instance, schema)

    def test_missing_field_rejected(self, load_schema):
        schema = load_schema("investigation_summary.schema.json")
        instance = {
            "iteration": 1,
            "what_was_tested": "test",
            # missing key_findings and others
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_empty_string_rejected(self, load_schema):
        schema = load_schema("investigation_summary.schema.json")
        instance = {
            "iteration": 1,
            "what_was_tested": "",
            "key_findings": "x",
            "principles_changed": "x",
            "open_questions": "x",
            "suggested_next_direction": "x",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_extra_field_rejected(self, load_schema):
        schema = load_schema("investigation_summary.schema.json")
        instance = {
            "iteration": 1,
            "what_was_tested": "x",
            "key_findings": "x",
            "principles_changed": "x",
            "open_questions": "x",
            "suggested_next_direction": "x",
            "extra": "nope",
        }
        with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
            jsonschema.validate(instance, schema)


class TestExperimentPlanSchema:
    """Tests for experiment_plan.schema.json."""

    def test_valid_plan(self, load_schema):
        schema = load_schema("experiment_plan.schema.json")
        instance = {
            "baseline": {
                "description": "Default config baseline",
                "command": "./sim run --metrics-path baseline.json",
            },
            "experiments": [
                {
                    "arm_type": "h-main",
                    "description": "Test admission control",
                    "config_changes": "Add --admission-threshold 0.8",
                    "command": "./sim run --admission-threshold 0.8 --metrics-path h-main.json",
                },
            ],
        }
        jsonschema.validate(instance, schema)

    def test_multiple_arms_valid(self, load_schema):
        schema = load_schema("experiment_plan.schema.json")
        instance = {
            "baseline": {
                "description": "Baseline",
                "command": "./sim run --metrics-path baseline.json",
            },
            "experiments": [
                {
                    "arm_type": "h-main",
                    "description": "Main hypothesis",
                    "command": "./sim run --flag-a --metrics-path h-main.json",
                },
                {
                    "arm_type": "h-control-negative",
                    "description": "Control",
                    "command": "./sim run --metrics-path h-control.json",
                },
            ],
        }
        jsonschema.validate(instance, schema)

    def test_missing_baseline_rejected(self, load_schema):
        schema = load_schema("experiment_plan.schema.json")
        instance = {
            "experiments": [
                {"arm_type": "h-main", "description": "x", "command": "x"},
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_empty_experiments_rejected(self, load_schema):
        schema = load_schema("experiment_plan.schema.json")
        instance = {
            "baseline": {"description": "x", "command": "x"},
            "experiments": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_missing_command_rejected(self, load_schema):
        schema = load_schema("experiment_plan.schema.json")
        instance = {
            "baseline": {"description": "x", "command": "x"},
            "experiments": [
                {"arm_type": "h-main", "description": "x"},
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)
