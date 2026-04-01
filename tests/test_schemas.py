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
