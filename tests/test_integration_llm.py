"""Integration test — full single-iteration loop with mocked LLM responses."""
import json
import shutil
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.engine import Engine
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.fastfail import check_fast_fail, FastFailAction
from orchestrator.gates import HumanGate


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

SAMPLE_CAMPAIGN = {
    "research_question": "Does batch size affect latency in TestSystem?",
    "target_system": {
        "name": "TestSystem",
        "description": "A test system for integration testing.",
        "observable_metrics": ["latency_ms", "throughput_rps"],
        "controllable_knobs": ["batch_size", "worker_count"],
    },
    "prompts": {
        "methodology_layer": "prompts/methodology",
        "domain_adapter_layer": None,
    },
}

BUNDLE_YAML = """\
metadata:
  iteration: 1
  family: integration-test
  research_question: "Does batch size affect latency in TestSystem?"
arms:
  - type: h-main
    prediction: "latency decreases by 20% when batch_size doubles"
    mechanism: "Larger batches amortize fixed overhead"
    diagnostic: "Check if overhead is actually fixed"
  - type: h-control-negative
    prediction: "no effect at batch_size=1"
    mechanism: "No batching means no amortization"
    diagnostic: "Verify single-item path"
"""

EXECUTE_ANALYZE_JSON = json.dumps({
    "plan": {
        "metadata": {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
        },
        "arms": [
            {
                "arm_id": "h-main",
                "conditions": [
                    {"name": "baseline", "cmd": "echo baseline"},
                    {"name": "treatment", "cmd": "echo treatment"},
                ],
            },
            {
                "arm_id": "h-control-negative",
                "conditions": [
                    {"name": "control", "cmd": "echo control"},
                ],
            },
        ],
    },
    "findings": {
        "iteration": 1,
        "bundle_ref": "runs/iter-1/bundle.yaml",
        "experiment_valid": True,
        "arms": [
            {
                "arm_type": "h-main",
                "predicted": "latency decreases when batch_size doubles",
                "observed": "latency decreased by 22%",
                "status": "CONFIRMED",
                "error_type": None,
                "diagnostic_note": "Consistent with amortization model.",
            },
            {
                "arm_type": "h-control-negative",
                "predicted": "no effect at batch_size=1",
                "observed": "no significant change observed",
                "status": "CONFIRMED",
                "error_type": None,
                "diagnostic_note": None,
            },
        ],
        "discrepancy_analysis": "All arms confirmed. Batch amortization holds.",
        "dominant_component_pct": None,
    },
    "principle_updates": [
        {
            "id": "RP-1",
            "statement": "Batch size amortizes fixed overhead",
            "confidence": "medium",
            "regime": "batch_size > 1",
            "evidence": ["iteration-1-h-main"],
            "contradicts": [],
            "extraction_iteration": 1,
            "mechanism": "Fixed per-request overhead shared across batch",
            "applicability_bounds": "Only when fixed overhead dominates",
            "superseded_by": None,
            "category": "domain",
            "status": "active",
        }
    ],
}, indent=2)


def _mock_responses() -> dict[str, str]:
    """Map route keys to canned LLM responses."""
    return {
        "design": f"## Research Question\n\nDoes batch size affect latency?\n\n## System Interface\n\nStub system interface.\n\n---\n\n```yaml\n{BUNDLE_YAML}```",
        "execute_analyze": f"```json\n{EXECUTE_ANALYZE_JSON}\n```",
    }


def _make_routing_completion(responses: dict[str, str]):
    """Build a completion_fn that returns canned responses based on prompt content."""
    call_log: list[dict] = []

    def mock_fn(**kwargs):
        call_log.append(kwargs)
        system_msg = kwargs["messages"][0]["content"]

        if "scientific executor" in system_msg.lower():
            text = responses["execute_analyze"]
        elif "hypothesis bundle" in system_msg:
            text = responses["design"]
        else:
            text = "Unrecognized prompt."

        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=text))]
        return resp

    mock_fn.call_log = call_log  # type: ignore[attr-defined]
    return mock_fn


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


@pytest.fixture(autouse=True)
def _allow_auto_approve(monkeypatch):
    monkeypatch.setenv("NOUS_ALLOW_AUTO_APPROVE", "1")


def _make_gate():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HumanGate(auto_approve=True)


class TestSingleIterationWithMockedLLM:
    """Drive the full orchestrator loop with LLMDispatcher and mocked LLM responses."""

    @pytest.fixture()
    def campaign_dir(self, tmp_path: Path) -> Path:
        shutil.copy(TEMPLATES_DIR / "state.json", tmp_path / "state.json")
        shutil.copy(TEMPLATES_DIR / "ledger.json", tmp_path / "ledger.json")
        shutil.copy(TEMPLATES_DIR / "principles.json", tmp_path / "principles.json")
        state = json.loads((tmp_path / "state.json").read_text())
        state["run_id"] = "test-llm-integration-001"
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        return tmp_path

    def test_full_iteration_with_mocked_llm(self, campaign_dir: Path) -> None:
        engine = Engine(campaign_dir)
        mock_fn = _make_routing_completion(_mock_responses())
        dispatcher = LLMDispatcher(
            work_dir=campaign_dir,
            campaign=SAMPLE_CAMPAIGN,
            completion_fn=mock_fn,
        )
        gate = _make_gate()
        iter_dir = campaign_dir / "runs" / "iter-1"

        # INIT -> DESIGN
        engine.transition("DESIGN")
        dispatcher.dispatch(
            "planner", "design",
            output_path=iter_dir / "design_raw.md", iteration=1,
        )
        from run_iteration import _split_design_output, _merge_principles
        _split_design_output((iter_dir / "design_raw.md").read_text(), iter_dir)
        bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
        jsonschema.validate(bundle, load_schema("bundle.schema.yaml"))

        # DESIGN -> HUMAN_DESIGN_GATE
        engine.transition("HUMAN_DESIGN_GATE")
        assert gate.prompt("Approve design?") == ("approve", None)

        # HUMAN_DESIGN_GATE -> EXECUTE_ANALYZE
        engine.transition("EXECUTE_ANALYZE")
        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "execute_analyze_output.json", iteration=1,
        )
        combined = json.loads((iter_dir / "execute_analyze_output.json").read_text())
        (iter_dir / "findings.json").write_text(json.dumps(combined["findings"], indent=2))
        (iter_dir / "principle_updates.json").write_text(
            json.dumps(combined["principle_updates"], indent=2)
        )
        findings = combined["findings"]
        jsonschema.validate(findings, load_schema("findings.schema.json"))

        # Check fast-fail
        ff = check_fast_fail(findings)
        assert ff == FastFailAction.CONTINUE

        # EXECUTE_ANALYZE -> VALIDATE
        engine.transition("VALIDATE")

        # VALIDATE -> HUMAN_FINDINGS_GATE
        engine.transition("HUMAN_FINDINGS_GATE")
        assert gate.prompt("Approve findings?") == ("approve", None)

        # Merge principles (Python, no LLM)
        _merge_principles(campaign_dir, iter_dir)
        principles = json.loads((campaign_dir / "principles.json").read_text())
        jsonschema.validate(principles, load_schema("principles.schema.json"))
        assert len(principles["principles"]) >= 1

        # HUMAN_FINDINGS_GATE -> DONE
        engine.transition("DONE")
        assert engine.phase == "DONE"

        # Verify all expected artifacts exist
        assert (iter_dir / "bundle.yaml").exists()
        assert (iter_dir / "findings.json").exists()

        # Verify LLM was called the expected number of times:
        # 1 design + 1 execute-analyze = 2
        assert len(mock_fn.call_log) == 2
