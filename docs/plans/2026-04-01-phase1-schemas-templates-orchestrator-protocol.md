# Phase 1: Schemas + Templates + Orchestrator Skeleton + Protocol Doc

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the Nous methodology backbone end-to-end — schemas that define the data contracts, templates that conform to them, a protocol doc, a BLIS case study, and an orchestrator state machine that drives the 5-phase loop with stub agents.

**Architecture:** The orchestrator is a Python state machine (NOT an LLM) that owns phase transitions, file I/O, and gate logic. It drives 4 agent roles (Planner, Executor, Reviewer, Extractor) through 11 states. All artifacts on disk are schema-governed. The orchestrator supports checkpoint/resume, fast-fail rules, and human approval gates.

**Tech Stack:** Python 3.11+, jsonschema, PyYAML, pytest

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `orchestrator/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "nous"
version = "0.1.0"
description = "Nous — hypothesis-driven experimentation framework for software systems"
requires-python = ">=3.11"
license = {text = "Apache-2.0"}
dependencies = [
    "jsonschema>=4.20.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
```

**Step 2: Create orchestrator/__init__.py and tests/__init__.py**

Empty files.

**Step 3: Create tests/conftest.py**

```python
import json
from pathlib import Path

import pytest
import yaml


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture
def schemas_dir():
    return SCHEMAS_DIR


@pytest.fixture
def templates_dir():
    return TEMPLATES_DIR


@pytest.fixture
def load_schema(schemas_dir):
    def _load(name: str) -> dict:
        path = schemas_dir / name
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(path.read_text())
        return json.loads(path.read_text())
    return _load


@pytest.fixture
def load_template(templates_dir):
    def _load(name: str):
        path = templates_dir / name
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(path.read_text())
        if path.suffix == ".json":
            return json.loads(path.read_text())
        return path.read_text()
    return _load
```

**Step 4: Install in dev mode and verify**

Run: `cd /Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/fork-agentic-evolution && pip install -e ".[dev]"`

**Step 5: Commit**

```bash
git add pyproject.toml orchestrator/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project setup with pyproject.toml and test fixtures"
```

---

## Task 2: State Schema

**Files:**
- Create: `schemas/state.schema.json`
- Create: `tests/test_schemas.py`

**Step 1: Write the failing test**

```python
"""tests/test_schemas.py"""
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
            "timestamp": "2026-04-01T00:00:00Z"
        }
        jsonschema.validate(instance, schema)

    def test_valid_running_state(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "RUNNING",
            "iteration": 3,
            "run_id": "campaign-001",
            "family": "routing-signals",
            "timestamp": "2026-04-01T12:00:00Z"
        }
        jsonschema.validate(instance, schema)

    def test_invalid_phase_rejected(self, load_schema):
        schema = load_schema("state.schema.json")
        instance = {
            "phase": "INVALID_PHASE",
            "iteration": 0,
            "run_id": "campaign-001",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z"
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
            "timestamp": "2026-04-01T00:00:00Z"
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py::TestStateSchema -v`
Expected: FAIL (schema file missing)

**Step 3: Write schemas/state.schema.json**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/state.schema.json",
  "title": "Investigation State",
  "description": "Current phase, family, and iteration — the investigation checkpoint.",
  "type": "object",
  "required": ["phase", "iteration", "run_id", "family", "timestamp"],
  "additionalProperties": false,
  "properties": {
    "phase": {
      "type": "string",
      "enum": [
        "INIT", "FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
        "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
        "TUNING", "EXTRACTION", "DONE"
      ],
      "description": "Current state machine phase."
    },
    "iteration": {
      "type": "integer",
      "minimum": 0,
      "description": "Current iteration number (0 = baseline)."
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "description": "Unique campaign identifier."
    },
    "family": {
      "type": ["string", "null"],
      "description": "Current mechanism family under investigation, null before framing."
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp of last state update."
    }
  }
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas.py::TestStateSchema -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add schemas/state.schema.json tests/test_schemas.py
git commit -m "feat: add state schema with validation tests"
```

---

## Task 3: Ledger Schema

**Files:**
- Create: `schemas/ledger.schema.json`
- Modify: `tests/test_schemas.py` (append TestLedgerSchema class)

**Step 1: Write the failing test**

Append to `tests/test_schemas.py`:

```python
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
                    "frontier_update": None
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
                        "h-ablation-qd": "REFUTED"
                    },
                    "control_result": "REFUTED",
                    "robustness_result": "PARTIALLY_CONFIRMED",
                    "prediction_accuracy": {
                        "arms_correct": 4,
                        "arms_total": 6,
                        "accuracy_pct": 66.7
                    },
                    "principles_extracted": [
                        {"id": "principle-005", "action": "INSERT"},
                        {"id": "principle-003", "action": "UPDATE"}
                    ],
                    "frontier_update": "Investigate QD signal degradation under bursty load"
                }
            ]
        }
        jsonschema.validate(instance, schema)

    def test_empty_ledger_valid(self, load_schema):
        schema = load_schema("ledger.schema.json")
        jsonschema.validate({"iterations": []}, schema)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py::TestLedgerSchema -v`

**Step 3: Write schemas/ledger.schema.json**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/ledger.schema.json",
  "title": "Investigation Ledger",
  "description": "Append-only log: one record per completed iteration.",
  "type": "object",
  "required": ["iterations"],
  "additionalProperties": false,
  "properties": {
    "iterations": {
      "type": "array",
      "items": { "$ref": "#/$defs/ledger_row" }
    }
  },
  "$defs": {
    "ledger_row": {
      "type": "object",
      "required": [
        "iteration", "family", "timestamp", "candidate_id",
        "h_main_result", "ablation_results", "control_result",
        "robustness_result", "prediction_accuracy",
        "principles_extracted", "frontier_update"
      ],
      "additionalProperties": false,
      "properties": {
        "iteration": { "type": "integer", "minimum": 0 },
        "family": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" },
        "candidate_id": { "type": "string" },
        "h_main_result": {
          "type": ["string", "null"],
          "enum": ["CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED", null]
        },
        "ablation_results": {
          "type": "object",
          "additionalProperties": {
            "type": "string",
            "enum": ["CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED"]
          }
        },
        "control_result": {
          "type": ["string", "null"],
          "enum": ["CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED", null]
        },
        "robustness_result": {
          "type": ["string", "null"],
          "enum": ["CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED", null]
        },
        "prediction_accuracy": {
          "oneOf": [
            { "type": "null" },
            { "$ref": "#/$defs/accuracy" }
          ]
        },
        "principles_extracted": {
          "type": "array",
          "items": { "$ref": "#/$defs/principle_ref" }
        },
        "frontier_update": { "type": ["string", "null"] }
      }
    },
    "accuracy": {
      "type": "object",
      "required": ["arms_correct", "arms_total", "accuracy_pct"],
      "additionalProperties": false,
      "properties": {
        "arms_correct": { "type": "integer", "minimum": 0 },
        "arms_total": { "type": "integer", "minimum": 1 },
        "accuracy_pct": { "type": "number", "minimum": 0, "maximum": 100 }
      }
    },
    "principle_ref": {
      "type": "object",
      "required": ["id", "action"],
      "additionalProperties": false,
      "properties": {
        "id": { "type": "string" },
        "action": { "type": "string", "enum": ["INSERT", "UPDATE", "PRUNE"] }
      }
    }
  }
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas.py::TestLedgerSchema -v`

**Step 5: Commit**

```bash
git add schemas/ledger.schema.json tests/test_schemas.py
git commit -m "feat: add ledger schema with validation tests"
```

---

## Task 4: Principles Schema

**Files:**
- Create: `schemas/principles.schema.json`
- Modify: `tests/test_schemas.py` (append TestPrinciplesSchema)

**Step 1: Write the failing test**

```python
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
                    "superseded_by": null,
                    "status": "active"
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
                    "mechanism": "KV-utilization scorer adds overhead without benefit when memory constrained",
                    "applicability_bounds": "high-memory-pressure regimes only",
                    "superseded_by": "RP-7",
                    "status": "pruned"
                }
            ]
        }
        jsonschema.validate(instance, schema)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py::TestPrinciplesSchema -v`

**Step 3: Write schemas/principles.schema.json**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/principles.schema.json",
  "title": "Principle Store",
  "description": "Living knowledge base of extracted principles. Supports insert, update, and prune operations.",
  "type": "object",
  "required": ["principles"],
  "additionalProperties": false,
  "properties": {
    "principles": {
      "type": "array",
      "items": { "$ref": "#/$defs/principle" }
    }
  },
  "$defs": {
    "principle": {
      "type": "object",
      "required": [
        "id", "statement", "confidence", "regime", "evidence",
        "contradicts", "extraction_iteration", "mechanism",
        "applicability_bounds", "superseded_by", "status"
      ],
      "additionalProperties": false,
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "statement": { "type": "string", "minLength": 1 },
        "confidence": {
          "type": "string",
          "enum": ["low", "medium", "high"]
        },
        "regime": { "type": "string" },
        "evidence": {
          "type": "array",
          "items": { "type": "string" }
        },
        "contradicts": {
          "type": "array",
          "items": { "type": "string" }
        },
        "extraction_iteration": { "type": "integer", "minimum": 0 },
        "mechanism": { "type": "string" },
        "applicability_bounds": { "type": "string" },
        "superseded_by": { "type": ["string", "null"] },
        "status": {
          "type": "string",
          "enum": ["active", "updated", "pruned"]
        }
      }
    }
  }
}
```

**Step 4: Run, verify, commit**

```bash
git add schemas/principles.schema.json tests/test_schemas.py
git commit -m "feat: add principles schema with validation tests"
```

---

## Task 5: Bundle Schema (YAML)

**Files:**
- Create: `schemas/bundle.schema.yaml`
- Modify: `tests/test_schemas.py` (append TestBundleSchema)

**Step 1: Write the failing test**

```python
class TestBundleSchema:
    def test_valid_full_bundle(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 5,
                "family": "routing-signals",
                "research_question": "Does compound routing reduce critical TTFT P99?"
            },
            "arms": [
                {
                    "type": "h-main",
                    "prediction": "Compound routing reduces critical TTFT P99 by >40%",
                    "mechanism": "PA reduces jitter, QD ensures fairness under saturation",
                    "diagnostic": "If failed, check interaction between scheduling priority and depth signal"
                },
                {
                    "type": "h-ablation",
                    "component": "prefix-affinity",
                    "prediction": "PA alone reduces P99 TTFT by >25%",
                    "mechanism": "Reduces jitter by grouping similar-length sequences",
                    "diagnostic": "If failed, check if variance reduction was correct metric"
                },
                {
                    "type": "h-control-negative",
                    "prediction": "At <50% utilization, compound ≈ round-robin",
                    "mechanism": "No contention → scheduling irrelevant",
                    "diagnostic": "If failed, overhead or secondary effect present"
                },
                {
                    "type": "h-robustness",
                    "prediction": "Effect holds under bursty arrivals",
                    "mechanism": "Mechanism independent of arrival distribution",
                    "diagnostic": "If failed, mechanism relies on arrival properties"
                }
            ]
        }
        jsonschema.validate(instance, schema)

    def test_invalid_arm_type_rejected(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 1,
                "family": "test",
                "research_question": "test?"
            },
            "arms": [
                {
                    "type": "h-invalid",
                    "prediction": "x",
                    "mechanism": "y",
                    "diagnostic": "z"
                }
            ]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_empty_arms_rejected(self, load_schema):
        schema = load_schema("bundle.schema.yaml")
        instance = {
            "metadata": {
                "iteration": 1,
                "family": "test",
                "research_question": "test?"
            },
            "arms": []
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py::TestBundleSchema -v`

**Step 3: Write schemas/bundle.schema.yaml**

This is a JSON Schema expressed in YAML for readability. Validated by loading YAML and using jsonschema.

```yaml
$schema: "https://json-schema.org/draft/2020-12/schema"
$id: "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/bundle.schema.yaml"
title: Hypothesis Bundle
description: >
  A structured set of falsifiable hypotheses (arms) designed to test a mechanism.
  Each arm is a (prediction, mechanism, diagnostic) triple.

type: object
required: [metadata, arms]
additionalProperties: false

properties:
  metadata:
    type: object
    required: [iteration, family, research_question]
    additionalProperties: false
    properties:
      iteration:
        type: integer
        minimum: 1
      family:
        type: string
        minLength: 1
      research_question:
        type: string
        minLength: 1

  arms:
    type: array
    minItems: 1
    items:
      $ref: "#/$defs/arm"

$defs:
  arm:
    type: object
    required: [type, prediction, mechanism, diagnostic]
    additionalProperties: false
    properties:
      type:
        type: string
        enum:
          - h-main
          - h-ablation
          - h-super-additivity
          - h-control-negative
          - h-robustness
      component:
        type: string
        description: "Component name, used for h-ablation arms."
      prediction:
        type: string
        minLength: 1
        description: "Quantitative claim with measurable success/failure threshold."
      mechanism:
        type: string
        minLength: 1
        description: "Causal explanation of how/why."
      diagnostic:
        type: string
        minLength: 1
        description: "What to investigate if the prediction is wrong."
```

**Step 4: Run, verify, commit**

```bash
git add schemas/bundle.schema.yaml tests/test_schemas.py
git commit -m "feat: add bundle schema (YAML) with validation tests"
```

---

## Task 6: Findings Schema

**Files:**
- Create: `schemas/findings.schema.json`
- Modify: `tests/test_schemas.py` (append TestFindingsSchema)

**Step 1: Write the failing test**

```python
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
                    "error_type": null,
                    "diagnostic_note": null
                },
                {
                    "arm_type": "h-control-negative",
                    "predicted": "≈round-robin at <50% util",
                    "observed": "2.1% improvement still observed",
                    "status": "REFUTED",
                    "error_type": "regime",
                    "diagnostic_note": "Threshold is ~60%, not 50%"
                }
            ],
            "discrepancy_analysis": "Control-negative failure indicates mechanism threshold is higher than predicted. Regime boundary for admission effect is ~60% utilization, not 50%."
        }
        jsonschema.validate(instance, schema)
```

**Step 2: Run test, verify fails**

**Step 3: Write schemas/findings.schema.json**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/findings.schema.json",
  "title": "Experiment Findings",
  "description": "Prediction-vs-outcome table with discrepancy analysis for one iteration.",
  "type": "object",
  "required": ["iteration", "bundle_ref", "arms", "discrepancy_analysis"],
  "additionalProperties": false,
  "properties": {
    "iteration": { "type": "integer", "minimum": 1 },
    "bundle_ref": { "type": "string", "minLength": 1 },
    "arms": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/arm_result" }
    },
    "discrepancy_analysis": { "type": "string" }
  },
  "$defs": {
    "arm_result": {
      "type": "object",
      "required": ["arm_type", "predicted", "observed", "status", "error_type", "diagnostic_note"],
      "additionalProperties": false,
      "properties": {
        "arm_type": {
          "type": "string",
          "enum": ["h-main", "h-ablation", "h-super-additivity", "h-control-negative", "h-robustness"]
        },
        "predicted": { "type": "string", "minLength": 1 },
        "observed": { "type": "string", "minLength": 1 },
        "status": {
          "type": "string",
          "enum": ["CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED"]
        },
        "error_type": {
          "type": ["string", "null"],
          "enum": ["direction", "magnitude", "regime", null]
        },
        "diagnostic_note": { "type": ["string", "null"] }
      }
    }
  }
}
```

**Step 4: Run, verify, commit**

```bash
git add schemas/findings.schema.json tests/test_schemas.py
git commit -m "feat: add findings schema with validation tests"
```

---

## Task 7: Trace Schema

**Files:**
- Create: `schemas/trace.schema.json`
- Modify: `tests/test_schemas.py` (append TestTraceSchema)

**Step 1: Write the failing test**

```python
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
                "trigger": "hypothesis.md written"
            }
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
                "cost_usd": 0.035
            }
        }
        jsonschema.validate(instance, schema)

    def test_valid_tool_call(self, load_schema):
        schema = load_schema("trace.schema.json")
        instance = {
            "timestamp": "2026-04-01T12:02:00Z",
            "run_id": "campaign-001",
            "event_type": "tool_call",
            "payload": {
                "tool": "bash",
                "command": "python run_experiment.py",
                "exit_code": 0
            }
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
                "artifact": "runs/iter-1/hypothesis.md"
            }
        }
        jsonschema.validate(instance, schema)
```

**Step 2: Run test, verify fails**

**Step 3: Write schemas/trace.schema.json**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/trace.schema.json",
  "title": "Trace Event",
  "description": "One line per event in trace.jsonl — LLM calls, tool calls, state transitions, gate decisions.",
  "type": "object",
  "required": ["timestamp", "run_id", "event_type", "payload"],
  "additionalProperties": false,
  "properties": {
    "timestamp": { "type": "string", "format": "date-time" },
    "run_id": { "type": "string", "minLength": 1 },
    "event_type": {
      "type": "string",
      "enum": ["llm_call", "tool_call", "state_transition", "gate_decision"]
    },
    "payload": { "type": "object" }
  }
}
```

**Step 4: Run, verify, commit**

```bash
git add schemas/trace.schema.json tests/test_schemas.py
git commit -m "feat: add trace schema with validation tests"
```

---

## Task 8: Summary Schema

**Files:**
- Create: `schemas/summary.schema.json`
- Modify: `tests/test_schemas.py` (append TestSummarySchema)

**Step 1: Write the failing test**

```python
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
                "DESIGN_REVIEW": 5.2,
                "RUNNING": 18.0,
                "FINDINGS_REVIEW": 4.1,
                "TUNING": 3.2,
                "EXTRACTION": 0.8
            },
            "per_iteration_stats": [
                {"iteration": 1, "family": "routing", "cost_usd": 3.2, "tokens": 95000, "h_main_result": "CONFIRMED"}
            ],
            "mechanism_families_investigated": ["routing-signals", "scheduling"],
            "principles_inserted": 14,
            "principles_updated": 3,
            "principles_pruned": 2,
            "final_principle_count": 15
        }
        jsonschema.validate(instance, schema)
```

**Step 2: Run test, verify fails**

**Step 3: Write schemas/summary.schema.json**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/schemas/summary.schema.json",
  "title": "Campaign Summary",
  "description": "Rolled-up statistics for a completed campaign run.",
  "type": "object",
  "required": [
    "run_id", "total_cost_usd", "total_tokens", "total_iterations",
    "cost_by_phase", "per_iteration_stats", "mechanism_families_investigated",
    "principles_inserted", "principles_updated", "principles_pruned",
    "final_principle_count"
  ],
  "additionalProperties": false,
  "properties": {
    "run_id": { "type": "string", "minLength": 1 },
    "total_cost_usd": { "type": "number", "minimum": 0 },
    "total_tokens": {
      "type": "object",
      "required": ["input", "output"],
      "additionalProperties": false,
      "properties": {
        "input": { "type": "integer", "minimum": 0 },
        "output": { "type": "integer", "minimum": 0 }
      }
    },
    "total_iterations": { "type": "integer", "minimum": 0 },
    "cost_by_phase": {
      "type": "object",
      "additionalProperties": { "type": "number", "minimum": 0 }
    },
    "per_iteration_stats": {
      "type": "array",
      "items": { "$ref": "#/$defs/iteration_stat" }
    },
    "mechanism_families_investigated": {
      "type": "array",
      "items": { "type": "string" }
    },
    "principles_inserted": { "type": "integer", "minimum": 0 },
    "principles_updated": { "type": "integer", "minimum": 0 },
    "principles_pruned": { "type": "integer", "minimum": 0 },
    "final_principle_count": { "type": "integer", "minimum": 0 }
  },
  "$defs": {
    "iteration_stat": {
      "type": "object",
      "required": ["iteration", "family", "cost_usd", "tokens", "h_main_result"],
      "additionalProperties": false,
      "properties": {
        "iteration": { "type": "integer", "minimum": 0 },
        "family": { "type": "string" },
        "cost_usd": { "type": "number", "minimum": 0 },
        "tokens": { "type": "integer", "minimum": 0 },
        "h_main_result": {
          "type": ["string", "null"],
          "enum": ["CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED", null]
        }
      }
    }
  }
}
```

**Step 4: Run, verify, commit**

```bash
git add schemas/summary.schema.json tests/test_schemas.py
git commit -m "feat: add summary schema with validation tests"
```

---

## Task 9: Templates

**Files:**
- Create: `templates/state.json`
- Create: `templates/ledger.json`
- Create: `templates/principles.json`
- Create: `templates/bundle.yaml`
- Create: `templates/problem.md`
- Create: `templates/findings.md`
- Create: `tests/test_templates.py`

**Step 1: Write the failing test**

```python
"""tests/test_templates.py"""
import json

import jsonschema
import pytest
import yaml


class TestTemplateConformance:
    def test_state_template_conforms(self, load_schema, load_template):
        schema = load_schema("state.schema.json")
        template = load_template("state.json")
        jsonschema.validate(template, schema)

    def test_ledger_template_conforms(self, load_schema, load_template):
        schema = load_schema("ledger.schema.json")
        template = load_template("ledger.json")
        jsonschema.validate(template, schema)

    def test_principles_template_conforms(self, load_schema, load_template):
        schema = load_schema("principles.schema.json")
        template = load_template("principles.json")
        jsonschema.validate(template, schema)

    def test_bundle_template_conforms(self, load_schema, load_template):
        schema = load_schema("bundle.schema.yaml")
        template = load_template("bundle.yaml")
        jsonschema.validate(template, schema)

    def test_state_template_is_init(self, load_template):
        t = load_template("state.json")
        assert t["phase"] == "INIT"
        assert t["iteration"] == 0

    def test_ledger_template_has_baseline(self, load_template):
        t = load_template("ledger.json")
        assert len(t["iterations"]) == 1
        assert t["iterations"][0]["iteration"] == 0

    def test_principles_template_is_empty(self, load_template):
        t = load_template("principles.json")
        assert t["principles"] == []

    def test_problem_template_exists(self, templates_dir):
        assert (templates_dir / "problem.md").exists()

    def test_findings_template_exists(self, templates_dir):
        assert (templates_dir / "findings.md").exists()
```

**Step 2: Run test, verify fails**

**Step 3: Create all template files**

`templates/state.json`:
```json
{
  "phase": "INIT",
  "iteration": 0,
  "run_id": "TODO-SET-RUN-ID",
  "family": null,
  "timestamp": "1970-01-01T00:00:00Z"
}
```

`templates/ledger.json`:
```json
{
  "iterations": [
    {
      "iteration": 0,
      "family": "baseline",
      "timestamp": "1970-01-01T00:00:00Z",
      "candidate_id": "baseline",
      "h_main_result": null,
      "ablation_results": {},
      "control_result": null,
      "robustness_result": null,
      "prediction_accuracy": null,
      "principles_extracted": [],
      "frontier_update": null
    }
  ]
}
```

`templates/principles.json`:
```json
{
  "principles": []
}
```

`templates/bundle.yaml`:
```yaml
metadata:
  iteration: 1  # TODO: set iteration number
  family: "TODO-mechanism-family"
  research_question: "TODO: What mechanism are you investigating?"

arms:
  - type: h-main
    prediction: "TODO: quantitative claim with measurable threshold"
    mechanism: "TODO: causal explanation of how/why"
    diagnostic: "TODO: what to investigate if prediction is wrong"

  - type: h-ablation
    component: "TODO-component-name"
    prediction: "TODO: component's individual contribution claim"
    mechanism: "TODO: why this component matters independently"
    diagnostic: "TODO: what to check if component doesn't contribute"

  - type: h-super-additivity
    prediction: "TODO: compound effect > sum of parts"
    mechanism: "TODO: why components interact non-linearly"
    diagnostic: "TODO: what to check if components are independent"

  - type: h-control-negative
    prediction: "TODO: where the effect should vanish"
    mechanism: "TODO: why mechanism is irrelevant in this regime"
    diagnostic: "TODO: what overhead or side-effect to look for"

  - type: h-robustness
    prediction: "TODO: effect holds across workloads/conditions"
    mechanism: "TODO: why mechanism generalizes"
    diagnostic: "TODO: what property the mechanism depends on"
```

`templates/problem.md`:
```markdown
# Problem Framing

## Research Question

<!-- What mechanism or behavior are you investigating? -->

## Baseline

<!-- What is the current system behavior without intervention? Include metrics. -->

## Workload

<!-- What workload will you use? Describe arrival patterns, request types, load levels. -->

## Success Criteria

<!-- Quantitative thresholds for success. Be specific. -->

## Constraints

<!-- What cannot be changed? Resource limits, SLOs, compatibility requirements. -->

## Prior Knowledge

<!-- What principles, findings, or domain knowledge apply? Reference principle IDs. -->
```

`templates/findings.md`:
```markdown
# Findings — Iteration N

## Prediction vs. Outcome

| Arm | Predicted | Observed | Status | Error Type |
|-----|-----------|----------|--------|------------|
| H-main | TODO | TODO | CONFIRMED/REFUTED | — |
| H-ablation-{component} | TODO | TODO | CONFIRMED/REFUTED | — |
| H-super-additivity | TODO | TODO | CONFIRMED/REFUTED | — |
| H-control-negative | TODO | TODO | CONFIRMED/REFUTED | — |
| H-robustness | TODO | TODO | CONFIRMED/REFUTED | — |

## Discrepancy Analysis

<!-- For each REFUTED or PARTIALLY_CONFIRMED arm:
     - What was wrong? (direction / magnitude / regime)
     - What does this reveal about the mechanism?
     - What principle should be extracted, updated, or pruned? -->

## Raw Data

<!-- Link to experiment results, logs, or data files. -->
```

**Step 4: Run, verify, commit**

```bash
git add templates/ tests/test_templates.py
git commit -m "feat: add templates conforming to schemas"
```

---

## Task 10: Protocol Doc

**Files:**
- Create: `docs/protocol.md`

**Step 1: Write docs/protocol.md**

Domain-agnostic prose methodology covering:
1. **Overview** — what Nous is, two key properties (hypothesis-driven, compounding knowledge)
2. **Preconditions** — observable metrics, controllable policy, reproducible execution, decomposable mechanisms
3. **The 5-Phase Loop** — Frame → Design → Run → Tune → Extract with detailed descriptions
4. **Hypothesis Bundles** — 5 arm types, the (prediction, mechanism, diagnostic) triple, sizing rules
5. **Prediction Error Taxonomy** — direction/magnitude/regime errors and what each reveals
6. **Principle Extraction** — insert/update/prune operations, how principles constrain future iterations
7. **Review Protocol** — multi-perspective design review (5 perspectives), findings review (10 perspectives), convergence gating (no CRITICAL findings)
8. **Human Gates** — design approval gate, findings approval gate, campaign continuation
9. **Fast-Fail Rules** — H-main refuted → skip to extraction; H-control-negative fails → redesign; single dominant component → simplify
10. **Stopping Criteria** — consecutive null iterations, human judgment
11. **Orchestrator** — state machine overview (11 states), checkpoint/resume, file layout
12. **Investigation Summary** — bounded working memory, O(summary) context

**CRITICAL:** Zero domain-specific references in core text. All examples use generic placeholders.

Full content in implementation — approximately 300-400 lines of markdown.

**Step 2: Commit**

```bash
git add docs/protocol.md
git commit -m "feat: add domain-agnostic protocol documentation"
```

---

## Task 11: BLIS Case Study

**Files:**
- Create: `docs/case-studies/blis.md`

**Step 1: Write docs/case-studies/blis.md**

Worked example referencing:
- **Context** — BLIS LLM inference serving simulator, 30 iterations, 1000+ experiments
- **Two convergence tracks** — scheduling (11 iterations, 73.7% critical TTFT improvement) and routing (19 iterations, 65% combined improvement)
- **Key discovery** — SLO-gated admission control emerged independently in both tracks as the "third lever"
- **Principles catalog** — RP-1 through RP-14 (routing principles), S1 through S16 (scheduling principles) with evidence links
- **Bundle examples** — PR #452 (scheduling iteration 1), PR #447 (routing iteration 6, KV-utilization removal)
- **Prediction error examples** — iteration 1 zero-sum discovery (H-zero-sum refuted, 62.4% cluster degradation), regime boundary corrections

**Step 2: Commit**

```bash
git add docs/case-studies/blis.md
git commit -m "feat: add BLIS case study with principle catalog"
```

---

## Task 12: Orchestrator — engine.py (State Machine)

**Files:**
- Create: `orchestrator/engine.py`
- Create: `tests/test_engine.py`

**Step 1: Write the failing test**

```python
"""tests/test_engine.py"""
import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.engine import Engine, TRANSITIONS


class TestStateTransitions:
    def test_valid_transitions_defined(self):
        """All non-terminal states have at least one valid transition."""
        for state in ["INIT", "FRAMING", "DESIGN", "DESIGN_REVIEW",
                       "HUMAN_DESIGN_GATE", "RUNNING", "FINDINGS_REVIEW",
                       "HUMAN_FINDINGS_GATE", "TUNING", "EXTRACTION"]:
            assert state in TRANSITIONS

    def test_done_is_terminal(self):
        assert "DONE" not in TRANSITIONS


class TestEngine:
    @pytest.fixture
    def work_dir(self, tmp_path):
        (tmp_path / "templates").mkdir()
        # Copy state template
        state = {
            "phase": "INIT",
            "iteration": 0,
            "run_id": "test-001",
            "family": None,
            "timestamp": "2026-04-01T00:00:00Z"
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        return tmp_path

    def test_load_state(self, work_dir):
        engine = Engine(work_dir)
        assert engine.state["phase"] == "INIT"

    def test_transition_init_to_framing(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        assert engine.state["phase"] == "FRAMING"
        # Verify persisted
        saved = json.loads((work_dir / "state.json").read_text())
        assert saved["phase"] == "FRAMING"

    def test_invalid_transition_rejected(self, work_dir):
        engine = Engine(work_dir)
        with pytest.raises(ValueError, match="Invalid transition"):
            engine.transition("RUNNING")  # Can't go INIT → RUNNING

    def test_checkpoint_resume(self, work_dir):
        engine = Engine(work_dir)
        engine.transition("FRAMING")
        # Simulate crash and resume
        engine2 = Engine(work_dir)
        assert engine2.state["phase"] == "FRAMING"

    def test_full_happy_path(self, work_dir):
        """Walk through a complete single-iteration (happy path)."""
        engine = Engine(work_dir)
        path = ["FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
                "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
                "TUNING", "EXTRACTION", "DONE"]
        for next_state in path:
            engine.transition(next_state)
        assert engine.state["phase"] == "DONE"

    def test_refuted_path_skips_tuning(self, work_dir):
        """H-main refuted: HUMAN_FINDINGS_GATE → EXTRACTION (skip TUNING)."""
        engine = Engine(work_dir)
        for s in ["FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
                   "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE"]:
            engine.transition(s)
        engine.transition("EXTRACTION")  # Skip TUNING
        assert engine.state["phase"] == "EXTRACTION"

    def test_iteration_increments_on_next_design(self, work_dir):
        engine = Engine(work_dir)
        for s in ["FRAMING", "DESIGN", "DESIGN_REVIEW", "HUMAN_DESIGN_GATE",
                   "RUNNING", "FINDINGS_REVIEW", "HUMAN_FINDINGS_GATE",
                   "EXTRACTION"]:
            engine.transition(s)
        assert engine.state["iteration"] == 0
        engine.transition("DESIGN")  # Next iteration
        assert engine.state["iteration"] == 1
```

**Step 2: Run test, verify fails**

**Step 3: Write orchestrator/engine.py**

```python
"""State machine engine for the Nous orchestrator.

Owns phase transitions and state.json checkpoint/resume.
This is NOT an LLM — it is a deterministic script.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

# Valid transitions: from_state → set of valid to_states
TRANSITIONS: dict[str, set[str]] = {
    "INIT":                 {"FRAMING"},
    "FRAMING":              {"DESIGN"},
    "DESIGN":               {"DESIGN_REVIEW"},
    "DESIGN_REVIEW":        {"HUMAN_DESIGN_GATE", "DESIGN"},  # DESIGN if criticals found
    "HUMAN_DESIGN_GATE":    {"RUNNING", "DESIGN"},            # DESIGN if human rejects
    "RUNNING":              {"FINDINGS_REVIEW"},
    "FINDINGS_REVIEW":      {"HUMAN_FINDINGS_GATE", "RUNNING"},  # RUNNING if criticals
    "HUMAN_FINDINGS_GATE":  {"TUNING", "EXTRACTION", "RUNNING"},  # TUNING if confirmed, EXTRACTION if refuted, RUNNING if rejected
    "TUNING":               {"EXTRACTION"},
    "EXTRACTION":           {"DESIGN", "DONE"},  # DESIGN for next iter, DONE to stop
}


class Engine:
    """Orchestrator state machine with checkpoint/resume."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.state_path = self.work_dir / "state.json"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        raise FileNotFoundError(f"No state.json found at {self.state_path}")

    def transition(self, to_state: str) -> None:
        current = self.state["phase"]
        if current == "DONE":
            raise ValueError("Campaign is already DONE")
        if current not in TRANSITIONS:
            raise ValueError(f"Unknown state: {current}")
        if to_state not in TRANSITIONS[current]:
            raise ValueError(
                f"Invalid transition: {current} → {to_state}. "
                f"Valid: {TRANSITIONS[current]}"
            )
        # Increment iteration when looping back to DESIGN from EXTRACTION
        if current == "EXTRACTION" and to_state == "DESIGN":
            self.state["iteration"] += 1
        self.state["phase"] = to_state
        self.state["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n")
```

**Step 4: Run, verify, commit**

```bash
git add orchestrator/engine.py tests/test_engine.py
git commit -m "feat: add orchestrator state machine with checkpoint/resume"
```

---

## Task 13: Orchestrator — gates.py

**Files:**
- Create: `orchestrator/gates.py`
- Create: `tests/test_gates.py`

**Step 1: Write the failing test**

```python
"""tests/test_gates.py"""
from orchestrator.gates import HumanGate


class TestHumanGate:
    def test_auto_approve(self):
        gate = HumanGate(auto_approve=True)
        decision = gate.prompt("Approve design?", artifact_path="runs/iter-1/hypothesis.md")
        assert decision == "approve"

    def test_auto_reject(self):
        gate = HumanGate(auto_response="reject")
        decision = gate.prompt("Approve design?", artifact_path="runs/iter-1/hypothesis.md")
        assert decision == "reject"

    def test_valid_decisions(self):
        for d in ["approve", "reject", "abort"]:
            gate = HumanGate(auto_response=d)
            assert gate.prompt("Q?") == d
```

**Step 2: Run test, verify fails**

**Step 3: Write orchestrator/gates.py**

```python
"""Human gate logic for the Nous orchestrator.

Pauses execution, surfaces artifact + review summary, prompts for decision.
Supports auto-approve mode for testing.
"""
from pathlib import Path

VALID_DECISIONS = {"approve", "reject", "abort"}


class HumanGate:
    """Gate that pauses for human approval."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_response: str | None = None,
    ) -> None:
        if auto_approve:
            self._response = "approve"
        elif auto_response:
            if auto_response not in VALID_DECISIONS:
                raise ValueError(f"Invalid auto_response: {auto_response}")
            self._response = auto_response
        else:
            self._response = None

    def prompt(
        self,
        question: str,
        artifact_path: str | None = None,
        reviews: list[str] | None = None,
    ) -> str:
        if self._response:
            return self._response
        # Interactive mode
        if artifact_path:
            print(f"\n--- Artifact: {artifact_path} ---")
            path = Path(artifact_path)
            if path.exists():
                print(path.read_text()[:2000])
        if reviews:
            print(f"\n--- Reviews ({len(reviews)}) ---")
            for r in reviews:
                print(f"  - {r}")
        while True:
            answer = input(f"\n{question} [{'/'.join(VALID_DECISIONS)}]: ").strip().lower()
            if answer in VALID_DECISIONS:
                return answer
            print(f"Invalid. Choose from: {VALID_DECISIONS}")
```

**Step 4: Run, verify, commit**

```bash
git add orchestrator/gates.py tests/test_gates.py
git commit -m "feat: add human gate logic with auto-approve for testing"
```

---

## Task 14: Orchestrator — dispatch.py

**Files:**
- Create: `orchestrator/dispatch.py`
- Create: `tests/test_dispatch.py`

**Step 1: Write the failing test**

```python
"""tests/test_dispatch.py"""
import json
from pathlib import Path

import pytest
import yaml

from orchestrator.dispatch import StubDispatcher


class TestStubDispatcher:
    @pytest.fixture
    def work_dir(self, tmp_path):
        (tmp_path / "schemas").mkdir()
        (tmp_path / "runs" / "iter-1" / "reviews").mkdir(parents=True)
        return tmp_path

    def test_dispatch_planner_produces_bundle(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "bundle.yaml"
        dispatcher.dispatch("planner", "design", output_path=output_path, iteration=1)
        assert output_path.exists()
        bundle = yaml.safe_load(output_path.read_text())
        assert bundle["metadata"]["iteration"] == 1
        assert len(bundle["arms"]) >= 1

    def test_dispatch_executor_produces_findings(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "findings.json"
        dispatcher.dispatch("executor", "run", output_path=output_path, iteration=1)
        assert output_path.exists()
        findings = json.loads(output_path.read_text())
        assert findings["iteration"] == 1

    def test_dispatch_reviewer_produces_review(self, work_dir):
        dispatcher = StubDispatcher(work_dir)
        output_path = work_dir / "runs" / "iter-1" / "reviews" / "review-stats.md"
        dispatcher.dispatch("reviewer", "review-design",
                            output_path=output_path, perspective="statistical-rigor")
        assert output_path.exists()

    def test_dispatch_extractor_returns_principles(self, work_dir):
        # Write empty principles store
        (work_dir / "principles.json").write_text('{"principles": []}')
        dispatcher = StubDispatcher(work_dir)
        dispatcher.dispatch("extractor", "extract",
                            output_path=work_dir / "principles.json", iteration=1)
        result = json.loads((work_dir / "principles.json").read_text())
        assert "principles" in result
```

**Step 2: Run test, verify fails**

**Step 3: Write orchestrator/dispatch.py**

```python
"""Agent dispatch for the Nous orchestrator.

Loads prompt template, invokes LLM API (or stub), writes output.
Default: StubDispatcher that produces valid schema-conformant artifacts
without calling any LLM.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


class StubDispatcher:
    """Produces valid, schema-conformant stub artifacts for testing."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)

    def dispatch(
        self,
        role: str,
        phase: str,
        *,
        output_path: Path,
        iteration: int = 1,
        perspective: str | None = None,
        h_main_result: str = "CONFIRMED",
    ) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        match role:
            case "planner":
                self._write_bundle(output_path, iteration)
            case "executor":
                self._write_findings(output_path, iteration, h_main_result)
            case "reviewer":
                self._write_review(output_path, perspective or "general")
            case "extractor":
                self._write_principles(output_path, iteration)
            case _:
                raise ValueError(f"Unknown role: {role}")

    def _write_bundle(self, path: Path, iteration: int) -> None:
        bundle = {
            "metadata": {
                "iteration": iteration,
                "family": "stub-family",
                "research_question": "Stub: does the mechanism work?",
            },
            "arms": [
                {
                    "type": "h-main",
                    "prediction": "Stub: >10% improvement",
                    "mechanism": "Stub: causal explanation",
                    "diagnostic": "Stub: check if effect exists",
                },
                {
                    "type": "h-control-negative",
                    "prediction": "Stub: no effect at low load",
                    "mechanism": "Stub: mechanism irrelevant without contention",
                    "diagnostic": "Stub: look for overhead",
                },
            ],
        }
        path.write_text(yaml.dump(bundle, default_flow_style=False, sort_keys=False))

    def _write_findings(self, path: Path, iteration: int, h_main_result: str) -> None:
        findings = {
            "iteration": iteration,
            "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": ">10% improvement",
                    "observed": "12.3% improvement" if h_main_result == "CONFIRMED" else "−2.1% regression",
                    "status": h_main_result,
                    "error_type": None if h_main_result == "CONFIRMED" else "direction",
                    "diagnostic_note": None if h_main_result == "CONFIRMED" else "Mechanism does not hold",
                },
                {
                    "arm_type": "h-control-negative",
                    "predicted": "no effect at low load",
                    "observed": "no significant effect",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                },
            ],
            "discrepancy_analysis": "Stub analysis: all predictions within expected range."
            if h_main_result == "CONFIRMED"
            else "Stub analysis: H-main refuted, mechanism does not hold.",
        }
        path.write_text(json.dumps(findings, indent=2) + "\n")

    def _write_review(self, path: Path, perspective: str) -> None:
        path.write_text(
            f"# Review — {perspective}\n\n"
            f"**Severity:** SUGGESTION\n\n"
            f"No CRITICAL or IMPORTANT findings.\n"
            f"Stub review from {perspective} perspective.\n"
        )

    def _write_principles(self, path: Path, iteration: int) -> None:
        store = json.loads(path.read_text()) if path.exists() else {"principles": []}
        store["principles"].append({
            "id": f"stub-principle-{iteration}",
            "statement": f"Stub principle extracted from iteration {iteration}",
            "confidence": "medium",
            "regime": "all",
            "evidence": [f"iteration-{iteration}-h-main"],
            "contradicts": [],
            "extraction_iteration": iteration,
            "mechanism": "Stub mechanism",
            "applicability_bounds": "stub",
            "superseded_by": None,
            "status": "active",
        })
        path.write_text(json.dumps(store, indent=2) + "\n")
```

**Step 4: Run, verify, commit**

```bash
git add orchestrator/dispatch.py tests/test_dispatch.py
git commit -m "feat: add agent dispatch with stub dispatcher for testing"
```

---

## Task 15: Orchestrator — fastfail.py

**Files:**
- Create: `orchestrator/fastfail.py`
- Create: `tests/test_fastfail.py`

**Step 1: Write the failing test**

```python
"""tests/test_fastfail.py"""
from orchestrator.fastfail import check_fast_fail, FastFailAction


class TestFastFail:
    def test_h_main_refuted_skips_to_extraction(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "REFUTED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
            ]
        }
        result = check_fast_fail(findings)
        assert result == FastFailAction.SKIP_TO_EXTRACTION

    def test_control_negative_fails_redesign(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "REFUTED"},
            ]
        }
        result = check_fast_fail(findings)
        assert result == FastFailAction.REDESIGN

    def test_all_confirmed_continues(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
                {"arm_type": "h-robustness", "status": "CONFIRMED"},
            ]
        }
        result = check_fast_fail(findings)
        assert result == FastFailAction.CONTINUE

    def test_h_main_refuted_takes_priority(self):
        """H-main refuted overrides control-negative failure."""
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "REFUTED"},
                {"arm_type": "h-control-negative", "status": "REFUTED"},
            ]
        }
        result = check_fast_fail(findings)
        assert result == FastFailAction.SKIP_TO_EXTRACTION

    def test_single_dominant_component_simplifies(self):
        """Single component >80% of effect → simplify."""
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
            ],
            "dominant_component_pct": 85.0,
        }
        result = check_fast_fail(findings)
        assert result == FastFailAction.SIMPLIFY

    def test_no_dominant_component_continues(self):
        findings = {
            "arms": [
                {"arm_type": "h-main", "status": "CONFIRMED"},
                {"arm_type": "h-control-negative", "status": "CONFIRMED"},
            ],
            "dominant_component_pct": 60.0,
        }
        result = check_fast_fail(findings)
        assert result == FastFailAction.CONTINUE
```

**Step 2: Run test, verify fails**

**Step 3: Write orchestrator/fastfail.py**

```python
"""Fast-fail rules for the Nous orchestrator.

Pure functions: take findings, return action. No side effects.

Rules (in priority order):
1. H-main refuted → skip remaining arms, go to EXTRACTION
2. H-control-negative fails → mechanism confounded, return to DESIGN
3. Single dominant component (>80% of total effect) → SIMPLIFY
4. Otherwise → CONTINUE normally
"""
from enum import Enum


class FastFailAction(Enum):
    CONTINUE = "continue"
    SKIP_TO_EXTRACTION = "skip_to_extraction"
    REDESIGN = "redesign"
    SIMPLIFY = "simplify"


def check_fast_fail(findings: dict) -> FastFailAction:
    arms = {a["arm_type"]: a for a in findings["arms"]}

    # Rule 1: H-main refuted → skip to extraction (highest priority)
    if arms.get("h-main", {}).get("status") == "REFUTED":
        return FastFailAction.SKIP_TO_EXTRACTION

    # Rule 2: H-control-negative fails → redesign
    if arms.get("h-control-negative", {}).get("status") == "REFUTED":
        return FastFailAction.REDESIGN

    # Rule 3: Single dominant component (>80%) → simplify
    if findings.get("dominant_component_pct") is not None:
        if findings["dominant_component_pct"] > 80:
            return FastFailAction.SIMPLIFY

    return FastFailAction.CONTINUE
```

**Step 4: Run, verify, commit**

```bash
git add orchestrator/fastfail.py tests/test_fastfail.py
git commit -m "feat: add fast-fail rules for orchestrator"
```

---

## Task 16: Integration Test — Full Single-Iteration with Stub Agents

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write the integration test**

```python
"""tests/test_integration.py — end-to-end single-iteration with stub agents."""
import json
import shutil
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.engine import Engine
from orchestrator.dispatch import StubDispatcher
from orchestrator.fastfail import check_fast_fail, FastFailAction
from orchestrator.gates import HumanGate


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


class TestSingleIterationHappyPath:
    """Orchestrator completes one full iteration with stub agents."""

    @pytest.fixture
    def campaign_dir(self, tmp_path):
        # Seed from templates
        shutil.copy(TEMPLATES_DIR / "state.json", tmp_path / "state.json")
        shutil.copy(TEMPLATES_DIR / "ledger.json", tmp_path / "ledger.json")
        shutil.copy(TEMPLATES_DIR / "principles.json", tmp_path / "principles.json")
        # Fix run_id in state
        state = json.loads((tmp_path / "state.json").read_text())
        state["run_id"] = "test-integration-001"
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        return tmp_path

    def test_happy_path_confirmed(self, campaign_dir):
        engine = Engine(campaign_dir)
        dispatcher = StubDispatcher(campaign_dir)
        gate = HumanGate(auto_approve=True)
        iter_dir = campaign_dir / "runs" / "iter-1"

        # INIT → FRAMING
        engine.transition("FRAMING")
        # Planner writes problem.md (stub: just copy template)
        shutil.copy(TEMPLATES_DIR / "problem.md", campaign_dir / "problem.md")

        # FRAMING → DESIGN
        engine.transition("DESIGN")
        dispatcher.dispatch("planner", "design",
                            output_path=iter_dir / "bundle.yaml", iteration=1)
        # Validate bundle against schema
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        jsonschema.validate(bundle, load_schema("bundle.schema.yaml"))

        # DESIGN → DESIGN_REVIEW
        engine.transition("DESIGN_REVIEW")
        for p in ["stats", "causal", "confound", "generalization", "clarity"]:
            dispatcher.dispatch("reviewer", "review-design",
                                output_path=iter_dir / "reviews" / f"review-{p}.md",
                                perspective=p)

        # DESIGN_REVIEW → HUMAN_DESIGN_GATE (no criticals)
        engine.transition("HUMAN_DESIGN_GATE")
        assert gate.prompt("Approve?") == "approve"

        # HUMAN_DESIGN_GATE → RUNNING
        engine.transition("RUNNING")
        dispatcher.dispatch("executor", "run",
                            output_path=iter_dir / "findings.json", iteration=1)
        findings = json.loads((iter_dir / "findings.json").read_text())
        jsonschema.validate(findings, load_schema("findings.schema.json"))

        # Check fast-fail
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.CONTINUE

        # RUNNING → FINDINGS_REVIEW
        engine.transition("FINDINGS_REVIEW")

        # FINDINGS_REVIEW → HUMAN_FINDINGS_GATE
        engine.transition("HUMAN_FINDINGS_GATE")
        assert gate.prompt("Approve?") == "approve"

        # H-main confirmed → TUNING
        engine.transition("TUNING")

        # TUNING → EXTRACTION
        engine.transition("EXTRACTION")
        dispatcher.dispatch("extractor", "extract",
                            output_path=campaign_dir / "principles.json", iteration=1)
        principles = json.loads((campaign_dir / "principles.json").read_text())
        jsonschema.validate(principles, load_schema("principles.schema.json"))

        # Campaign done
        engine.transition("DONE")
        assert engine.state["phase"] == "DONE"

    def test_fast_fail_h_main_refuted(self, campaign_dir):
        engine = Engine(campaign_dir)
        dispatcher = StubDispatcher(campaign_dir)
        gate = HumanGate(auto_approve=True)
        iter_dir = campaign_dir / "runs" / "iter-1"

        for s in ["FRAMING", "DESIGN"]:
            engine.transition(s)
        dispatcher.dispatch("planner", "design",
                            output_path=iter_dir / "bundle.yaml", iteration=1)

        engine.transition("DESIGN_REVIEW")
        engine.transition("HUMAN_DESIGN_GATE")
        engine.transition("RUNNING")

        # Executor produces refuted findings
        dispatcher.dispatch("executor", "run",
                            output_path=iter_dir / "findings.json",
                            iteration=1, h_main_result="REFUTED")
        findings = json.loads((iter_dir / "findings.json").read_text())

        # Fast-fail triggers
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.SKIP_TO_EXTRACTION

        engine.transition("FINDINGS_REVIEW")
        engine.transition("HUMAN_FINDINGS_GATE")
        # Skip TUNING → go to EXTRACTION
        engine.transition("EXTRACTION")
        assert engine.state["phase"] == "EXTRACTION"

    def test_checkpoint_resume(self, campaign_dir):
        engine = Engine(campaign_dir)
        engine.transition("FRAMING")
        engine.transition("DESIGN")

        # Simulate crash: create new engine from same dir
        engine2 = Engine(campaign_dir)
        assert engine2.state["phase"] == "DESIGN"
        # Continue
        engine2.transition("DESIGN_REVIEW")
        assert engine2.state["phase"] == "DESIGN_REVIEW"
```

**Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: add integration tests for full single-iteration with stubs"
```

---

## Task 17: Final Validation and Cleanup

**Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass

**Step 2: Verify schema self-validation**

Run: `python -c "import json, jsonschema; [jsonschema.Draft202012Validator.check_schema(json.loads(open(f).read())) for f in __import__('glob').glob('schemas/*.json')]"`

**Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final validation and cleanup"
```

---

## Verification Checklist (from issue #11)

- [ ] All JSON schemas pass `jsonschema` validation
- [ ] Sample data round-trips through each schema without loss
- [ ] All templates conform to their schemas
- [ ] Protocol doc covers all 5 phases with no domain-specific references in core text
- [ ] BLIS case study references actual principles (RP-1–RP-14, S1–S16) with evidence links
- [ ] Orchestrator walks through a complete single-iteration with stub agents
- [ ] `state.json` transitions correctly through all states
- [ ] Fast-fail: stub H-main refuted → skips directly to EXTRACTION
- [ ] Checkpoint/resume: kill orchestrator mid-iteration, restart, continues from last state
- [ ] Human gates pause correctly and accept approve/reject input
